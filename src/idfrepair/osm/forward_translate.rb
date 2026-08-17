# frozen_string_literal: true

require "digest"
require "json"
require "set"

MAX_MAPPINGS = 20_000
MAX_VALIDITY_ERRORS = 500
MAX_DIAGNOSTIC_ADAPTATIONS = 2_000
MAX_INVENTORY_OBJECTS = 50_000
MAX_REVERSE_REFERENCES = 2_000
WRITEBACK_MAPPING_CONTRACT = "exact-source-handle-typed-surface-v2"
AIR_BOUNDARY_IDENTITY_BASIS = "raw-loaded-derived-typed-air-boundary-v2"
DERIVED_OBJECT_INDEX_BASIS = "idf-document-order-including-version-v1"

def optional_value(value)
  if value.respond_to?(:get)
    return nil if value.respond_to?(:empty?) && value.empty?

    value = value.get
  end
  return value.valueName if value.respond_to?(:valueName)
  return value.str if value.respond_to?(:str)

  value.to_s
end

def safe_optional_value(object, method_name)
  return nil unless object.respond_to?(method_name)

  optional_value(object.public_send(method_name))
rescue StandardError
  nil
end

def log_messages(values)
  values.map { |value| value.respond_to?(:logMessage) ? value.logMessage : value.to_s }
end

def validity(model, level_name)
  level = OpenStudio::StrictnessLevel.new(level_name)
  report = model.validityReport(level)
  count = report.numErrors
  errors = []
  [count, MAX_VALIDITY_ERRORS].min.times do
    optional = report.nextError
    next if optional.empty?

    error = optional.get
    errors << {
      "scope" => safe_optional_value(error, :scope),
      "error_type" => safe_optional_value(error, :type),
      "object_type" => safe_optional_value(error, :objectType),
      "object_name" => safe_optional_value(error, :objectName),
      "field" => safe_optional_value(error, :fieldIdentifier),
      "raw" => error.to_s
    }
  end
  {
    "valid" => model.isValid(level),
    "error_count" => count,
    "errors" => errors,
    "errors_truncated" => count > errors.length
  }
end

def handle_text(model_object)
  model_object.handle.to_s.delete("{}").downcase
end

def object_type_name(model_object)
  model_object.iddObject.name
end

def object_ref(model_object, object_type = nil)
  {
    "handle" => handle_text(model_object),
    "object_type" => object_type || object_type_name(model_object),
    "name" => model_object.nameString
  }
end

def json_digest(value)
  Digest::SHA256.hexdigest(JSON.generate(value))
end

def identity_binding_ref_values(value, key)
  reference = value[key]
  return [key, nil, nil, nil] unless reference.is_a?(Hash)

  fields = ["handle", "object_type", "name"]
  fields.insert(1, "object_index") if key == "derived_object"
  [key, *reference.values_at(*fields)]
end

def identity_binding_projection_values(value)
  projection = value["mapping_projection"]
  fields = [
    "mapping_id", "mapping_contract", "mapping_status", "mapping_truncated",
    "osm_handle", "osm_object_type", "osm_object_name",
    "derived_idf_object_index", "derived_object_index_basis",
    "derived_idf_object_type", "derived_idf_object_name",
    "derived_workspace_handle", "source_sha256",
    "source_handle_inventory_sha256", "loaded_handle_inventory_sha256"
  ]
  return ["mapping_projection", *Array.new(fields.length)] unless projection.is_a?(Hash)

  ["mapping_projection", *projection.values_at(*fields)]
end

def identity_binding_digest(value)
  json_digest([
    value["status"], value["mapping_contract"], value["basis"],
    value["mapping_truncated"], value["mapping_id"], value["source_sha256"],
    value["source_handle_inventory_sha256"],
    value["loaded_handle_inventory_sha256"],
    identity_binding_ref_values(value, "source_object"),
    identity_binding_ref_values(value, "loaded_object"),
    identity_binding_ref_values(value, "derived_object"),
    identity_binding_projection_values(value)
  ])
