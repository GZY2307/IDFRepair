# frozen_string_literal: true

# Read-only, fail-closed audit for the exact Airport Occupancy V3 source OSM.

require 'csv'
require 'fileutils'
require 'json'
require 'optparse'


def fail_closed(message)
  warn(message)
  exit(2)
end


def optional_space_name(sub_surface)
  surface = sub_surface.surface
  return nil unless surface.is_initialized

  space = surface.get.space
  space.is_initialized ? space.get.nameString : nil
end


options = {}
OptionParser.new do |parser|
  parser.on('--input PATH') { |value| options[:input] = value }
  parser.on('--mapping PATH') { |value| options[:mapping] = value }
  parser.on('--output PATH') { |value| options[:output] = value }
end.parse!

%i[input mapping output].each do |key|
  fail_closed("#{key}_missing") unless options[key]
end

source = File.expand_path(options.fetch(:input))
mapping = File.expand_path(options.fetch(:mapping))
output = File.expand_path(options.fetch(:output))
fail_closed('source_not_found') unless File.file?(source)
fail_closed('mapping_not_found') unless File.file?(mapping)
fail_closed('output_must_not_equal_source') if output == source

source_state_before = [File.size(source), File.mtime(source).to_f, File.stat(source).ino]
mapping_state_before = [File.size(mapping), File.mtime(mapping).to_f, File.stat(mapping).ino]

version_translator = OpenStudio::OSVersion::VersionTranslator.new
loaded = version_translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_model_load_failed') if loaded.empty?
model = loaded.get

draft_report = model.validityReport(OpenStudio::StrictnessLevel.new('Draft'))
draft_errors = draft_report.numErrors

forward = OpenStudio::EnergyPlus::ForwardTranslator.new
forward.translateModel(model)
forward_errors = forward.errors.map(&:logMessage)
forward_warnings = forward.warnings.map(&:logMessage)

doors = model.getSubSurfaces.select do |sub_surface|
  sub_surface.subSurfaceType.casecmp('Door').zero?
end
door_by_handle = doors.to_h { |door| [door.handle.to_s, door] }
physical_pairs = {}
space_connections = {}
unpaired_doors = []
nonreciprocal_doors = []
door_to_non_door = []

doors.each do |door|
  adjacent = door.adjacentSubSurface
  unless adjacent.is_initialized
    unpaired_doors << door.handle.to_s
    next
  end
  mate = adjacent.get
  door_to_non_door << [door.handle.to_s, mate.handle.to_s] unless mate.subSurfaceType.casecmp('Door').zero?
  mate_back = mate.adjacentSubSurface
  unless mate_back.is_initialized && mate_back.get.handle == door.handle
    nonreciprocal_doors << [door.handle.to_s, mate.handle.to_s]
  end
  pair_key = [door.handle.to_s, mate.handle.to_s].sort
  physical_pairs[pair_key] ||= {
    'door_handles' => pair_key,
    'space_names' => [optional_space_name(door), optional_space_name(mate)].compact.sort
  }
end

physical_pairs.each_value do |pair|
  spaces = pair.fetch('space_names')
  next unless spaces.size == 2

  (space_connections[spaces] ||= []) << pair.fetch('door_handles')
end

surface_pairs = {}
surface_space_connections = {}
model.getSurfaces.each do |surface|
  adjacent = surface.adjacentSurface
  next unless adjacent.is_initialized

  mate = adjacent.get
  pair_key = [surface.handle.to_s, mate.handle.to_s].sort
  surface_pairs[pair_key] = true
  source_space = surface.space
  target_space = mate.space
  next unless source_space.is_initialized && target_space.is_initialized

  spaces = [source_space.get.nameString, target_space.get.nameString].sort
  rows = (surface_space_connections[spaces] ||= [])
  rows << pair_key unless rows.include?(pair_key)
end

mapping_rows = CSV.read(mapping, headers: true).map(&:to_h)
mapping_names = mapping_rows.map { |row| row.fetch('space').strip }
mapping_duplicates = mapping_names.group_by(&:itself).select { |_name, rows| rows.size > 1 }.keys.sort
function_counts = mapping_rows.group_by { |row| row.fetch('function').strip }
                              .transform_values(&:size)
