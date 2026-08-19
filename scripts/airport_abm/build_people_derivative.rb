# frozen_string_literal: true

# Build a People-only OpenStudio derivative. Source identity is checked outside
# this program; this program only proves byte-for-byte source immutability while
# it runs and never writes to the source path.

require 'fileutils'
require 'json'
require 'optparse'


SCHEMA = 'idfrepair.airport-abm-people-manifest.v3'
MUTABLE_TYPES = %w[
  OS_People
  OS_Schedule_File
  OS_External_File
].freeze

OUTPUT_VARIABLES = [
  'Space People Occupant Count',
  'Space People Total Heating Energy',
  'Zone People Sensible Heating Energy',
  'Zone People Latent Gain Energy',
  'Zone People Radiant Heating Energy',
  'Zone Air System Sensible Heating Energy',
  'Zone Air System Sensible Cooling Energy',
  'Zone Air Temperature',
  'Zone Air Relative Humidity',
  'Zone Air Terminal Outdoor Air Volume Flow Rate',
  'Facility Total HVAC Electricity Demand Rate',
  'Facility Heating Setpoint Not Met While Occupied Time',
  'Facility Cooling Setpoint Not Met While Occupied Time',
  'Air System Outdoor Air Mass Flow Rate',
  'Air System Fan Electricity Energy',
  'Air System Total Heating Energy',
  'Air System Total Cooling Energy',
  'Fan Electricity Energy',
  'Fan Coil Fan Electricity Energy',
  'Pump Electricity Energy'
].freeze

OUTPUT_METERS = [
  'Electricity:Facility',
  'Fans:Electricity',
  'Pumps:Electricity',
  'DistrictCooling:Facility',
  'DistrictHeating:Facility'
].freeze


def fail_closed(message)
  warn(message)
  exit(2)
end


def within_root?(path, root)
  path == root || path.start_with?(root + File::SEPARATOR)
end


def object_type(object)
  object.iddObject.type.valueName
end


def protected_rows(model, handles = nil)
  model.objects.filter_map do |object|
    type = object_type(object)
    next if MUTABLE_TYPES.include?(type)
    next if handles && !handles.include?(object.handle.to_s)

    [type, object.handle.to_s, object.to_s]
  end.sort_by { |row| [row[0], row[1]] }
end


def inventory(model)
  {
    'spaces' => model.getSpaces.size,
    'thermal_zones' => model.getThermalZones.size,
    'people' => model.getPeoples.size,
    'people_definitions' => model.getPeopleDefinitions.size,
    'space_types' => model.getSpaceTypes.size,
    'lights' => model.getLightss.size,
    'electric_equipment' => model.getElectricEquipments.size,
    'dsoa' => model.getDesignSpecificationOutdoorAirs.size,
    'air_loops' => model.getAirLoopHVACs.size,
    'plant_loops' => model.getPlantLoops.size,
    'fan_coils' => model.getZoneHVACFourPipeFanCoils.size,
    'zone_exhaust_fans' => model.getFanZoneExhausts.size,
    'heat_recovery' => model.getHeatExchangerAirToAirSensibleAndLatents.size,
    'ideal_loads' => model.getZoneHVACIdealLoadsAirSystems.size,
    'output_variables' => model.getOutputVariables.size
  }
end


def exact_space(model, name)
  matches = model.getSpaces.select { |space| space.nameString == name }
  fail_closed("space_not_unique:#{name}:#{matches.size}") unless matches.one?
  matches.first
end


def source_people_for(space)
  direct = space.people
  fail_closed("source_direct_people_not_supported:#{space.nameString}") unless direct.empty?
  space_type = space.spaceType
  return [] if space_type.empty?

  space_type.get.people
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

