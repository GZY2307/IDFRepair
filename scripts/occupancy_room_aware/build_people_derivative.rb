# frozen_string_literal: true

# 从只读 OSM 构建逐 Space People-only reference derivative 与 IdealLoads 端点。

require 'digest'
require 'fileutils'
require 'json'
require 'optparse'


MANIFEST_SCHEMA = 'idfrepair.room-aware-people-manifest.v1'
MUTABLE_DERIVATIVE_TYPES = %w[
  OS_People
  OS_People_Definition
  OS_PortList
  OS_ThermalZone
  OS_ZoneHVAC_EquipmentList
].freeze


def fail_closed(message)
  warn(message)
  exit(2)
end


def within_root?(path, root)
  path == root || path.start_with?(root + File::SEPARATOR)
end


def canonical_rows(model, handles = nil)
  rows = model.objects.filter_map do |object|
    type = object.iddObject.type.valueName
    next if MUTABLE_DERIVATIVE_TYPES.include?(type)
    next if handles && !handles.include?(object.handle.to_s)

    [type, object.handle.to_s, object.to_s]
  end
  rows.sort_by { |row| [row[0], row[1]] }
end


def snapshot(rows)
  serialized = rows.map { |row| row.join("\u001f") }.join("\u001e")
  Digest::SHA256.hexdigest(serialized)
end


def zone_semantic_rows(model)
  model.getThermalZones.sort_by(&:nameString).map do |zone|
    thermostat = zone.thermostatSetpointDualSetpoint
    {
      'name' => zone.nameString,
      'multiplier' => zone.multiplier,
      'space_names' => zone.spaces.map(&:nameString).sort,
      'space_floor_area_m2' => zone.spaces.sum(&:floorArea),
      'thermostat_setpoint_dual_setpoint' => (
        thermostat.is_initialized ? thermostat.get.nameString : nil
      )
    }
  end
end


def exact_object_by_name(objects, name, kind)
  matches = objects.select { |object| object.nameString == name }
  fail_closed("#{kind}_not_unique:#{name}:#{matches.size}") unless matches.one?
  matches.first
end


def counts(model)
  {
    'spaces' => model.getSpaces.size,
    'thermal_zones' => model.getThermalZones.size,
    'people' => model.getPeoples.size,
    'people_definitions' => model.getPeopleDefinitions.size,
    'space_types' => model.getSpaceTypes.size,
    'lights' => model.getLightss.size,
    'electric_equipment' => model.getElectricEquipments.size,
    'infiltration' => model.getSpaceInfiltrationDesignFlowRates.size,
    'dsoa' => model.getDesignSpecificationOutdoorAirs.size,
    'air_loops' => model.getAirLoopHVACs.size,
    'plant_loops' => model.getPlantLoops.size,
    'ideal_loads' => model.getZoneHVACIdealLoadsAirSystems.size
  }
end


options = {}
OptionParser.new do |parser|
  parser.on('--input PATH') { |value| options[:input] = value }
  parser.on('--manifest PATH') { |value| options[:manifest] = value }
  parser.on('--output-dir PATH') { |value| options[:output_dir] = value }
  parser.on('--allowed-root PATH') { |value| options[:allowed_root] = value }
end.parse!

%i[input manifest output_dir allowed_root].each do |key|
  fail_closed("#{key}_missing") unless options[key]
end
source = File.expand_path(options[:input])
manifest_path = File.expand_path(options[:manifest])
output_dir = File.expand_path(options[:output_dir])
allowed_root = File.expand_path(options[:allowed_root])
fail_closed('source_not_found') unless File.file?(source)
fail_closed('manifest_not_found') unless File.file?(manifest_path)
fail_closed('output_outside_allowed_root') unless within_root?(output_dir, allowed_root)
fail_closed('output_must_not_equal_source') if output_dir == source

source_sha_before = Digest::SHA256.file(source).hexdigest
manifest_sha = Digest::SHA256.file(manifest_path).hexdigest
manifest = JSON.parse(File.read(manifest_path, encoding: 'UTF-8'))
fail_closed('manifest_schema_invalid') unless manifest['schema_version'] == MANIFEST_SCHEMA
fail_closed('manifest_source_hash_mismatch') unless manifest['source_sha256'] == source_sha_before
manifest_spaces = manifest['spaces']
fail_closed('manifest_spaces_invalid') unless manifest_spaces.is_a?(Array)
if manifest['space_count'] && manifest['space_count'] != manifest_spaces.size
  fail_closed('manifest_space_count_mismatch')
end