region_counts = mapping_rows.group_by { |row| row.fetch('region').strip }
                            .transform_values(&:size)

controllers = model.getControllerMechanicalVentilations
dcv_enabled = controllers.count(&:demandControlledVentilation)

source_state_after = [File.size(source), File.mtime(source).to_f, File.stat(source).ino]
mapping_state_after = [File.size(mapping), File.mtime(mapping).to_f, File.stat(mapping).ino]
fail_closed('source_changed_during_audit') unless source_state_after == source_state_before
fail_closed('mapping_changed_during_audit') unless mapping_state_after == mapping_state_before

result = {
  'schema_version' => 'idfrepair.airport-abm-model-audit.v3',
  'source_alias' => 'Airport V3 exact baseline',
  'source_unchanged' => true,
  'mapping_unchanged' => true,
  'openstudio_version' => OpenStudio::openStudioVersion,
  'osm_schema_version' => model.version.str,
  'draft_validity_errors' => draft_errors,
  'forward_translation_errors' => forward_errors.size,
  'forward_translation_error_messages' => forward_errors,
  'forward_translation_warnings' => forward_warnings,
  'counts' => {
    'spaces' => model.getSpaces.size,
    'thermal_zones' => model.getThermalZones.size,
    'air_loops' => model.getAirLoopHVACs.size,
    'plant_loops' => model.getPlantLoops.size,
    'fan_coils' => model.getZoneHVACFourPipeFanCoils.size,
    'zone_exhaust_fans' => model.getFanZoneExhausts.size,
    'heat_recovery_units' => model.getHeatExchangerAirToAirSensibleAndLatents.size,
    'ideal_loads' => model.getZoneHVACIdealLoadsAirSystems.size,
    'doors' => doors.size,
    'physical_reciprocal_door_pairs' => physical_pairs.size,
    'unique_space_door_connections' => space_connections.size,
    'people_objects' => model.getPeoples.size,
    'people_definitions' => model.getPeopleDefinitions.size
  },
  'door_audit' => {
    'unpaired_door_count' => unpaired_doors.size,
    'nonreciprocal_door_count' => nonreciprocal_doors.size,
    'door_to_non_door_count' => door_to_non_door.size,
    'space_connections' => space_connections.sort_by { |spaces, _pairs| spaces }.map do |spaces, pairs|
      {
        'space_names' => spaces,
        'physical_door_pairs' => pairs.sort
      }
    end,
    'multi_door_space_connections' => space_connections.select { |_key, values| values.size > 1 }.map do |spaces, pairs|
      {
        'space_names' => spaces,
        'physical_door_pairs' => pairs
      }
    end
  },
  'surface_audit' => {
    'surface_count' => model.getSurfaces.size,
    'reciprocal_surface_pairs' => surface_pairs.size,
    'routing_input_count' => 0,
    'candidate_space_connections' => surface_space_connections.sort_by { |spaces, _pairs| spaces }.map do |spaces, pairs|
      {
        'space_names' => spaces,
        'physical_surface_pairs' => pairs.sort,
        'status' => 'CANDIDATE_NOT_WALKABLE_BY_DEFAULT'
      }
    end
  },
  'mechanical_ventilation_controllers' => {
    'count' => controllers.size,
    'demand_controlled_ventilation_enabled' => dcv_enabled
  },
  'mapping' => {
    'space_count' => mapping_rows.size,
    'unique_space_count' => mapping_names.uniq.size,
    'duplicate_spaces' => mapping_duplicates,
    'function_counts' => function_counts.sort.to_h,
    'region_counts' => region_counts.sort.to_h
  }
}

FileUtils.mkdir_p(File.dirname(output))
File.write(output, JSON.pretty_generate(result) + "\n")
puts JSON.generate({
  'status' => 'audit_complete',
  'counts' => result.fetch('counts'),
  'draft_validity_errors' => draft_errors,
  'forward_translation_errors' => forward_errors.size
})
