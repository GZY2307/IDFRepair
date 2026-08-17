"""Compile proof-gated model-preflight plans into finite OpenStudio operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
import json
import math
import re
from typing import Any

from idfrepair.io.idf import canonical
from idfrepair.knowledge.geometry_graph import Point3D
from idfrepair.preflight.partition import (
    prove_direct_surface_pair,
    prove_surface_partition,
)


PATCH_SCHEMA = "idfrepair.openstudio-patch.v1"
WRITEBACK_MAPPING_CONTRACT = "exact-source-handle-typed-surface-v2"
AIR_BOUNDARY_IDENTITY_BASIS = "raw-loaded-derived-typed-air-boundary-v2"
DERIVED_OBJECT_INDEX_BASIS = "idf-document-order-including-version-v1"
ALLOWED_OPERATIONS = frozenset({
    "set_surface_vertices",
    "set_adjacent_surfaces",
    "set_surface_construction",
    "create_surface_piece",
    "remove_unreferenced_air_boundary",
})

_SURFACE_SNAPSHOT_KEYS = frozenset({
    "source_object",
    "loaded_object",
    "derived_object",
    "space",
    "space_transformation",
    "surface_type",
    "local_vertices",
    "local_vertices_sha256",
    "building_vertices",
    "building_vertices_sha256",
    "construction",
    "adjacent_surface_handle",
    "subsurface_handles",
    "typed_reverse_references",
    "typed_reverse_references_sha256",
})
_AIR_IDENTITY_BINDING_KEYS = frozenset({
    "status",
    "mapping_contract",
    "basis",
    "mapping_truncated",
    "mapping_id",
    "source_sha256",
    "source_handle_inventory_sha256",
    "loaded_handle_inventory_sha256",
    "source_object",
    "loaded_object",
    "derived_object",
    "mapping_projection",
})
_AIR_MAPPING_PROJECTION_KEYS = frozenset({
    "mapping_id",
    "mapping_contract",
    "mapping_status",
    "mapping_truncated",
    "osm_handle",
    "osm_object_type",
    "osm_object_name",
    "derived_idf_object_index",
    "derived_object_index_basis",
    "derived_idf_object_type",
    "derived_idf_object_name",
    "derived_workspace_handle",
    "source_sha256",
    "source_handle_inventory_sha256",
    "loaded_handle_inventory_sha256",
})
_HANDLE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_OPERATION_ORDER = {
    "set_surface_vertices": 0,
    "set_surface_construction": 1,
    "create_surface_piece": 2,
    "set_adjacent_surfaces": 3,
    "remove_unreferenced_air_boundary": 4,
}


class _PlanRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _reject(reason: str) -> None:
    raise _PlanRejected(reason)


def _normalized_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        _reject("plan_payload_not_finite_json")
    raise AssertionError("unreachable")


def _json_sha256(value: object) -> str:
    return sha256(_normalized_json(value).encode("utf-8")).hexdigest()


def _canonical_operation_value(value: object) -> list[object]:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, (int, float)):
        return ["number", _number_token(value)]
    if isinstance(value, str):
        return ["string", value.encode("utf-8").hex()]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            _reject("operation_identity_payload_invalid")
        return ["object", [
            [key.encode("utf-8").hex(), _canonical_operation_value(value[key])]
            for key in sorted(value, key=lambda item: item.encode("utf-8"))
        ]]
    if (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
    ):
        return ["array", [_canonical_operation_value(item) for item in value]]
    _reject("operation_identity_payload_invalid")
    raise AssertionError("unreachable")


def _canonical_operation_body_json(operation: Mapping[str, Any]) -> str:
    body = {key: value for key, value in operation.items() if key != "operation_id"}
    return json.dumps(
        _canonical_operation_value(body),
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _operation_id(operation: Mapping[str, Any]) -> str:
    digest = sha256(_canonical_operation_body_json(operation).encode("ascii")).hexdigest()
    return f"osm-op-{digest[:23]}"


def _number_token(value: object) -> str:
    if isinstance(value, bool):
        _reject("surface_before_value_invalid")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        _reject("surface_before_value_invalid")
    if not math.isfinite(number):
        _reject("surface_before_value_invalid")
    return "0" if number == 0.0 else format(number, ".17g")


def _points(value: object, *, reason: str) -> list[list[float]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) < 3
    ):
        _reject(reason)
    points: list[list[float]] = []
    for raw_point in value:
        if (
            not isinstance(raw_point, Sequence)
            or isinstance(raw_point, (str, bytes, bytearray))
            or len(raw_point) != 3
        ):
            _reject(reason)
        point: list[float] = []
        for coordinate in raw_point:
            token = _number_token(coordinate)
            point.append(float(token))
        points.append(point)
    return points


def _points_sha256(points: Sequence[Sequence[object]]) -> str:
    return _json_sha256([
        [_number_token(coordinate) for coordinate in point]
        for point in points
    ])


def _reverse_references_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    return _json_sha256([
        [
            row.get("source_handle"),
            row.get("source_object_type"),
            row.get("source_object_name"),
            row.get("field_index"),
            row.get("field_name"),
        ]
        for row in rows
    ])


def _typed_reference_identity(
    row: Mapping[str, Any],
    *,
    reason: str,
) -> tuple[str, str, str, int, str]:
    if set(row) != {
        "source_handle",
        "source_object_type",
        "source_object_name",
        "field_index",
        "field_name",
    }:
        _reject(reason)
    source_handle = _handle(row.get("source_handle"), reason=reason)
    source_type = row.get("source_object_type")
    source_name = row.get("source_object_name")
    field_index = row.get("field_index")
    field_name = row.get("field_name")
    if (
        not isinstance(source_type, str)
        or not isinstance(source_name, str)
        or isinstance(field_index, bool)
        or not isinstance(field_index, int)
        or field_index < 0
        or not isinstance(field_name, str)
        or not field_name
    ):
        _reject(reason)
    return source_handle, source_type, source_name, field_index, field_name


def _plan_object_identity(value: object, *, reason: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "object_index", "object_type", "object_name",
    }:
        _reject(reason)
    object_index = value.get("object_index")
    object_type = value.get("object_type")
    object_name = value.get("object_name")
    if (
        isinstance(object_index, bool)
        or not isinstance(object_index, int)
        or object_index < 0
        or not isinstance(object_type, str)
        or not object_type
        or not isinstance(object_name, str)
        or not object_name
    ):
        _reject(reason)
    return {
        "object_index": object_index,
        "object_type": object_type,
        "object_name": object_name,
    }


def _air_identity_binding_sha256(binding: Mapping[str, Any]) -> str:
    def tagged_ref(key: str) -> list[object]:
        value = binding.get(key)
        if not isinstance(value, Mapping):
            return [key, None, None, None]
        fields = ["handle", "object_type", "name"]
        if key == "derived_object":
            fields.insert(1, "object_index")
        return [key, *(value.get(field) for field in fields)]

    projection = binding.get("mapping_projection")
    projection_values: list[object] = ["mapping_projection"]
    for key in (
        "mapping_id", "mapping_contract", "mapping_status", "mapping_truncated",
        "osm_handle", "osm_object_type", "osm_object_name",
        "derived_idf_object_index", "derived_object_index_basis",
        "derived_idf_object_type", "derived_idf_object_name",
        "derived_workspace_handle", "source_sha256",
        "source_handle_inventory_sha256", "loaded_handle_inventory_sha256",
    ):
        projection_values.append(
            projection.get(key) if isinstance(projection, Mapping) else None
        )

    return _json_sha256([
        binding.get("status"),
        binding.get("mapping_contract"),
        binding.get("basis"),
        binding.get("mapping_truncated"),
        binding.get("mapping_id"),
        binding.get("source_sha256"),
        binding.get("source_handle_inventory_sha256"),
        binding.get("loaded_handle_inventory_sha256"),
        tagged_ref("source_object"),
        tagged_ref("loaded_object"),
        tagged_ref("derived_object"),
        projection_values,
    ])


def _air_mapping_projection(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {key: mapping.get(key) for key in (
        "mapping_id", "mapping_contract", "mapping_status", "mapping_truncated",
        "osm_handle", "osm_object_type", "osm_object_name",
        "derived_idf_object_index", "derived_object_index_basis",
        "derived_idf_object_type", "derived_idf_object_name",
        "derived_workspace_handle", "source_sha256",
        "source_handle_inventory_sha256", "loaded_handle_inventory_sha256",
    )}


def _expected_mapping_id(mapping: Mapping[str, Any]) -> str:
    identity = "|".join((
        str(mapping.get("osm_object_type") or ""),
        str(mapping.get("osm_handle") or ""),
        str(mapping.get("derived_idf_object_type") or ""),
        str(mapping.get("osm_object_name") or ""),
    ))
    return f"osm-map-{sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def _air_boundary_plan_signature(
    snapshot: Mapping[str, Any],
    expected_length: int,
) -> list[str]:
    rows = _mapping_list(snapshot.get("signature"))
    if len(rows) < expected_length:
        _reject("air_boundary_signature_mismatch")
    values: list[str] = []
    for row in rows[:expected_length]:
        if "value" in row:
            values.append(str(row.get("value") or ""))
        elif isinstance(row.get("target_name"), str):
            values.append(canonical(str(row["target_name"])))
        else:
            _reject("air_boundary_signature_mismatch")
    return values


def _handle(value: object, *, reason: str) -> str:
    text = str(value or "").strip().strip("{}").casefold()
    if not _HANDLE_RE.fullmatch(text):
        _reject(reason)
    return text


def _sha(value: object, *, reason: str) -> str:
    text = str(value or "").casefold()
    if not _SHA_RE.fullmatch(text):
        _reject(reason)
    return text


def _mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _inventory(
    bridge_report: Mapping[str, Any],
    key: str,
    *,
    incomplete_reason: str,
) -> tuple[str, dict[str, Mapping[str, Any]]]:
    value = bridge_report.get(key)
    if not isinstance(value, Mapping):
        _reject(incomplete_reason)
    if value.get("status") != "COMPLETE" or value.get("objects_truncated") is not False:
        _reject(incomplete_reason)
    rows = _mapping_list(value.get("objects"))
    if value.get("count") != len(rows):
        _reject(incomplete_reason)
    normalized: list[list[str]] = []
    index: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        handle = _handle(row.get("handle"), reason=incomplete_reason)
        object_type = row.get("object_type")
        name = row.get("name")
        if not isinstance(object_type, str) or not isinstance(name, str) or handle in index:
            _reject(incomplete_reason)
        index[handle] = row
        normalized.append([handle, object_type, name])
    normalized.sort()
    digest = _sha(value.get("sha256"), reason=incomplete_reason)
    if _json_sha256(normalized) != digest:
        _reject(f"{key}_digest_mismatch")
    return digest, index


def _ref_matches(
    value: object,
    *,
    handle: str,
    object_type: str,
    name: str,
) -> bool:
    return bool(
        isinstance(value, Mapping)
        and str(value.get("handle") or "").strip("{}").casefold() == handle
        and value.get("object_type") == object_type
        and value.get("name") == name
    )


def _validate_surface_mapping(
    mapping: Mapping[str, Any],
    *,
    derived_type: str,
    derived_name: str,
    source_sha256: str,
    source_inventory_sha256: str,
    loaded_inventory_sha256: str,
    source_inventory: Mapping[str, Mapping[str, Any]],
    loaded_inventory: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if mapping.get("osm_object_type") != "OS:Surface":
        _reject("surface_mapping_type_mismatch")
    if (
        mapping.get("derived_idf_object_type") != derived_type
        or mapping.get("derived_idf_object_name") != derived_name
    ):
        _reject("surface_mapping_derived_identity_mismatch")
    if mapping.get("mapping_contract") != WRITEBACK_MAPPING_CONTRACT:
        _reject("mapping_contract_not_writeback_capable")
    if mapping.get("mapping_status") != "EXPLICIT_EXACT_TYPE_NAME":
        _reject("exact_typed_mapping_unavailable")
    if mapping.get("source_sha256") != source_sha256:
        _reject("mapping_source_identity_mismatch")
    if (
        mapping.get("source_handle_inventory_sha256") != source_inventory_sha256
        or mapping.get("loaded_handle_inventory_sha256") != loaded_inventory_sha256
    ):
        _reject("mapping_inventory_binding_mismatch")
    handle = _handle(mapping.get("osm_handle"), reason="surface_handle_invalid")
    if handle not in source_inventory:
        _reject("source_handle_absent_from_inventory")
    if handle not in loaded_inventory:
        _reject("loaded_handle_absent_from_inventory")
    if mapping.get("osm_object_name") != derived_name:
        _reject("surface_mapping_name_mismatch")
    if mapping.get("writeback_eligible") is not True:
        reasons = mapping.get("writeback_reasons")
        if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes)):
            for reason in (
                "surface_has_subsurfaces",
                "unsupported_typed_reverse_reference",
                "typed_reverse_references_truncated",
                "source_handle_absent_from_raw_osm",
            ):
                if reason in reasons:
                    _reject(reason)
        _reject("exact_typed_mapping_unavailable")
    before = mapping.get("expected_before")
    if not isinstance(before, Mapping) or set(before) != _SURFACE_SNAPSHOT_KEYS:
        _reject("surface_expected_before_incomplete")
    source_object = source_inventory[handle]
    loaded_object = loaded_inventory[handle]
    if (
        source_object.get("object_type") != "OS:Surface"
        or loaded_object.get("object_type") != "OS:Surface"
        or source_object.get("name") != derived_name
        or loaded_object.get("name") != derived_name
    ):
        _reject("surface_mapping_type_mismatch")
    if not _ref_matches(
        before.get("source_object"),
        handle=handle,
        object_type="OS:Surface",
        name=derived_name,
    ) or not _ref_matches(
        before.get("loaded_object"),
        handle=handle,
        object_type="OS:Surface",
        name=derived_name,
    ):
        _reject("surface_before_identity_mismatch")
    derived_handle = _handle(
        mapping.get("derived_workspace_handle"),
        reason="derived_surface_handle_invalid",
    )
    if not _ref_matches(
        before.get("derived_object"),
        handle=derived_handle,
        object_type="BuildingSurface:Detailed",
        name=derived_name,
    ):
        _reject("surface_before_derived_identity_mismatch")

    local = _points(before.get("local_vertices"), reason="surface_before_vertices_invalid")
    building = _points(
        before.get("building_vertices"), reason="surface_before_vertices_invalid",
    )
    if len(local) != len(building):
        _reject("surface_before_vertices_invalid")
    if (
        before.get("local_vertices_sha256") != _points_sha256(local)
        or before.get("building_vertices_sha256") != _points_sha256(building)
    ):
        _reject("surface_before_fingerprint_mismatch")

    space = before.get("space")
    if not isinstance(space, Mapping):
        _reject("surface_space_provenance_missing")
    space_handle = _handle(space.get("handle"), reason="surface_space_handle_invalid")
    raw_space = source_inventory.get(space_handle)
    loaded_space = loaded_inventory.get(space_handle)
    if (
        raw_space is None
        or loaded_space is None
        or raw_space.get("object_type") != "OS:Space"
        or loaded_space.get("object_type") != "OS:Space"
        or not _ref_matches(
            space,
            handle=space_handle,
            object_type="OS:Space",
            name=str(raw_space.get("name")),
        )
    ):
        _reject("surface_space_provenance_mismatch")
    transformation = before.get("space_transformation")
    if not isinstance(transformation, Mapping):
        _reject("surface_space_transformation_missing")
    matrix = transformation.get("matrix")
    if (
        not isinstance(matrix, Sequence)
        or isinstance(matrix, (str, bytes))
        or len(matrix) != 4
        or any(
            not isinstance(row, Sequence)
            or isinstance(row, (str, bytes))
            or len(row) != 4
            for row in matrix
        )
    ):
        _reject("surface_space_transformation_missing")
    matrix_tokens = [[_number_token(value) for value in row] for row in matrix]
    if transformation.get("sha256") != _json_sha256(matrix_tokens):
        _reject("surface_space_transformation_mismatch")

    construction = before.get("construction")
    if not isinstance(construction, Mapping):
        _reject("surface_construction_provenance_missing")
    construction_handle = _handle(
        construction.get("handle"), reason="surface_construction_handle_invalid",
    )
    raw_construction = source_inventory.get(construction_handle)
    loaded_construction = loaded_inventory.get(construction_handle)
    if (
        raw_construction is None
        or loaded_construction is None
        or raw_construction.get("object_type") != construction.get("object_type")
        or loaded_construction.get("object_type") != construction.get("object_type")
        or raw_construction.get("name") != construction.get("name")
        or loaded_construction.get("name") != construction.get("name")
    ):
        _reject("surface_construction_provenance_mismatch")
    subsurfaces = before.get("subsurface_handles")
    if not isinstance(subsurfaces, list):
        _reject("surface_expected_before_incomplete")
    if subsurfaces:
        _reject("surface_has_subsurfaces")
    reverse_references = _mapping_list(before.get("typed_reverse_references"))
    if before.get("typed_reverse_references_sha256") != _reverse_references_sha256(
        reverse_references
    ):
        _reject("typed_reverse_reference_digest_mismatch")
    if any(
        row.get("source_object_type") != "OS:Surface"
        or row.get("field_name") != "Outside Boundary Condition Object"
        for row in reverse_references
    ):
        _reject("unsupported_typed_reverse_reference")
    adjacent = before.get("adjacent_surface_handle")
    if adjacent is not None:
        adjacent_handle = _handle(adjacent, reason="surface_adjacent_handle_invalid")
        if (
            adjacent_handle not in source_inventory
            or source_inventory[adjacent_handle].get("object_type") != "OS:Surface"
        ):
            _reject("surface_adjacent_provenance_mismatch")
    surface_type = before.get("surface_type")
    if not isinstance(surface_type, str) or not surface_type:
        _reject("surface_type_provenance_missing")
    return deepcopy(dict(before))


def _expected_plan_id(plan: Mapping[str, Any]) -> str | None:
    kind = str(plan.get("kind") or "")
    if kind in {"reciprocal_surface_pair", "split_and_pair", "resegment_and_pair"}:
        ids = plan.get("surface_ids")
        if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)):
            return None
        token = "|".join((kind, *(sorted(str(row) for row in ids))))
    elif kind == "vertex_snap":
        after = plan.get("after_world")
        if not isinstance(after, Sequence) or isinstance(after, (str, bytes)):
            return None
        token = "|".join((
            kind,
            str(plan.get("source_vertex_id") or ""),
            *(_number_token(value) for value in after),
        ))
    elif kind == "canonicalize_air_boundary":
        signature = plan.get("signature")
        duplicates = plan.get("duplicate_names")
        if (
            not isinstance(signature, Sequence)
            or isinstance(signature, (str, bytes))
            or not isinstance(duplicates, Sequence)
            or isinstance(duplicates, (str, bytes))
        ):
            return None
        members = [plan.get("canonical_name"), *duplicates]
        token = "|".join((
            kind,
            *(str(row) for row in signature),
            *(canonical(str(row or "")) for row in members),
        ))
    else:
        return None
    return f"preflight:{sha256(token.encode('utf-8')).hexdigest()[:20]}"


def _validate_plan(plan: Mapping[str, Any]) -> dict[str, str]:
    kind = str(plan.get("kind") or "")
    if kind not in {
        "reciprocal_surface_pair",
        "split_and_pair",
        "resegment_and_pair",
        "vertex_snap",
        "canonicalize_air_boundary",
    }:
        _reject("unmapped_idfrepair_operation")
    if plan.get("safe_to_apply") is not True:
        _reject("plan_not_safe_to_apply")
    blockers = plan.get("blocking_reasons")
    if not isinstance(blockers, Sequence) or isinstance(blockers, (str, bytes)):
        _reject("plan_blocking_reasons_invalid")
    if blockers:
        _reject("plan_has_blocking_reasons")
    expected_id = _expected_plan_id(plan)
    if expected_id is None or plan.get("plan_id") != expected_id:
        _reject("plan_identity_mismatch")
    dependencies = plan.get("blocking_dependencies", [])
    if not isinstance(dependencies, Sequence) or isinstance(dependencies, (str, bytes)):
        _reject("plan_dependencies_invalid")
    if dependencies:
        _reject("plan_dependencies_present")
    if kind in {"reciprocal_surface_pair", "split_and_pair", "resegment_and_pair"}:
        if "construction_source_surface_id" not in plan:
            _reject("construction_source_surface_id_missing")
        source_id = plan.get("construction_source_surface_id")
        surface_ids = plan.get("surface_ids")
        if source_id is not None and (
            not isinstance(source_id, str)
            or not isinstance(surface_ids, Sequence)
            or isinstance(surface_ids, (str, bytes))
            or source_id not in {str(value) for value in surface_ids}
        ):
            _reject("construction_source_surface_not_participant")
        if source_id is not None and not plan.get("construction_after"):
            _reject("construction_source_surface_target_mismatch")
    if kind == "reciprocal_surface_pair":
        proof = plan.get("direct_pair_proof")
        if not isinstance(proof, Mapping) or proof.get("passed") is not True:
            _reject("plan_proof_not_passed")
    elif kind in {"split_and_pair", "resegment_and_pair"}:
        proof = plan.get("partition_proof")
        if not isinstance(proof, Mapping) or proof.get("passed") is not True:
            _reject("plan_proof_not_passed")
        if kind == "resegment_and_pair" and any(
            not isinstance(row, Mapping) or row.get("passed") is not True
            for row in plan.get("existing_pair_proofs", [])
        ):
            _reject("plan_proof_not_passed")
    elif kind == "canonicalize_air_boundary":
        if plan.get("unknown_references") or plan.get("incompatible_reference_fields"):
            _reject("air_boundary_reference_proof_incomplete")
    plan_hash = _json_sha256(plan)
    return {"plan_id": expected_id, "plan_sha256": plan_hash}


def _building_points(before: Mapping[str, Any]) -> tuple[Point3D, ...]:
    return tuple(
        tuple(point)  # type: ignore[arg-type]
        for point in _points(
            before.get("building_vertices"),
            reason="surface_building_vertices_invalid",
        )
    )


def _proof_matches(expected: object, actual: object) -> bool:
    if isinstance(actual, Mapping):
        return (
            isinstance(expected, Mapping)
            and set(expected) == set(actual)
            and all(_proof_matches(expected[key], value) for key, value in actual.items())
        )
    if isinstance(actual, Sequence) and not isinstance(actual, (str, bytes)):
        return (
            isinstance(expected, Sequence)
            and not isinstance(expected, (str, bytes))
            and len(expected) == len(actual)
            and all(
                _proof_matches(left, right)
                for left, right in zip(expected, actual, strict=True)
            )
        )
    if isinstance(actual, bool) or actual is None or isinstance(actual, str):
        return type(expected) is type(actual) and expected == actual
    if isinstance(actual, (int, float)):
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            return False
        expected_number = float(expected)
        actual_number = float(actual)
        return (
            math.isfinite(expected_number)
            and math.isfinite(actual_number)
            and abs(expected_number - actual_number)
            <= 1e-12 * max(abs(expected_number), abs(actual_number), 1.0)
        )
    return expected == actual


class _Compiler:
    def __init__(self, preflight: Mapping[str, Any], bridge: Mapping[str, Any]) -> None:
        self.preflight = preflight
        self.bridge = bridge
        try:
            self.tolerance_m = float(preflight.get("tolerance_m"))
        except (TypeError, ValueError, OverflowError):
            _reject("preflight_tolerance_invalid")
        self.source_sha256 = _sha(
            bridge.get("source_sha256"), reason="bridge_source_sha256_missing",
        )
        self.derived_sha256 = _sha(
            bridge.get("derived_idf_sha256"), reason="bridge_derived_sha256_missing",
        )
        self.source_inventory_sha256, self.source_inventory = _inventory(
            bridge,
            "source_handle_inventory",
            incomplete_reason="source_handle_inventory_incomplete",
        )
        self.loaded_inventory_sha256, self.loaded_inventory = _inventory(
            bridge,
            "loaded_handle_inventory",
            incomplete_reason="loaded_handle_inventory_incomplete",
        )
        self.mappings = _mapping_list(bridge.get("mappings"))
        self.derived_object_index_basis = bridge.get("derived_object_index_basis")
        self.mapping_index: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        self.mapping_id_index: dict[str, list[Mapping[str, Any]]] = {}
        for mapping in self.mappings:
            object_type = mapping.get("derived_idf_object_type")
            name = mapping.get("derived_idf_object_name")
            if isinstance(object_type, str) and isinstance(name, str):
                self.mapping_index.setdefault((object_type, name), []).append(mapping)
            mapping_id = mapping.get("mapping_id")
            if isinstance(mapping_id, str):
                self.mapping_id_index.setdefault(mapping_id, []).append(mapping)
        self.air_snapshots = _mapping_list(bridge.get("air_boundary_snapshots"))

    def global_rejection(self) -> str | None:
        if self.bridge.get("mapping_contract") != WRITEBACK_MAPPING_CONTRACT:
            return "mapping_contract_not_writeback_capable"
        if self.bridge.get("mapping_truncated") is not False:
            return "mapping_truncated"
        if self.bridge.get("source_loaded_handle_inventories_match") is not True:
            return "source_loaded_handle_inventory_mismatch"
        if self.source_inventory_sha256 != self.loaded_inventory_sha256:
            return "source_loaded_handle_inventory_mismatch"
        if self.preflight.get("input_sha256") != self.derived_sha256:
            return "preflight_derived_identity_mismatch"
        return None

    def surface(self, object_type: object, name: object) -> tuple[Mapping[str, Any], dict[str, Any]]:
        if object_type != "BuildingSurface:Detailed" or not isinstance(name, str):
            _reject("preflight_target_not_building_surface")
        matches = self.mapping_index.get((object_type, name), [])
        if len(matches) != 1:
            _reject("exact_typed_mapping_not_unique" if matches else "exact_typed_mapping_unavailable")
        mapping = matches[0]
        before = _validate_surface_mapping(
            mapping,
            derived_type=object_type,
            derived_name=name,
            source_sha256=self.source_sha256,
            source_inventory_sha256=self.source_inventory_sha256,
            loaded_inventory_sha256=self.loaded_inventory_sha256,
            source_inventory=self.source_inventory,
            loaded_inventory=self.loaded_inventory,
        )
        return mapping, before

    def construction_from_plan_source(
        self,
        plan: Mapping[str, Any],
        identities: Mapping[str, Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        expected_name = plan.get("construction_after")
        if not isinstance(expected_name, str) or not expected_name:
            _reject("construction_mapping_unavailable")
        if "construction_source_surface_id" not in plan:
            _reject("construction_source_surface_id_missing")
        source_id = plan.get("construction_source_surface_id")
        if source_id is None:
            _reject("construction_source_surface_v2_binding_unavailable")
        if not isinstance(source_id, str) or source_id not in identities:
            _reject("construction_source_surface_not_participant")
        _mapping, before = self._mapped_surface_id(identities, source_id)
        construction = before.get("construction")
        if not isinstance(construction, Mapping):
            _reject("construction_mapping_unavailable")
        if construction.get("name") != expected_name:
            _reject("construction_source_surface_target_mismatch")
        handle = _handle(
            construction.get("handle"), reason="construction_handle_invalid",
        )
        source = self.source_inventory.get(handle)
        loaded = self.loaded_inventory.get(handle)
        if (
            source is None
            or loaded is None
            or source.get("object_type") != construction.get("object_type")
            or loaded.get("object_type") != construction.get("object_type")
            or source.get("name") != expected_name
            or loaded.get("name") != expected_name
        ):
            _reject("construction_provenance_mismatch")
        return construction

    def _air_mapping_for_plan_identity(
        self,
        identity: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        named_mappings = [
            mapping for mapping in self.mappings
            if mapping.get("osm_object_type") == "OS:Construction:AirBoundary"
            and mapping.get("derived_idf_object_type") == identity["object_type"]
            and mapping.get("derived_idf_object_name") == identity["object_name"]
        ]
        mappings = [
            mapping for mapping in named_mappings
            if mapping.get("derived_idf_object_index") == identity["object_index"]
        ]
        if not mappings:
            _reject(
                "air_boundary_mapping_plan_identity_mismatch"
                if named_mappings else "air_boundary_mapping_row_missing"
            )
        if len(mappings) != 1:
            _reject("air_boundary_mapping_row_not_unique")
        mapping = mappings[0]
        if mapping.get("mapping_truncated") is not False:
            _reject("air_boundary_mapping_truncated")
        return mapping

    def _validate_air_mapping_projection(
        self,
        *,
        binding: Mapping[str, Any],
        mapping: Mapping[str, Any],
        identity: Mapping[str, Any],
        handle: str,
        name: str,
        derived_handle: str,
    ) -> None:
        projection = binding.get("mapping_projection")
        mapping_id = binding.get("mapping_id")
        if (
            not isinstance(projection, Mapping)
            or set(projection) != _AIR_MAPPING_PROJECTION_KEYS
            or dict(projection) != _air_mapping_projection(mapping)
            or self.derived_object_index_basis != DERIVED_OBJECT_INDEX_BASIS
            or mapping.get("derived_object_index_basis")
            != DERIVED_OBJECT_INDEX_BASIS
            or mapping.get("mapping_contract") != WRITEBACK_MAPPING_CONTRACT
            or mapping.get("mapping_status") != "EXPLICIT_EXACT_TYPE_NAME"
            or mapping.get("source_sha256") != self.source_sha256
            or mapping.get("source_handle_inventory_sha256")
            != self.source_inventory_sha256
            or mapping.get("loaded_handle_inventory_sha256")
            != self.loaded_inventory_sha256
            or mapping.get("osm_handle") != handle
            or mapping.get("osm_object_type") != "OS:Construction:AirBoundary"
            or mapping.get("osm_object_name") != name
            or mapping.get("derived_idf_object_index")
            != identity.get("object_index")
            or mapping.get("derived_idf_object_type")
            != identity.get("object_type")
            or mapping.get("derived_idf_object_name")
            != identity.get("object_name")
            or mapping.get("derived_workspace_handle") != derived_handle
            or mapping_id != mapping.get("mapping_id")
            or mapping_id != _expected_mapping_id(mapping)
        ):
            _reject("air_boundary_mapping_projection_mismatch")

    def _air_handle_from_identity_binding(
        self,
        snapshot: Mapping[str, Any],
        identity: Mapping[str, Any],
        mapping: Mapping[str, Any],
    ) -> str:
        binding = snapshot.get("identity_binding")
        if (
            not isinstance(binding, Mapping)
            or set(binding) != _AIR_IDENTITY_BINDING_KEYS
            or snapshot.get("identity_binding_sha256")
            != _air_identity_binding_sha256(binding)
        ):
            _reject("air_boundary_identity_binding_mismatch")
        if (
            binding.get("status") != "COMPLETE"
            or binding.get("mapping_contract") != WRITEBACK_MAPPING_CONTRACT
            or binding.get("basis") != AIR_BOUNDARY_IDENTITY_BASIS
            or binding.get("mapping_truncated") is not False
            or not isinstance(binding.get("mapping_id"), str)
            or re.fullmatch(r"osm-map-[0-9a-f]{20}", str(binding["mapping_id"])) is None
            or binding.get("source_sha256") != self.source_sha256
            or binding.get("source_handle_inventory_sha256")
            != self.source_inventory_sha256
            or binding.get("loaded_handle_inventory_sha256")
            != self.loaded_inventory_sha256
            or snapshot.get("writeback_eligible") is not True
        ):
            _reject("air_boundary_identity_binding_ineligible")
        mapping_id = binding.get("mapping_id")
        if (
            not isinstance(mapping_id, str)
            or len(self.mapping_id_index.get(mapping_id, ())) != 1
            or self.mapping_id_index[mapping_id][0] is not mapping
        ):
            _reject("air_boundary_mapping_row_not_unique")
        if mapping.get("mapping_truncated") is not False:
            _reject("air_boundary_mapping_truncated")
        handle = _handle(
            snapshot.get("handle"), reason="air_boundary_handle_invalid",
        )
        name = snapshot.get("name")
        if not isinstance(name, str):
            _reject("air_boundary_identity_binding_mismatch")
        expected_ref = {
            "handle": handle,
            "object_type": "OS:Construction:AirBoundary",
            "name": name,
        }
        if (
            not isinstance(binding.get("source_object"), Mapping)
            or dict(binding["source_object"]) != expected_ref
            or not isinstance(binding.get("loaded_object"), Mapping)
            or dict(binding["loaded_object"]) != expected_ref
            or not isinstance(snapshot.get("source_object"), Mapping)
            or dict(snapshot["source_object"]) != expected_ref
            or not isinstance(snapshot.get("loaded_object"), Mapping)
            or dict(snapshot["loaded_object"]) != expected_ref
        ):
            _reject("air_boundary_provenance_mismatch")
        source = self.source_inventory.get(handle)
        loaded = self.loaded_inventory.get(handle)
        if (
            source is None
            or loaded is None
            or dict(source) != expected_ref
            or dict(loaded) != expected_ref
        ):
            _reject("air_boundary_provenance_mismatch")
        derived = binding.get("derived_object")
        if (
            not isinstance(derived, Mapping)
            or set(derived) != {"handle", "object_index", "object_type", "name"}
            or derived.get("object_index") != identity.get("object_index")
            or derived.get("object_type") != identity.get("object_type")
            or derived.get("name") != identity.get("object_name")
        ):
            _reject("air_boundary_identity_binding_unavailable")
        derived_handle = _handle(
            derived.get("handle"), reason="air_boundary_mapping_projection_mismatch",
        )
        self._validate_air_mapping_projection(
            binding=binding,
            mapping=mapping,
            identity=identity,
            handle=handle,
            name=name,
            derived_handle=derived_handle,
        )
        return handle

    def air_boundary_from_plan_identity(
        self,
        value: object,
        plan_signature: Sequence[str],
    ) -> Mapping[str, Any]:
        identity = _plan_object_identity(
            value, reason="air_boundary_plan_identity_invalid",
        )
        if identity["object_type"] != "Construction:AirBoundary":
            _reject("air_boundary_plan_identity_invalid")
        mapping = self._air_mapping_for_plan_identity(identity)
        mapping_id = mapping.get("mapping_id")
        if not isinstance(mapping_id, str):
            _reject("air_boundary_mapping_projection_mismatch")
        rows = [
            snapshot for snapshot in self.air_snapshots
            if isinstance(snapshot.get("identity_binding"), Mapping)
            and snapshot["identity_binding"].get("mapping_id") == mapping_id
        ]
        if not rows:
            _reject("air_boundary_mapping_row_missing")
        if len(rows) != 1:
            _reject("air_boundary_handle_ambiguous")
        row = rows[0]
        handle = self._air_handle_from_identity_binding(row, identity, mapping)
        return self.air_boundary_by_handle(
            handle, identity["object_name"], plan_signature,
        )

    def air_boundary_by_handle(
        self,
        handle_value: object,
        expected_name: object,
        plan_signature: Sequence[str],
    ) -> Mapping[str, Any]:
        handle = _handle(handle_value, reason="air_boundary_handle_invalid")
        rows = [
            row for row in self.air_snapshots
            if str(row.get("handle") or "").strip("{}").casefold() == handle
        ]
        if len(rows) != 1:
            _reject("air_boundary_ambiguous" if rows else "air_boundary_snapshot_missing")
        row = rows[0]
        if row.get("object_type") != "OS:Construction:AirBoundary":
            _reject("air_boundary_type_mismatch")
        if row.get("writeback_eligible") is not True:
            _reject("air_boundary_snapshot_ineligible")
        signature = row.get("signature")
        if not isinstance(signature, list) or row.get("signature_sha256") != _json_sha256(signature):
            _reject("air_boundary_signature_mismatch")
        if _air_boundary_plan_signature(row, len(plan_signature)) != list(plan_signature):
            _reject("air_boundary_signature_mismatch")
        references = _mapping_list(row.get("typed_reverse_references"))
        if row.get("typed_reverse_references_sha256") != _reverse_references_sha256(references):
            _reject("typed_reverse_reference_digest_mismatch")
        if (
            handle not in self.source_inventory
            or handle not in self.loaded_inventory
            or self.source_inventory[handle].get("object_type") != "OS:Construction:AirBoundary"
            or self.loaded_inventory[handle].get("object_type") != "OS:Construction:AirBoundary"
            or self.source_inventory[handle].get("name") != row.get("name")
            or self.loaded_inventory[handle].get("name") != row.get("name")
        ):
            _reject("air_boundary_provenance_mismatch")
        if expected_name is not None and row.get("name") != expected_name:
            _reject("air_boundary_expected_name_mismatch")
        return row

    def _identity_by_surface_id(
        self, plan: Mapping[str, Any],
    ) -> dict[str, Mapping[str, Any]]:
        ids = plan.get("surface_ids")
        identities = plan.get("surface_identities")
        if (
            not isinstance(ids, Sequence)
            or isinstance(ids, (str, bytes))
            or not isinstance(identities, Sequence)
            or isinstance(identities, (str, bytes))
            or len(ids) != len(identities)
            or any(not isinstance(row, Mapping) for row in identities)
        ):
            _reject("preflight_surface_identity_incomplete")
        return {
            str(surface_id): identity
            for surface_id, identity in zip(ids, identities, strict=True)
        }

    def _mapped_surface_id(
        self,
        identities: Mapping[str, Mapping[str, Any]],
        surface_id: object,
    ) -> tuple[Mapping[str, Any], dict[str, Any]]:
        identity = identities.get(str(surface_id))
        if identity is None:
            _reject("preflight_surface_identity_incomplete")
        return self.surface(identity.get("object_type"), identity.get("name"))

    @staticmethod
    def _surface_ref(mapping: Mapping[str, Any]) -> dict[str, str]:
        return {"handle": str(mapping["osm_handle"])}

    def _verify_direct_proof(
        self,
        expected: object,
        left_before: Mapping[str, Any],
        right_before: Mapping[str, Any],
    ) -> None:
        try:
            actual = prove_direct_surface_pair(
                _building_points(left_before),
                _building_points(right_before),
                self.tolerance_m,
            )
        except ValueError:
            _reject("plan_proof_recompute_failed")
        if actual["passed"] is not True:
            _reject("plan_proof_not_passed")
        if not _proof_matches(expected, actual):
            _reject("plan_proof_mismatch")

    def _verify_partition_proof(
        self,
        expected: object,
        parent_before: Mapping[str, Any],
        piece_befores: Sequence[Mapping[str, Any]],
    ) -> None:
        try:
            actual = prove_surface_partition(
                _building_points(parent_before),
                [_building_points(before) for before in piece_befores],
                self.tolerance_m,
            ).as_dict()
        except ValueError:
            _reject("plan_proof_recompute_failed")
        if actual["passed"] is not True:
            _reject("plan_proof_not_passed")
        if not _proof_matches(expected, actual):
            _reject("plan_proof_mismatch")

    def _construction_operation(
        self,
        mapping: Mapping[str, Any],
        before: Mapping[str, Any],
        target: Mapping[str, Any],
        plan_ref: Mapping[str, str],
    ) -> dict[str, Any] | None:
        current = before["construction"]
        if current["handle"] == target["handle"]:
            return None
        return {
            "operation": "set_surface_construction",
            "plan_refs": [dict(plan_ref)],
            "surface": self._surface_ref(mapping),
            "expected_surface_before": deepcopy(dict(before)),
            "construction_handle": target["handle"],
            "expected_construction_before": {
                "handle": target["handle"],
                "object_type": target["object_type"],
                "name": target["name"],
            },
        }

    def _adjacency_operation(
        self,
        left: Mapping[str, Any],
        left_before: Mapping[str, Any] | None,
        right: Mapping[str, Any],
        right_before: Mapping[str, Any] | None,
        plan_ref: Mapping[str, str],
    ) -> dict[str, Any]:
        return {
            "operation": "set_adjacent_surfaces",
            "plan_refs": [dict(plan_ref)],
            "left": dict(left),
            "right": dict(right),
            "expected_before": {
                "left": deepcopy(dict(left_before)) if left_before is not None else None,
                "right": deepcopy(dict(right_before)) if right_before is not None else None,
            },
        }

    def compile_plan(
        self, plan: Mapping[str, Any], plan_ref: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        kind = str(plan["kind"])
        if kind == "reciprocal_surface_pair":
            return self._compile_direct(plan, plan_ref)
        if kind == "split_and_pair":
            return self._compile_split(plan, plan_ref)
        if kind == "resegment_and_pair":
            return self._compile_resegment(plan, plan_ref)
        if kind == "vertex_snap":
            return self._compile_snap(plan, plan_ref)
        if kind == "canonicalize_air_boundary":
            return self._compile_air_boundary(plan, plan_ref)
        _reject("unmapped_idfrepair_operation")
        raise AssertionError("unreachable")

    def _compile_direct(
        self, plan: Mapping[str, Any], plan_ref: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        identities = self._identity_by_surface_id(plan)
        left, left_before = self._mapped_surface_id(identities, plan.get("anchor_surface_id"))
        right, right_before = self._mapped_surface_id(identities, plan.get("target_surface_id"))
        self._verify_direct_proof(
            plan.get("direct_pair_proof"), left_before, right_before,
        )
        after_vertices = list(reversed(left_before["building_vertices"]))
        operations = [{
            "operation": "set_surface_vertices",
            "plan_refs": [dict(plan_ref)],
            "surface": self._surface_ref(right),
            "expected_before": deepcopy(right_before),
            "building_vertices_after": after_vertices,
            "building_vertices_after_sha256": _points_sha256(after_vertices),
            "lineage": None,
        }]
        construction_name = plan.get("construction_after")
        if construction_name:
            construction = self.construction_from_plan_source(plan, identities)
            for mapping, before in ((left, left_before), (right, right_before)):
                operation = self._construction_operation(
                    mapping, before, construction, plan_ref,
                )
                if operation is not None:
                    operations.append(operation)
        operations.append(self._adjacency_operation(
            self._surface_ref(left), left_before,
            self._surface_ref(right), right_before,
            plan_ref,
        ))
        return operations

    def _compile_split(
        self,
        plan: Mapping[str, Any],
        plan_ref: Mapping[str, str],
        *,
        minimum_leaf_count: int = 2,
        verify_partition: bool = True,
    ) -> list[dict[str, Any]]:
        identities = self._identity_by_surface_id(plan)
        parent, parent_before = self._mapped_surface_id(
            identities, plan.get("large_surface_id"),
        )
        raw_leaf_ids = plan.get("small_surface_ids")
        names = plan.get("part_names")
        if (
            not isinstance(raw_leaf_ids, Sequence)
            or isinstance(raw_leaf_ids, (str, bytes))
            or not isinstance(names, Sequence)
            or isinstance(names, (str, bytes))
            or len(raw_leaf_ids) != len(names)
            or len(raw_leaf_ids) < minimum_leaf_count
        ):
            _reject("split_lineage_incomplete")
        leaves = [self._mapped_surface_id(identities, row) for row in raw_leaf_ids]
        if verify_partition:
            self._verify_partition_proof(
                plan.get("partition_proof"),
                parent_before,
                [before for _mapping, before in leaves],
            )
        construction = (
            self.construction_from_plan_source(plan, identities)
            if plan.get("construction_after") else parent_before["construction"]
        )
        operations: list[dict[str, Any]] = []
        for index, ((leaf, leaf_before), part_name) in enumerate(
            zip(leaves, names, strict=True)
        ):
            vertices = list(reversed(leaf_before["building_vertices"]))
            lineage = {
                "parent_surface_handle": parent["osm_handle"],
                "piece_index": index,
                "part_name": str(part_name),
                "identity": "retained_source_handle" if index == 0 else "generated_handle",
            }
            if index == 0:
                operations.append({
                    "operation": "set_surface_vertices",
                    "plan_refs": [dict(plan_ref)],
                    "surface": self._surface_ref(parent),
                    "expected_before": deepcopy(parent_before),
                    "building_vertices_after": vertices,
                    "building_vertices_after_sha256": _points_sha256(vertices),
                    "lineage": lineage,
                })
                piece_ref = self._surface_ref(parent)
                piece_before: Mapping[str, Any] | None = parent_before
            else:
                generated_id = (
                    "generated-surface:"
                    + sha256(
                        f"{plan_ref['plan_id']}|{parent['osm_handle']}|{index}".encode()
                    ).hexdigest()[:20]
                )
                operations.append({
                    "operation": "create_surface_piece",
                    "plan_refs": [dict(plan_ref)],
                    "generated_object_id": generated_id,
                    "source_surface_handle": parent["osm_handle"],
                    "expected_source_before": deepcopy(parent_before),
                    "space_handle": parent_before["space"]["handle"],
                    "surface_type": parent_before["surface_type"],
                    "construction_handle": construction["handle"],
                    "expected_construction_before": {
                        "handle": construction["handle"],
                        "object_type": construction["object_type"],
                        "name": construction["name"],
                    },
                    "building_vertices_after": vertices,
                    "building_vertices_after_sha256": _points_sha256(vertices),
                    "lineage": lineage,
                })
                piece_ref = {"generated_object_id": generated_id}
                piece_before = None
            operations.append(self._adjacency_operation(
                piece_ref, piece_before,
                self._surface_ref(leaf), leaf_before,
                plan_ref,
            ))
            leaf_construction = self._construction_operation(
                leaf, leaf_before, construction, plan_ref,
            )
            if leaf_construction is not None:
                operations.append(leaf_construction)
        parent_construction = self._construction_operation(
            parent, parent_before, construction, plan_ref,
        )
        if parent_construction is not None:
            operations.append(parent_construction)
        return operations

    def _compile_resegment(
        self, plan: Mapping[str, Any], plan_ref: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        identities = self._identity_by_surface_id(plan)
        operations: list[dict[str, Any]] = []
        existing_surface_rows: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        pairs = plan.get("existing_pairs")
        proofs = plan.get("existing_pair_proofs")
        if (
            not isinstance(pairs, Sequence)
            or isinstance(pairs, (str, bytes))
            or not isinstance(proofs, Sequence)
            or isinstance(proofs, (str, bytes))
            or len(proofs) != len(pairs)
        ):
            _reject("resegment_existing_pair_proof_incomplete")
        partition_piece_befores: list[Mapping[str, Any]] = []
        for pair_index, pair in enumerate(pairs):
            if not isinstance(pair, Mapping):
                _reject("resegment_existing_pair_incomplete")
            ids = pair.get("surface_ids")
            if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)) or len(ids) != 2:
                _reject("resegment_existing_pair_incomplete")
            left, left_before = self._mapped_surface_id(identities, ids[0])
            right, right_before = self._mapped_surface_id(identities, ids[1])
            expected_proof = proofs[pair_index]
            if (
                not isinstance(expected_proof, Mapping)
                or expected_proof.get("surface_ids") != list(ids)
            ):
                _reject("resegment_existing_pair_proof_incomplete")
            self._verify_direct_proof(
                {
                    key: value for key, value in expected_proof.items()
                    if key != "surface_ids"
                },
                left_before,
                right_before,
            )
            existing_surface_rows.extend(((left, left_before), (right, right_before)))
            partition_piece_befores.append(right_before)
            vertices = list(reversed(left_before["building_vertices"]))
            operations.append({
                "operation": "set_surface_vertices",
                "plan_refs": [dict(plan_ref)],
                "surface": self._surface_ref(right),
                "expected_before": deepcopy(right_before),
                "building_vertices_after": vertices,
                "building_vertices_after_sha256": _points_sha256(vertices),
                "lineage": None,
            })
            operations.append(self._adjacency_operation(
                self._surface_ref(left), left_before,
                self._surface_ref(right), right_before,
                plan_ref,
            ))
        cover_id = plan.get("cover_surface_id")
        piece_ids = plan.get("new_piece_surface_ids")
        names = plan.get("part_names")
        if (
            not isinstance(piece_ids, Sequence)
            or isinstance(piece_ids, (str, bytes))
            or not isinstance(names, Sequence)
            or isinstance(names, (str, bytes))
            or len(piece_ids) != len(names)
            or not piece_ids
        ):
            _reject("split_lineage_incomplete")
        cover, cover_before = self._mapped_surface_id(identities, cover_id)
        new_piece_rows = [
            self._mapped_surface_id(identities, piece_id) for piece_id in piece_ids
        ]
        partition_piece_befores.extend(
            before for _mapping, before in new_piece_rows
        )
        self._verify_partition_proof(
            plan.get("partition_proof"), cover_before, partition_piece_befores,
        )
        if plan.get("construction_after"):
            construction = self.construction_from_plan_source(plan, identities)
            for mapping, before in existing_surface_rows:
                operation = self._construction_operation(
                    mapping, before, construction, plan_ref,
                )
                if operation is not None:
                    operations.append(operation)
        subset = dict(plan)
        subset["large_surface_id"] = cover_id
        subset["small_surface_ids"] = list(piece_ids)
        subset["part_names"] = list(names)
        subset["construction_after"] = plan.get("construction_after")
        subset["construction_source_surface_id"] = plan.get(
            "construction_source_surface_id"
        )
        operations.extend(
            self._compile_split(
                subset, plan_ref, minimum_leaf_count=1, verify_partition=False,
            )
        )
        return operations

    def _compile_snap(
        self, plan: Mapping[str, Any], plan_ref: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        if plan.get("source_object_type") != "BuildingSurface:Detailed":
            _reject("preflight_target_not_building_surface")
        mapping, before = self.surface(
            plan.get("source_object_type"), plan.get("source_object_name"),
        )
        try:
            vertex_index = int(plan.get("source_vertex_index"))
        except (TypeError, ValueError, OverflowError):
            _reject("snap_vertex_identity_mismatch")
        if not 0 <= vertex_index < len(before["building_vertices"]):
            _reject("snap_vertex_identity_mismatch")
        before_world = _points(
            [plan.get("before_world"), plan.get("before_world"), plan.get("before_world")],
            reason="snap_before_world_mismatch",
        )[0]
        # The ForwardTranslator and Space transform may differ by a few ULPs
        # when they independently round-trip the same building-frame point.
        # This remains a strict geometric identity check at one nanometre;
        # Ruby later rechecks the raw-source snapshot exactly by handle/value.
        if any(
            abs(float(plan_value) - float(source_value)) > 1.0e-9
            for plan_value, source_value in zip(
                before_world,
                before["building_vertices"][vertex_index],
                strict=True,
            )
        ):
            _reject("snap_before_world_mismatch")
        after_world = _points(
            [plan.get("after_world"), plan.get("after_world"), plan.get("after_world")],
            reason="snap_after_world_invalid",
        )[0]
        after = deepcopy(before["building_vertices"])
        after[vertex_index] = after_world
        return [{
            "operation": "set_surface_vertices",
            "plan_refs": [dict(plan_ref)],
            "surface": self._surface_ref(mapping),
            "expected_before": deepcopy(before),
            "building_vertices_after": after,
            "building_vertices_after_sha256": _points_sha256(after),
            "lineage": None,
            "_vertex_updates": {str(vertex_index): after_world},
        }]

    def _compile_air_boundary(
        self, plan: Mapping[str, Any], plan_ref: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        raw_plan_signature = plan.get("signature")
        if (
            not isinstance(raw_plan_signature, Sequence)
            or isinstance(raw_plan_signature, (str, bytes))
        ):
            _reject("air_boundary_signature_mismatch")
        plan_signature = [str(value) for value in raw_plan_signature]
        raw_rewrites = plan.get("reference_rewrites")
        if not isinstance(raw_rewrites, Sequence) or isinstance(raw_rewrites, (str, bytes)):
            _reject("unsupported_preflight_field_mapping")
        for rewrite in raw_rewrites:
            if not isinstance(rewrite, Mapping):
                _reject("unsupported_preflight_field_mapping")
            if (
                rewrite.get("object_type") != "BuildingSurface:Detailed"
                or rewrite.get("field_name") != "Construction Name"
                or rewrite.get("field_index") != 3
                or rewrite.get("after") != plan.get("canonical_name")
            ):
                _reject(
                    "air_boundary_reference_bijection_mismatch"
                    if rewrite.get("object_type") == "BuildingSurface:Detailed"
                    and rewrite.get("field_name") == "Construction Name"
                    else "unsupported_preflight_field_mapping"
                )

        canonical_identity = _plan_object_identity(
            plan.get("canonical_object_identity"),
            reason="air_boundary_plan_identity_invalid",
        )
        if (
            canonical_identity["object_index"] != plan.get("canonical_object_index")
            or canonical_identity["object_name"] != plan.get("canonical_name")
        ):
            _reject("air_boundary_plan_identity_mismatch")
        raw_duplicate_identities = plan.get("duplicate_object_identities")
        raw_remove_identities = plan.get("remove_object_identities")
        if (
            not isinstance(raw_duplicate_identities, Sequence)
            or isinstance(raw_duplicate_identities, (str, bytes))
            or not isinstance(raw_remove_identities, Sequence)
            or isinstance(raw_remove_identities, (str, bytes))
        ):
            _reject("air_boundary_removal_identity_mismatch")
        duplicate_identities = [
            _plan_object_identity(
                value, reason="air_boundary_removal_identity_mismatch",
            )
            for value in raw_duplicate_identities
        ]
        remove_identities = [
            _plan_object_identity(
                value, reason="air_boundary_removal_identity_mismatch",
            )
            for value in raw_remove_identities
        ]
        duplicate_indices = plan.get("duplicate_object_indices")
        duplicate_names = plan.get("duplicate_names")
        remove_indices = plan.get("remove_object_indices")
        remove_names = plan.get("remove_object_names")
        if (
            duplicate_identities != remove_identities
            or not isinstance(duplicate_indices, Sequence)
            or isinstance(duplicate_indices, (str, bytes))
            or not isinstance(duplicate_names, Sequence)
            or isinstance(duplicate_names, (str, bytes))
            or not isinstance(remove_indices, Sequence)
            or isinstance(remove_indices, (str, bytes))
            or not isinstance(remove_names, Sequence)
            or isinstance(remove_names, (str, bytes))
            or [row["object_index"] for row in duplicate_identities]
            != list(duplicate_indices)
            or [row["object_name"] for row in duplicate_identities]
            != list(duplicate_names)
            or list(duplicate_indices) != list(remove_indices)
            or list(duplicate_names) != list(remove_names)
        ):
            _reject("air_boundary_removal_identity_mismatch")

        canonical_snapshot = self.air_boundary_from_plan_identity(
            canonical_identity, plan_signature,
        )
        canonical_handle = _handle(
            canonical_snapshot.get("handle"), reason="air_boundary_handle_invalid",
        )
        duplicate_snapshots = [
            self.air_boundary_from_plan_identity(identity, plan_signature)
            for identity in duplicate_identities
        ]
        duplicate_by_index = {
            identity["object_index"]: snapshot
            for identity, snapshot in zip(
                duplicate_identities, duplicate_snapshots, strict=True,
            )
        }
        duplicate_handles = {
            _handle(snapshot.get("handle"), reason="air_boundary_handle_invalid")
            for snapshot in duplicate_snapshots
        }
        if canonical_handle in duplicate_handles or len(duplicate_handles) != len(
            duplicate_snapshots
        ):
            _reject("air_boundary_removal_identity_mismatch")

        resolved_rewrites: list[
            tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]
        ] = []
        declared_references: dict[
            str, list[tuple[str, str, str, int, str]]
        ] = {}
        for rewrite in raw_rewrites:
            mapping, before = self.surface(
                rewrite.get("object_type"), rewrite.get("object_name"),
            )
            construction_before = before.get("construction")
            if not isinstance(construction_before, Mapping):
                _reject("air_boundary_reference_before_mismatch")
            before_identity = _plan_object_identity(
                rewrite.get("before_target_identity"),
                reason="air_boundary_reference_before_mismatch",
            )
            if (
                before_identity["object_index"] != rewrite.get("target_object_index")
                or before_identity["object_name"] != rewrite.get("before")
                or construction_before.get("name") != rewrite.get("before")
            ):
                _reject("air_boundary_reference_before_mismatch")
            before_handle = _handle(
                construction_before.get("handle"),
                reason="air_boundary_handle_invalid",
            )
            if before_identity["object_type"] == "Construction:AirBoundary":
                duplicate = duplicate_by_index.get(before_identity["object_index"])
                if (
                    duplicate is None
                    or construction_before.get("object_type")
                    != "OS:Construction:AirBoundary"
                    or before_handle != duplicate.get("handle")
                ):
                    _reject("air_boundary_reference_before_mismatch")
                declared_identity = _typed_reference_identity({
                    "source_handle": mapping.get("osm_handle"),
                    "source_object_type": mapping.get("osm_object_type"),
                    "source_object_name": mapping.get("osm_object_name"),
                    "field_index": rewrite.get("field_index"),
                    "field_name": rewrite.get("field_name"),
                }, reason="air_boundary_reference_bijection_mismatch")
                declared_references.setdefault(before_handle, []).append(
                    declared_identity
                )
            elif (
                before_identity["object_type"] != "Construction"
                or construction_before.get("object_type") != "OS:Construction"
                or before_identity["object_index"] in duplicate_by_index
            ):
                _reject("air_boundary_reference_before_mismatch")
            resolved_rewrites.append((rewrite, mapping, before))

        for duplicate in duplicate_snapshots:
            handle = _handle(
                duplicate.get("handle"), reason="air_boundary_handle_invalid",
            )
            snapshot_references = duplicate.get("typed_reverse_references")
            if (
                not isinstance(snapshot_references, Sequence)
                or isinstance(snapshot_references, (str, bytes))
                or any(not isinstance(row, Mapping) for row in snapshot_references)
            ):
                _reject("air_boundary_reference_bijection_mismatch")
            actual_identities = [
                _typed_reference_identity(
                    row, reason="air_boundary_reference_bijection_mismatch",
                )
                for row in snapshot_references
                if isinstance(row, Mapping)
            ]
            expected_identities = declared_references.get(handle, [])
            if (
                len(set(actual_identities)) != len(actual_identities)
                or len(set(expected_identities)) != len(expected_identities)
                or sorted(actual_identities) != sorted(expected_identities)
            ):
                _reject("air_boundary_reference_bijection_mismatch")

        operations: list[dict[str, Any]] = []
        for _rewrite, mapping, before in resolved_rewrites:
            operation = self._construction_operation(
                mapping, before, canonical_snapshot, plan_ref,
            )
            if operation is not None:
                operations.append(operation)
        for duplicate in duplicate_snapshots:
            if duplicate["handle"] == canonical_handle:
                _reject("air_boundary_removal_identity_mismatch")
            if duplicate["signature_sha256"] != canonical_snapshot["signature_sha256"]:
                _reject("air_boundary_signature_mismatch")
            operations.append({
                "operation": "remove_unreferenced_air_boundary",
                "plan_refs": [dict(plan_ref)],
                "construction_handle": duplicate["handle"],
                "expected_before": deepcopy(dict(duplicate)),
            })
        return operations


def _operation_ref_key(value: Mapping[str, Any]) -> str:
    if "handle" in value:
        return f"handle:{value['handle']}"
    return f"generated:{value.get('generated_object_id')}"


def _merge_plan_operations(
    current: list[dict[str, Any]],
    additions: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Transactionally merge one plan while rejecting conflicting mutations."""

    result = deepcopy(current)
    for addition in additions:
        kind = addition["operation"]
        if kind == "set_surface_vertices":
            key = _operation_ref_key(addition["surface"])
            existing = next((
                row for row in result
                if row["operation"] == kind and _operation_ref_key(row["surface"]) == key
            ), None)
            if existing is not None:
                if existing["expected_before"] != addition["expected_before"]:
                    _reject("operation_expected_before_conflict")
                existing_updates = existing.get("_vertex_updates")
                new_updates = addition.get("_vertex_updates")
                if isinstance(existing_updates, Mapping) and isinstance(new_updates, Mapping):
                    after = deepcopy(existing["building_vertices_after"])
                    for raw_index, point in new_updates.items():
                        index = int(raw_index)
                        if raw_index in existing_updates and existing_updates[raw_index] != point:
                            _reject("operation_vertex_conflict")
                        after[index] = deepcopy(point)
                    existing["building_vertices_after"] = after
                    existing["building_vertices_after_sha256"] = _points_sha256(after)
                    existing["_vertex_updates"] = {**existing_updates, **new_updates}
                elif existing["building_vertices_after"] != addition["building_vertices_after"]:
                    _reject("operation_vertex_conflict")
                existing["plan_refs"] = sorted(
                    {row["plan_id"]: row for row in [
                        *existing["plan_refs"], *addition["plan_refs"],
                    ]}.values(),
                    key=lambda row: row["plan_id"],
                )
                continue
        elif kind == "set_surface_construction":
            key = _operation_ref_key(addition["surface"])
            existing = next((
                row for row in result
                if row["operation"] == kind and _operation_ref_key(row["surface"]) == key
            ), None)
            if existing is not None:
                if (
                    existing["construction_handle"] != addition["construction_handle"]
                    or existing["expected_surface_before"] != addition["expected_surface_before"]
                ):
                    _reject("operation_construction_conflict")
                existing["plan_refs"] = sorted(
                    {row["plan_id"]: row for row in [
                        *existing["plan_refs"], *addition["plan_refs"],
                    ]}.values(), key=lambda row: row["plan_id"],
                )
                continue
        elif kind == "set_adjacent_surfaces":
            left = _operation_ref_key(addition["left"])
            right = _operation_ref_key(addition["right"])
            for row in result:
                if row["operation"] != kind:
                    continue
                existing_pair = {
                    _operation_ref_key(row["left"]), _operation_ref_key(row["right"]),
                }
                if left in existing_pair or right in existing_pair:
                    if existing_pair != {left, right}:
                        _reject("operation_adjacency_conflict")
                    row["plan_refs"] = sorted(
                        {ref["plan_id"]: ref for ref in [
                            *row["plan_refs"], *addition["plan_refs"],
                        ]}.values(), key=lambda ref: ref["plan_id"],
                    )
                    break
            else:
                result.append(deepcopy(addition))
            continue
        elif kind == "create_surface_piece":
            generated_id = addition["generated_object_id"]
            if any(
                row["operation"] == kind and row["generated_object_id"] == generated_id
                for row in result
            ):
                _reject("generated_lineage_conflict")
        elif kind == "remove_unreferenced_air_boundary":
            handle = addition["construction_handle"]
            existing = next((
                row for row in result
                if row["operation"] == kind and row["construction_handle"] == handle
            ), None)
            if existing is not None:
                existing["plan_refs"] = sorted(
                    {row["plan_id"]: row for row in [
                        *existing["plan_refs"], *addition["plan_refs"],
                    ]}.values(), key=lambda row: row["plan_id"],
                )
                continue
        result.append(deepcopy(addition))
    return result