end

def derived_object_index_catalog(idf_file)
  offset = idf_file.versionObject.empty? ? 0 : 1
  idf_file.objects.each_with_index.each_with_object(Hash.new { |hash, key| hash[key] = [] }) do |
    (object, index), catalog|
    catalog[[object.iddObject.name, object.nameString]] << index + offset
  end
end

def air_mapping_projection(mapping)
  {
    "mapping_id" => mapping["mapping_id"],
    "mapping_contract" => mapping["mapping_contract"],
    "mapping_status" => mapping["mapping_status"],
    "mapping_truncated" => mapping["mapping_truncated"],
    "osm_handle" => mapping["osm_handle"],
    "osm_object_type" => mapping["osm_object_type"],
    "osm_object_name" => mapping["osm_object_name"],
    "derived_idf_object_index" => mapping["derived_idf_object_index"],
    "derived_object_index_basis" => mapping["derived_object_index_basis"],
    "derived_idf_object_type" => mapping["derived_idf_object_type"],
    "derived_idf_object_name" => mapping["derived_idf_object_name"],
    "derived_workspace_handle" => mapping["derived_workspace_handle"],
    "source_sha256" => mapping["source_sha256"],
    "source_handle_inventory_sha256" => mapping["source_handle_inventory_sha256"],
    "loaded_handle_inventory_sha256" => mapping["loaded_handle_inventory_sha256"]
  }
end

def finite_number(value)
  number = Float(value)
  raise ArgumentError, "non_finite_number" unless number.finite?

  number.zero? ? 0.0 : number
end

def number_token(value)
  number = finite_number(value)
  return "0" if number.zero?

  format("%.17g", number)
end

def point_values(point)
  [finite_number(point.x), finite_number(point.y), finite_number(point.z)]
end

def vector_values(points)
  points.map { |point| point_values(point) }
end

def vector_fingerprint(points)
  json_digest(points.map { |point| point_values(point).map { |value| number_token(value) } })
end

def matrix_values(transformation)
  matrix = transformation.matrix
  (0...4).map do |row|
    (0...4).map { |column| finite_number(matrix[row, column]) }
  end
end

def transformation_snapshot(transformation)
  values = matrix_values(transformation)
  {
    "matrix" => values,
    "sha256" => json_digest(values.map { |row| row.map { |value| number_token(value) } })
  }
end

def inventory_rows(objects)
  objects.map do |object|
    [handle_text(object), object_type_name(object), object.nameString]
  end.sort
end

def handle_inventory(objects, status = "COMPLETE")
  rows = inventory_rows(objects)
  {
    "status" => status,
    "count" => rows.length,
    "sha256" => json_digest(rows),
    "objects" => rows.first(MAX_INVENTORY_OBJECTS).map do |handle, object_type, name|
      {"handle" => handle, "object_type" => object_type, "name" => name}
    end,
    "objects_truncated" => rows.length > MAX_INVENTORY_OBJECTS
  }
end

def unavailable_inventory(reason)
  {
    "status" => "UNAVAILABLE",
    "count" => 0,
    "sha256" => nil,
    "objects" => [],
    "objects_truncated" => false,
    "reason" => reason
  }
end

def inventory_index(inventory)
  inventory.fetch("objects", []).each_with_object({}) do |row, index|
    index[row.fetch("handle")] = row
  end
end

def typed_reverse_references(model_object)
  rows = []
  model_object.sources.each do |source|
    source.getSourceIndices(model_object.handle).each do |field_index|
      optional_field = source.iddObject.getField(field_index)
      field_name = optional_field.empty? ? "" : optional_field.get.name
      rows << {
        "source_handle" => handle_text(source),
        "source_object_type" => object_type_name(source),
        "source_object_name" => source.nameString,
        "field_index" => field_index,
        "field_name" => field_name
      }
    end
  end
  rows.sort_by! do |row|
    [row["source_handle"], row["field_index"], row["source_object_type"]]
  end
  [rows.first(MAX_REVERSE_REFERENCES), rows.length > MAX_REVERSE_REFERENCES]