source_bytes_before = File.binread(source)
manifest = JSON.parse(File.read(manifest_path, encoding: 'UTF-8'))
fail_closed('manifest_schema_invalid') unless manifest['schema_version'] == SCHEMA
days = Integer(manifest.fetch('calendar_days'))
interval = Integer(manifest.fetch('interval_minutes'))
fail_closed('calendar_days_invalid') unless [365, 366].include?(days)
fail_closed('interval_minutes_invalid') unless interval == 15
schedule_path = File.expand_path(manifest.fetch('schedule_file'))
fail_closed('schedule_file_not_found') unless File.file?(schedule_path)
fail_closed('schedule_file_outside_allowed_root') unless within_root?(schedule_path, allowed_root)
rows = manifest.fetch('spaces')
fail_closed('manifest_spaces_invalid') unless rows.is_a?(Array) && !rows.empty?
names = rows.map { |row| row['source_space_name'] }
fail_closed('manifest_space_name_invalid') if names.any? { |name| !name.is_a?(String) || name.empty? }
fail_closed('manifest_space_name_duplicate') unless names.uniq.size == names.size
columns = rows.map { |row| Integer(row.fetch('schedule_column')) }
fail_closed('manifest_schedule_column_duplicate') unless columns.uniq.size == columns.size
fail_closed('manifest_schedule_column_invalid') if columns.any? { |value| value <= 0 }

translator = OpenStudio::OSVersion::VersionTranslator.new
loaded = translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_model_load_failed') if loaded.empty?
model = loaded.get
before_counts = inventory(model)
before_rows = protected_rows(model)
before_handles = before_rows.map { |row| row[1] }
original_people = model.getPeoples.to_a

occupancy_limits = OpenStudio::Model::ScheduleTypeLimits.new(model)
occupancy_limits.setName('IDFRepair V3 Occupancy Multiplier')
fail_closed('occupancy_limits_lower_failed') unless occupancy_limits.setLowerLimitValue(0.0)
fail_closed('occupancy_limits_numeric_failed') unless occupancy_limits.setNumericType('Continuous')
fail_closed('occupancy_limits_unit_failed') unless occupancy_limits.setUnitType('Dimensionless')

external = OpenStudio::Model::ExternalFile.getExternalFile(
  model,
  schedule_path,
  false
)
fail_closed('external_schedule_file_unavailable') if external.empty?

created = []
rows.sort_by { |row| row.fetch('source_space_name') }.each do |row|
  name = row.fetch('source_space_name')
  space = exact_space(model, name)
  templates = source_people_for(space)
  fail_closed("source_people_template_not_unique:#{name}:#{templates.size}") unless templates.one?
  template = templates.first
  expected = Float(row.fetch('source_design_people'))
  actual = template.getNumberOfPeople(space.floorArea)
  tolerance = Float(row.fetch('source_design_people_tolerance'))
  if !tolerance.finite? || tolerance <= 0 || tolerance > 0.001
    fail_closed("source_design_people_tolerance_invalid:#{name}:#{tolerance}")
  end
  if !expected.finite? || expected <= 0 || (actual - expected).abs > tolerance
    fail_closed("source_design_people_mismatch:#{name}:#{actual}:#{expected}")
  end

  schedule = OpenStudio::Model::ScheduleFile.new(
    external.get,
    Integer(row.fetch('schedule_column')),
    1
  )
  schedule.setName("IDFRepair V3 Occupancy :: #{name}")
  fail_closed("schedule_separator_failed:#{name}") unless schedule.setColumnSeparator('Comma')
  fail_closed("schedule_interval_failed:#{name}") unless schedule.setMinutesperItem(interval)
  fail_closed("schedule_interpolation_failed:#{name}") unless schedule.setInterpolatetoTimestep(false)
  fail_closed("schedule_dst_failed:#{name}") unless schedule.setAdjustScheduleforDaylightSavings(false)
  hours = days == 366 ? 8784 : 8760
  fail_closed("schedule_hours_failed:#{name}") unless schedule.setNumberofHoursofData(hours)

  direct = template.clone(model).to_People
  fail_closed("people_clone_failed:#{name}") if direct.empty?
  people = direct.get
  people.setName("IDFRepair V3 People :: #{name}")
  fail_closed("people_space_assignment_failed:#{name}") unless people.setSpace(space)
  unless people.setNumberofPeopleSchedule(schedule)
    fail_closed("people_schedule_assignment_failed:#{name}")
  end
  unless schedule.setScheduleTypeLimits(occupancy_limits)
    fail_closed("schedule_type_limits_assignment_failed:#{name}")
  end
  created << people
