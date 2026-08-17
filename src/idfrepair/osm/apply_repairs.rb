# frozen_string_literal: true

require "digest"
require "json"

PATCH_SCHEMA = "idfrepair.openstudio-patch.v1"
WRITEBACK_MAPPING_CONTRACT = "exact-source-handle-typed-surface-v2"
DERIVED_OBJECT_INDEX_BASIS = "idf-document-order-including-version-v1"
ALLOWED_OPERATIONS = [
  "set_surface_vertices",
  "set_adjacent_surfaces",
  "set_surface_construction",
  "create_surface_piece",
  "remove_unreferenced_air_boundary"
].freeze
MAX_VALIDITY_ERRORS = 500
MAX_VALIDITY_FIELD_CHARS = 1_000
VALIDITY_TRUNCATION_MARKER = "␞<truncated>␞"
MAX_INVENTORY_OBJECTS = 50_000
MAX_OPERATION_RESULTS = 20_000
MAX_PATCH_BYTES = 50 * 1024 * 1024
HANDLE_PATTERN = /\A[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\z/.freeze
SHA_PATTERN = /\A[0-9a-f]{64}\z/.freeze

class PatchFailure < StandardError
  attr_reader :code

  def initialize(code)
    @code = code.to_s
    super(@code)
  end
end

def fail_patch(code)
  raise PatchFailure, code
end

def optional_value(value)
  if value.respond_to?(:get)
    return nil if value.respond_to?(:empty?) && value.empty?

    value = value.get
  end
  return value.valueName if value.respond_to?(:valueName)
  return value.str if value.respond_to?(:str)

  value.to_s
end

def normalize_handle(value)
  text = value.to_s.strip.delete("{}").downcase
  fail_patch("patch_handle_invalid") unless HANDLE_PATTERN.match?(text)

  text
end

def normalize_sha(value, code = "patch_sha256_invalid")
  text = value.to_s.downcase
  fail_patch(code) unless SHA_PATTERN.match?(text)

  text
end

def object_type_name(model_object)
  model_object.iddObject.name
end

def object_ref(model_object, object_type = nil)
  {
    "handle" => normalize_handle(model_object.handle),
    "object_type" => object_type || object_type_name(model_object),
    "name" => model_object.nameString
  }
end

def json_digest(value)
  Digest::SHA256.hexdigest(JSON.generate(value))
end

def air_identity_binding_ref_values(value, key)
  reference = value[key]
  return [key, nil, nil, nil] unless reference.is_a?(Hash)

  fields = ["handle", "object_type", "name"]
  fields.insert(1, "object_index") if key == "derived_object"
  [key, *reference.values_at(*fields)]
end

def air_identity_binding_projection_values(value)
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

def air_identity_binding_digest(value)
  json_digest([
    value["status"], value["mapping_contract"], value["basis"],
    value["mapping_truncated"], value["mapping_id"], value["source_sha256"],
    value["source_handle_inventory_sha256"],
    value["loaded_handle_inventory_sha256"],
    air_identity_binding_ref_values(value, "source_object"),
    air_identity_binding_ref_values(value, "loaded_object"),
    air_identity_binding_ref_values(value, "derived_object"),
    air_identity_binding_projection_values(value)
  ])
rescue NoMethodError
  fail_patch("air_boundary_identity_binding_mismatch")
end

def expected_mapping_id(projection)
  identity = [
    projection["osm_object_type"], projection["osm_handle"],
    projection["derived_idf_object_type"], projection["osm_object_name"]
  ].join("|")
  "osm-map-#{Digest::SHA256.hexdigest(identity)[0, 20]}"
end

def finite_number(value, code = "patch_number_invalid")
  number = Float(value)
  fail_patch(code) unless number.finite?

  number.zero? ? 0.0 : number
rescue ArgumentError, TypeError
  fail_patch(code)
end

def number_token(value)
  number = finite_number(value)
  return "0" if number.zero?

  format("%.17g", number)
end

def operation_string_hex(value)
  encoded = value.dup
  encoded.force_encoding(Encoding::UTF_8) if encoded.encoding == Encoding::ASCII_8BIT
  fail_patch("patch_operation_identity_invalid") unless encoded.valid_encoding?

  encoded.encode(Encoding::UTF_8).unpack1("H*")
rescue EncodingError
  fail_patch("patch_operation_identity_invalid")
end

def canonical_operation_value(value)
  case value
  when NilClass
    ["null"]
  when TrueClass, FalseClass
    ["bool", value]
  when Integer, Float
    ["number", number_token(value)]
  when String
    ["string", operation_string_hex(value)]
  when Array
    ["array", value.map { |item| canonical_operation_value(item) }]
  when Hash
    unless value.keys.all? { |key| key.is_a?(String) }
      fail_patch("patch_operation_identity_invalid")
    end
    keys = value.keys.sort_by { |key| operation_string_hex(key) }
    ["object", keys.map do |key|
      [operation_string_hex(key), canonical_operation_value(value[key])]
    end]
  else
    fail_patch("patch_operation_identity_invalid")
  end
end

def canonical_operation_body_json(operation)
  fail_patch("patch_operation_identity_invalid") unless operation.is_a?(Hash)

  body = operation.reject { |key, _value| key == "operation_id" }
  JSON.generate(canonical_operation_value(body))
end

def operation_identity(operation)
  digest = Digest::SHA256.hexdigest(canonical_operation_body_json(operation))
  "osm-op-#{digest[0, 23]}"
end

def point_values(point)
  [finite_number(point.x), finite_number(point.y), finite_number(point.z)]
end

def vector_values(points)
  points.map { |point| point_values(point) }
end

def serialize_points(points)
  points.map { |point| point_values(point).map { |value| number_token(value) } }
end

def vector_fingerprint(points)
  json_digest(serialize_points(points))
end

def values_fingerprint(values)
  json_digest(values.map do |point|
    fail_patch("patch_vertices_invalid") unless point.is_a?(Array) && point.length == 3

    point.map { |value| number_token(value) }
  end)
end

def points_from_values(values, code = "patch_vertices_invalid")
  fail_patch(code) unless values.is_a?(Array) && !values.empty?

  points = OpenStudio::Point3dVector.new
  values.each do |row|
    fail_patch(code) unless row.is_a?(Array) && row.length == 3

    points << OpenStudio::Point3d.new(
      finite_number(row[0], code),
      finite_number(row[1], code),
      finite_number(row[2], code)
    )
  end
  points
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
    "sha256" => json_digest(values.map do |row|
      row.map { |value| number_token(value) }
    end)
  }
end

def building_points_to_local(space, values)
  building = points_from_values(values)
  inverse = space.transformation.inverse
  local = OpenStudio::Point3dVector.new
  building.each { |point| local << inverse * point }
  local
rescue PatchFailure
  raise
rescue StandardError
  fail_patch("space_transformation_inverse_failed")
end

def inventory_rows(objects)
  objects.map do |object|
    [normalize_handle(object.handle), object_type_name(object), object.nameString]
  end.sort
end