end

def typed_reverse_references_digest(rows)
  json_digest(rows.map do |row|
    [
      row["source_handle"], row["source_object_type"], row["source_object_name"],
      row["field_index"], row["field_name"]
    ]
  end)
end

def supported_surface_reverse_reference?(row)
  row["source_object_type"] == "OS:Surface" &&
    row["field_name"] == "Outside Boundary Condition Object"
end

def normalized_signature_value(field, value)
  type_name = field.properties.type.valueName
  if ["RealType", "IntegerType"].include?(type_name) && !value.to_s.empty?
    number_token(value)
  else
    value.to_s.strip.downcase
  end
end

def air_boundary_signature(construction)
  (2...construction.iddObject.numFields).map do |field_index|
    field = construction.iddObject.getField(field_index).get
    target = construction.getTarget(field_index)
    if target.empty?
      value = optional_value(construction.getString(field_index, true))
      {
        "field_index" => field_index,
        "field_name" => field.name,
        "field_type" => field.properties.type.valueName,
        "value" => normalized_signature_value(field, value)
      }
    else
      {
        "field_index" => field_index,
        "field_name" => field.name,
        "field_type" => field.properties.type.valueName,
        "target_handle" => handle_text(target.get),
        "target_name" => target.get.nameString,
        "target_object_type" => object_type_name(target.get)
      }
    end
  end
end

def air_boundary_snapshot(construction)
  references, truncated = typed_reverse_references(construction)
  signature = air_boundary_signature(construction)
  {
    **object_ref(construction, "OS:Construction:AirBoundary"),
    "signature" => signature,
    "signature_sha256" => json_digest(signature),
    "typed_reverse_references" => references,
    "typed_reverse_references_sha256" => typed_reverse_references_digest(references),
    "typed_reverse_references_truncated" => truncated
  }
end

def construction_snapshot(construction)
  object_ref(construction)
end

def bind_air_boundary_identities(
  snapshots,
  mappings,
  source_sha256,
  source_inventory,
  loaded_inventory,
  mapping_truncated
)
  snapshots.map do |snapshot|
    matches = mappings.select do |mapping|
      mapping["mapping_contract"] == WRITEBACK_MAPPING_CONTRACT &&
        mapping["mapping_status"] == "EXPLICIT_EXACT_TYPE_NAME" &&
        mapping["osm_handle"] == snapshot["handle"] &&
        mapping["osm_object_type"] == "OS:Construction:AirBoundary" &&
        mapping["osm_object_name"] == snapshot["name"] &&
        mapping["derived_idf_object_type"] == "Construction:AirBoundary" &&
        mapping["derived_idf_object_name"] == snapshot["name"]
    end
    mapping = matches.first if matches.length == 1
    derived_object = if mapping.nil?
                       nil
                     else
                       {
                         "handle" => mapping["derived_workspace_handle"],
                         "object_index" => mapping["derived_idf_object_index"],
                         "object_type" => mapping["derived_idf_object_type"],
                         "name" => mapping["derived_idf_object_name"]
                       }
                     end
    expected_ref = {
      "handle" => snapshot["handle"],
      "object_type" => snapshot["object_type"],
      "name" => snapshot["name"]
    }
    complete = (
      !mapping_truncated && !mapping.nil? &&
      mapping["mapping_truncated"] == false &&
      mapping["derived_idf_object_index"].is_a?(Integer) &&
      snapshot["source_object"] == expected_ref &&
      snapshot["loaded_object"] == expected_ref &&
      source_inventory["status"] == "COMPLETE" &&
      loaded_inventory["status"] == "COMPLETE" &&
      !source_inventory["objects_truncated"] &&
      !loaded_inventory["objects_truncated"] &&
      source_inventory["sha256"] == loaded_inventory["sha256"]
    )
    binding = {
      "status" => complete ? "COMPLETE" : "REJECTED",
      "mapping_contract" => WRITEBACK_MAPPING_CONTRACT,
      "basis" => AIR_BOUNDARY_IDENTITY_BASIS,
      "mapping_truncated" => mapping_truncated,
      "mapping_id" => mapping.nil? ? nil : mapping["mapping_id"],
      "source_sha256" => source_sha256,
      "source_handle_inventory_sha256" => source_inventory["sha256"],
      "loaded_handle_inventory_sha256" => loaded_inventory["sha256"],
      "source_object" => snapshot["source_object"],
      "loaded_object" => snapshot["loaded_object"],
      "derived_object" => derived_object,
      "mapping_projection" => mapping.nil? ? nil : air_mapping_projection(mapping)
    }
    snapshot.merge({
      "identity_binding" => binding,
      "identity_binding_sha256" => identity_binding_digest(binding),
      "writeback_eligible" => snapshot["writeback_eligible"] && complete
    })
  end
