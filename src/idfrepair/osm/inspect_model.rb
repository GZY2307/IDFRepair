# frozen_string_literal: true

ENV["IDFREPAIR_APPLY_REPAIRS_HELPERS_ONLY"] = "1"
require_relative "apply_repairs"

AUDIT_SCHEMA = "idfrepair.openstudio-child-audit.v1"

def audit_failure(code)
  {
    "schema_version" => AUDIT_SCHEMA,
    "status" => "REJECTED",
    "failure_code" => code.to_s[0, 160],
    "reverse_translation_used" => false,
    "osm_writeback_authorized" => false
  }
end

def inspect_child_model(input_path)
  source_sha256 = Digest::SHA256.file(input_path).hexdigest
  raw_optional = OpenStudio::Workspace.load(OpenStudio::Path.new(input_path))
  fail_patch("child_source_workspace_load_failed") if raw_optional.empty?
  source_inventory = handle_inventory(raw_optional.get.objects)
  if source_inventory["objects_truncated"]
    fail_patch("child_source_inventory_incomplete")
  end

  translator = OpenStudio::OSVersion::VersionTranslator.new
  model_optional = translator.loadModel(OpenStudio::Path.new(input_path))
  fail_patch("child_model_load_failed") if model_optional.empty?
  model = model_optional.get
  loaded_inventory = handle_inventory(model.modelObjects)
  if loaded_inventory["objects_truncated"]
    fail_patch("child_loaded_inventory_incomplete")
  end
  unless source_inventory == loaded_inventory
    fail_patch("child_source_loaded_inventory_mismatch")
  end
  validity_raw = model_validity(model)
  validity = validity_stage_report(validity_raw, validity_raw)

  {
    "schema_version" => AUDIT_SCHEMA,
    "status" => "COMPLETE",
    "source_sha256" => source_sha256,
    "source_handle_inventory" => source_inventory,
    "loaded_handle_inventory" => loaded_inventory,
    "source_loaded_handle_inventories_match" => true,
    "model_validity" => validity,
    "reverse_translation_used" => false,
    "osm_writeback_authorized" => false
  }
end

if ARGV.length != 2
  warn "inspect_model_argument_count_invalid"
  exit 2
end

input_path, report_path = ARGV
begin
  write_report(report_path, inspect_child_model(input_path))
rescue PatchFailure => error
  write_report(report_path, audit_failure(error.code))
  warn error.code
  exit 3
rescue StandardError
  write_report(report_path, audit_failure("child_model_audit_internal_error"))
  warn "child_model_audit_internal_error"
  exit 4
end