def inventory_digest(rows)
  normalized = rows.map do |row|
    if row.is_a?(Hash)
      [normalize_handle(row["handle"]), row["object_type"].to_s, row["name"].to_s]
    else
      [normalize_handle(row[0]), row[1].to_s, row[2].to_s]
    end
  end.sort
  json_digest(normalized)
end

def handle_inventory(objects)
  rows = inventory_rows(objects)
  {
    "status" => "COMPLETE",
    "count" => rows.length,
    "sha256" => json_digest(rows),
    "objects" => rows.first(MAX_INVENTORY_OBJECTS).map do |handle, object_type, name|
      {"handle" => handle, "object_type" => object_type, "name" => name}
    end,
    "objects_truncated" => rows.length > MAX_INVENTORY_OBJECTS
  }
end

def typed_reverse_references(model_object)
  rows = []
  model_object.sources.each do |source|
    source.getSourceIndices(model_object.handle).each do |field_index|
      optional_field = source.iddObject.getField(field_index)
      rows << {
        "source_handle" => normalize_handle(source.handle),
        "source_object_type" => object_type_name(source),
        "source_object_name" => source.nameString,
        "field_index" => field_index,
        "field_name" => optional_field.empty? ? "" : optional_field.get.name
      }
    end
  end
  rows.sort_by do |row|
    [row["source_handle"], row["field_index"], row["source_object_type"]]
  end
end

def typed_reverse_references_digest(rows)
  json_digest(rows.map do |row|
    [
      row["source_handle"], row["source_object_type"], row["source_object_name"],
      row["field_index"], row["field_name"]
    ]
  end)
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
        "target_handle" => normalize_handle(target.get.handle),
        "target_name" => target.get.nameString,
        "target_object_type" => object_type_name(target.get)
      }
    end
  end
end

def air_boundary_runtime_snapshot(construction)
  signature = air_boundary_signature(construction)
  references = typed_reverse_references(construction)
  {
    **object_ref(construction, "OS:Construction:AirBoundary"),
    "signature" => signature,
    "signature_sha256" => json_digest(signature),
    "typed_reverse_references" => references,
    "typed_reverse_references_sha256" => typed_reverse_references_digest(references),
    "typed_reverse_references_truncated" => false
  }
end

def surface_runtime_snapshot(surface)
  fail_patch("expected_before_space_missing") unless surface.space.is_initialized
  fail_patch("expected_before_construction_missing") unless surface.construction.is_initialized

  space = surface.space.get
  construction = surface.construction.get
  local = surface.vertices
  building = OpenStudio::Point3dVector.new
  local.each { |point| building << space.transformation * point }
  references = typed_reverse_references(surface)
  {
    "loaded_object" => object_ref(surface, "OS:Surface"),
    "space" => object_ref(space, "OS:Space"),
    "space_transformation" => transformation_snapshot(space.transformation),
    "surface_type" => surface.surfaceType,
    "local_vertices" => vector_values(local),
    "local_vertices_sha256" => vector_fingerprint(local),
    "building_vertices" => vector_values(building),
    "building_vertices_sha256" => vector_fingerprint(building),
    "construction" => object_ref(construction),
    "adjacent_surface_handle" => (
      normalize_handle(surface.adjacentSurface.get.handle) if surface.adjacentSurface.is_initialized
    ),
    "subsurface_handles" => surface.subSurfaces.map do |row|
      normalize_handle(row.handle)
    end.sort,
    "typed_reverse_references" => references,
    "typed_reverse_references_sha256" => typed_reverse_references_digest(references)
  }
end

SURFACE_EXPECTED_KEYS = [
  "source_object", "loaded_object", "derived_object", "space",
  "space_transformation", "surface_type", "local_vertices",
  "local_vertices_sha256", "building_vertices", "building_vertices_sha256",
  "construction", "adjacent_surface_handle", "subsurface_handles",
  "typed_reverse_references", "typed_reverse_references_sha256"
].freeze

AIR_BOUNDARY_EXPECTED_KEYS = [
  "handle", "object_type", "name", "signature", "signature_sha256",
  "typed_reverse_references", "typed_reverse_references_sha256",
  "typed_reverse_references_truncated", "source_object", "loaded_object",
  "source_sha256", "source_handle_inventory_sha256",
  "loaded_handle_inventory_sha256", "identity_binding",
  "identity_binding_sha256", "writeback_eligible"
].freeze

SURFACE_RUNTIME_EXPECTED_KEYS = SURFACE_EXPECTED_KEYS - [
  "source_object", "derived_object"
]

def verify_surface_expected_before(surface, expected, require_complete: false)
  allowed_keys = require_complete ? SURFACE_EXPECTED_KEYS : SURFACE_RUNTIME_EXPECTED_KEYS
  unless expected.is_a?(Hash) && expected.keys.sort == allowed_keys.sort
    fail_patch("expected_before_snapshot_invalid")
  end

  actual = surface_runtime_snapshot(surface)
  expected_loaded = expected["loaded_object"]
  unless expected_loaded.is_a?(Hash) && expected_loaded == actual["loaded_object"]
    fail_patch("expected_before_surface_identity_mismatch")
  end
  unless expected["space"] == actual["space"]
    fail_patch("expected_before_space_mismatch")
  end
  unless expected["space_transformation"] == actual["space_transformation"]
    fail_patch("expected_before_space_transformation_mismatch")
  end
  unless expected["surface_type"] == actual["surface_type"]
    fail_patch("expected_before_surface_type_mismatch")
  end
  unless expected["local_vertices_sha256"] == actual["local_vertices_sha256"] &&
         expected["local_vertices"] == actual["local_vertices"]
    fail_patch("expected_before_local_vertices_mismatch")
  end
  unless expected["building_vertices_sha256"] == actual["building_vertices_sha256"] &&
         expected["building_vertices"] == actual["building_vertices"]
    fail_patch("expected_before_building_vertices_mismatch")
  end
  unless expected["construction"] == actual["construction"]
    fail_patch("expected_before_construction_mismatch")
  end
  unless expected["adjacent_surface_handle"] == actual["adjacent_surface_handle"]
    fail_patch("expected_before_adjacent_surface_mismatch")
  end
  unless expected["subsurface_handles"] == actual["subsurface_handles"]
    fail_patch("expected_before_subsurface_mismatch")
  end
  unless expected["typed_reverse_references_sha256"] ==
         actual["typed_reverse_references_sha256"] &&
         expected["typed_reverse_references"] == actual["typed_reverse_references"]
    fail_patch("expected_before_reverse_reference_mismatch")
  end
  true
end

def safe_optional_value(object, method_name)
  return nil unless object.respond_to?(method_name)

  optional_value(object.public_send(method_name))
rescue StandardError
  nil
end

def model_validity(model)
  level = OpenStudio::StrictnessLevel.new("Final")
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

def canonical_validity_value(value)
  return [nil, false] if value.nil?

  canonical_validity_text(value)
end