end

def space_snapshot(space)
  {
    **object_ref(space, "OS:Space"),
    "transformation" => transformation_snapshot(space.transformation)
  }
end

def surface_expected_before(surface, raw_object, derived_object)
  return [nil, ["surface_space_missing"]] unless surface.space.is_initialized
  return [nil, ["surface_construction_missing"]] unless surface.construction.is_initialized

  space = surface.space.get
  construction = surface.construction.get
  local_vertices = surface.vertices
  building_vertices = local_vertices.map { |point| space.transformation * point }
  references, references_truncated = typed_reverse_references(surface)
  subsurface_handles = surface.subSurfaces.map { |row| handle_text(row) }.sort
  adjacent_handle = (
    handle_text(surface.adjacentSurface.get) if surface.adjacentSurface.is_initialized
  )
  snapshot = {
    "source_object" => object_ref(raw_object),
    "loaded_object" => object_ref(surface, "OS:Surface"),
    "derived_object" => object_ref(derived_object, "BuildingSurface:Detailed"),
    "space" => object_ref(space, "OS:Space"),
    "space_transformation" => transformation_snapshot(space.transformation),
    "surface_type" => surface.surfaceType,
    "local_vertices" => vector_values(local_vertices),
    "local_vertices_sha256" => vector_fingerprint(local_vertices),
    "building_vertices" => vector_values(building_vertices),
    "building_vertices_sha256" => vector_fingerprint(building_vertices),
    "construction" => construction_snapshot(construction),
    "adjacent_surface_handle" => adjacent_handle,
    "subsurface_handles" => subsurface_handles,
    "typed_reverse_references" => references,
    "typed_reverse_references_sha256" => typed_reverse_references_digest(references)
  }
  reasons = []
  reasons << "surface_has_subsurfaces" unless subsurface_handles.empty?
  reasons << "typed_reverse_references_truncated" if references_truncated
  reasons << "unsupported_typed_reverse_reference" if references.any? do |row|
    !supported_surface_reverse_reference?(row)
  end
  [snapshot, reasons]
end

def diagnostic_zone_slug(space_name)
  slug = space_name.to_s.downcase.gsub(/[^a-z0-9]+/, "-").gsub(/\A-+|-+\z/, "")
  slug = "space-#{Digest::SHA256.hexdigest(space_name.to_s)[0, 10]}" if slug.empty?
  slug[0, 48].sub(/-+\z/, "")
end

def unique_diagnostic_zone_name(space_name, used_names)
  # Keep the temporary derived-model zone recognizable to a user reading the
  # source Space name.  The collision suffix is deterministic and the source
  # OSM is never modified.
  base = diagnostic_zone_slug(space_name)
  candidate = base
  suffix = 2
  while used_names.include?(candidate.downcase)
    candidate = "#{base}-#{suffix}"
    suffix += 1
  end
  used_names.add(candidate.downcase)
  candidate
end

