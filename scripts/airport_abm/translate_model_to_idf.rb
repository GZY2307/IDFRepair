# frozen_string_literal: true

# Forward-translate a private OpenStudio model without modifying its source.

require 'fileutils'
require 'json'
require 'optparse'


def fail_closed(message)
  warn(message)
  exit(2)
end


def within_root?(path, root)
  path == root || path.start_with?(root + File::SEPARATOR)
end


options = {}
OptionParser.new do |parser|
  parser.on('--input PATH') { |value| options[:input] = value }
  parser.on('--output PATH') { |value| options[:output] = value }
  parser.on('--allowed-root PATH') { |value| options[:allowed_root] = value }
end.parse!
%i[input output allowed_root].each { |key| fail_closed("#{key}_missing") unless options[key] }

source = File.expand_path(options[:input])
output = File.expand_path(options[:output])
allowed_root = File.expand_path(options[:allowed_root])
fail_closed('source_not_found') unless File.file?(source)
fail_closed('output_outside_allowed_root') unless within_root?(output, allowed_root)
fail_closed('output_must_not_replace_source') if output == source
source_bytes = File.binread(source)

translator = OpenStudio::OSVersion::VersionTranslator.new
loaded = translator.loadModel(OpenStudio::Path.new(source))
fail_closed('openstudio_model_load_failed') if loaded.empty?
model = loaded.get
forward = OpenStudio::EnergyPlus::ForwardTranslator.new
workspace = forward.translateModel(model)
fail_closed('forward_translation_errors') unless forward.errors.empty?
FileUtils.mkdir_p(File.dirname(output))
saved = workspace.save(OpenStudio::Path.new(output), true)
fail_closed('forward_translation_save_failed') unless saved
fail_closed('source_bytes_changed') unless File.binread(source) == source_bytes

puts JSON.generate({
  'status' => 'PASS',
  'forward_translation_warning_count' => forward.warnings.size,
  'forward_translation_error_count' => forward.errors.size
})
