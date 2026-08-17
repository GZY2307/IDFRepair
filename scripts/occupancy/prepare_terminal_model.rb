# frozen_string_literal: true

# Read-only OpenStudio preparation for controlled terminal occupancy studies.
# The source OSM is loaded but never saved. All translation and optional
# Ideal Loads supplementation is written to an explicit derived directory.

require 'digest'
require 'fileutils'
require 'json'
require 'optparse'


def fail_closed(message)
  warn(message)
  exit(2)
end


def model_counts(model)
  zone_equipment = model.getThermalZones.flat_map(&:equipment).uniq do |item|
    item.handle.to_s
  end
  real_zone_equipment = zone_equipment.reject do |item|
    item.iddObjectType.valueName == 'OS_ZoneHVAC_IdealLoadsAirSystem'
  end
  {
    'spaces' => model.getSpaces.size,
    'thermal_zones' => model.getThermalZones.size,
    'people' => model.getPeoples.size,
    'people_definitions' => model.getPeopleDefinitions.size,
    'schedules' => model.getSchedules.size,
    'air_loops' => model.getAirLoopHVACs.size,
    'plant_loops' => model.getPlantLoops.size,
    'ideal_loads' => model.getZoneHVACIdealLoadsAirSystems.size,
    'zone_equipment' => zone_equipment.size,
    'real_zone_equipment' => real_zone_equipment.size,
    'weather_assigned' => model.weatherFile.is_initialized
  }
end


options = { mode: 'translate' }
OptionParser.new do |parser|
  parser.on('--input PATH') { |value| options[:input] = value }
  parser.on('--output-dir PATH') { |value| options[:output_dir] = value }
  parser.on('--mode MODE') { |value| options[:mode] = value }
end.parse!

fail_closed('input_missing') unless options[:input]
fail_closed('output_directory_missing') unless options[:output_dir]
unless %w[translate ideal-loads-demo].include?(options[:mode])
  fail_closed("unsupported_mode:#{options[:mode]}")
end

source = File.expand_path(options[:input])
output_dir = File.expand_path(options[:output_dir])
fail_closed('output_must_not_equal_source') if source == output_dir
fail_closed("source_not_found:#{source}") unless File.file?(source)
fail_closed("output_is_file:#{output_dir}") if File.file?(output_dir)

source_sha_before = Digest::SHA256.file(source).hexdigest
translator = OpenStudio::OSVersion::VersionTranslator.new
loaded = translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_model_load_failed') if loaded.empty?
model = loaded.get
before_counts = model_counts(model)

FileUtils.mkdir_p(output_dir)
synthetic_added = 0
synthetic_skipped_no_spaces = 0
derived_osm = nil
if options[:mode] == 'ideal-loads-demo'
  model.getThermalZones.each do |zone|
    next unless zone.equipment.empty?
    if zone.spaces.empty?
      synthetic_skipped_no_spaces += 1
      next
    end

    ideal = OpenStudio::Model::ZoneHVACIdealLoadsAirSystem.new(model)
    ideal.setName("IDFRepair Synthetic Ideal Loads #{synthetic_added + 1}")
    fail_closed('ideal_loads_assignment_failed') unless ideal.addToThermalZone(zone)
    synthetic_added += 1
  end
  derived_osm = File.join(output_dir, 'derived.osm')
  saved = model.save(OpenStudio::Path.new(derived_osm), true)
  fail_closed('derived_osm_save_failed') unless saved
end

forward = OpenStudio::EnergyPlus::ForwardTranslator.new
workspace = forward.translateModel(model)
derived_idf = File.join(output_dir, 'derived.idf')
saved_idf = workspace.save(OpenStudio::Path.new(derived_idf), true)
fail_closed('derived_idf_save_failed') unless saved_idf

source_sha_after = Digest::SHA256.file(source).hexdigest
fail_closed('source_hash_changed') unless source_sha_before == source_sha_after

provenance = {
  'schema_version' => 1,
  'mode' => options[:mode],
  'source_basename' => File.basename(source),
  'source_sha256_before' => source_sha_before,
  'source_sha256_after' => source_sha_after,
  'source_unchanged' => true,
  'openstudio_version' => OpenStudio::openStudioVersion,
  'osm_schema_version' => model.version.str,
  'before_counts' => before_counts,
  'after_counts' => model_counts(model),
  'synthetic_hvac_demo' => options[:mode] == 'ideal-loads-demo',
  'synthetic_ideal_loads_added' => synthetic_added,
  'synthetic_zones_skipped_no_spaces' => synthetic_skipped_no_spaces,
  'derived_idf_sha256' => Digest::SHA256.file(derived_idf).hexdigest,
  'derived_osm_sha256' => derived_osm ? Digest::SHA256.file(derived_osm).hexdigest : nil,
  'forward_translation_warning_count' => forward.warnings.size,
  'forward_translation_error_count' => forward.errors.size,
  'forward_translation_warnings' => forward.warnings.map(&:logMessage),
  'forward_translation_errors' => forward.errors.map(&:logMessage)
}
provenance_path = File.join(output_dir, 'provenance.json')
File.write(provenance_path, JSON.pretty_generate(provenance) + "\n")
puts(JSON.generate(provenance))