def _finalize_operations(operations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for operation in operations:
        row = {key: deepcopy(value) for key, value in operation.items() if not key.startswith("_")}
        if row.get("operation") not in ALLOWED_OPERATIONS:
            raise ValueError("osm_patch_disallowed_operation")
        row["operation_id"] = _operation_id(row)
        rows.append(row)
    rows.sort(key=lambda row: (
        _OPERATION_ORDER[str(row["operation"])], str(row["operation_id"]),
    ))
    return rows


def build_osm_patch(
    preflight: Mapping[str, Any],
    bridge_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an exact handle-addressed patch from authoritative reports.

    Eligibility failures are report rows, not exceptions, so callers can retain a
    complete explanation while applying any unrelated, independently proven plan.
    """

    raw_plans = preflight.get("repair_plans")
    plans: list[object]
    if (
        isinstance(raw_plans, Sequence)
        and not isinstance(raw_plans, (str, bytes, bytearray))
    ):
        plans = list(raw_plans)
    else:
        plans = [None]
    source_sha256 = str(bridge_report.get("source_sha256") or "")
    raw_tolerance = preflight.get("tolerance_m")
    tolerance_reason: str | None = None
    try:
        if isinstance(raw_tolerance, bool):
            raise ValueError
        tolerance_m = float(raw_tolerance)  # type: ignore[arg-type]
        if not math.isfinite(tolerance_m) or tolerance_m < 0.0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        tolerance_m = 0.0
        tolerance_reason = "preflight_tolerance_invalid"
    source_inventory = bridge_report.get("source_handle_inventory")
    loaded_inventory = bridge_report.get("loaded_handle_inventory")
    source_inventory_sha = (
        str(source_inventory.get("sha256") or "")
        if isinstance(source_inventory, Mapping) else ""
    )
    loaded_inventory_sha = (
        str(loaded_inventory.get("sha256") or "")
        if isinstance(loaded_inventory, Mapping) else ""
    )
    base: dict[str, Any] = {
        "schema_version": PATCH_SCHEMA,
        "mapping_contract": WRITEBACK_MAPPING_CONTRACT,
        "source": {
            "sha256": source_sha256,
            "source_handle_inventory_sha256": source_inventory_sha,
            "loaded_handle_inventory_sha256": loaded_inventory_sha,
        },
        "preflight": {
            "input_sha256": str(preflight.get("input_sha256") or ""),
            "tolerance_m": tolerance_m,
            "authorized_plans": [],
        },
        "operations": [],
        "rejected_plans": [],
        "counts": {
            "plans_considered": len(plans),
            "plans_authorized": 0,
            "plans_rejected": 0,
            "operations": 0,
        },
    }
    try:
        compiler = _Compiler(preflight, bridge_report)
        global_reason = tolerance_reason or compiler.global_rejection()
    except _PlanRejected as exc:
        compiler = None
        global_reason = exc.reason

    operations: list[dict[str, Any]] = []
    authorized: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for plan in plans:
        if not isinstance(plan, Mapping):
            rejected.append({
                "plan_id": "",
                "kind": "",
                "reason": "plan_payload_invalid",
            })
            continue
        plan_id = str(plan.get("plan_id") or "")[:96]
        kind = str(plan.get("kind") or "")[:64]
        try:
            if global_reason is not None:
                _reject(global_reason)
            if compiler is None:  # pragma: no cover - global_reason always accompanies it
                _reject("bridge_provenance_invalid")
            plan_ref = _validate_plan(plan)
            additions = compiler.compile_plan(plan, plan_ref)
            operations = _merge_plan_operations(operations, additions)
            authorized.append(plan_ref)
        except _PlanRejected as exc:
            rejected.append({
                "plan_id": plan_id,
                "kind": kind,
                "reason": exc.reason,
            })

    finalized = _finalize_operations(operations)
    base["preflight"]["authorized_plans"] = sorted(
        authorized, key=lambda row: row["plan_id"],
    )
    base["operations"] = finalized
    base["rejected_plans"] = rejected
    base["counts"] = {
        "plans_considered": len(plans),
        "plans_authorized": len(authorized),
        "plans_rejected": len(rejected),
        "operations": len(finalized),
    }
    return base


__all__ = [
    "ALLOWED_OPERATIONS",
    "PATCH_SCHEMA",
    "WRITEBACK_MAPPING_CONTRACT",
    "build_osm_patch",
]