end

original_people.each(&:remove)
fail_closed('source_people_removal_incomplete') unless model.getPeoples.size == created.size
fail_closed('direct_people_assignment_incomplete') unless created.all? { |people| people.space.is_initialized }
fail_closed('space_type_people_remains') unless model.getSpaceTypes.all? { |space_type| space_type.people.empty? }

OUTPUT_VARIABLES.each do |name|
  request = OpenStudio::Model::OutputVariable.new(name, model)
  request.setKeyValue('*')
  fail_closed("output_frequency_failed:#{name}") unless request.setReportingFrequency('Timestep')
end
if model.getOptionalOutputSQLite.empty?
  sqlite = model.getOutputSQLite
  fail_closed('output_sqlite_option_failed') unless sqlite.setOptionType('SimpleAndTabular')
end

manifest_names = names.to_h { |name| [name, true] }
flow_only = model.getSpaces.filter_map do |space|
  next if manifest_names.key?(space.nameString)
  next unless source_people_for(space).empty?

  space.nameString
end.sort

after_rows = protected_rows(model, before_handles)
protected_unchanged = before_rows == after_rows
fail_closed('protected_objects_changed') unless protected_unchanged
after_counts = inventory(model)
fail_closed('ideal_loads_changed') unless after_counts['ideal_loads'] == before_counts['ideal_loads']
%w[air_loops plant_loops fan_coils zone_exhaust_fans heat_recovery dsoa lights electric_equipment].each do |key|
  fail_closed("protected_inventory_changed:#{key}") unless after_counts[key] == before_counts[key]
end

FileUtils.mkdir_p(output_dir)
derived_osm = File.join(output_dir, 'derived.osm')
saved = model.save(OpenStudio::Path.new(derived_osm), true)
fail_closed('derived_osm_save_failed') unless saved

forward = OpenStudio::EnergyPlus::ForwardTranslator.new
workspace = forward.translateModel(model)
fail_closed('forward_translation_errors') unless forward.errors.empty?
OUTPUT_METERS.each do |name|
  request = OpenStudio::IdfObject.load("Output:Meter,#{name},Timestep;")
  fail_closed("output_meter_object_failed:#{name}") if request.empty?
  added = workspace.addObject(request.get)
  fail_closed("output_meter_add_failed:#{name}") if added.empty?
end
derived_idf = File.join(output_dir, 'derived.idf')
saved_idf = workspace.save(OpenStudio::Path.new(derived_idf), true)
fail_closed('derived_idf_save_failed') unless saved_idf

source_unchanged = File.binread(source) == source_bytes_before
fail_closed('source_bytes_changed') unless source_unchanged
summary = {
  'schema_version' => 'idfrepair.airport-abm-people-derivative.v3',
  'source_unchanged' => source_unchanged,
  'protected_objects_unchanged' => protected_unchanged,
  'before_counts' => before_counts,
  'after_counts' => after_counts,
  'people_removed_from_space_types' => original_people.size,
  'direct_space_people_added' => created.size,
  'flow_only_spaces_without_people' => flow_only,
  'schedule_calendar_days' => days,
  'schedule_interval_minutes' => interval,
  'timestep_output_variables_added' => OUTPUT_VARIABLES,
  'timestep_output_meters_added' => OUTPUT_METERS,
  'forward_translation_warning_count' => forward.warnings.size,
  'forward_translation_error_count' => forward.errors.size,
  'forward_translation_warnings' => forward.warnings.map(&:logMessage)
}
File.write(
  File.join(output_dir, 'derivative_summary.json'),
  JSON.pretty_generate(summary) + "\n"
)
puts JSON.generate({
  'status' => 'people_only_derivative_complete',
  'source_unchanged' => source_unchanged,
  'direct_space_people_added' => created.size,
  'ideal_loads_added' => after_counts['ideal_loads'] - before_counts['ideal_loads']
})