def prepare_diagnostic_model(model)
  rows = []
  generated_source_handles = Set.new
  used_zone_names = Set.new(model.getThermalZones.map { |zone| zone.nameString.downcase })
  model.getSpaces.sort_by { |space| [space.nameString, handle_text(space)] }.each do |space|
    next if space.thermalZone.is_initialized

    zone = OpenStudio::Model::ThermalZone.new(model)
    zone.setName(unique_diagnostic_zone_name(space.nameString, used_zone_names))
    unless space.setThermalZone(zone)
      zone.remove
      next
    end
    generated_source_handles.add(handle_text(zone))
    if rows.length < MAX_DIAGNOSTIC_ADAPTATIONS
      rows << {
        "adaptation" => "temporary_thermal_zone_for_unzoned_space",
        "reason" => "openstudio_forward_translation_requires_zone_context",
        "space_handle" => handle_text(space),
        "space_name" => space.nameString,
        "temporary_zone_handle" => handle_text(zone),
        "temporary_zone_name" => zone.nameString,
        "source_osm_modified" => false,
        "derived_model_only" => true,
        "simulation_semantic_equivalence_claimed" => false
      }
    end
  end
  return [{
    "adaptation" => "temporary_thermal_zone_for_unzoned_space",
    "count" => generated_source_handles.length,
    "objects" => rows,
    "objects_truncated" => generated_source_handles.length > rows.length,
    "source_osm_modified" => false,
    "derived_model_only" => true,
    "simulation_semantic_equivalence_claimed" => false
  }], generated_source_handles
end

def model_ref(model_object, object_type)
  object_ref(model_object, object_type)
end

def surface_context(surface)
  context = {}
  if surface.space.is_initialized
    space = surface.space.get
    context["space"] = model_ref(space, "OS:Space")
    if space.thermalZone.is_initialized
      context["thermal_zone"] = model_ref(space.thermalZone.get, "OS:ThermalZone")
    end
    if space.buildingStory.is_initialized
      context["building_story"] = model_ref(space.buildingStory.get, "OS:BuildingStory")
    end
  end
  context
end

def subsurface_context(subsurface)
  context = {}
  if subsurface.surface.is_initialized
    surface = subsurface.surface.get
    context["parent_surface"] = model_ref(surface, "OS:Surface")
    context.merge!(surface_context(surface))
  end
  context
end

def space_context(space)
  context = {}
  if space.thermalZone.is_initialized
    context["thermal_zone"] = model_ref(space.thermalZone.get, "OS:ThermalZone")
  end
  if space.buildingStory.is_initialized
    context["building_story"] = model_ref(space.buildingStory.get, "OS:BuildingStory")
  end
  context
end

