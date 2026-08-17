"""Independent verification for a transactional repaired OSM child."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Protocol

from idfrepair.io.idf import canonical
from idfrepair.osm.validity import (
    ValidatedValidity,
    is_validity_subset,
    validate_validity_chain,
    validate_validity_stage,
    validity_error_multiset,
)
from idfrepair.osm.writeback import build_osm_patch
from idfrepair.preflight.analysis import GeometryAnalysisContext
from idfrepair.preflight.model import build_model_preflight, target_issue_remains


class TranslationResult(Protocol):
    derived_idf: bytes
    report: dict[str, Any]


Translate = Callable[[bytes, str, Path], TranslationResult]
InventoryValidator = Callable[
    [object], tuple[str, dict[str, dict[str, str]]] | None
]


@dataclass(frozen=True, slots=True)
class OSMChildVerification:
    """Independent evidence for one repaired OSM and its repaired IDF sibling."""

    forward_idf: bytes
    forward_report: dict[str, Any]
    preflight_report: dict[str, Any]
    report: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OSMValidityEvidence:
    """Exact, bounded handoff from direct audits into child verification."""

    source_osm_sha256: str
    repaired_osm_sha256: str
    validity_not_worsened: bool
    source_error_count: int | None
    repaired_error_count: int | None
    failure_reasons: tuple[dict[str, Any], ...]
    failure_reasons_truncated: bool = False
    schema_version: str = "idfrepair.osm-validity-evidence.v1"

    @classmethod
    def from_mapping(
        cls,
        value: object,
        *,
        expected_source_sha256: str,
        expected_repaired_sha256: str,
    ) -> OSMValidityEvidence | None:
        required = {
            "schema_version", "source_osm_sha256", "repaired_osm_sha256",
            "validity_not_worsened", "source_error_count",
            "repaired_error_count", "failure_reasons",
            "failure_reasons_truncated",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            return None
        counts = (value.get("source_error_count"), value.get("repaired_error_count"))
        reasons = value.get("failure_reasons")
        if (
            value.get("schema_version") != "idfrepair.osm-validity-evidence.v1"
            or not all(
                isinstance(value.get(key), str)
                and len(value[key]) == 64
                and all(character in "0123456789abcdef" for character in value[key])
                for key in ("source_osm_sha256", "repaired_osm_sha256")
            )
            or value.get("source_osm_sha256") != expected_source_sha256
            or value.get("repaired_osm_sha256") != expected_repaired_sha256
            or not isinstance(value.get("validity_not_worsened"), bool)
            or any(
                count is not None
                and (
                    not isinstance(count, int)
                    or isinstance(count, bool)
                    or not 0 <= count <= 500
                )
                for count in counts
            )
            or not isinstance(reasons, list)
            or len(reasons) > 50
            or not isinstance(value.get("failure_reasons_truncated"), bool)
        ):
            return None
        normalized_reasons: list[dict[str, Any]] = []
        reason_tokens: set[str] = set()
        for reason in reasons:
            if (
                not isinstance(reason, Mapping)
                or set(reason) != {"code", "details"}
                or not isinstance(reason.get("code"), str)
                or not 0 < len(reason["code"]) <= 160
                or not reason["code"].replace("_", "").isalnum()
                or not isinstance(reason.get("details"), Mapping)
            ):
                return None
            normalized = {"code": reason["code"], "details": dict(reason["details"])}
            token = _normalized_json(normalized)
            if len(token) > 4_000 or token in reason_tokens:
                return None
            reason_tokens.add(token)
            normalized_reasons.append(normalized)
        return cls(
            source_osm_sha256=value["source_osm_sha256"],
            repaired_osm_sha256=value["repaired_osm_sha256"],
            validity_not_worsened=value["validity_not_worsened"],
            source_error_count=counts[0],
            repaired_error_count=counts[1],
            failure_reasons=tuple(normalized_reasons),
            failure_reasons_truncated=value["failure_reasons_truncated"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_osm_sha256": self.source_osm_sha256,
            "repaired_osm_sha256": self.repaired_osm_sha256,
            "validity_not_worsened": self.validity_not_worsened,
            "source_error_count": self.source_error_count,
            "repaired_error_count": self.repaired_error_count,
            "failure_reasons": [dict(reason) for reason in self.failure_reasons],
            "failure_reasons_truncated": self.failure_reasons_truncated,
        }


def _validated_model_audit(
    value: object,
    *,
    artifact_sha256: str,
    inventory_validator: InventoryValidator,
) -> tuple[tuple[str, dict[str, dict[str, str]]], ValidatedValidity] | None:
    required = {
        "schema_version", "status", "source_sha256",
        "source_handle_inventory", "loaded_handle_inventory",
        "source_loaded_handle_inventories_match", "model_validity",
        "reverse_translation_used", "osm_writeback_authorized",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        return None
    source_inventory = inventory_validator(value.get("source_handle_inventory"))
    loaded_inventory = inventory_validator(value.get("loaded_handle_inventory"))
    validity = validate_validity_stage(value.get("model_validity"))
    if (
        value.get("schema_version") != "idfrepair.openstudio-child-audit.v1"
        or value.get("status") != "COMPLETE"
        or value.get("source_sha256") != artifact_sha256
        or value.get("source_loaded_handle_inventories_match") is not True
        or value.get("reverse_translation_used") is not False
        or value.get("osm_writeback_authorized") is not False
        or not isinstance(value.get("model_validity"), Mapping)
        or value["model_validity"].get("no_regression") is not True
        or source_inventory is None
        or loaded_inventory is None
        or source_inventory != loaded_inventory
        or validity is None
    ):
        return None
    return loaded_inventory, validity


def audit_validity_evidence(
    source_osm: object,
    repaired_osm: object,
    *,
    source_audit: object,
    writeback_child_audit: object,
    fresh_child_audit: object,
    writeback_validity: object,
    inventory_validator: InventoryValidator,
) -> OSMValidityEvidence:
    """Recompute same-context source→child Final-validity evidence."""

    reasons: list[dict[str, Any]] = []
    source = (
        _validated_model_audit(
            source_audit,
            artifact_sha256=sha256(source_osm).hexdigest(),
            inventory_validator=inventory_validator,
        )
        if isinstance(source_osm, bytes)
        else None
    )
    task5_child = (
        _validated_model_audit(
            writeback_child_audit,
            artifact_sha256=sha256(repaired_osm).hexdigest(),
            inventory_validator=inventory_validator,
        )
        if isinstance(repaired_osm, bytes)
        else None
    )
    fresh_child = (
        _validated_model_audit(
            fresh_child_audit,
            artifact_sha256=sha256(repaired_osm).hexdigest(),
            inventory_validator=inventory_validator,
        )
        if isinstance(repaired_osm, bytes)
        else None
    )
    if source is None:
        reasons.append(_verification_reason("source_validity_audit_invalid"))
    if task5_child is None:
        reasons.append(_verification_reason("writeback_validity_audit_invalid"))
    if fresh_child is None:
        reasons.append(_verification_reason("repaired_validity_audit_invalid"))

    validity_not_worsened = False
    if source is not None and task5_child is not None and fresh_child is not None:
        if (
            task5_child[0] != fresh_child[0]
            or task5_child[1].multiset != fresh_child[1].multiset
            or not validate_validity_chain(
                writeback_validity,
                independent_source=source[1],
                independent_child=task5_child[1],
            )
        ):
            reasons.append(_verification_reason(
                "writeback_validity_audit_mismatch",
            ))
        validity_not_worsened = is_validity_subset(fresh_child[1], source[1])
        if not validity_not_worsened:
            reasons.append(_verification_reason(
                "strict_validity_error_multiset_worsened",
                source_error_count=source[1].error_count,
                post_error_count=fresh_child[1].error_count,
            ))
    return OSMValidityEvidence(
        source_osm_sha256=(
            sha256(source_osm).hexdigest() if isinstance(source_osm, bytes) else "0" * 64
        ),
        repaired_osm_sha256=(
            sha256(repaired_osm).hexdigest()
            if isinstance(repaired_osm, bytes) else "0" * 64
        ),
        validity_not_worsened=validity_not_worsened,
        source_error_count=source[1].error_count if source is not None else None,
        repaired_error_count=(
            fresh_child[1].error_count if fresh_child is not None else None
        ),
        failure_reasons=tuple(reasons),
    )


def _normalized_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _verification_reason(code: str, **details: object) -> dict[str, Any]:
    """Return one bounded, stable reason without embedding tool output."""

    bounded: dict[str, object] = {}
    for key, value in sorted(details.items()):
        if isinstance(value, str):
            bounded[key] = value[:240]
        elif isinstance(value, (bool, int, float)) or value is None:
            bounded[key] = value
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            bounded[key] = [str(row)[:160] for row in value[:20]]
    return {"code": code, "details": bounded}


def _authorized_plans(
    preflight: Mapping[str, Any], patch: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    patch_preflight = patch.get("preflight")
    authorized = (
        patch_preflight.get("authorized_plans")
        if isinstance(patch_preflight, Mapping)
        else None
    )
    if not isinstance(authorized, Sequence) or isinstance(authorized, (str, bytes)):
        return ()
    wanted = {
        str(row.get("plan_id"))
        for row in authorized
        if isinstance(row, Mapping) and isinstance(row.get("plan_id"), str)
    }
    plans = preflight.get("repair_plans")
    if not isinstance(plans, Sequence) or isinstance(plans, (str, bytes)):
        return ()
    return tuple(
        row for row in plans
        if isinstance(row, Mapping)
        and row.get("safe_to_apply") is True
        and str(row.get("plan_id")) in wanted
    )


def _surface_index(
    context: GeometryAnalysisContext,
) -> dict[tuple[str, str], object]:
    return {
        (canonical(surface.object_type), canonical(surface.object_name)): surface
        for surface in context.graph.surfaces.values()
    }


def _points_match(
    expected: Sequence[Sequence[float]],
    actual: Sequence[Sequence[float]],
    *,
    tolerance_m: float,
) -> bool:
    if len(expected) != len(actual):
        return False
    unmatched = list(actual)
    for point in expected:
        match = next((
            index for index, candidate in enumerate(unmatched)
            if len(point) == len(candidate)
            and all(
                abs(float(left) - float(right)) <= tolerance_m
                for left, right in zip(point, candidate, strict=True)
            )
        ), None)
        if match is None:
            return False
        unmatched.pop(match)
    return True


def _compare_target_surfaces(
    repaired: GeometryAnalysisContext,
    forwarded: GeometryAnalysisContext,
    target_pairs: Sequence[
        tuple[tuple[str, str], tuple[str, str]]
    ],
) -> tuple[list[str], list[str]]:
    repaired_index = _surface_index(repaired)
    forwarded_index = _surface_index(forwarded)
    geometry_mismatches: list[str] = []
    adjacency_mismatches: list[str] = []
    actual_to_expected_name = {
        actual[1]: expected[1] for expected, actual in target_pairs
    }
    for expected_identity, actual_identity in sorted(target_pairs):
        expected = repaired_index.get(expected_identity)
        actual = forwarded_index.get(actual_identity)
        label = ":".join(expected_identity)
        if expected is None or actual is None:
            geometry_mismatches.append(label)
            adjacency_mismatches.append(label)
            continue
        if not _points_match(
            expected.world_vertices,
            actual.world_vertices,
            tolerance_m=1e-7,
        ):
            geometry_mismatches.append(label)
        if (
            canonical(expected.outside_boundary_condition)
            != canonical(actual.outside_boundary_condition)
            or canonical(expected.outside_boundary_object)
            != actual_to_expected_name.get(
                canonical(actual.outside_boundary_object),
                canonical(actual.outside_boundary_object),
            )
        ):
            adjacency_mismatches.append(label)
    return geometry_mismatches, adjacency_mismatches


def _mapping_surface_identities(
    report: Mapping[str, Any],
) -> dict[str, tuple[str, str]]:
    mappings = report.get("mappings")
    if not isinstance(mappings, Sequence) or isinstance(mappings, (str, bytes)):
        return {}
    identities: dict[str, tuple[str, str]] = {}
    duplicates: set[str] = set()
    for row in mappings:
        if (
            not isinstance(row, Mapping)
            or row.get("osm_object_type") != "OS:Surface"
            or not isinstance(row.get("osm_handle"), str)
            or not isinstance(row.get("derived_idf_object_type"), str)
            or not isinstance(row.get("derived_idf_object_name"), str)
        ):
            continue
        handle = str(row["osm_handle"])
        if handle in identities:
            duplicates.add(handle)
        identities[handle] = (
            canonical(str(row["derived_idf_object_type"])),
            canonical(str(row["derived_idf_object_name"])),
        )
    for handle in duplicates:
        identities.pop(handle, None)
    return identities


def _target_surface_pairs(
    source_report: Mapping[str, Any],
    post_report: Mapping[str, Any],
    patch: Mapping[str, Any],
    writeback_report: Mapping[str, Any],
) -> tuple[tuple[tuple[str, str], tuple[str, str]], ...]:
    expected_by_handle = _mapping_surface_identities(source_report)
    actual_by_handle = _mapping_surface_identities(post_report)
    generated_handles: dict[str, str] = {}
    generated_lineage = writeback_report.get("generated_lineage")
    if isinstance(generated_lineage, Sequence) and not isinstance(
        generated_lineage, (str, bytes),
    ):
        for row in generated_lineage:
            if (
                isinstance(row, Mapping)
                and isinstance(row.get("generated_object_id"), str)
                and isinstance(row.get("generated_handle"), str)
            ):
                generated_handles[str(row["generated_object_id"])] = str(
                    row["generated_handle"]
                )
    target_handles = _target_surface_handles(patch)
    operations = patch.get("operations")
    if isinstance(operations, Sequence) and not isinstance(operations, (str, bytes)):
        for operation in operations:
            if not isinstance(operation, Mapping):
                continue
            kind = operation.get("operation")
            if kind == "set_surface_vertices":
                surface = operation.get("surface")
                lineage = operation.get("lineage")
                if (
                    isinstance(surface, Mapping)
                    and isinstance(surface.get("handle"), str)
                    and isinstance(lineage, Mapping)
                    and isinstance(lineage.get("part_name"), str)
                ):
                    handle = str(surface["handle"])
                    source_identity = expected_by_handle.get(handle)
                    if source_identity is not None:
                        expected_by_handle[handle] = (
                            source_identity[0], canonical(str(lineage["part_name"])),
                        )
            elif kind == "create_surface_piece":
                generated_id = operation.get("generated_object_id")
                lineage = operation.get("lineage")
                if (
                    isinstance(generated_id, str)
                    and generated_id in generated_handles
                    and isinstance(lineage, Mapping)
                    and isinstance(lineage.get("part_name"), str)
                ):
                    handle = generated_handles[generated_id]
                    target_handles.add(handle)
                    expected_by_handle[handle] = (
                        "buildingsurface:detailed",
                        canonical(str(lineage["part_name"])),
                    )
    pairs = []
    for handle in sorted(target_handles):
        expected = expected_by_handle.get(handle)
        actual = actual_by_handle.get(handle)
        if expected is not None and actual is not None:
            pairs.append((expected, actual))
        else:
            missing = ("__missing__", handle)
            pairs.append((expected or missing, actual or missing))
    return tuple(pairs)


def _target_surface_handles(patch: Mapping[str, Any]) -> set[str]:
    handles: set[str] = set()
    operations = patch.get("operations")
    if not isinstance(operations, Sequence) or isinstance(operations, (str, bytes)):
        return handles
    for operation in operations:
        if not isinstance(operation, Mapping):
            continue
        for key in ("surface", "left", "right"):
            reference = operation.get(key)
            if isinstance(reference, Mapping) and isinstance(reference.get("handle"), str):
                handles.add(str(reference["handle"]))
        source_handle = operation.get("source_surface_handle")
        if isinstance(source_handle, str):
            handles.add(source_handle)
    return handles


_SURFACE_FINGERPRINT_KEYS = (
    "source_object",
    "loaded_object",
    "space",
    "space_transformation",
    "surface_type",
    "local_vertices_sha256",
    "building_vertices_sha256",
    "construction",
    "adjacent_surface_handle",
    "subsurface_handles",
    "typed_reverse_references_sha256",
)


def _surface_mapping_fingerprints(
    report: Mapping[str, Any],
) -> dict[str, str]:
    mappings = report.get("mappings")
    if not isinstance(mappings, Sequence) or isinstance(mappings, (str, bytes)):
        return {}
    fingerprints: dict[str, str] = {}
    duplicates: set[str] = set()
    for row in mappings:
        if (
            not isinstance(row, Mapping)
            or row.get("osm_object_type") != "OS:Surface"
            or not isinstance(row.get("osm_handle"), str)
            or not isinstance(row.get("expected_before"), Mapping)
        ):
            continue
        handle = str(row["osm_handle"])
        before = row["expected_before"]
        fingerprint = _normalized_json({
            key: before.get(key) for key in _SURFACE_FINGERPRINT_KEYS
        })
        if handle in fingerprints:
            duplicates.add(handle)
        fingerprints[handle] = fingerprint
    for handle in duplicates:
        fingerprints.pop(handle, None)
    return fingerprints


def _compare_non_target_fingerprints(
    source_report: Mapping[str, Any],
    post_report: Mapping[str, Any],
    target_handles: set[str],
) -> list[str]:
    source = _surface_mapping_fingerprints(source_report)
    post = _surface_mapping_fingerprints(post_report)
    return sorted(
        handle for handle, fingerprint in source.items()
        if handle not in target_handles and post.get(handle) != fingerprint
    )


def _patch_writeback_reasons(
    authoritative_preflight: Mapping[str, Any],
    authoritative_forward_report: Mapping[str, Any],
    patch: Mapping[str, Any],
    writeback_report: Mapping[str, Any],
    repaired_sha256: str,
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    try:
        expected_patch = build_osm_patch(
            authoritative_preflight,
            authoritative_forward_report,
        )
        patch_authoritative = _normalized_json(expected_patch) == _normalized_json(
            patch
        )
    except Exception:
        patch_authoritative = False
    if not patch_authoritative:
        reasons.append(_verification_reason("patch_authority_mismatch"))

    patch_operations = patch.get("operations")
    writeback_operations = writeback_report.get("operations")
    operation_ids_match = bool(
        isinstance(patch_operations, Sequence)
        and not isinstance(patch_operations, (str, bytes))
        and isinstance(writeback_operations, Sequence)
        and not isinstance(writeback_operations, (str, bytes))
        and [
            row.get("operation_id") if isinstance(row, Mapping) else None
            for row in patch_operations
        ]
        == [
            row.get("operation_id") if isinstance(row, Mapping) else None
            for row in writeback_operations
        ]
        and all(
            isinstance(row, Mapping) and row.get("status") == "APPLIED"
            for row in writeback_operations
        )
    )
    if not operation_ids_match:
        reasons.append(_verification_reason(
            "writeback_operation_journal_mismatch",
        ))
    if (
        writeback_report.get("status") != "VALIDATED"
        or writeback_report.get("repaired_sha256") != repaired_sha256
        or writeback_report.get("osm_writeback_authorized") is not True
        or writeback_report.get("reverse_translation_used") is not False
    ):
        reasons.append(_verification_reason("writeback_report_invalid"))
    return reasons


def _forward_report_evidence(
    inventory_validator: InventoryValidator,
    post_report: Mapping[str, Any],
    *,
    repaired_sha256: str,
    derived_sha256: str,
) -> tuple[bool, bool, list[dict[str, Any]]]:
    reasons: list[dict[str, Any]] = []
    post_validity = (
        post_report.get("model_validity")
        if isinstance(post_report.get("model_validity"), Mapping)
        else {}
    )
    post_errors = validity_error_multiset(post_validity.get("final"))

    source_inventory = inventory_validator(
        post_report.get("source_handle_inventory")
    )
    loaded_inventory = inventory_validator(
        post_report.get("loaded_handle_inventory")
    )
    forward_report_complete = bool(
        post_report.get("schema_version") == "idfrepair.openstudio-forward.v1"
        and post_report.get("mapping_contract")
        == "exact-source-handle-typed-surface-v2"
        and post_report.get("source_sha256") == repaired_sha256
        and post_report.get("derived_idf_sha256") == derived_sha256
        and post_report.get("source_osm_modified") is False
        and post_report.get("reverse_translation_used") is False
        and post_report.get("osm_writeback_authorized") is False
        and post_report.get("mapping_truncated") is False
        and post_report.get("source_loaded_handle_inventories_match") is True
        and source_inventory is not None
        and loaded_inventory is not None
        and source_inventory == loaded_inventory
        and post_errors is not None
    )
    if not forward_report_complete:
        reasons.append(_verification_reason("post_forward_report_incomplete"))
    return forward_report_complete, reasons


def _post_model_contexts(
    repaired_idf: bytes,
    post_idf: bytes,
    idd_text: str,
    authoritative_preflight: Mapping[str, Any],
) -> tuple[
    GeometryAnalysisContext | None,
    GeometryAnalysisContext | None,
    dict[str, Any],
    list[dict[str, Any]],
]:
    tolerance_m = float(authoritative_preflight.get("tolerance_m") or 0.05)
    raw_checks = authoritative_preflight.get("checked_rules")
    checks = (
        tuple(str(row) for row in raw_checks)
        if isinstance(raw_checks, Sequence)
        and not isinstance(raw_checks, (str, bytes))
        else None
    )
    try:
        repaired_text = repaired_idf.decode("utf-8-sig")
        post_text = post_idf.decode("utf-8-sig")
        repaired_context = GeometryAnalysisContext.from_text(
            repaired_text, idd_text, tolerance_m=tolerance_m,
        )
        post_context = GeometryAnalysisContext.from_text(
            post_text, idd_text, tolerance_m=tolerance_m,
        )
        post_preflight = build_model_preflight(
            post_text,
            idd_text,
            tolerance_m=tolerance_m,
            checks=checks,
            analysis_context=post_context,
        )
        return repaired_context, post_context, post_preflight, []
    except (UnicodeError, ValueError, TypeError, OverflowError):
        return None, None, {
            "schema_version": "idfrepair.model-preflight.v1",
            "tolerance_m": tolerance_m,
            "checked_rules": sorted(checks or ()),
            "repair_plans": [],
        }, [_verification_reason("post_preflight_failed")]


def _model_evidence(
    repaired_context: GeometryAnalysisContext | None,
    post_context: GeometryAnalysisContext | None,
    post_preflight: Mapping[str, Any],
    authoritative_preflight: Mapping[str, Any],
    authoritative_forward_report: Mapping[str, Any],
    post_report: Mapping[str, Any],
    patch: Mapping[str, Any],
    writeback_report: Mapping[str, Any],
) -> tuple[
    int, list[str], list[str], list[str], list[str], list[dict[str, Any]],
]:
    reasons: list[dict[str, Any]] = []
    authorized_plans = _authorized_plans(authoritative_preflight, patch)
    post_plan_rows = post_preflight.get("repair_plans")
    post_plans = (
        tuple(row for row in post_plan_rows if isinstance(row, Mapping))
        if isinstance(post_plan_rows, Sequence)
        and not isinstance(post_plan_rows, (str, bytes))
        else ()
    )
    remaining_targets = [
        str(row.get("plan_id") or "")
        for row in authorized_plans
        if target_issue_remains(row, post_plans)
    ]
    if remaining_targets:
        reasons.append(_verification_reason(
            "targeted_safe_issue_remains",
            plan_ids=remaining_targets,
        ))

    target_pairs = _target_surface_pairs(
        authoritative_forward_report,
        post_report,
        patch,
        writeback_report,
    )
    if repaired_context is not None and post_context is not None:
        geometry_mismatches, adjacency_mismatches = _compare_target_surfaces(
            repaired_context,
            post_context,
            target_pairs,
        )
    else:
        geometry_mismatches = ["geometry_context_unavailable"]
        adjacency_mismatches = ["geometry_context_unavailable"]
    if geometry_mismatches:
        reasons.append(_verification_reason(
            "target_surface_geometry_mismatch",
            surfaces=geometry_mismatches,
        ))
    if adjacency_mismatches:
        reasons.append(_verification_reason(
            "target_surface_adjacency_mismatch",
            surfaces=adjacency_mismatches,
        ))

    non_target_changes = _compare_non_target_fingerprints(
        authoritative_forward_report,
        post_report,
        _target_surface_handles(patch),
    )
    if non_target_changes:
        reasons.append(_verification_reason(
            "non_target_surface_fingerprint_changed",
            handles=non_target_changes,
        ))
    return (
        len(authorized_plans), remaining_targets, geometry_mismatches,
        adjacency_mismatches, non_target_changes, reasons,
    )


def _verification_report(
    *,
    reasons: Sequence[Mapping[str, Any]],
    repaired_osm_sha256: str,
    repaired_idf_sha256: str,
    post_forward_idf_sha256: str,
    forward_report_complete: bool,
    validity_not_worsened: bool,
    authorized_plan_count: int,
    remaining_targets: Sequence[str],
    geometry_mismatches: Sequence[str],
    adjacency_mismatches: Sequence[str],
    non_target_changes: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": "idfrepair.osm-child-verification.v1",
        "status": "VERIFIED" if not reasons else "FAILED",
        "independent_verifier": "OpenStudioBridge.verify_repaired",
        "reopened_repaired_osm": True,
        "repaired_osm_sha256": repaired_osm_sha256,
        "repaired_idf_sha256": repaired_idf_sha256,
        "post_forward_idf_sha256": post_forward_idf_sha256,
        "post_forward_report_complete": forward_report_complete,
        "strict_validity_error_multiset_not_worsened": validity_not_worsened,
        "authorized_safe_plan_count": authorized_plan_count,
        "remaining_targeted_safe_issue_count": len(remaining_targets),
        "mapped_surface_geometry_and_adjacency_match": not (
            geometry_mismatches or adjacency_mismatches
        ),
        "non_target_surface_fingerprints_unchanged": not non_target_changes,
        "simulation_semantic_equivalence_claimed": False,
        "failure_reasons": [dict(row) for row in reasons[:50]],
        "failure_reasons_truncated": len(reasons) > 50,
    }


def verify_repaired_osm(
    translate: Translate,
    inventory_validator: InventoryValidator,
    repaired_osm: bytes,
    input_name: str,
    output_root: Path,
    *,
    repaired_idf: bytes,
    idd_text: str,
    authoritative_preflight: Mapping[str, Any],
    authoritative_forward_report: Mapping[str, Any],
    patch: Mapping[str, Any],
    writeback_report: Mapping[str, Any],
    audit_evidence: OSMValidityEvidence,
) -> OSMChildVerification:
    """Reopen and independently compare a repaired OSM/IDF child pair."""

    post = translate(repaired_osm, input_name, output_root)
    post_report = post.report
    repaired_sha256 = sha256(repaired_osm).hexdigest()
    derived_sha256 = sha256(post.derived_idf).hexdigest()
    reasons = _patch_writeback_reasons(
        authoritative_preflight,
        authoritative_forward_report,
        patch,
        writeback_report,
        repaired_sha256,
    )
    forward_report_complete, forward_reasons = (
        _forward_report_evidence(
            inventory_validator,
            post_report,
            repaired_sha256=repaired_sha256,
            derived_sha256=derived_sha256,
        )
    )
    validity_not_worsened = audit_evidence.validity_not_worsened
    repaired_context, post_context, post_preflight, model_setup_reasons = (
        _post_model_contexts(
            repaired_idf,
            post.derived_idf,
            idd_text,
            authoritative_preflight,
        )
    )
    (
        authorized_plan_count, remaining_targets, geometry_mismatches,
        adjacency_mismatches, non_target_changes, model_reasons,
    ) = _model_evidence(
        repaired_context,
        post_context,
        post_preflight,
        authoritative_preflight,
        authoritative_forward_report,
        post_report,
        patch,
        writeback_report,
    )
    audit_reasons = audit_evidence.failure_reasons
    reasons.extend((*audit_reasons, *forward_reasons, *model_setup_reasons, *model_reasons))
    report = _verification_report(
        reasons=reasons,
        repaired_osm_sha256=repaired_sha256,
        repaired_idf_sha256=sha256(repaired_idf).hexdigest(),
        post_forward_idf_sha256=derived_sha256,
        forward_report_complete=forward_report_complete,
        validity_not_worsened=validity_not_worsened,
        authorized_plan_count=authorized_plan_count,
        remaining_targets=remaining_targets,
        geometry_mismatches=geometry_mismatches,
        adjacency_mismatches=adjacency_mismatches,
        non_target_changes=non_target_changes,
    )
    return OSMChildVerification(
        forward_idf=post.derived_idf,
        forward_report=dict(post_report),
        preflight_report=dict(post_preflight),
        report=report,
    )


__all__ = [
    "OSMChildVerification", "OSMValidityEvidence", "audit_validity_evidence",
    "verify_repaired_osm",
]