translator = OpenStudio::OSVersion::VersionTranslator.new
loaded = translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_model_load_failed') if loaded.empty?
model = loaded.get
before_counts = counts(model)
fail_closed('manifest_model_space_count_mismatch') unless manifest_spaces.size == model.getSpaces.size

protected_before = canonical_rows(model)
protected_handles = protected_before.map { |row| row[1] }.to_h { |handle| [handle, true] }
protected_sha_before = snapshot(protected_before)
zone_semantics_before = zone_semantic_rows(model)
zone_semantics_sha_before = Digest::SHA256.hexdigest(JSON.generate(zone_semantics_before))

people_removed = model.getPeoples.size
model.getPeoples.each(&:remove)
people_definitions_removed = model.getPeopleDefinitions.size
model.getPeopleDefinitions.each(&:remove)
fail_closed('source_people_removal_incomplete') unless model.getPeoples.empty?
fail_closed('source_people_definition_removal_incomplete') unless model.getPeopleDefinitions.empty?

placeholder = OpenStudio::Model::ScheduleConstant.new(model)
placeholder.setName('IDFRepair Room-Aware Placeholder Fraction')
placeholder.setValue(1.0)

spaces = model.getSpaces
schedules = model.getSchedules
modifications = []
manifest_names = manifest_spaces.map { |row| row['source_space_name'] }
fail_closed('manifest_space_name_missing') if manifest_names.any? { |name| !name.is_a?(String) || name.empty? }
if manifest_names.uniq.size != manifest_names.size
  fail_closed('manifest_space_name_duplicate')
end

manifest_spaces.each_with_index do |row, index|
  name = row.fetch('source_space_name')
  space = exact_object_by_name(spaces, name, 'space')
  activity_name = row['activity_schedule']
  fail_closed("activity_schedule_missing:#{name}") unless activity_name.is_a?(String) && !activity_name.empty?
  activity = exact_object_by_name(schedules, activity_name, 'activity_schedule')
  target = Float(row.fetch('target_design_people'))
  fail_closed("target_design_people_invalid:#{name}") unless target.finite? && target >= 0.0

  definition = OpenStudio::Model::PeopleDefinition.new(model)
  definition.setName(format('IDFRepair RA People Definition %03d', index + 1))
  fail_closed("number_people_set_failed:#{name}") unless definition.setNumberofPeople(target)
  fraction_radiant = Float(row.fetch('fraction_radiant'))
  unless definition.setFractionRadiant(fraction_radiant)
    fail_closed("fraction_radiant_set_failed:#{name}")
  end
  sensible = row['sensible_heat_fraction']
  if !sensible.nil? && !definition.setSensibleHeatFraction(Float(sensible))
    fail_closed("sensible_heat_fraction_set_failed:#{name}")
  end
  co2 = Float(row.fetch('co2_generation_rate_m3_s_person'))
  unless definition.setCarbonDioxideGenerationRate(co2)
    fail_closed("co2_generation_rate_set_failed:#{name}")
  end

  people = OpenStudio::Model::People.new(definition)
  people.setName("IDFRepair RA People :: #{name}")
  fail_closed("people_space_assignment_failed:#{name}") unless people.setSpace(space)
  unless people.setNumberofPeopleSchedule(placeholder)
    fail_closed("people_count_schedule_assignment_failed:#{name}")
  end
  unless people.setActivityLevelSchedule(activity)
    fail_closed("people_activity_schedule_assignment_failed:#{name}")
  end
  modifications << {
    'source_space_name' => name,
    'room_category' => row['room_category'],
    'source_design_people' => row['source_design_people'],
    'target_design_people' => target,
    'count_evidence_id' => row['count_evidence_id'],
    'metadata_status' => row['metadata_status'],
    'preserve_source_people_parameters' => row['preserve_source_people_parameters'],
    'modified_fields' => ['People target', 'People design count', 'People number schedule'],
    'preserved_fields' => [
      'activity schedule',
      'fraction radiant',
      'sensible heat fraction',
      'CO2 generation rate'
    ]
  }
end

ideal_loads_added = 0
orphan_zones_skipped = []
zones_with_existing_equipment = []
model.getThermalZones.sort_by(&:nameString).each do |zone|
  if zone.spaces.empty?
    orphan_zones_skipped << zone.nameString
    next
  end
  unless zone.equipment.empty?
    zones_with_existing_equipment << zone.nameString
    next
  end
  ideal = OpenStudio::Model::ZoneHVACIdealLoadsAirSystem.new(model)
  ideal.setName("IDFRepair Room-Aware IdealLoads :: #{zone.nameString}")
  fail_closed("ideal_loads_assignment_failed:#{zone.nameString}") unless ideal.addToThermalZone(zone)
  ideal_loads_added += 1
