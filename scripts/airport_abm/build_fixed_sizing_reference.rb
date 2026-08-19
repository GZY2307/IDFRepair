# frozen_string_literal: true

require 'fileutils'
require 'json'
require 'optparse'


SCHEMA = 'idfrepair.airport-fixed-sizing-audit.v31'


def fail_closed(message)
  warn(message)
  exit(2)
end


def category_for(object_type)
  case object_type
  when /^OS_Fan_/
    'Fan'
  when /^OS_Coil_/
    'Coil'
  when /^OS_AirTerminal_SingleDuct_VAV/
    'VAV terminal'
  when /^OS_AirTerminal_/
    'Air terminal'
  when /^OS_AirLoopHVAC/
    'AirLoop'
  when /^OS_PlantLoop/, /^OS_DistrictCooling/, /^OS_DistrictHeating/
    'PlantLoop'
  when /^OS_Pump_/
    'Pump'
  when /^OS_ZoneHVAC_FourPipeFanCoil/
    'FourPipeFanCoil'
  when /OutdoorAir/
    'OutdoorAir'
  when /^OS_HeatExchanger_/
    'HeatExchanger'
  else
    'Other critical HVAC'
  end
end


def typed_objects(model)
  collection_getters = %i[
    getAirLoopHVACs
    getAirTerminalSingleDuctConstantVolumeNoReheats
    getAirTerminalSingleDuctVAVReheats
    getCoilCoolingWaters
    getCoilHeatingWaters
    getControllerOutdoorAirs
    getControllerWaterCoils
    getDistrictCoolings
    getDistrictHeatings
    getFanConstantVolumes
    getFanOnOffs
    getFanVariableVolumes
    getHeatExchangerAirToAirSensibleAndLatents
    getPlantLoops
    getPumpVariableSpeeds
    getSizingSystems
    getZoneHVACFourPipeFanCoils
  ].freeze
  output = {}
  collection_getters.each do |getter|
    fail_closed("typed_collection_missing:#{getter}") unless model.respond_to?(getter)
    model.send(getter).each do |object|
      handle = object.handle.to_s
      previous = output[handle]
      score = object.methods.grep(/^is.*Autosized$/).size
      previous_score = previous ? previous.methods.grep(/^is.*Autosized$/).size : -1
      output[handle] = object if score > previous_score
    end
  end
  output
end


def model_rows(model)
  model.objects.map do |object|
    [object.iddObject.type.valueName, object.handle.to_s, object.to_s]
  end.sort_by { |row| [row[0], row[1]] }
end


def autosized_fields(objects)
  output = []
  objects.each_value do |object|
    object.methods.grep(/^is.*Autosized$/).sort.each do |predicate|
      begin
        next unless object.send(predicate)

        suffix = predicate.to_s.sub(/^is/, '').sub(/Autosized$/, '')
        autosized_getter = "autosized#{suffix}"
        value_getter = suffix.sub(/^./) { |character| character.downcase }
        setter = "set#{suffix}"
        resetter = "autosize#{suffix}"
        available = false
        if object.respond_to?(autosized_getter)
          optional = object.send(autosized_getter)
          available = optional.respond_to?(:empty?) && !optional.empty?
        end
        output << {
          'handle' => object.handle.to_s,
          'object_type' => object.iddObject.type.valueName,
          'category' => category_for(object.iddObject.type.valueName),
          'predicate' => predicate.to_s,
          'autosized_getter' => autosized_getter,
          'value_getter' => value_getter,
          'setter' => setter,
          'resetter' => resetter,
          'available' => available
        }
      rescue StandardError => error
        fail_closed("autosized_field_probe_failed:#{object.handle}:#{predicate}:#{error.message}")
      end
    end
  end
  output.sort_by { |row| [row['object_type'], row['handle'], row['predicate']] }
end


def numeric_value(object, getter)
  fail_closed("sized_value_getter_missing:#{object.handle}:#{getter}") unless object.respond_to?(getter)
  value = object.send(getter)
  if value.respond_to?(:empty?) && value.respond_to?(:get)
    fail_closed("sized_value_empty:#{object.handle}:#{getter}") if value.empty?
    value = value.get
  end
  fail_closed("sized_value_not_numeric:#{object.handle}:#{getter}") unless value.is_a?(Numeric)
  value