def canonical_validity_text(value)
  text = value.to_s
  fail_patch("model_final_validity_report_incomplete") unless text.valid_encoding?

  text = text.encode(Encoding::UTF_8)
  text = text.gsub(
    %r{\[(?:(?:[A-Za-z]:[\\/])|(?:\\\\)|/)[^\]\r\n]*\]},
    "[<path>]"
  )
  text = text.gsub(
    %r{"(?:(?:[A-Za-z]:[\\/])|(?:\\\\)|/)[^"\r\n]*"},
    '"<path>"'
  )
  text = text.gsub(
    %r{'(?:(?:[A-Za-z]:[\\/])|(?:\\\\)|/)[^'\r\n]*'},
    "'<path>'"
  )
  text = text.gsub(
    %r{(?<![A-Za-z0-9_\\/])(?:(?:[A-Za-z]:[\\/])|(?:\\\\)|/)[^\]\[;,"'\r\n]*?\.(?:[oO][sS][mM]|[iI][dD][fF]|[jJ][sS][oO][nN]|[eE][pP][wW]|[iI][dD][dD])(?::[0-9]+)?(?=$|[\t\n\v\f\r \u{0085}\u{00A0}\u{1680}\u{2000}-\u{200A}\u{2028}\u{2029}\u{202F}\u{205F}\u{3000}\]\[;,"')])}u,
    "<path>"
  )
  text = text.gsub(
    /[\t\n\v\f\r \u{0085}\u{00A0}\u{1680}\u{2000}-\u{200A}\u{2028}\u{2029}\u{202F}\u{205F}\u{3000}]+/u,
    " "
  ).sub(/\A +/, "").sub(/ +\z/, "")
  text = text.gsub("~", "~0").gsub("<truncated>", "~1")
  return [text, false] if text.length <= MAX_VALIDITY_FIELD_CHARS

  keep = MAX_VALIDITY_FIELD_CHARS - VALIDITY_TRUNCATION_MARKER.length
  keep -= 1 if text[keep - 1] == "~"
  [text[0, keep] + VALIDITY_TRUNCATION_MARKER, true]
end

def normalized_validity_error(error)
  fields = ["scope", "error_type", "object_type", "object_name", "field", "raw"]
  unless error.is_a?(Hash) && error.keys.sort == fields.sort
    fail_patch("model_final_validity_report_incomplete")
  end
  unless fields.all? { |key| error[key].nil? || error[key].is_a?(String) }
    fail_patch("model_final_validity_report_incomplete")
  end

  truncated_field_count = 0
  normalized = fields.to_h do |field|
    value = error[field]
    canonical, truncated = canonical_validity_value(value)
    truncated_field_count += 1 if truncated
    [field, canonical]
  end
  [normalized, truncated_field_count]
end

def validity_error_multiset(report)
  required = ["valid", "error_count", "errors", "errors_truncated"]
  unless report.is_a?(Hash) && report.keys.sort == required.sort &&
         [true, false].include?(report["valid"]) &&
         report["error_count"].is_a?(Integer) && report["error_count"] >= 0 &&
         report["error_count"] <= MAX_VALIDITY_ERRORS &&
         report["errors"].is_a?(Array) &&
         report["error_count"] == report["errors"].length &&
         report["errors_truncated"] == false &&
         report["valid"] == report["errors"].empty?
    fail_patch("model_final_validity_report_incomplete")
  end

  counts = Hash.new(0)
  rows = {}
  truncated_field_count = 0
  report["errors"].each do |error|
    normalized, row_truncated_field_count = normalized_validity_error(error)
    truncated_field_count += row_truncated_field_count
    token = JSON.generate(normalized.keys.sort.to_h { |key| [key, normalized[key]] })
    counts[token] += 1
    rows[token] = normalized
  end
  [
    counts,
    counts.keys.sort.map { |token| rows[token].merge("count" => counts[token]) },
    truncated_field_count
  ]
end

def validity_stage_report(source, candidate)
  source_counts, = validity_error_multiset(source)
  candidate_counts, candidate_rows, truncated_field_count =
    validity_error_multiset(candidate)
  normalized_errors = candidate["errors"].map do |error|
    normalized_validity_error(error)[0]
  end
  truncated_fields = []
  candidate["errors"].each_with_index do |error, error_index|
    fields = ["scope", "error_type", "object_type", "object_name", "field", "raw"]
    fields.each do |field|
      _, truncated = canonical_validity_value(error[field])
      if truncated
        truncated_fields << {"error_index" => error_index, "field" => field}
      end
    end
  end
  truncated_fields.sort_by! { |row| [row["error_index"], row["field"]] }
  no_regression = candidate_counts.all? do |token, count|
    count <= source_counts.fetch(token, 0)
  end
  candidate.merge(
    "errors" => normalized_errors,
    "normalized_error_multiset" => candidate_rows,
    "normalized_error_count" => candidate["error_count"],
    "normalization_truncated" => truncated_field_count > 0,
    "normalization_truncated_field_count" => truncated_field_count,
    "normalization_truncated_fields" => truncated_fields,
    "no_regression" => no_regression
  )
end

def model_object_by_handle(model, handle, missing_code)
  uuid = OpenStudio.toUUID(normalize_handle(handle))
  optional = model.getModelObject(uuid)
  fail_patch(missing_code) if optional.empty?

  optional.get
rescue PatchFailure
  raise
rescue StandardError
  fail_patch(missing_code)
end

def resolve_surface_exact(model, handle)
  object = model_object_by_handle(model, handle, "surface_handle_not_found")
  optional = object.to_Surface
  fail_patch("surface_handle_type_mismatch") if optional.empty?

  optional.get
end

def resolve_space_exact(model, handle)
  object = model_object_by_handle(model, handle, "space_handle_not_found")
  optional = object.to_Space
  fail_patch("space_handle_type_mismatch") if optional.empty?

  optional.get
end

def resolve_construction_exact(model, handle, expected)
  object = model_object_by_handle(model, handle, "construction_handle_not_found")
  unless expected.is_a?(Hash) && object_ref(object) == expected
    fail_patch("construction_expected_before_mismatch")
  end
  optional = object.to_ConstructionBase
  fail_patch("construction_handle_type_mismatch") if optional.empty?

  optional.get
end

def resolve_air_boundary_exact(model, handle, expected)
  object = model_object_by_handle(model, handle, "air_boundary_handle_not_found")
  optional = object.to_ConstructionAirBoundary
  fail_patch("air_boundary_handle_type_mismatch") if optional.empty?

  construction = optional.get
  actual = air_boundary_runtime_snapshot(construction)
  unless expected.is_a?(Hash) &&
         expected["signature_sha256"] == actual["signature_sha256"] &&
         expected["signature"] == actual["signature"]
    fail_patch("air_boundary_signature_mismatch")
  end
  construction
end

OPERATION_KEYS = {
  "set_surface_vertices" => [
    "operation_id", "operation", "plan_refs", "surface", "expected_before",
    "building_vertices_after", "building_vertices_after_sha256", "lineage"
  ],
  "set_adjacent_surfaces" => [
    "operation_id", "operation", "plan_refs", "left", "right", "expected_before"
  ],
  "set_surface_construction" => [
    "operation_id", "operation", "plan_refs", "surface", "expected_surface_before",
    "construction_handle", "expected_construction_before"
  ],
  "create_surface_piece" => [
    "operation_id", "operation", "plan_refs", "generated_object_id",
    "source_surface_handle", "expected_source_before", "space_handle", "surface_type",
    "construction_handle", "expected_construction_before", "building_vertices_after",
    "building_vertices_after_sha256", "lineage"
  ],
  "remove_unreferenced_air_boundary" => [
    "operation_id", "operation", "plan_refs", "construction_handle", "expected_before"
  ]
}.freeze

def validate_plan_refs(value)
  fail_patch("patch_plan_refs_invalid") unless value.is_a?(Array) && !value.empty?

  value.each do |row|
    unless row.is_a?(Hash) && row.keys.sort == ["plan_id", "plan_sha256"] &&
           row["plan_id"].to_s.match?(/\Apreflight:[0-9a-f]{20}\z/) &&
           SHA_PATTERN.match?(row["plan_sha256"].to_s)
      fail_patch("patch_plan_refs_invalid")
    end
  end
end

def validate_operation_schema(operation)
  fail_patch("patch_operation_invalid") unless operation.is_a?(Hash)

  kind = operation["operation"]
  fail_patch("patch_operation_not_allowed") unless ALLOWED_OPERATIONS.include?(kind)
  expected_keys = OPERATION_KEYS.fetch(kind).sort
  fail_patch("patch_operation_unknown_fields") unless operation.keys.sort == expected_keys
  unless operation["operation_id"].to_s.match?(/\Aosm-op-[0-9a-f]{23}\z/)
    fail_patch("patch_operation_id_invalid")
  end
  unless operation["operation_id"] == operation_identity(operation)
    fail_patch("patch_operation_id_mismatch")
  end
  validate_plan_refs(operation["plan_refs"])
  true
end

def exact_hash(value, keys, code)
  fail_patch(code) unless value.is_a?(Hash) && value.keys.sort == keys.sort

  value
end

def exact_object_ref(value, code)
  exact_hash(value, ["handle", "object_type", "name"], code)
  normalize_handle(value["handle"])
  fail_patch(code) unless value["object_type"].is_a?(String) && value["name"].is_a?(String)

  value
end

def validate_surface_ref(value, generated_definitions, code)
  fail_patch(code) unless value.is_a?(Hash)
  if value.keys == ["handle"]
    normalize_handle(value["handle"])
  elsif value.keys == ["generated_object_id"]
    generated_id = value["generated_object_id"].to_s
    fail_patch(code) unless generated_definitions.key?(generated_id)
    generated_id
  else
    fail_patch(code)
  end
end

def validate_lineage(lineage, generated:, source_handle:)
  code = generated ? "generated_lineage_missing" : "retained_lineage_missing"
  exact_hash(
    lineage,
    ["parent_surface_handle", "piece_index", "part_name", "identity"],
    code
  )
  parent = normalize_handle(lineage["parent_surface_handle"])
  fail_patch(code) unless parent == normalize_handle(source_handle)
  piece_index = lineage["piece_index"]
  expected_index = piece_index.is_a?(Integer) && (
    generated ? piece_index >= 1 : piece_index == 0
  )
  fail_patch(code) unless expected_index
  expected_identity = generated ? "generated_handle" : "retained_source_handle"
  fail_patch(code) unless lineage["identity"] == expected_identity
  fail_patch(code) unless lineage["part_name"].is_a?(String) && !lineage["part_name"].empty?

  true
end

def validate_vertices_after(operation)
  values = operation["building_vertices_after"]
  fail_patch("patch_vertices_invalid") unless values.is_a?(Array) && values.length >= 3
  digest = normalize_sha(
    operation["building_vertices_after_sha256"],
    "patch_vertices_sha256_invalid"
  )
  fail_patch("patch_vertices_fingerprint_mismatch") unless values_fingerprint(values) == digest

  true
end

def validate_patch_document(patch)
  exact_hash(
    patch,
    [
      "schema_version", "mapping_contract", "source", "preflight", "operations",
      "rejected_plans", "counts"
    ],
    "patch_root_schema_invalid"
  )
  fail_patch("patch_schema_version_mismatch") unless patch["schema_version"] == PATCH_SCHEMA
  unless patch["mapping_contract"] == WRITEBACK_MAPPING_CONTRACT
    fail_patch("patch_mapping_contract_mismatch")
  end
  source = exact_hash(
    patch["source"],
    [
      "sha256", "source_handle_inventory_sha256",
      "loaded_handle_inventory_sha256"
    ],
    "patch_source_schema_invalid"
  )
  normalize_sha(source["sha256"], "patch_source_sha256_invalid")
  normalize_sha(
    source["source_handle_inventory_sha256"],
    "patch_source_inventory_sha256_invalid"
  )
  normalize_sha(
    source["loaded_handle_inventory_sha256"],
    "patch_loaded_inventory_sha256_invalid"
  )
  preflight = exact_hash(
    patch["preflight"],
    ["input_sha256", "tolerance_m", "authorized_plans"],
    "patch_preflight_schema_invalid"
  )
  normalize_sha(preflight["input_sha256"], "patch_preflight_sha256_invalid")
  finite_number(preflight["tolerance_m"], "patch_tolerance_invalid")
  authorized = preflight["authorized_plans"]
  fail_patch("patch_authorized_plans_invalid") unless authorized.is_a?(Array) && !authorized.empty?
  plan_index = {}
  authorized.each do |row|
    validate_plan_refs([row])
    fail_patch("patch_authorized_plan_duplicate") if plan_index.key?(row["plan_id"])

    plan_index[row["plan_id"]] = row
  end
  rejected = patch["rejected_plans"]
  fail_patch("patch_rejected_plans_invalid") unless rejected.is_a?(Array)
  # A child artifact is all-or-nothing: an unsupported plan is never silently
  # omitted while unrelated plans are written to the model.
  fail_patch("patch_contains_rejected_plans") unless rejected.empty?
  operations = patch["operations"]
  unless operations.is_a?(Array) && !operations.empty? && operations.length <= MAX_OPERATION_RESULTS
    fail_patch("patch_operations_invalid")
  end
  counts = exact_hash(
    patch["counts"],
    [
      "plans_considered", "plans_authorized", "plans_rejected", "operations"
    ],
    "patch_counts_schema_invalid"
  )
  unless counts.values.all? { |value| value.is_a?(Integer) && value >= 0 } &&
         counts["plans_considered"] == authorized.length + rejected.length &&
         counts["plans_authorized"] == authorized.length &&
         counts["plans_rejected"] == rejected.length &&
         counts["operations"] == operations.length
    fail_patch("patch_counts_mismatch")
  end

  generated_definitions = {}
  operation_ids = {}
  operations.each do |operation|
    validate_operation_schema(operation)
    operation_id = operation["operation_id"]
    fail_patch("patch_operation_id_duplicate") if operation_ids.key?(operation_id)

    operation_ids[operation_id] = true
    operation["plan_refs"].each do |ref|
      expected = plan_index[ref["plan_id"]]
      fail_patch("patch_operation_plan_binding_mismatch") unless expected == ref
    end
    next unless operation["operation"] == "create_surface_piece"

    generated_id = operation["generated_object_id"].to_s
    unless generated_id.match?(/\Agenerated-surface:[0-9a-f]{20}\z/) &&
           !generated_definitions.key?(generated_id)
      fail_patch("generated_object_id_invalid")
    end
    generated_definitions[generated_id] = operation
  end
  referenced_plans = operations.flat_map do |operation|
    operation["plan_refs"].map { |row| row["plan_id"] }
  end.uniq.sort
  fail_patch("patch_authorized_plan_unreferenced") unless referenced_plans == plan_index.keys.sort

  operations.each do |operation|
    kind = operation["operation"]
    case kind
    when "set_surface_vertices"
      validate_surface_ref(operation["surface"], generated_definitions, "surface_reference_invalid")
      fail_patch("expected_before_snapshot_invalid") unless operation["expected_before"].is_a?(Hash)
      validate_vertices_after(operation)
      unless operation["lineage"].nil?
        fail_patch("retained_lineage_surface_invalid") unless operation["surface"].key?("handle")
        validate_lineage(
          operation["lineage"], generated: false,
          source_handle: operation["surface"]["handle"]
        )
      end
    when "set_surface_construction"
      validate_surface_ref(operation["surface"], generated_definitions, "surface_reference_invalid")
      fail_patch("expected_before_snapshot_invalid") unless operation["expected_surface_before"].is_a?(Hash)
      target_handle = normalize_handle(operation["construction_handle"])
      expected = exact_object_ref(
        operation["expected_construction_before"],
        "construction_expected_before_invalid"
      )
      fail_patch("construction_expected_before_mismatch") unless expected["handle"] == target_handle
    when "create_surface_piece"
      source_handle = normalize_handle(operation["source_surface_handle"])
      fail_patch("expected_before_snapshot_invalid") unless operation["expected_source_before"].is_a?(Hash)
      normalize_handle(operation["space_handle"])
      unless operation["surface_type"].is_a?(String) && !operation["surface_type"].empty?
        fail_patch("generated_surface_type_invalid")
      end
      construction_handle = normalize_handle(operation["construction_handle"])
      expected = exact_object_ref(
        operation["expected_construction_before"],
        "construction_expected_before_invalid"
      )
      unless expected["handle"] == construction_handle
        fail_patch("construction_expected_before_mismatch")
      end
      validate_vertices_after(operation)
      validate_lineage(operation["lineage"], generated: true, source_handle: source_handle)
    when "set_adjacent_surfaces"
      left = operation["left"]
      right = operation["right"]
      validate_surface_ref(left, generated_definitions, "adjacency_surface_reference_invalid")
      validate_surface_ref(right, generated_definitions, "adjacency_surface_reference_invalid")
      if left == right
        fail_patch("adjacency_self_reference")
      end
      expected = exact_hash(
        operation["expected_before"], ["left", "right"],
        "adjacency_expected_before_invalid"
      )
      [[left, expected["left"]], [right, expected["right"]]].each do |ref, before|
        if ref.key?("handle")
          fail_patch("adjacency_expected_before_invalid") unless before.is_a?(Hash)
        else
          fail_patch("adjacency_expected_before_invalid") unless before.nil?
        end
      end
    when "remove_unreferenced_air_boundary"
      normalize_handle(operation["construction_handle"])
      fail_patch("air_boundary_expected_before_invalid") unless operation["expected_before"].is_a?(Hash)
    end
  end
  {"operations" => operations, "generated_definitions" => generated_definitions}
end

def source_objects_by_handle(workspace)
  workspace.objects.each_with_object({}) do |object, rows|
    handle = normalize_handle(object.handle)
    fail_patch("source_handle_inventory_duplicate") if rows.key?(handle)

    rows[handle] = object
  end
end

def verify_raw_object_ref(raw_objects, expected, code)
  exact_object_ref(expected, code)
  handle = normalize_handle(expected["handle"])
  object = raw_objects[handle]
  fail_patch(code) if object.nil? || object_ref(object) != expected

  true
end

def verify_surface_source_identity(raw_objects, expected)
  verify_raw_object_ref(
    raw_objects, expected["source_object"],
    "expected_before_source_surface_mismatch"
  )
end

def verify_air_boundary_expected_before(construction, expected, raw_objects, patch_source)
  unless expected.is_a?(Hash) && expected.keys.sort == AIR_BOUNDARY_EXPECTED_KEYS.sort
    fail_patch("air_boundary_expected_before_invalid")
  end
  unless expected["object_type"] == "OS:Construction:AirBoundary" &&
         expected["loaded_object"] == object_ref(construction, "OS:Construction:AirBoundary") &&
         expected["source_object"] == object_ref(construction, "OS:Construction:AirBoundary")
    fail_patch("air_boundary_identity_mismatch")
  end
  verify_raw_object_ref(raw_objects, expected["source_object"], "air_boundary_identity_mismatch")
  binding = expected["identity_binding"]
  binding_keys = [
    "status", "mapping_contract", "basis", "mapping_truncated", "mapping_id",
    "source_sha256", "source_handle_inventory_sha256",
    "loaded_handle_inventory_sha256", "source_object", "loaded_object",
    "derived_object", "mapping_projection"
  ]
  projection = binding["mapping_projection"] if binding.is_a?(Hash)
  projection_keys = [
    "mapping_id", "mapping_contract", "mapping_status", "mapping_truncated",
    "osm_handle", "osm_object_type", "osm_object_name",
    "derived_idf_object_index", "derived_object_index_basis",
    "derived_idf_object_type", "derived_idf_object_name",
    "derived_workspace_handle", "source_sha256",
    "source_handle_inventory_sha256", "loaded_handle_inventory_sha256"
  ]
  derived = binding["derived_object"] if binding.is_a?(Hash)
  unless binding.is_a?(Hash) && binding.keys.sort == binding_keys.sort &&
         expected["identity_binding_sha256"] == air_identity_binding_digest(binding) &&
         binding["status"] == "COMPLETE" &&
         binding["mapping_contract"] == WRITEBACK_MAPPING_CONTRACT &&
         binding["basis"] == "raw-loaded-derived-typed-air-boundary-v2" &&
         binding["mapping_truncated"] == false &&
         binding["mapping_id"].to_s.match?(/\Aosm-map-[0-9a-f]{20}\z/) &&
         binding["source_object"] == expected["source_object"] &&
         binding["loaded_object"] == expected["loaded_object"] &&
         derived.is_a?(Hash) &&
         derived.keys.sort == ["handle", "object_index", "object_type", "name"].sort &&
         derived["object_index"].is_a?(Integer) && derived["object_index"] >= 0 &&
         derived["handle"].to_s.match?(HANDLE_PATTERN) &&
         derived["object_type"] == "Construction:AirBoundary" &&
         derived["name"] == expected["name"]
    fail_patch("air_boundary_identity_binding_mismatch")
  end
  unless projection.is_a?(Hash) && projection.keys.sort == projection_keys.sort &&
         projection["mapping_id"] == binding["mapping_id"] &&
         projection["mapping_id"] == expected_mapping_id(projection) &&
         projection["mapping_contract"] == WRITEBACK_MAPPING_CONTRACT &&
         projection["mapping_status"] == "EXPLICIT_EXACT_TYPE_NAME" &&
         projection["mapping_truncated"] == false &&
         projection["osm_handle"] == expected["handle"] &&
         projection["osm_object_type"] == "OS:Construction:AirBoundary" &&
         projection["osm_object_name"] == expected["name"] &&
         projection["derived_idf_object_index"] == derived["object_index"] &&
         projection["derived_object_index_basis"] == DERIVED_OBJECT_INDEX_BASIS &&
         projection["derived_idf_object_type"] == derived["object_type"] &&
         projection["derived_idf_object_name"] == derived["name"] &&
         projection["derived_workspace_handle"] == derived["handle"] &&
         projection["source_sha256"] == patch_source["sha256"] &&
         projection["source_handle_inventory_sha256"] ==
           patch_source["source_handle_inventory_sha256"] &&
         projection["loaded_handle_inventory_sha256"] ==
           patch_source["loaded_handle_inventory_sha256"]
    fail_patch("air_boundary_mapping_projection_mismatch")
  end
  unless expected["source_sha256"] == patch_source["sha256"] &&
         expected["source_handle_inventory_sha256"] ==
           patch_source["source_handle_inventory_sha256"] &&
         expected["loaded_handle_inventory_sha256"] ==
           patch_source["loaded_handle_inventory_sha256"] &&
         binding["source_sha256"] == patch_source["sha256"] &&
         binding["source_handle_inventory_sha256"] ==
           patch_source["source_handle_inventory_sha256"] &&
         binding["loaded_handle_inventory_sha256"] ==
           patch_source["loaded_handle_inventory_sha256"] &&
         expected["writeback_eligible"] == true &&
         expected["typed_reverse_references_truncated"] == false
    fail_patch("air_boundary_provenance_mismatch")
  end
  actual = air_boundary_runtime_snapshot(construction)
  unless expected["signature"] == actual["signature"] &&
         expected["signature_sha256"] == actual["signature_sha256"]
    fail_patch("air_boundary_signature_mismatch")
  end
  unless expected["typed_reverse_references"] == actual["typed_reverse_references"] &&
         expected["typed_reverse_references_sha256"] ==
           actual["typed_reverse_references_sha256"]
    fail_patch("air_boundary_reverse_reference_mismatch")
  end
  true
end

def resolve_surface_ref(model, value, generated_surfaces)
  if value.key?("handle")
    resolve_surface_exact(model, value["handle"])
  else
    surface = generated_surfaces[value["generated_object_id"]]
    fail_patch("generated_surface_not_available") if surface.nil?

    surface
  end
end

def surface_building_vertices(surface)
  fail_patch("surface_space_missing_after_operation") unless surface.space.is_initialized

  transformation = surface.space.get.transformation
  points = OpenStudio::Point3dVector.new
  surface.vertices.each { |point| points << transformation * point }
  points
end

def verify_surface_vertices_after(surface, operation)
  actual = vector_values(surface_building_vertices(surface))
  expected = operation["building_vertices_after"]
  close = actual.length == expected.length && actual.each_with_index.all? do |point, index|
    point.each_with_index.all? do |coordinate, axis|
      (coordinate - finite_number(expected[index][axis])).abs <= 1.0e-9
    end
  end
  unless close
    fail_patch("surface_vertices_after_mismatch")
  end
  true
end

def prevalidate_operations(model, raw_objects, patch, context)
  definitions = context["generated_definitions"]
  context["operations"].each do |operation|
    case operation["operation"]
    when "set_surface_vertices"
      fail_patch("generated_surface_mutated_before_creation") if operation["surface"].key?("generated_object_id")
      surface = resolve_surface_exact(model, operation["surface"]["handle"])
      verify_surface_source_identity(raw_objects, operation["expected_before"])
      verify_surface_expected_before(surface, operation["expected_before"], require_complete: true)
    when "set_surface_construction"
      fail_patch("generated_surface_construction_operation_invalid") if operation["surface"].key?("generated_object_id")
      surface = resolve_surface_exact(model, operation["surface"]["handle"])
      verify_surface_source_identity(raw_objects, operation["expected_surface_before"])
      verify_surface_expected_before(
        surface, operation["expected_surface_before"], require_complete: true
      )
      expected = operation["expected_construction_before"]
      verify_raw_object_ref(raw_objects, expected, "construction_expected_before_mismatch")
      resolve_construction_exact(model, operation["construction_handle"], expected)
    when "create_surface_piece"
      source = resolve_surface_exact(model, operation["source_surface_handle"])
      expected_source = operation["expected_source_before"]
      verify_surface_source_identity(raw_objects, expected_source)
      verify_surface_expected_before(source, expected_source, require_complete: true)
      unless normalize_handle(expected_source["space"]["handle"]) ==
               normalize_handle(operation["space_handle"])
        fail_patch("generated_space_handle_mismatch")
      end
      space = resolve_space_exact(model, operation["space_handle"])
      verify_raw_object_ref(raw_objects, expected_source["space"], "generated_space_identity_mismatch")
      unless object_ref(space, "OS:Space") == expected_source["space"]
        fail_patch("generated_space_identity_mismatch")
      end
      unless operation["surface_type"] == expected_source["surface_type"]
        fail_patch("generated_surface_type_mismatch")
      end
      expected = operation["expected_construction_before"]
      verify_raw_object_ref(raw_objects, expected, "construction_expected_before_mismatch")
      resolve_construction_exact(model, operation["construction_handle"], expected)
    when "set_adjacent_surfaces"
      expected = operation["expected_before"]
      [[operation["left"], expected["left"]], [operation["right"], expected["right"]]].each do |ref, before|
        next if ref.key?("generated_object_id")

        surface = resolve_surface_exact(model, ref["handle"])
        verify_surface_source_identity(raw_objects, before)
        verify_surface_expected_before(surface, before, require_complete: true)
      end
    when "remove_unreferenced_air_boundary"
      expected = operation["expected_before"]
      construction = resolve_air_boundary_exact(
        model, operation["construction_handle"], expected
      )
      verify_air_boundary_expected_before(construction, expected, raw_objects, patch["source"])
    end
  end
  # Every generated reference has exactly one already validated definition.
  definitions.each_key do |generated_id|
    reference_count = context["operations"].count do |operation|
      operation["operation"] == "set_adjacent_surfaces" &&
        [operation["left"], operation["right"]].any? do |ref|
          ref["generated_object_id"] == generated_id
        end
    end
    fail_patch("generated_adjacency_missing") unless reference_count == 1
  end
  true
end

def apply_operations(model, context)
  generated_surfaces = {}
  generated_lineage = []
  retained_lineage = []
  removed_handles = []
  results = []
  context["operations"].each do |operation|
    case operation["operation"]
    when "set_surface_vertices"
      surface = resolve_surface_ref(model, operation["surface"], generated_surfaces)
      fail_patch("surface_space_missing_before_vertices") unless surface.space.is_initialized
      local = building_points_to_local(
        surface.space.get, operation["building_vertices_after"]
      )
      fail_patch("set_surface_vertices_failed") unless surface.setVertices(local)
      verify_surface_vertices_after(surface, operation)
      unless operation["lineage"].nil?
        retained_lineage << operation["lineage"].merge(
          "surface_handle" => normalize_handle(surface.handle)
        )
      end
    when "set_surface_construction"
      surface = resolve_surface_ref(model, operation["surface"], generated_surfaces)
      construction = resolve_construction_exact(
        model, operation["construction_handle"],
        operation["expected_construction_before"]
      )
      fail_patch("set_surface_construction_failed") unless surface.setConstruction(construction)
      unless surface.construction.is_initialized &&
             normalize_handle(surface.construction.get.handle) ==
               normalize_handle(operation["construction_handle"])
        fail_patch("surface_construction_after_mismatch")
      end
    when "create_surface_piece"
      space = resolve_space_exact(model, operation["space_handle"])
      construction = resolve_construction_exact(
        model, operation["construction_handle"],
        operation["expected_construction_before"]
      )
      local = building_points_to_local(space, operation["building_vertices_after"])
      begin
        surface = OpenStudio::Model::Surface.new(local, model)
      rescue StandardError
        fail_patch("create_surface_piece_failed")
      end
      # OpenStudio 3.6.1 exposes only Surface.new(vertices, model). These two
      # typed initializers are confined to this operation and checked exactly.
      fail_patch("create_surface_piece_set_space_failed") unless surface.setSpace(space)
      unless surface.setSurfaceType(operation["surface_type"])
        fail_patch("create_surface_piece_set_surface_type_failed")
      end
      unless surface.setConstruction(construction)
        fail_patch("create_surface_piece_set_construction_failed")
      end
      verify_surface_vertices_after(surface, operation)
      unless surface.space.is_initialized &&
             normalize_handle(surface.space.get.handle) == normalize_handle(operation["space_handle"])
        fail_patch("generated_space_after_mismatch")
      end
      fail_patch("generated_surface_type_after_mismatch") unless surface.surfaceType == operation["surface_type"]
      unless surface.construction.is_initialized &&
             normalize_handle(surface.construction.get.handle) ==
               normalize_handle(operation["construction_handle"])
        fail_patch("generated_construction_after_mismatch")
      end
      generated_id = operation["generated_object_id"]
      generated_surfaces[generated_id] = surface
      generated_lineage << operation["lineage"].merge({
        "generated_object_id" => generated_id,
        "generated_handle" => normalize_handle(surface.handle),
        "space_handle" => normalize_handle(space.handle),
        "surface_type" => surface.surfaceType,
        "construction_handle" => normalize_handle(construction.handle)
      })
    when "set_adjacent_surfaces"
      left = resolve_surface_ref(model, operation["left"], generated_surfaces)
      right = resolve_surface_ref(model, operation["right"], generated_surfaces)
      fail_patch("set_adjacent_surfaces_failed") unless left.setAdjacentSurface(right)
      unless left.adjacentSurface.is_initialized && right.adjacentSurface.is_initialized &&
             normalize_handle(left.adjacentSurface.get.handle) == normalize_handle(right.handle) &&
             normalize_handle(right.adjacentSurface.get.handle) == normalize_handle(left.handle)
        fail_patch("surface_adjacency_after_mismatch")
      end
    when "remove_unreferenced_air_boundary"
      construction = resolve_air_boundary_exact(
        model, operation["construction_handle"], operation["expected_before"]
      )
      fail_patch("air_boundary_still_referenced") unless construction.sources.empty?
      handle = normalize_handle(construction.handle)
      construction.remove
      optional = model.getModelObject(OpenStudio.toUUID(handle))
      fail_patch("remove_air_boundary_failed") unless optional.empty?
      removed_handles << handle
    end
    results << {
      "operation_id" => operation["operation_id"],
      "operation" => operation["operation"],
      "status" => "APPLIED"
    }
  end
  {
    "generated_surfaces" => generated_surfaces,
    "generated_lineage" => generated_lineage,
    "retained_lineage" => retained_lineage,
    "removed_handles" => removed_handles,
    "results" => results
  }
end

def verify_after_reload(model, context, journal)
  generated_handles = journal["generated_lineage"].each_with_object({}) do |row, values|
    values[row["generated_object_id"]] = row["generated_handle"]
  end
  context["operations"].each do |operation|
    ref_to_handle = lambda do |ref|
      ref.key?("handle") ? ref["handle"] : generated_handles[ref["generated_object_id"]]
    end
    case operation["operation"]
    when "set_surface_vertices"
      surface = resolve_surface_exact(model, ref_to_handle.call(operation["surface"]))
      verify_surface_vertices_after(surface, operation)
    when "set_surface_construction"
      surface = resolve_surface_exact(model, ref_to_handle.call(operation["surface"]))
      unless surface.construction.is_initialized &&
             normalize_handle(surface.construction.get.handle) ==
               normalize_handle(operation["construction_handle"])
        fail_patch("reload_surface_construction_mismatch")
      end
    when "create_surface_piece"
      surface = resolve_surface_exact(model, generated_handles[operation["generated_object_id"]])
      verify_surface_vertices_after(surface, operation)
      unless surface.space.is_initialized &&
             normalize_handle(surface.space.get.handle) == normalize_handle(operation["space_handle"])
        fail_patch("reload_generated_space_mismatch")
      end
      fail_patch("reload_generated_surface_type_mismatch") unless surface.surfaceType == operation["surface_type"]
      unless surface.construction.is_initialized &&
             normalize_handle(surface.construction.get.handle) ==
               normalize_handle(operation["construction_handle"])
        fail_patch("reload_generated_construction_mismatch")
      end
    when "set_adjacent_surfaces"
      left = resolve_surface_exact(model, ref_to_handle.call(operation["left"]))
      right = resolve_surface_exact(model, ref_to_handle.call(operation["right"]))
      unless left.adjacentSurface.is_initialized && right.adjacentSurface.is_initialized &&
             normalize_handle(left.adjacentSurface.get.handle) == normalize_handle(right.handle) &&
             normalize_handle(right.adjacentSurface.get.handle) == normalize_handle(left.handle)
        fail_patch("reload_surface_adjacency_mismatch")
      end
    when "remove_unreferenced_air_boundary"
      optional = model.getModelObject(OpenStudio.toUUID(operation["construction_handle"]))
      fail_patch("reload_removed_air_boundary_present") unless optional.empty?
    end
  end
  true
end

def failure_report(code)
  {
    "schema_version" => "idfrepair.openstudio-writeback.v1",
    "status" => "REJECTED",
    "failure_code" => code.to_s[0, 160],
    "source_osm_modified" => false,
    "reverse_translation_used" => false,
    "osm_writeback_authorized" => false
  }
end

def write_report(path, payload)
  File.write(path, JSON.pretty_generate(payload) + "\n")
end

def execute_patch(input_path, patch_path, output_path)
  fail_patch("patch_output_already_exists") if File.exist?(output_path)
  fail_patch("patch_file_too_large") if File.size(patch_path) > MAX_PATCH_BYTES
  patch = JSON.parse(File.read(patch_path, encoding: "UTF-8"))
  context = validate_patch_document(patch)
  source_sha256 = Digest::SHA256.file(input_path).hexdigest
  fail_patch("source_sha256_mismatch") unless source_sha256 == patch["source"]["sha256"]

  raw_optional = OpenStudio::Workspace.load(OpenStudio::Path.new(input_path))
  fail_patch("source_workspace_load_failed") if raw_optional.empty?
  raw_workspace = raw_optional.get
  raw_inventory = handle_inventory(raw_workspace.objects)
  fail_patch("source_handle_inventory_incomplete") if raw_inventory["objects_truncated"]
  unless raw_inventory["sha256"] == patch["source"]["source_handle_inventory_sha256"]
    fail_patch("source_handle_inventory_mismatch")
  end
  raw_objects = source_objects_by_handle(raw_workspace)

  translator = OpenStudio::OSVersion::VersionTranslator.new
  optional_model = translator.loadModel(OpenStudio::Path.new(input_path))
  fail_patch("source_model_load_failed") if optional_model.empty?
  model = optional_model.get
  loaded_inventory = handle_inventory(model.modelObjects)
  fail_patch("loaded_handle_inventory_incomplete") if loaded_inventory["objects_truncated"]
  unless loaded_inventory["sha256"] == patch["source"]["loaded_handle_inventory_sha256"]
    fail_patch("loaded_handle_inventory_mismatch")
  end
  unless raw_inventory["sha256"] == loaded_inventory["sha256"]
    fail_patch("source_loaded_handle_inventory_mismatch")
  end
  source_validity_raw = model_validity(model)
  source_validity = validity_stage_report(
    source_validity_raw, source_validity_raw
  )
  prevalidate_operations(model, raw_objects, patch, context)
  initial_handles = model.modelObjects.map { |object| normalize_handle(object.handle) }.sort
  journal = apply_operations(model, context)

  before_save_validity_raw = model_validity(model)
  before_save_validity = validity_stage_report(
    source_validity_raw, before_save_validity_raw
  )
  unless before_save_validity["no_regression"]
    fail_patch("model_final_validity_regressed_before_save")
  end
  staging_path = "#{output_path}.staged.osm"
  fail_patch("patch_staging_exists") if File.exist?(staging_path)
  unless model.save(OpenStudio::Path.new(staging_path), true)
    fail_patch("staged_model_save_failed")
  end
  reload_translator = OpenStudio::OSVersion::VersionTranslator.new
  optional_reloaded = reload_translator.loadModel(OpenStudio::Path.new(staging_path))
  fail_patch("staged_model_reload_failed") if optional_reloaded.empty?
  reloaded = optional_reloaded.get
  after_reload_validity = validity_stage_report(
    before_save_validity_raw, model_validity(reloaded)
  )
  unless after_reload_validity["no_regression"]
    fail_patch("model_final_validity_regressed_after_reload")
  end
  verify_after_reload(reloaded, context, journal)

  final_handles = reloaded.modelObjects.map { |object| normalize_handle(object.handle) }.sort
  generated_handles = journal["generated_lineage"].map { |row| row["generated_handle"] }.sort
  removed_handles = journal["removed_handles"].sort
  added = final_handles - initial_handles
  removed = initial_handles - final_handles
  untracked = added - generated_handles
  missing = generated_handles - added
  unexpected_removed = removed - removed_handles
  fail_patch("untracked_generated_object") unless untracked.empty?
  fail_patch("generated_object_missing_after_reload") unless missing.empty?
  fail_patch("unexpected_removed_object") unless unexpected_removed.empty?
  fail_patch("removed_object_present_after_reload") unless (removed_handles - removed).empty?
  fail_patch("source_osm_modified") unless Digest::SHA256.file(input_path).hexdigest == source_sha256

  repaired_sha256 = Digest::SHA256.file(staging_path).hexdigest
  result = {
    "schema_version" => "idfrepair.openstudio-writeback.v1",
    "status" => "VALIDATED",
    "mapping_contract" => WRITEBACK_MAPPING_CONTRACT,
    "source_sha256" => source_sha256,
    "repaired_sha256" => repaired_sha256,
    "source_osm_modified" => false,
    "reverse_translation_used" => false,
    "osm_writeback_authorized" => true,
    "operations" => journal["results"],
    "counts" => {
      "operations_requested" => context["operations"].length,
      "operations_applied" => journal["results"].length,
      "generated_surfaces" => generated_handles.length,
      "removed_air_boundaries" => removed_handles.length
    },
    "generated_lineage" => journal["generated_lineage"],
    "retained_lineage" => journal["retained_lineage"],
    "model_validity" => {
      "source_before" => source_validity,
      "after_mutation_before_save" => before_save_validity,
      "after_reload" => after_reload_validity
    },
    "inventory_audit" => {
      "initial_sha256" => loaded_inventory["sha256"],
      "final_sha256" => handle_inventory(reloaded.modelObjects)["sha256"],
      "generated_handles" => generated_handles,
      "removed_handles" => removed_handles,
      "untracked_generated_handles" => untracked,
      "missing_generated_handles" => missing,
      "unexpected_removed_handles" => unexpected_removed
    },
    "api_deviations" => (
      context["generated_definitions"].empty? ? [] : [{
        "operation" => "create_surface_piece",
        "reason" => "openstudio_3_6_1_surface_constructor_requires_model_then_typed_initializers",
        "typed_initializers" => ["setSpace", "setSurfaceType"]
      }]
    )
  }
  [result, staging_path]
rescue JSON::ParserError, EncodingError
  fail_patch("patch_json_invalid")
rescue Errno::ENOENT
  fail_patch("patch_input_missing")
end

unless ENV["IDFREPAIR_APPLY_REPAIRS_HELPERS_ONLY"] == "1"
  if ARGV.length != 4
    warn "apply_repairs_argument_count_invalid"
    exit 2
  end
  input_path, patch_path, output_path, report_path = ARGV
  staging_path = "#{output_path}.staged.osm"
  published = false
  begin
    result, staged = execute_patch(input_path, patch_path, output_path)
    File.rename(staged, output_path)
    published = true
    write_report(report_path, result)
  rescue PatchFailure => error
    File.delete(staging_path) if File.file?(staging_path)
    File.delete(output_path) if published && File.file?(output_path)
    write_report(report_path, failure_report(error.code))
    warn error.code
    exit 3
  rescue StandardError
    File.delete(staging_path) if File.file?(staging_path)
    File.delete(output_path) if published && File.file?(output_path)
    write_report(report_path, failure_report("openstudio_patch_internal_error"))
    warn "openstudio_patch_internal_error"
    exit 4
  end
end