end

protected_after = canonical_rows(model, protected_handles)
protected_sha_after = snapshot(protected_after)
protected_unchanged = protected_before == protected_after
zone_semantics_after = zone_semantic_rows(model)
zone_semantics_sha_after = Digest::SHA256.hexdigest(JSON.generate(zone_semantics_after))
zone_semantics_unchanged = zone_semantics_before == zone_semantics_after
fail_closed('thermal_zone_source_semantics_changed') unless zone_semantics_unchanged
unless protected_unchanged
  before_by_handle = protected_before.to_h { |row| [row[1], row] }
  after_by_handle = protected_after.to_h { |row| [row[1], row] }
  changed = before_by_handle.keys.filter_map do |handle|
    before_row = before_by_handle[handle]
    after_row = after_by_handle[handle]
    next if before_row == after_row

    {
      'handle' => handle,
      'object_type' => before_row[0],
      'missing_after' => after_row.nil?,
      'before_sha256' => Digest::SHA256.hexdigest(before_row[2]),
      'after_sha256' => after_row ? Digest::SHA256.hexdigest(after_row[2]) : nil
    }
  end
  warn("protected_source_objects_changed_detail:#{JSON.generate(changed.first(20))}")
  fail_closed('protected_source_objects_changed')
end

FileUtils.mkdir_p(output_dir)
derived_osm = File.join(output_dir, 'derived.osm')
saved = model.save(OpenStudio::Path.new(derived_osm), true)
fail_closed('derived_osm_save_failed') unless saved

forward = OpenStudio::EnergyPlus::ForwardTranslator.new
workspace = forward.translateModel(model)
fail_closed('forward_translation_errors') unless forward.errors.empty?
derived_idf = File.join(output_dir, 'derived.idf')
saved_idf = workspace.save(OpenStudio::Path.new(derived_idf), true)
fail_closed('derived_idf_save_failed') unless saved_idf

source_sha_after = Digest::SHA256.file(source).hexdigest
fail_closed('source_hash_changed') unless source_sha_before == source_sha_after
after_counts = counts(model)
provenance = {
  'schema_version' => 'idfrepair.room-aware-people-derivative.v1',
  'scenario_id' => manifest['scenario_id'],
  'source_alias' => manifest['source_alias'] || 'Terminal Model A',
  'source_sha256_before' => source_sha_before,
  'source_sha256_after' => source_sha_after,
  'source_unchanged' => true,
  'manifest_sha256' => manifest_sha,
  'openstudio_version' => OpenStudio::openStudioVersion,
  'osm_schema_version' => model.version.str,
  'before_counts' => before_counts,
  'after_counts' => after_counts,
  'people_removed' => people_removed,
  'people_definitions_removed' => people_definitions_removed,
  'people_added' => manifest_spaces.size,
  'people_definitions_added' => manifest_spaces.size,
  'ideal_loads_added' => ideal_loads_added,
  'orphan_zones_skipped' => orphan_zones_skipped,
  'zones_with_existing_equipment' => zones_with_existing_equipment,
  'protected_source_object_count' => protected_before.size,
  'protected_snapshot_sha256_before' => protected_sha_before,
  'protected_snapshot_sha256_after' => protected_sha_after,
  'protected_source_objects_unchanged' => protected_unchanged,
  'thermal_zone_semantics_sha256_before' => zone_semantics_sha_before,
  'thermal_zone_semantics_sha256_after' => zone_semantics_sha_after,
  'thermal_zone_source_semantics_unchanged' => zone_semantics_unchanged,
  'non_people_fields_modified' => 0,
  'modifications' => modifications,
  'derived_osm_sha256' => Digest::SHA256.file(derived_osm).hexdigest,
  'derived_idf_sha256' => Digest::SHA256.file(derived_idf).hexdigest,
  'forward_translation_warning_count' => forward.warnings.size,
  'forward_translation_error_count' => forward.errors.size,
  'forward_translation_warnings' => forward.warnings.map(&:logMessage)
}
provenance_path = File.join(output_dir, 'provenance.json')
File.write(provenance_path, JSON.pretty_generate(provenance) + "\n")
puts JSON.generate({
  'status' => 'people_derivative_complete',
  'source_sha256' => source_sha_after,
  'people_added' => manifest_spaces.size,
  'ideal_loads_added' => ideal_loads_added,
  'protected_source_objects_unchanged' => protected_unchanged,
  'derived_osm_sha256' => provenance['derived_osm_sha256'],
  'derived_idf_sha256' => provenance['derived_idf_sha256']
})