end


def write_sized_values(model, fields, values)
  objects = typed_objects(model)
  fields.each do |field|
    key = [field['handle'], field['predicate']]
    next unless values.key?(key)

    object = objects.fetch(field['handle'])
    setter = field.fetch('setter')
    fail_closed("sized_value_setter_missing:#{object.handle}:#{setter}") unless object.respond_to?(setter)
    result = object.send(setter, values.fetch(key))
    fail_closed("sized_value_set_failed:#{object.handle}:#{setter}") if result == false
    fail_closed("sized_value_remains_autosized:#{object.handle}:#{setter}") if object.send(field['predicate'])
  end
  objects
end


def normalize_originally_autosized_fields(model, fields)
  objects = typed_objects(model)
  fields.each do |field|
    object = objects.fetch(field['handle'])
    resetter = field.fetch('resetter')
    fail_closed("autosize_resetter_missing:#{object.handle}:#{resetter}") unless object.respond_to?(resetter)
    result = object.send(resetter)
    fail_closed("autosize_normalize_failed:#{object.handle}:#{resetter}") if result == false
  end
  model
end


def category_counts(fields, applied_keys, unresolved_keys)
  categories = fields.map { |field| field['category'] }.uniq.sort
  categories.to_h do |category|
    selected = fields.select { |field| field['category'] == category }
    keys = selected.map { |field| [field['handle'], field['predicate']] }
    [
      category,
      {
        'before' => selected.size,
        'available' => selected.count { |field| field['available'] },
        'applied' => keys.count { |key| applied_keys.include?(key) },
        'unresolved' => keys.count { |key| unresolved_keys.include?(key) }
      }
    ]
  end
end


options = {}
OptionParser.new do |parser|
  parser.on('--input PATH') { |value| options[:input] = value }
  parser.on('--sql PATH') { |value| options[:sql] = value }
  parser.on('--output PATH') { |value| options[:output] = value }
  parser.on('--audit PATH') { |value| options[:audit] = value }
end.parse!
%i[input sql output audit].each { |key| fail_closed("#{key}_missing") unless options[key] }

source = File.expand_path(options[:input])
sql_path = File.expand_path(options[:sql])
output = File.expand_path(options[:output])
audit_path = File.expand_path(options[:audit])
fail_closed('source_not_found') unless File.file?(source)
fail_closed('sizing_sql_not_found') unless File.file?(sql_path)
fail_closed('output_must_not_replace_source') if output == source
fail_closed('audit_must_not_replace_source') if audit_path == source
source_bytes = File.binread(source)

translator = OpenStudio::OSVersion::VersionTranslator.new
loaded = translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_model_load_failed') if loaded.empty?
model = loaded.get
objects = typed_objects(model)

sql = OpenStudio::SqlFile.new(OpenStudio::Path.new(sql_path))
fail_closed('sizing_sql_connection_failed') unless sql.connectionOpen
fail_closed('sizing_sql_attach_failed') unless model.setSqlFile(sql)
fields = autosized_fields(objects)
fail_closed('source_has_no_autosized_fields') if fields.empty?
available_count = fields.count { |field| field['available'] }
fail_closed('sizing_sql_has_no_autosized_values') if available_count.zero?

model.applySizingValues
applied_keys = []
unresolved_keys = []
applied_values = {}
fields.each do |field|
  object = objects.fetch(field['handle'])
  key = [field['handle'], field['predicate']]
  if object.send(field['predicate'])
    unresolved_keys << key
  else
    applied_keys << key
    applied_values[key] = numeric_value(object, field.fetch('value_getter'))
  end
end

model.resetSqlFile
sql.close

# Model::applySizingValues also updates some companion fields that were already
# explicit in the source model (for example terminal minimum-flow controls).
# Build the deliverable from a fresh source load and copy only fields that were
# originally autosized, so topology, controls, schedules, constructions, and
# loads remain byte-for-byte equivalent after those allowed fields are reset.
fixed_loaded = translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_fixed_model_reload_failed') if fixed_loaded.empty?
fixed_model = fixed_loaded.get
write_sized_values(fixed_model, fields, applied_values)