def exact_mappings(
  workspace,
  model,
  generated_source_handles,
  raw_objects_by_handle,
  source_sha256,
  source_inventory,
  loaded_inventory,
  derived_object_indices
)
  families = [
    {
      "sources" => model.getSurfaces,
      "osm_type" => "OS:Surface",
      "idf_type" => "BuildingSurface:Detailed",
      "stable_target" => {
        "name_field_index" => 1,
        "geometry_relation" => "ordered_vertices",
        "geometry_fields" => "number-of-vertices-and-extensible-coordinates"
      },
      "context" => lambda { |object| surface_context(object) }
    },
    {
      "sources" => model.getSubSurfaces,
      "osm_type" => "OS:SubSurface",
      "idf_type" => "FenestrationSurface:Detailed",
      "stable_target" => {
        "name_field_index" => 1,
        "geometry_relation" => "ordered_vertices",
        "geometry_fields" => "number-of-vertices-and-extensible-coordinates"
      },
      "context" => lambda { |object| subsurface_context(object) }
    },
    {
      "sources" => model.getThermalZones,
      "osm_type" => "OS:ThermalZone",
      "idf_type" => "Zone",
      "stable_target" => {"name_field_index" => 1},
      "context" => lambda { |_object| {} }
    },
    {
      "sources" => model.getSpaces,
      "osm_type" => "OS:Space",
      "idf_type" => "Space",
      "stable_target" => {"name_field_index" => 1},
      "context" => lambda { |object| space_context(object) }
    },
    {
      "sources" => model.getConstructionAirBoundarys,
      "osm_type" => "OS:Construction:AirBoundary",
      "idf_type" => "Construction:AirBoundary",
      "stable_target" => {"name_field_index" => 1},
      "context" => lambda { |_object| {} }
    }
  ]
  mappings = []
  source_count = 0
  inventories_complete = (
    source_inventory["status"] == "COMPLETE" &&
    loaded_inventory["status"] == "COMPLETE" &&
    !source_inventory["objects_truncated"] &&
    !loaded_inventory["objects_truncated"]
  )
  inventories_match = (
    inventories_complete &&
    source_inventory["sha256"] == loaded_inventory["sha256"]
  )
  families.each do |family|
    idd_type = OpenStudio::IddObjectType.new(family["idf_type"])
    targets = workspace.getObjectsByType(idd_type).group_by(&:nameString)
    family["sources"].sort_by { |object| [object.nameString, handle_text(object)] }.each do |source|
      next if generated_source_handles.include?(handle_text(source))

      source_count += 1
      next if mappings.length >= MAX_MAPPINGS

      matches = targets.fetch(source.nameString, [])
      exact = matches.length == 1
      indices = derived_object_indices.fetch(
        [family["idf_type"], source.nameString], []
      )
      derived_object_index = indices.first if exact && indices.length == 1
      raw_object = raw_objects_by_handle[handle_text(source)]
      expected_before = nil
      eligibility_reasons = []
      eligibility_reasons << "source_handle_inventory_incomplete" unless inventories_complete
      eligibility_reasons << "source_loaded_handle_inventory_mismatch" unless inventories_match
      if raw_object.nil?
        eligibility_reasons << "source_handle_absent_from_raw_osm"
      elsif object_type_name(raw_object) != family["osm_type"]
        eligibility_reasons << "source_object_type_mismatch"
      elsif raw_object.nameString != source.nameString
        eligibility_reasons << "source_object_name_mismatch"
      end
      unless exact
        eligibility_reasons << (
          matches.empty? ? "derived_object_not_found" : "derived_object_not_unique"
        )
      end
      if exact && derived_object_index.nil?
        eligibility_reasons << (
          indices.empty? ? "derived_object_index_not_found" :
            "derived_object_index_not_unique"
        )
      end
      if family["osm_type"] == "OS:Surface" && !raw_object.nil? && exact
        expected_before, snapshot_reasons = surface_expected_before(
          source, raw_object, matches.first
        )
        eligibility_reasons.concat(snapshot_reasons)
      else
        eligibility_reasons << "mapping_object_type_not_writeback_surface"
        if family["osm_type"] == "OS:Space"
          expected_before = space_snapshot(source)
        elsif family["osm_type"] == "OS:Construction:AirBoundary"
          expected_before = air_boundary_snapshot(source)
        end
      end
      identity = [family["osm_type"], handle_text(source), family["idf_type"], source.nameString].join("|")
      mappings << {
        "mapping_id" => "osm-map-#{Digest::SHA256.hexdigest(identity)[0, 20]}",
        "mapping_status" => exact ? "EXPLICIT_EXACT_TYPE_NAME" : "OSM_MAPPING_UNSUPPORTED",
        "mapping_reason" => exact ? nil : (matches.empty? ? "derived_object_not_found" : "derived_object_not_unique"),
        "provenance_basis" => "openstudio-forward-exact-type-and-name-unique-v1",
        "osm_handle" => handle_text(source),
        "osm_object_type" => family["osm_type"],
        "osm_object_name" => source.nameString,
        "derived_idf_object_type" => exact ? family["idf_type"] : nil,
        "derived_idf_object_name" => exact ? matches.first.nameString : nil,
        "derived_idf_object_index" => derived_object_index,
        "derived_object_index_basis" => DERIVED_OBJECT_INDEX_BASIS,
        "derived_workspace_handle" => exact ? handle_text(matches.first) : nil,
        "stable_target" => family["stable_target"],
        "context" => family["context"].call(source),
        "mapping_contract" => WRITEBACK_MAPPING_CONTRACT,
        "source_sha256" => source_sha256,
        "source_handle_inventory_sha256" => source_inventory["sha256"],
        "loaded_handle_inventory_sha256" => loaded_inventory["sha256"],
        "mapping_truncated" => false,
        "expected_before" => expected_before,
        "writeback_eligible" => eligibility_reasons.empty?,
        "writeback_reasons" => eligibility_reasons.uniq.sort,
        "candidate_preview_authorized" => false,
        "writeback_authorized" => false
      }
    end
  end
  truncated = source_count > mappings.length
  if truncated
    mappings.each do |mapping|
      mapping["mapping_truncated"] = true
      mapping["writeback_eligible"] = false
      mapping["writeback_reasons"] = (
        mapping.fetch("writeback_reasons", []) + ["mapping_truncated"]
      ).uniq.sort
    end
  end
  [mappings, source_count, truncated]
