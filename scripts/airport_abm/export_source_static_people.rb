# frozen_string_literal: true

require 'csv'
require 'fileutils'
require 'json'
require 'optparse'


SCHEMA = 'idfrepair.airport-source-static-people.v31'
FUNCTION_ALIASES = {
  'general_commercial' => 'commercial',
  'staff_breakroom' => 'breakroom',
  'information_room' => 'info'
}.freeze
STAFF_FUNCTIONS = %w[office breakroom].freeze


def fail_closed(message)
  warn(message)
  exit(2)
end


def source_people_for(space)
  direct = space.people
  return direct unless direct.empty?

  space_type = space.spaceType
  return [] if space_type.empty?

  space_type.get.people
end


def exact_space(model, name)
  matches = model.getSpaces.select { |space| space.nameString == name }
  fail_closed("space_not_unique:#{name}:#{matches.size}") unless matches.one?
  matches.first
end


def default_day_profile(schedule)
  ruleset = schedule.to_ScheduleRuleset
  fail_closed("people_schedule_not_ruleset:#{schedule.nameString}") if ruleset.empty?
  day = ruleset.get.defaultDaySchedule
  (0...96).map do |index|
    midpoint_seconds = index * 15 * 60 + 7 * 60 + 30
    value = day.getValue(OpenStudio::Time.new(0, 0, 0, midpoint_seconds))
    fail_closed("schedule_value_invalid:#{schedule.nameString}:#{index}") unless value.finite? && value >= 0
    value
  end
end


options = {}
OptionParser.new do |parser|
  parser.on('--input PATH') { |value| options[:input] = value }
  parser.on('--mapping PATH') { |value| options[:mapping] = value }
  parser.on('--output PATH') { |value| options[:output] = value }
end.parse!
%i[input mapping output].each { |key| fail_closed("#{key}_missing") unless options[key] }

source = File.expand_path(options[:input])
mapping_path = File.expand_path(options[:mapping])
output = File.expand_path(options[:output])
fail_closed('source_not_found') unless File.file?(source)
fail_closed('mapping_not_found') unless File.file?(mapping_path)
fail_closed('output_must_not_replace_source') if output == source
source_bytes = File.binread(source)

translator = OpenStudio::OSVersion::VersionTranslator.new
loaded = translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_model_load_failed') if loaded.empty?
model = loaded.get

required = %w[
  space thermal_zone region function original_space_type area_m2
  people_m2_per_person public_air_loop office_doas zone_hvac
]
mapping = CSV.read(mapping_path, headers: true, encoding: 'bom|utf-8')
missing = required - mapping.headers.compact
fail_closed("mapping_columns_missing:#{missing.sort.join(',')}") unless missing.empty?
fail_closed('mapping_space_count_mismatch') unless mapping.size == model.getSpaces.size

profiles = {}
spaces = []
flow_only = []
public_person_hours = 0.0
staff_person_hours = 0.0

mapping.each_with_index do |row, index|
  name = row['space'].to_s.strip
  fail_closed("mapping_space_missing:#{index + 2}") if name.empty?
  space = exact_space(model, name)
  function_source = row['function'].to_s.strip
  function = FUNCTION_ALIASES.fetch(function_source, function_source)
  region = row['region'].to_s.strip
  hvac_group = [row['public_air_loop'], row['office_doas'], row['zone_hvac']]
               .map { |value| value.to_s.strip }
               .find { |value| !value.empty? } || 'NO_SOURCE_HVAC_GROUP'
  raw_density = row['people_m2_per_person'].to_s.strip
  people = source_people_for(space)
  if raw_density.empty?
    fail_closed("flow_only_has_source_people:#{name}") unless people.empty?
    flow_only << name
    next
  end
  fail_closed("source_people_not_unique:#{name}:#{people.size}") unless people.one?
  density = Float(raw_density)
  area = Float(row['area_m2'])
  fail_closed("mapping_people_reference_invalid:#{name}") unless density.positive? && area.positive?
  design_people = area / density
  actual_design_people = people.first.getNumberOfPeople(space.floorArea)
  tolerance = 0.0005 / density + 1.0e-9
  if (actual_design_people - design_people).abs > tolerance
    fail_closed("source_people_reference_mismatch:#{name}:#{actual_design_people}:#{design_people}")
  end
  schedule_optional = people.first.numberofPeopleSchedule
  fail_closed("source_people_schedule_missing:#{name}") if schedule_optional.empty?
  schedule = schedule_optional.get
  multiplier = profiles[schedule.handle.to_s] ||= default_day_profile(schedule)
  counts = multiplier.map { |value| value * design_people }
  person_hours = counts.sum * 0.25
  if STAFF_FUNCTIONS.include?(function)
    staff_person_hours += person_hours
  else
    public_person_hours += person_hours
  end
  spaces << {
    'space_name' => name,
    'function' => function,
    'region' => region,
    'hvac_group' => hvac_group,
    'source_design_people' => design_people,
    'occupant_counts' => counts
  }
end

fail_closed('supported_space_count_mismatch') unless spaces.size + flow_only.size == mapping.size
source_unchanged = File.binread(source) == source_bytes
fail_closed('source_bytes_changed') unless source_unchanged
payload = {
  'schema_version' => SCHEMA,
  'source_unchanged' => source_unchanged,
  'interval_minutes' => 15,
  'source_supported_space_count' => spaces.size,
  'flow_only_space_count' => flow_only.size,
  'public_person_hours' => public_person_hours,
  'staff_person_hours' => staff_person_hours,
  'spaces' => spaces.sort_by { |row| row['space_name'] }
}
FileUtils.mkdir_p(File.dirname(output))
File.write(output, JSON.pretty_generate(payload) + "\n")
puts JSON.generate({
  'status' => 'PASS',
  'source_supported_space_count' => spaces.size,
  'flow_only_space_count' => flow_only.size,
  'source_unchanged' => source_unchanged
})