# Prove that the fixed model differs from SOURCE_STATIC only at fields that were
# originally autosized. OpenStudio serializes some equivalent source states as
# blank and others as the literal "Autosize", so normalize those allowed fields
# on independent source and audit copies before comparing every model object.
audit_loaded = translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_audit_model_reload_failed') if audit_loaded.empty?
audit_model = audit_loaded.get
write_sized_values(audit_model, fields, applied_values)
normalize_originally_autosized_fields(audit_model, fields)

protected_source_loaded = translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_protected_source_reload_failed') if protected_source_loaded.empty?
protected_source_model = protected_source_loaded.get
normalize_originally_autosized_fields(protected_source_model, fields)

before_rows = model_rows(protected_source_model)
restored_rows = model_rows(audit_model)
protected_unchanged = restored_rows == before_rows
source_unchanged = File.binread(source) == source_bytes
fail_closed('source_bytes_changed') unless source_unchanged
unless protected_unchanged
  before_by_handle = before_rows.to_h { |row| [row[1], row] }
  restored_by_handle = restored_rows.to_h { |row| [row[1], row] }
  changed = (before_by_handle.keys | restored_by_handle.keys).filter_map do |handle|
    before = before_by_handle[handle]
    after = restored_by_handle[handle]
    next if before == after

    {
      'handle' => handle,
      'before_type' => before&.first,
      'after_type' => after&.first,
      'before' => before&.last,
      'after' => after&.last
    }
  end
  warn(JSON.generate({
    'diagnostic' => 'restored_model_difference',
    'changed_object_count' => changed.size,
    'changed_types' => changed.map { |row| row['before_type'] || row['after_type'] }.tally,
    'first_changes' => changed.first(5)
  }))
end
fail_closed('non_autosized_model_object_changed') unless protected_unchanged

forward = OpenStudio::EnergyPlus::ForwardTranslator.new
forward.translateModel(fixed_model)
fail_closed('fixed_reference_forward_translation_failed') unless forward.errors.empty?
FileUtils.mkdir_p(File.dirname(output))
saved = fixed_model.save(OpenStudio::Path.new(output), true)
fail_closed('fixed_reference_save_failed') unless saved

categories = category_counts(fields, applied_keys, unresolved_keys)
payload = {
  'schema_version' => SCHEMA,
  'source_unchanged' => source_unchanged,
  'protected_objects_unchanged' => protected_unchanged,
  'autosizable_fields_before' => fields.size,
  'autosized_values_available' => available_count,
  'values_applied' => applied_keys.size,
  'autosizable_fields_unresolved' => unresolved_keys.size,
  'categories' => categories,
  'object_types' => fields.group_by { |field| field['object_type'] }.sort.to_h.transform_values do |selected|
    keys = selected.map { |field| [field['handle'], field['predicate']] }
    {
      'before' => selected.size,
      'available' => selected.count { |field| field['available'] },
      'applied' => keys.count { |key| applied_keys.include?(key) },
      'unresolved' => keys.count { |key| unresolved_keys.include?(key) }
    }
  end,
  'unresolved_fields' => fields.select do |field|
    unresolved_keys.include?([field['handle'], field['predicate']])
  end.group_by do |field|
    [field['object_type'], field['category'], field['predicate']]
  end.sort_by { |key, _selected| key }.map do |key, selected|
    {
      'object_type' => key[0],
      'category' => key[1],
      'field' => key[2],
      'count' => selected.size
    }
  end,
  'forward_translation_warning_count' => forward.warnings.size,
  'forward_translation_error_count' => forward.errors.size
}
FileUtils.mkdir_p(File.dirname(audit_path))
File.write(audit_path, JSON.pretty_generate(payload) + "\n")
puts JSON.generate({
  'status' => unresolved_keys.empty? ? 'FIXED_OPERATION_COMPARISON_VALID' : 'FIXED_OPERATION_INCOMPLETE',
  'autosizable_fields_before' => fields.size,
  'values_applied' => applied_keys.size,
  'autosizable_fields_unresolved' => unresolved_keys.size,
  'source_unchanged' => source_unchanged,
  'protected_objects_unchanged' => protected_unchanged
})