end

unless ENV["IDFREPAIR_FORWARD_TRANSLATE_HELPERS_ONLY"] == "1"
if ARGV.length != 3
  warn "usage: forward_translate.rb INPUT.osm OUTPUT.idf REPORT.json"
  exit 64
end

input_path, output_path, report_path = ARGV
source_sha256 = Digest::SHA256.file(input_path).hexdigest
raw_workspace_optional = OpenStudio::Workspace.load(OpenStudio::Path.new(input_path))
if raw_workspace_optional.empty?
  source_inventory = unavailable_inventory("raw_source_workspace_load_failed")
  raw_objects_by_handle = {}
else
  raw_workspace = raw_workspace_optional.get
  source_inventory = handle_inventory(raw_workspace.objects)
  raw_objects_by_handle = raw_workspace.objects.each_with_object({}) do |object, index|
    index[handle_text(object)] = object
  end
end
translator = OpenStudio::OSVersion::VersionTranslator.new
optional_model = translator.loadModel(OpenStudio::Path.new(input_path))
if optional_model.empty?
  File.write(report_path, JSON.pretty_generate({
    "schema_version" => "idfrepair.openstudio-forward.v1",
    "source_sha256" => source_sha256,
    "source_handle_inventory" => source_inventory,
    "loaded_handle_inventory" => unavailable_inventory(
      "version_translator_load_failed"
    ),
    "source_loaded_handle_inventories_match" => false,
    "mapping_contract" => WRITEBACK_MAPPING_CONTRACT,
    "version_translator" => {
      "loaded" => false,
      "warnings" => log_messages(translator.warnings),
      "errors" => log_messages(translator.errors)
    },
    "reverse_translation_used" => false,
    "osm_writeback_authorized" => false
  }))
  warn "OpenStudio VersionTranslator could not load the OSM"
  exit 2
end

model = optional_model.get
loaded_inventory = handle_inventory(model.modelObjects)
source_loaded_handle_inventories_match = (
  source_inventory["status"] == "COMPLETE" &&
  loaded_inventory["status"] == "COMPLETE" &&
  !source_inventory["objects_truncated"] &&
  !loaded_inventory["objects_truncated"] &&
  source_inventory["sha256"] == loaded_inventory["sha256"]
)
space_snapshots = model.getSpaces.map { |space| space_snapshot(space) }.sort_by do |row|
  row["handle"]
end
construction_snapshots = model.getConstructions.map do |construction|
  construction_snapshot(construction)
