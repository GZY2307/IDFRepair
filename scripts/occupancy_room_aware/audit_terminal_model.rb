# frozen_string_literal: true

# 对指定 OSM 做源只读、fail-closed 的房间功能与 People/OA 审计。

require 'digest'
require 'fileutils'
require 'json'
require 'optparse'


ROOM_TOKENS = {
  'hall' => 'terminal_hall',
  'office' => 'office',
  'commerce' => 'commerce_retail',
  'dining' => 'dining',
  'restroom' => 'restroom',
  'breakroom' => 'breakroom'
}.freeze


def fail_closed(message)
  warn(message)
  exit(2)
end


def optional_name(value)
  value.is_initialized ? value.get.nameString : nil
end


def classify_space_name(name)
  matches = ROOM_TOKENS.keys.select do |token|
    name.match?(/(?<![A-Za-z])#{Regexp.escape(token)}(?![A-Za-z])/i)
  end
  return [ROOM_TOKENS.fetch(matches.first), matches] if matches.one?

  [nil, matches]
end


def people_definition(definition)
  method = if definition.numberofPeople.is_initialized
             'People'
           elsif definition.peopleperSpaceFloorArea.is_initialized
             'People/Area'
           elsif definition.spaceFloorAreaPerPerson.is_initialized
             'Area/Person'
           else
             'Unknown'
           end
  value = case method
          when 'People' then definition.numberofPeople.get
          when 'People/Area' then definition.peopleperSpaceFloorArea.get
          when 'Area/Person' then definition.spaceFloorAreaPerPerson.get
          end
  {
    'name' => definition.nameString,
    'method' => method,
    'value' => value,
    'fraction_radiant' => definition.fractionRadiant,
    'sensible_heat_fraction' => (
      definition.sensibleHeatFraction.is_initialized ? definition.sensibleHeatFraction.get : nil
    ),
    'co2_generation_rate_m3_s_person' => definition.carbonDioxideGenerationRate
  }
end


def people_record(person, source_kind, source_name)
  {
    'name' => person.nameString,
    'source_kind' => source_kind,
    'source_name' => source_name,
    'definition' => people_definition(person.peopleDefinition),
    'count_schedule' => optional_name(person.numberofPeopleSchedule),
    'activity_schedule' => optional_name(person.activityLevelSchedule)
  }
end


def oa_record(oa)
  {
    'name' => oa.nameString,
    'method' => oa.outdoorAirMethod,
    'flow_per_person_m3_s_person' => oa.outdoorAirFlowperPerson,
    'flow_per_area_m3_s_m2' => oa.outdoorAirFlowperFloorArea,
    'flow_rate_m3_s' => oa.outdoorAirFlowRate,
    'ach_per_h' => oa.outdoorAirFlowAirChangesperHour,
    'schedule' => optional_name(oa.outdoorAirFlowRateFractionSchedule)
  }
end


def exterior_area(space)
  space.surfaces.select do |surface|
    surface.outsideBoundaryCondition.casecmp('Outdoors').zero?
  end.sum(&:grossArea)
end


def metadata_conflicts(category, explicit_space_type)
  return [] if explicit_space_type.nil?

  lowered = explicit_space_type.downcase
  case category
  when 'terminal_hall'
    lowered.include?('hall') ? [] : ['hall_name_vs_explicit_space_type']
  when 'office'
    return ['office_name_vs_it_room_space_type'] if lowered.include?('it_room')

    (lowered.include?('office') ? [] : ['office_name_vs_explicit_space_type'])
  when 'commerce_retail'
    (lowered.match?(/commerce|retail/) ? [] : ['commerce_name_vs_explicit_space_type'])
  when 'dining'
    (lowered.match?(/dining|restaurant/) ? [] : ['dining_name_vs_explicit_space_type'])
  when 'restroom'
    (lowered.match?(/restroom|toilet/) ? [] : ['restroom_name_vs_explicit_space_type'])
  when 'breakroom'
    (lowered.match?(/breakroom|break room/) ? [] : ['breakroom_name_vs_explicit_space_type'])
  else
    ['unrecognized_room_category']
  end
end


def non_people_snapshot(model)
  excluded = %w[OS_People OS_People_Definition]
  rows = model.objects.reject do |object|
    excluded.include?(object.iddObject.type.valueName)
  end.map do |object|
    [object.iddObject.type.valueName, object.handle.to_s, object.to_s]
  end.sort_by { |row| [row[0], row[1]] }
  serialized = rows.map { |row| row.join("\u001f") }.join("\u001e")
  [rows.size, Digest::SHA256.hexdigest(serialized)]
end


options = {}
OptionParser.new do |parser|
  parser.on('--input PATH') { |value| options[:input] = value }
  parser.on('--output PATH') { |value| options[:output] = value }
end.parse!

fail_closed('input_missing') unless options[:input]
fail_closed('output_missing') unless options[:output]
source = File.expand_path(options[:input])
output = File.expand_path(options[:output])
fail_closed('source_not_found') unless File.file?(source)
fail_closed('output_must_not_equal_source') if source == output

source_sha_before = Digest::SHA256.file(source).hexdigest
translator = OpenStudio::OSVersion::VersionTranslator.new
loaded = translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_model_load_failed') if loaded.empty?
model = loaded.get
building = model.getBuilding

rejections = []
spaces = model.getSpaces.sort_by(&:nameString).map do |space|
  category, tokens = classify_space_name(space.nameString)
  if category.nil?
    rejection_kind = tokens.empty? ? 'UNKNOWN_ROOM_TOKEN' : 'MULTIPLE_ROOM_TOKENS'
    rejections << {
      'source_space_name' => space.nameString,
      'kind' => rejection_kind,
      'matched_tokens' => tokens
    }
    next
  end

  effective_type = space.spaceType
  is_defaulted = space.isSpaceTypeDefaulted
  explicit_type_name = is_defaulted ? nil : optional_name(effective_type)
  effective_type_name = optional_name(effective_type)
  people_sources = space.people.map do |person|
    people_record(person, 'direct_space', space.nameString)
  end
  if effective_type.is_initialized
    source_kind = is_defaulted ? 'building_default_space_type' : 'space_type'
    people_sources.concat(
      effective_type.get.people.map do |person|
        people_record(person, source_kind, effective_type.get.nameString)
      end
    )
  end
  effective_oa = space.designSpecificationOutdoorAir
  conflicts = metadata_conflicts(category, explicit_type_name)
  metadata_status = if conflicts.empty?
                      is_defaulted ? 'SOURCE_METADATA_DEFAULTED' : 'SOURCE_METADATA_CONSISTENT'
                    else
                      'SOURCE_METADATA_CONFLICT'
                    end
  floor_area = space.floorArea
  design_people = space.numberOfPeople
  density = floor_area.positive? ? design_people / floor_area : nil
  {
    'source_space_name' => space.nameString,
    'source_handle' => space.handle.to_s,
    'matched_token' => tokens.first,
    'room_category' => category,
    'classification_status' => 'CLASSIFIED',
    'floor_area_m2' => floor_area,
    'exterior_area_m2' => exterior_area(space),
    'thermal_zone' => optional_name(space.thermalZone),
    'space_type_defaulted' => is_defaulted,
    'explicit_space_type' => explicit_type_name,
    'effective_space_type' => effective_type_name,
    'metadata_status' => metadata_status,
    'metadata_conflicts' => conflicts,
    'design_people' => design_people,
    'people_per_m2' => density,
    'm2_per_person' => density&.positive? ? 1.0 / density : nil,
    'people_sources' => people_sources,
    'oa_defaulted' => space.isDesignSpecificationOutdoorAirDefaulted,
    'oa' => effective_oa.is_initialized ? oa_record(effective_oa.get) : nil
  }
end.compact

unless rejections.empty?
  fail_closed("space_classification_rejected:#{JSON.generate(rejections)}")
end

category_counts = spaces.group_by { |space| space.fetch('room_category') }
                        .transform_values(&:size)
zones = model.getThermalZones.sort_by(&:nameString).map do |zone|
  {
    'name' => zone.nameString,
    'space_names' => zone.spaces.map(&:nameString).sort,
    'equipment' => zone.equipment.map do |item|
      {
        'object_type' => item.iddObjectType.valueName,
        'name' => item.nameString
      }
    end
  }
end
non_people_count, non_people_sha = non_people_snapshot(model)
source_sha_after = Digest::SHA256.file(source).hexdigest
fail_closed('source_hash_changed') unless source_sha_before == source_sha_after

result = {
  'schema_version' => 'idfrepair.room-aware-source-audit.v1',
  'source_alias' => 'Terminal Model A',
  'source_sha256_before' => source_sha_before,
  'source_sha256_after' => source_sha_after,
  'source_unchanged' => true,
  'openstudio_version' => OpenStudio::openStudioVersion,
  'osm_schema_version' => model.version.str,
  'building_default_space_type' => optional_name(building.spaceType),
  'space_count' => spaces.size,
  'thermal_zone_count' => zones.size,
  'orphan_zones' => zones.select { |zone| zone.fetch('space_names').empty? }
                         .map { |zone| zone.fetch('name') },
  'category_counts' => category_counts,
  'classification_rejections' => [],
  'metadata_conflict_count' => spaces.count do |space|
    space.fetch('metadata_status') == 'SOURCE_METADATA_CONFLICT'
  end,
  'non_people_snapshot_object_count' => non_people_count,
  'non_people_snapshot_sha256' => non_people_sha,
  'spaces' => spaces,
  'zones' => zones
}

FileUtils.mkdir_p(File.dirname(output))
File.write(output, JSON.pretty_generate(result) + "\n")
puts JSON.generate({
  'status' => 'audit_complete',
  'source_alias' => result.fetch('source_alias'),
  'source_sha256' => source_sha_after,
  'space_count' => result.fetch('space_count'),
  'thermal_zone_count' => result.fetch('thermal_zone_count'),
  'category_counts' => category_counts,
  'metadata_conflict_count' => result.fetch('metadata_conflict_count'),
  'orphan_zones' => result.fetch('orphan_zones')
})