end.sort_by { |row| row["handle"] }
air_boundary_snapshots = model.getConstructionAirBoundarys.map do |construction|
  snapshot = air_boundary_snapshot(construction)
  raw_object = raw_objects_by_handle[handle_text(construction)]
  snapshot.merge({
    "source_object" => raw_object.nil? ? nil : object_ref(raw_object),
    "loaded_object" => object_ref(construction),
    "source_sha256" => source_sha256,
    "source_handle_inventory_sha256" => source_inventory["sha256"],
    "loaded_handle_inventory_sha256" => loaded_inventory["sha256"],
    "writeback_eligible" => (
      source_loaded_handle_inventories_match && !raw_object.nil? &&
      object_type_name(raw_object) == "OS:Construction:AirBoundary" &&
      raw_object.nameString == construction.nameString &&
      !snapshot["typed_reverse_references_truncated"]
    )
  })
end.sort_by { |row| row["handle"] }
diagnostic_adaptations, generated_source_handles = prepare_diagnostic_model(model)
forward = OpenStudio::EnergyPlus::ForwardTranslator.new
forward.setExcludeSpaceTranslation(false) if forward.respond_to?(:setExcludeSpaceTranslation)
workspace = forward.translateModel(model)
unless workspace.save(OpenStudio::Path.new(output_path), true)
  warn "OpenStudio ForwardTranslator could not save the derived IDF"
  exit 3
end

derived_text = File.read(output_path, encoding: "UTF-8")
derived_version = derived_text[/\bVersion\s*,\s*([^,;\s]+)/im, 1]
derived_idf_optional = OpenStudio::IdfFile.load(OpenStudio::Path.new(output_path))
derived_object_indices = if derived_idf_optional.empty?
                           {}
                         else
                           derived_object_index_catalog(derived_idf_optional.get)
                         end
mappings, mapping_source_count, mapping_truncated = exact_mappings(
  workspace,
  model,
  generated_source_handles,
  raw_objects_by_handle,
  source_sha256,
  source_inventory,
  loaded_inventory,
  derived_object_indices
)
air_boundary_snapshots = bind_air_boundary_identities(
  air_boundary_snapshots,
  mappings,
  source_sha256,
  source_inventory,
  loaded_inventory,
  mapping_truncated
)
payload = {
  "schema_version" => "idfrepair.openstudio-forward.v1",
  "source_sha256" => source_sha256,
  "derived_idf_sha256" => Digest::SHA256.hexdigest(derived_text),
  "derived_object_index_basis" => DERIVED_OBJECT_INDEX_BASIS,
  "source_handle_inventory" => source_inventory,
  "loaded_handle_inventory" => loaded_inventory,
  "source_loaded_handle_inventories_match" => source_loaded_handle_inventories_match,
  "space_snapshots" => space_snapshots,
  "construction_snapshots" => construction_snapshots,
  "air_boundary_snapshots" => air_boundary_snapshots,
  "source_model_version" => translator.originalVersion.str,
  "loaded_model_version" => model.version.str,
  "derived_idf_version" => derived_version,
  "version_translator" => {
    "loaded" => true,
    "warnings" => log_messages(translator.warnings),
    "errors" => log_messages(translator.errors)
  },
  "model_validity" => {
    "minimal" => validity(model, "Minimal"),
    "final" => validity(model, "Final")
  },
  "diagnostic_adaptations" => diagnostic_adaptations,
  "source_osm_modified" => false,
  "simulation_semantic_equivalence_claimed" => false,
  "forward_translator" => {
    "warnings" => log_messages(forward.warnings),
    "errors" => log_messages(forward.errors)
  },
  "model_object_count" => model.modelObjects.size,
  "derived_workspace_object_count" => workspace.objects.size,
  "mapping_source_count" => mapping_source_count,
  "mappings" => mappings,
  "mapping_truncated" => mapping_truncated,
  "mapping_contract" => WRITEBACK_MAPPING_CONTRACT,
  "reverse_translation_used" => false,
  "osm_candidate_preview_authorized" => false,
  "osm_writeback_authorized" => false
}
File.write(report_path, JSON.pretty_generate(payload) + "\n")
end
