"""Preview and apply deterministic repairs to a derived IDF copy.

This workflow is deliberately separate from the frozen IDFRepair candidate
engine.  It repairs only strongly evidenced surface relationships before an
OSM-derived IDF is handed to the normal diagnostic workflow.  The caller keeps
the original text and can therefore roll back by switching to the parent copy.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping, Sequence

from idfrepair.audit.model import AUDIT_CHECKS, audit_model
from idfrepair.io.idf import IDFObject, canonical, parse_idf, text_sha256
from idfrepair.knowledge.geometry_graph import (
    GeometryEvidenceGraph,
    SurfaceNode,
)
from idfrepair.knowledge.idd import IDDField, IDDObject, IDDSchema
from idfrepair.preflight.analysis import GeometryAnalysisContext
from idfrepair.preflight.issues import build_preflight_issues
from idfrepair.preflight.partition import (
    prove_direct_surface_pair,
    prove_surface_partition,
)
from idfrepair.preflight.spatial_snap import build_snap_proposals


_INTERIOR_CONSTRUCTIONS = {
    "wall": "Interior Wall",
    "floor": "Interior Floor",
    "roof": "Interior Ceiling",
    "ceiling": "Interior Ceiling",
}
_EXTERIOR_MARKERS = ("extwall", "exterior", "external", "extroof", "extfloor")


@dataclass(frozen=True, slots=True)
class PreflightApplication:
    output_text: str
    report: dict[str, Any]


def _surface_ids(finding: Mapping[str, Any]) -> tuple[str, str] | None:
    left = finding.get("surface")
    right = finding.get("paired_surface")
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return None
    left_id = left.get("surface_id")
    right_id = right.get("surface_id")
    if not isinstance(left_id, str) or not isinstance(right_id, str):
        return None
    return left_id, right_id


def _components(edges: Iterable[tuple[str, str]]) -> list[list[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    seen: set[str] = set()
    rows: list[list[str]] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component: list[str] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbour in sorted(adjacency[current], reverse=True):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                stack.append(neighbour)
        rows.append(sorted(component))
    return rows


def _construction_names(objects: Iterable[IDFObject]) -> set[str]:
    return {
        canonical(obj.name)
        for obj in objects
        if canonical(obj.object_type) in {"construction", "construction:airboundary"}
        and obj.name
    }


def _semantic_value(value: str, *, numeric: bool) -> str:
    stripped = value.strip()
    if not numeric:
        return canonical(stripped)
    try:
        number = Decimal(stripped)
    except InvalidOperation:
        return canonical(stripped)
    if not number.is_finite():
        return canonical(stripped)
    if number == 0:
        return "0"
    normalized = number.normalize()
    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def air_boundary_signature(
    obj: IDFObject,
    definition: IDDObject,
) -> tuple[str, ...]:
    """Return every non-name semantic field in IDD order."""

    values: list[str] = []
    for field in definition.fields:
        if canonical(field.name) == "name":
            continue
        value = (
            obj.fields[field.index - 1].value
            if field.index <= len(obj.fields)
            else (field.default or "")
        )
        if not value.strip() and field.default is not None:
            value = field.default
        values.append(_semantic_value(
            value,
            numeric=(
                field.token.upper().startswith("N")
                or canonical(field.data_type or "") in {"integer", "real"}
            ),
        ))
    for field in obj.fields[len(definition.fields):]:
        field_definition = definition.field_at(field.index)
        values.append(_semantic_value(
            field.value,
            numeric=bool(
                field_definition is not None
                and (
                    field_definition.token.upper().startswith("N")
                    or canonical(field_definition.data_type or "") in {"integer", "real"}
                )
            ),
        ))
    return tuple(values)


@dataclass(frozen=True, slots=True)
class _AirBoundaryCatalog:
    canonical_by_name: Mapping[str, str]
    signature_by_name: Mapping[str, tuple[str, ...]]
    plans: tuple[dict[str, Any], ...]


def _air_reference_incompatibility(
    obj: IDFObject,
    field_index: int | None,
    field_definition: IDDField | None,
    required_target_references: Sequence[str],
) -> dict[str, Any] | None:
    field_object_list_keys = {
        canonical(value)
        for value in (field_definition.object_lists if field_definition else ())
    }
    required_keys = {canonical(value) for value in required_target_references}
    if (
        field_index is not None
        and field_definition is not None
        and field_object_list_keys.intersection(required_keys)
    ):
        return None
    field_name = (
        field_definition.name if field_definition is not None
        else "Construction Name"
    )
    return {
        "object_index": obj.index,
        "object_type": obj.object_type,
        "object_name": obj.name,
        "field_index": field_index,
        "field_name": field_name,
        "field_object_lists": list(
            field_definition.object_lists if field_definition else ()
        ),
        "required_target_references": list(required_target_references),
    }


def _air_reference_blocker(row: Mapping[str, Any]) -> str:
    return (
        "air_boundary_construction_reference_incompatible:"
        f"{row['object_type']}:{row['object_name']}:{row['field_name']}"
    )


def _idf_object_identity(obj: IDFObject) -> dict[str, Any]:
    return {
        "object_index": obj.index,
        "object_type": obj.object_type,
        "object_name": obj.name,
    }


def _matches_idf_object_identity(value: object, obj: IDFObject) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"object_index", "object_type", "object_name"}
        and value.get("object_index") == obj.index
        and value.get("object_type") == obj.object_type
        and value.get("object_name") == obj.name
    )


def _air_boundary_catalog(context: GeometryAnalysisContext) -> _AirBoundaryCatalog:
    definition = context.idd.get("Construction:AirBoundary")
    if definition is None:
        return _AirBoundaryCatalog({}, {}, ())
    name_field = next(
        (field for field in definition.fields if canonical(field.name) == "name"),
        None,
    )
    air_reference_names = tuple(name_field.references if name_field is not None else ())
    objects = sorted(
        (
            obj for obj in context.objects_by_index.values()
            if canonical(obj.object_type) == "construction:airboundary" and obj.name
        ),
        key=lambda row: (row.index, canonical(row.name), row.name),
    )
    groups: dict[tuple[str, ...], list[IDFObject]] = defaultdict(list)
    for obj in objects:
        groups[air_boundary_signature(obj, definition)].append(obj)
    canonical_objects: dict[tuple[str, ...], IDFObject] = {}
    for signature, members in groups.items():
        referenced = [
            obj for obj in members if context.reverse_references.get(obj.index, ())
        ]
        canonical_objects[signature] = min(
            referenced or members,
            key=lambda row: (row.index, canonical(row.name), row.name),
        )
    surface_id_by_index = {
        surface.object_index: surface.surface_id
        for surface in context.graph.surfaces.values()
    }
    object_by_construction_name = {
        canonical(obj.name): obj
        for obj in context.objects_by_index.values()
        if canonical(obj.object_type) in {"construction", "construction:airboundary"}
        and obj.name
    }
    signature_by_object_name = {
        canonical(obj.name): signature
        for signature, members in groups.items()
        for obj in members
    }
    pair_rewrites: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    pair_surface_ids: dict[tuple[str, ...], set[str]] = defaultdict(set)
    pair_blockers: dict[tuple[str, ...], list[str]] = defaultdict(list)
    pair_reference_blocks: dict[
        tuple[str, ...], list[dict[str, Any]]
    ] = defaultdict(list)
    for relation in context.graph.paired_surface_edges:
        if not relation.reciprocal:
            continue
        pair = (
            context.graph.surfaces[relation.left_surface_id],
            context.graph.surfaces[relation.right_surface_id],
        )
        constructions = [
            str(context.surface_details[surface.surface_id].get("construction") or "")
            for surface in pair
        ]
        signatures = {
            signature_by_object_name[canonical(value)]
            for value in constructions
            if canonical(value) in signature_by_object_name
        }
        if not signatures:
            continue
        for signature in signatures:
            pair_surface_ids[signature].update(surface.surface_id for surface in pair)
        if len(signatures) != 1:
            for signature in signatures:
                pair_blockers[signature].append("air_boundary_signature_mismatch")
            continue
        signature = next(iter(signatures))
        canonical_obj = canonical_objects[signature]
        for surface, current in zip(pair, constructions, strict=True):
            if canonical(current) == canonical(canonical_obj.name):
                continue
            obj = context.objects_by_index[surface.object_index]
            surface_definition = context.idd.get(obj.object_type)
            field_index = (
                _field_index(surface_definition, "construction", "name")
                if surface_definition is not None else None
            )
            field_definition = (
                surface_definition.field_at(field_index)
                if surface_definition is not None and field_index is not None else None
            )
            incompatibility = _air_reference_incompatibility(
                obj, field_index, field_definition, air_reference_names,
            )
            if incompatibility is not None:
                pair_blockers[signature].append(
                    _air_reference_blocker(incompatibility)
                )
                pair_reference_blocks[signature].append(incompatibility)
                continue
            current_target = object_by_construction_name.get(canonical(current))
            if current_target is None:
                pair_blockers[signature].append(
                    "air_boundary_reference_target_identity_unresolved"
                )
                continue
            pair_rewrites[signature].append({
                "object_index": obj.index,
                "object_type": obj.object_type,
                "object_name": obj.name,
                "field_index": field_index,
                "field_name": field_definition.name,
                "before": current,
                "after": canonical_obj.name,
                "target_object_index": current_target.index,
                "before_target_identity": _idf_object_identity(current_target),
            })
    canonical_by_name: dict[str, str] = {}
    signature_by_name: dict[str, tuple[str, ...]] = {}
    plans: list[dict[str, Any]] = []
    for signature, members in sorted(
        groups.items(), key=lambda row: (row[0], row[1][0].index),
    ):
        canonical_obj = canonical_objects[signature]
        for obj in members:
            canonical_by_name[canonical(obj.name)] = canonical_obj.name
            signature_by_name[canonical(obj.name)] = signature
        duplicates = [obj for obj in members if obj.index != canonical_obj.index]
        if not duplicates and not pair_rewrites.get(signature) and not pair_blockers.get(signature):
            continue
        rewrites: list[dict[str, Any]] = list(pair_rewrites.get(signature, ()))
        unknown_references: list[dict[str, Any]] = []
        typed_keys: set[tuple[int, int, int]] = set()
        for duplicate in duplicates:
            for reference in context.reverse_references.get(duplicate.index, ()):
                source = context.objects_by_index[reference.source_object_index]
                before = (
                    source.fields[reference.field_index - 1].value
                    if reference.field_index <= len(source.fields) else ""
                )
                rewrites.append({
                    "object_index": reference.source_object_index,
                    "object_type": reference.source_object_type,
                    "object_name": reference.source_object_name,
                    "field_index": reference.field_index,
                    "field_name": reference.field_name,
                    "before": before,
                    "after": canonical_obj.name,
                    "target_object_index": duplicate.index,
                    "before_target_identity": _idf_object_identity(duplicate),
                })
                typed_keys.add((
                    duplicate.index,
                    reference.source_object_index,
                    reference.field_index,
                ))
            duplicate_key = canonical(duplicate.name)
            for source in context.objects_by_index.values():
                for field in source.fields:
                    if source.index == duplicate.index and field.index == 1:
                        continue
                    if canonical(field.value) != duplicate_key:
                        continue
                    if (duplicate.index, source.index, field.index) in typed_keys:
                        continue
                    unknown_references.append({
                        "target_object_index": duplicate.index,
                        "object_index": source.index,
                        "object_type": source.object_type,
                        "object_name": source.name,
                        "field_index": field.index,
                    })
        rewrites = list({
            (int(row["object_index"]), int(row["field_index"])): row
            for row in rewrites
        }.values())
        rewrites.sort(key=lambda row: (
            int(row["object_index"]), int(row["field_index"]), str(row["object_name"]),
        ))
        unknown_references.sort(key=lambda row: (
            int(row["target_object_index"]), int(row["object_index"]), int(row["field_index"]),
        ))
        blockers = list(pair_blockers.get(signature, ()))
        blockers.extend([
            (
                "untyped_air_boundary_reference:"
                f"{row['object_type']}:{row['object_name']}:{row['field_index']}"
            )
            for row in unknown_references
        ])
        surface_ids = list(dict.fromkeys(
            surface_id_by_index[int(row["object_index"])]
            for row in rewrites
            if int(row["object_index"]) in surface_id_by_index
        ))
        surface_ids.extend(
            surface_id for surface_id in sorted(pair_surface_ids.get(signature, ()))
            if surface_id not in surface_ids
        )
        identity = "|".join((
            "canonicalize_air_boundary",
            *signature,
            *(canonical(obj.name) for obj in members),
        ))
        plans.append({
            "plan_id": f"preflight:{sha256(identity.encode('utf-8')).hexdigest()[:20]}",
            "kind": "canonicalize_air_boundary",
            "safe_to_apply": not blockers,
            "blocking_reasons": blockers,
            "surface_ids": surface_ids,
            "surfaces": [context.graph.surfaces[row].object_name for row in surface_ids],
            "canonical_object_index": canonical_obj.index,
            "canonical_name": canonical_obj.name,
            "canonical_object_identity": _idf_object_identity(canonical_obj),
            "signature": list(signature),
            "duplicate_object_indices": [obj.index for obj in duplicates],
            "duplicate_names": [obj.name for obj in duplicates],
            "duplicate_object_identities": [
                _idf_object_identity(obj) for obj in duplicates
            ],
            "reference_rewrites": rewrites,
            "remove_object_indices": [obj.index for obj in duplicates],
            "remove_object_names": [obj.name for obj in duplicates],
            "remove_object_identities": [
                _idf_object_identity(obj) for obj in duplicates
            ],
            "unknown_references": unknown_references,
            "incompatible_reference_fields": sorted(
                pair_reference_blocks.get(signature, ()),
                key=lambda row: (
                    int(row["object_index"]),
                    int(row["field_index"] or 0),
                ),
            ),
            "air_wall_context": True,
            "changes": [
                "rewrite_explicit_construction_references",
                "remove_unreferenced_exact_air_boundary_duplicates",
            ],
        })
    return _AirBoundaryCatalog(
        canonical_by_name=canonical_by_name,
        signature_by_name=signature_by_name,
        plans=tuple(plans),
    )


def _prospective_air_reference_blocks(
    context: GeometryAnalysisContext,
    surfaces: Sequence[SurfaceNode],
    construction_after: str | None,
    air_catalog: _AirBoundaryCatalog,
) -> list[dict[str, Any]]:
    if (
        construction_after is None
        or canonical(construction_after) not in air_catalog.signature_by_name
    ):
        return []
    definition = context.idd.get("Construction:AirBoundary")
    name_field = next((
        field for field in definition.fields
        if canonical(field.name) == "name"
    ), None) if definition is not None else None
    required_references = tuple(
        name_field.references if name_field is not None else ()
    )
    rows: list[dict[str, Any]] = []
    for surface in surfaces:
        current = str(
            context.surface_details[surface.surface_id].get("construction") or ""
        )
        if canonical(current) == canonical(construction_after):
            continue
        obj = context.objects_by_index[surface.object_index]
        surface_definition = context.idd.get(obj.object_type)
        field_index = (
            _field_index(surface_definition, "construction", "name")
            if surface_definition is not None else None
        )
        field_definition = (
            surface_definition.field_at(field_index)
            if surface_definition is not None and field_index is not None else None
        )
        incompatibility = _air_reference_incompatibility(
            obj, field_index, field_definition, required_references,
        )
        if incompatibility is not None:
            rows.append(incompatibility)
    return sorted(rows, key=lambda row: (
        int(row["object_index"]), int(row["field_index"] or 0),
    ))


def _is_air_wall(value: str) -> bool:
    key = canonical(value).replace(" ", "")
    return "airwall" in key or "airboundary" in key


def _construction_for(
    surfaces: Sequence[SurfaceNode],
    details: Mapping[str, Mapping[str, Any]],
    available: set[str],
    air_catalog: _AirBoundaryCatalog,
) -> tuple[str | None, str, list[str]]:
    current = [str(details[row.surface_id].get("construction") or "") for row in surfaces]
    air = [
        value for value in current
        if canonical(value) in air_catalog.signature_by_name
    ]
    if air:
        signatures = {
            air_catalog.signature_by_name[canonical(value)] for value in air
        }
        if len(signatures) != 1:
            return None, "air_boundary_signature_mismatch", [
                "air_boundary_signature_mismatch",
            ]
        canonical_name = air_catalog.canonical_by_name[canonical(air[0])]
        return canonical_name, "use_canonical_air_boundary_construction", []
    unresolved_air = [value for value in current if _is_air_wall(value)]
    if unresolved_air and len(unresolved_air) == len(current) and len({
        canonical(value) for value in unresolved_air
    }) == 1:
        return unresolved_air[0], "preserve_identical_air_boundary_construction", []
    if unresolved_air:
        return None, "air_boundary_definition_unresolved", [
            "air_boundary_definition_unresolved",
        ]
    kinds = {canonical(row.surface_type) for row in surfaces}
    preferred = _INTERIOR_CONSTRUCTIONS.get(next(iter(kinds))) if len(kinds) == 1 else None
    if preferred and canonical(preferred) in available:
        return preferred, "use_existing_interior_construction", []
    if any(marker in canonical(value).replace(" ", "") for value in current for marker in _EXTERIOR_MARKERS):
        return None, "interior_construction_unresolved", ["interior_construction_unresolved"]
    return None, "preserve_existing_constructions", []


def _construction_source_surface_id(
    surfaces: Sequence[SurfaceNode],
    details: Mapping[str, Mapping[str, Any]],
    construction_after: str | None,
) -> str | None:
    """Return a deterministic participant already bound to the target construction."""

    if construction_after is None:
        return None
    candidates = [
        surface for surface in surfaces
        if canonical(str(details[surface.surface_id].get("construction") or ""))
        == canonical(construction_after)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda surface: (
            surface.object_index,
            canonical(surface.object_name),
            surface.object_name,
            surface.surface_id,
        ),
    ).surface_id


def _validate_construction_source_surface(
    plan: Mapping[str, Any],
    graph: GeometryEvidenceGraph,
    details: Mapping[str, Mapping[str, Any]],
) -> None:
    """Recheck Task 4's construction source before IDF-copy mutation."""

    if str(plan.get("kind") or "") not in {
        "reciprocal_surface_pair", "split_and_pair", "resegment_and_pair",
    }:
        return
    if "construction_source_surface_id" not in plan:
        raise ValueError("preflight_construction_source_surface_id_missing")
    source_id = plan.get("construction_source_surface_id")
    construction_after = plan.get("construction_after")
    if not construction_after:
        if source_id is not None:
            raise ValueError("preflight_construction_source_surface_unexpected")
        return
    # IDF-only application remains supported when the target construction exists in
    # the authoritative IDF but no participating Surface currently references it.
    # OSM writeback rejects that case until a first-class V2 Construction binding exists.
    if source_id is None:
        return
    surface_ids = plan.get("surface_ids")
    if (
        not isinstance(source_id, str)
        or not isinstance(surface_ids, Sequence)
        or isinstance(surface_ids, (str, bytes))
        or source_id not in {str(value) for value in surface_ids}
        or source_id not in graph.surfaces
    ):
        raise ValueError("preflight_construction_source_surface_not_participant")
    before_name = str(details.get(source_id, {}).get("construction") or "")
    if canonical(before_name) != canonical(str(construction_after)):
        raise ValueError("preflight_construction_source_surface_target_mismatch")


def _allowed_adjacent_reference(
    reference: Any,
    component_object_indices: set[int],
) -> bool:
    field_name = canonical(str(reference.field_name))
    return bool(
        reference.source_object_index in component_object_indices
        and "outside" in field_name
        and "boundary" in field_name
        and "condition" in field_name
        and "object" in field_name
    )


def _blocking_dependencies(
    context: GeometryAnalysisContext,
    surfaces: Sequence[SurfaceNode],
    component_object_indices: set[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for surface in surfaces:
        for reference in context.reverse_references.get(surface.object_index, ()):
            if _allowed_adjacent_reference(reference, component_object_indices):
                continue
            identity = (reference.source_object_index, reference.field_index)
            if identity in seen:
                continue
            seen.add(identity)
            rows.append({
                "object_index": reference.source_object_index,
                "object_type": reference.source_object_type,
                "object_name": reference.source_object_name,
                "field_index": reference.field_index,
                "field_name": reference.field_name,
            })
    return sorted(rows, key=lambda row: (
        int(row["object_index"]), int(row["field_index"]), str(row["object_type"]),
    ))


def _dependency_reasons(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        (
            "typed_reverse_reference:"
            f"{row['object_type']}:{row['object_name']}:{row['field_name']}"
        )
        for row in rows
    ]


def _direct_pair_proof(
    left: SurfaceNode,
    right: SurfaceNode,
    evidence: Mapping[str, Any],
    tolerance_m: float,
) -> dict[str, Any]:
    return prove_direct_surface_pair(
        left.world_vertices,
        right.world_vertices,
        tolerance_m,
        evidence=evidence,
    )


def _plan_id(kind: str, surface_ids: Sequence[str]) -> str:
    token = "|".join((kind, *sorted(surface_ids)))
    return f"preflight:{sha256(token.encode('utf-8')).hexdigest()[:20]}"


def _surface_identities(
    graph: GeometryEvidenceGraph,
    surface_ids: Sequence[str],
) -> list[dict[str, str]]:
    return [
        {
            "object_type": graph.surfaces[surface_id].object_type,
            "name": graph.surfaces[surface_id].object_name,
        }
        for surface_id in surface_ids
    ]


def _part_names(base: str, count: int, existing: set[str]) -> list[str]:
    names = []
    for index in range(1, count + 1):
        seed = f"{base}-idfrepair-part-{index:02d}"
        candidate = seed
        suffix = 2
        while canonical(candidate) in existing:
            candidate = f"{seed}-{suffix}"
            suffix += 1
        existing.add(canonical(candidate))
        names.append(candidate)
    return names


def build_model_preflight(
    input_text: str,
    idd_text: str,
    *,
    tolerance_m: float = 0.05,
    checks: Iterable[str] | None = None,
    analysis_context: GeometryAnalysisContext | None = None,
    context: GeometryAnalysisContext | None = None,
) -> dict[str, Any]:
    """Combine relationship checks and concrete derived-copy repair plans."""

    if not 1e-8 <= tolerance_m <= 0.05:
        raise ValueError("preflight_tolerance_out_of_bounds")
    if analysis_context is not None and context is not None:
        raise ValueError("preflight_geometry_context_duplicate")
    analysis = analysis_context or context
    if analysis is None:
        analysis = GeometryAnalysisContext.from_text(
            input_text, idd_text, tolerance_m=tolerance_m,
        )
    elif analysis.document.text != input_text or analysis.idd.text != idd_text:
        raise ValueError("preflight_geometry_context_mismatch")
    graph = analysis.graph
    audit = audit_model(
        input_text,
        idd_text,
        checks=AUDIT_CHECKS if checks is None else checks,
        geometry_tolerance_m=tolerance_m,
        analysis_context=analysis,
    )
    overlap_findings = [
        row for row in audit["findings"]
        if row.get("rule_id") == "coincident_outdoor_surfaces"
        and _surface_ids(row) is not None
    ]
    edge_findings = {
        frozenset(_surface_ids(row) or ()): row for row in overlap_findings
    }
    edges = [pair for row in overlap_findings if (pair := _surface_ids(row)) is not None]
    adjacency: dict[str, set[str]] = defaultdict(set)
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    details = {
        str(row["surface"]["surface_id"]): row["surface"]
        for row in overlap_findings
    }
    details.update({
        str(row["paired_surface"]["surface_id"]): row["paired_surface"]
        for row in overlap_findings
    })
    available = _construction_names(analysis.objects_by_index.values())
    air_catalog = _air_boundary_catalog(analysis)
    existing_names = {
        canonical(obj.name) for obj in analysis.objects_by_index.values() if obj.name
    }
    plans: list[dict[str, Any]] = [dict(row) for row in air_catalog.plans]
    unresolved_components = 0

    for component in _components(edges):
        surfaces = [graph.surfaces[surface_id] for surface_id in component]
        component_indices = {row.object_index for row in surfaces}
        construction_after, construction_basis, construction_blocks = _construction_for(
            surfaces, details, available, air_catalog,
        )
        construction_source_surface_id = _construction_source_surface_id(
            surfaces, details, construction_after,
        )
        incompatible_reference_fields = _prospective_air_reference_blocks(
            analysis, surfaces, construction_after, air_catalog,
        )
        construction_blocks.extend(
            _air_reference_blocker(row)
            for row in incompatible_reference_fields
        )
        if len(component) == 2 and all(len(adjacency[row]) == 1 for row in component):
            left, right = sorted(surfaces, key=lambda row: (row.object_index, row.object_name))
            finding = edge_findings[frozenset((left.surface_id, right.surface_id))]
            evidence = dict(finding.get("evidence") or {})
            preview = dict(finding.get("repair_preview") or {})
            blocking = list(construction_blocks)
            if not preview.get("direct_reciprocal_pair"):
                blocking.append("surface_overlap_not_one_to_one")
            direct_proof = _direct_pair_proof(
                left, right, evidence, tolerance_m,
            )
            blocking.extend(direct_proof["blocking_reasons"])
            dependencies = _blocking_dependencies(
                analysis, (left, right), component_indices,
            )
            if dependencies:
                blocking.append("referenced_child_objects")
                blocking.extend(_dependency_reasons(dependencies))
            plan = {
                "plan_id": _plan_id("reciprocal_surface_pair", component),
                "kind": "reciprocal_surface_pair",
                "safe_to_apply": not blocking,
                "blocking_reasons": sorted(set(blocking)),
                "surface_ids": [left.surface_id, right.surface_id],
                "surfaces": [left.object_name, right.object_name],
                "surface_identities": _surface_identities(
                    graph, (left.surface_id, right.surface_id),
                ),
                "anchor_surface_id": left.surface_id,
                "target_surface_id": right.surface_id,
                "geometry_mutated_surface_ids": [right.surface_id],
                "blocking_dependencies": dependencies,
                "construction_after": construction_after,
                "construction_source_surface_id": construction_source_surface_id,
                "construction_basis": construction_basis,
                "incompatible_reference_fields": incompatible_reference_fields,
                "air_wall_context": any(
                    _is_air_wall(str(details[row.surface_id].get("construction") or ""))
                    for row in surfaces
                ),
                "evidence": evidence,
                "direct_pair_proof": direct_proof,
                "changes": [
                    "set_reciprocal_surface_boundary",
                    "set_no_sun_no_wind",
                    "align_paired_vertices_exactly",
                    *(["use_interior_construction"] if construction_after else []),
                ],
            }
            plans.append(plan)
            continue

        hubs = [row for row in component if len(adjacency[row]) == len(component) - 1]
        leaves = [row for row in component if len(adjacency[row]) == 1]
        if len(hubs) != 1 or len(leaves) != len(component) - 1:
            zone_groups: dict[str, list[str]] = defaultdict(list)
            for surface_id in component:
                zone_groups[canonical(graph.surfaces[surface_id].zone_name)].append(surface_id)
            resegment: dict[str, Any] | None = None
            for zone_key, primary_ids in sorted(zone_groups.items()):
                if not zone_key or len(primary_ids) < 2:
                    continue
                other_ids = [row for row in component if row not in set(primary_ids)]
                if not other_ids or any(
                    not (adjacency[other_id] & set(primary_ids)) for other_id in other_ids
                ):
                    continue
                other_area = sum(graph.surfaces[row].area for row in other_ids)
                covers = [
                    row for row in primary_ids
                    if abs(graph.surfaces[row].area - other_area)
                    <= max(1e-6, other_area * 0.001)
                    and set(other_ids) <= adjacency[row]
                ]
                if len(covers) != 1:
                    continue
                cover_id = covers[0]
                remaining_primary = [row for row in primary_ids if row != cover_id]
                assigned_other: set[str] = set()
                existing_pairs: list[tuple[str, str]] = []
                ambiguous = False
                for primary_id in sorted(remaining_primary):
                    matches = [
                        row for row in other_ids
                        if row not in assigned_other
                        and row in adjacency[primary_id]
                        and abs(graph.surfaces[primary_id].area - graph.surfaces[row].area)
                        <= max(1e-6, graph.surfaces[row].area * 0.001)
                    ]
                    if len(matches) != 1:
                        ambiguous = True
                        break
                    assigned_other.add(matches[0])
                    existing_pairs.append((primary_id, matches[0]))
                if ambiguous:
                    continue
                new_piece_ids = [row for row in other_ids if row not in assigned_other]
                cover = graph.surfaces[cover_id]
                component_indices = {
                    graph.surfaces[row].object_index for row in component
                }
                blocking = list(construction_blocks)
                partition = prove_surface_partition(
                    cover.world_vertices,
                    [graph.surfaces[row].world_vertices for row in other_ids],
                    tolerance_m,
                )
                blocking.extend(partition.blocking_reasons)
                geometry_mutated_ids = [cover_id]
                direct_proofs = []
                for left_id, right_id in existing_pairs:
                    pair_finding = edge_findings[frozenset((left_id, right_id))]
                    proof = _direct_pair_proof(
                        graph.surfaces[left_id],
                        graph.surfaces[right_id],
                        dict(pair_finding.get("evidence") or {}),
                        tolerance_m,
                    )
                    direct_proofs.append({
                        "surface_ids": [left_id, right_id],
                        **proof,
                    })
                    blocking.extend(proof["blocking_reasons"])
                    geometry_mutated_ids.append(right_id)
                child_refs = _blocking_dependencies(
                    analysis,
                    [graph.surfaces[row] for row in component],
                    component_indices,
                )
                if child_refs:
                    blocking.append("referenced_child_objects")
                    blocking.extend(_dependency_reasons(child_refs))
                names = _part_names(cover.object_name, len(new_piece_ids), existing_names)
                resegment = {
                    "plan_id": _plan_id("resegment_and_pair", component),
                    "kind": "resegment_and_pair",
                    "safe_to_apply": not blocking,
                    "blocking_reasons": sorted(set(blocking)),
                    "surface_ids": component,
                    "surfaces": [graph.surfaces[row].object_name for row in component],
                    "surface_identities": _surface_identities(graph, component),
                    "cover_surface_id": cover_id,
                    "cover_surface": cover.object_name,
                    "existing_pairs": [{
                        "surface_ids": [left, right],
                        "surfaces": [
                            graph.surfaces[left].object_name,
                            graph.surfaces[right].object_name,
                        ],
                    } for left, right in existing_pairs],
                    "new_piece_surface_ids": new_piece_ids,
                    "new_piece_surfaces": [graph.surfaces[row].object_name for row in new_piece_ids],
                    "part_names": names,
                    "coverage_ratio": other_area / max(cover.area, 1e-12),
                    "referenced_child_objects": child_refs,
                    "blocking_dependencies": child_refs,
                    "geometry_mutated_surface_ids": list(dict.fromkeys(geometry_mutated_ids)),
                    "partition_proof": partition.as_dict(),
                    "existing_pair_proofs": direct_proofs,
                    "construction_after": construction_after,
                    "construction_source_surface_id": construction_source_surface_id,
                    "construction_basis": construction_basis,
                    "incompatible_reference_fields": incompatible_reference_fields,
                    "air_wall_context": any(
                        _is_air_wall(str(details[row].get("construction") or ""))
                        for row in component
                    ),
                    "changes": [
                        "prefer_existing_exact_segments",
                        "remove_overlapping_region_from_large_surface",
                        "create_only_missing_matching_pieces",
                        "set_reciprocal_surface_boundary",
                        "reuse_observed_counterpart_vertices",
                    ],
                }
                break
            if resegment is None:
                unresolved_components += 1
            else:
                plans.append(resegment)
            continue
        hub = graph.surfaces[hubs[0]]
        leaf_surfaces = sorted(
            (graph.surfaces[row] for row in leaves),
            key=lambda row: (row.object_index, row.object_name),
        )
        coverage = sum(row.area for row in leaf_surfaces) / max(hub.area, 1e-12)
        blocking = list(construction_blocks)
        if not 0.999 <= coverage <= 1.001:
            blocking.append("split_coverage_not_complete")
        for leaf in leaf_surfaces:
            finding = edge_findings[frozenset((hub.surface_id, leaf.surface_id))]
            if float((finding.get("evidence") or {}).get("smaller_surface_overlap_ratio") or 0) < 0.999:
                blocking.append("split_piece_overlap_not_complete")
        partition = prove_surface_partition(
            hub.world_vertices,
            [row.world_vertices for row in leaf_surfaces],
            tolerance_m,
        )
        blocking.extend(partition.blocking_reasons)
        child_refs = _blocking_dependencies(
            analysis, [hub, *leaf_surfaces], component_indices,
        )
        if child_refs:
            blocking.append("referenced_child_objects")
            blocking.extend(_dependency_reasons(child_refs))
        names = _part_names(hub.object_name, len(leaf_surfaces), existing_names)
        plans.append({
            "plan_id": _plan_id("split_and_pair", component),
            "kind": "split_and_pair",
            "safe_to_apply": not blocking,
            "blocking_reasons": sorted(set(blocking)),
            "surface_ids": component,
            "surfaces": [graph.surfaces[row].object_name for row in component],
            "surface_identities": _surface_identities(graph, component),
            "large_surface_id": hub.surface_id,
            "large_surface": hub.object_name,
            "small_surface_ids": [row.surface_id for row in leaf_surfaces],
            "small_surfaces": [row.object_name for row in leaf_surfaces],
            "part_names": names,
            "coverage_ratio": coverage,
            "referenced_child_objects": child_refs,
            "blocking_dependencies": child_refs,
            "geometry_mutated_surface_ids": [hub.surface_id],
            "partition_proof": partition.as_dict(),
            "construction_after": construction_after,
            "construction_source_surface_id": construction_source_surface_id,
            "construction_basis": construction_basis,
            "incompatible_reference_fields": incompatible_reference_fields,
            "air_wall_context": any(
                _is_air_wall(str(details[row.surface_id].get("construction") or ""))
                for row in (hub, *leaf_surfaces)
            ),
            "changes": [
                "split_large_surface_to_matching_pieces",
                "set_reciprocal_surface_boundary",
                "set_no_sun_no_wind",
                "reuse_observed_counterpart_vertices",
                *(["use_interior_construction"] if construction_after else []),
            ],
        })

    relationship_surface_ids = {
        str(surface_id)
        for plan in plans
        if plan.get("kind") in {
            "reciprocal_surface_pair", "split_and_pair", "resegment_and_pair",
        }
        for surface_id in plan.get("surface_ids", ())
    }
    for proposal in build_snap_proposals(analysis, tolerance_m):
        source = graph.surfaces[proposal.source_surface_id]
        supporting_ids = list(proposal.supporting_surface_ids)
        surface_ids = list(dict.fromkeys((source.surface_id, *supporting_ids)))
        component_indices = {
            graph.surfaces[row].object_index
            for row in surface_ids
            if row in graph.surfaces
        }
        dependencies = _blocking_dependencies(
            analysis, [source], component_indices,
        )
        blockers = list(proposal.rejection_reasons)
        if source.surface_id in relationship_surface_ids:
            blockers.append("surface_participates_in_geometry_relationship_repair")
        if dependencies:
            blockers.append("referenced_child_objects")
            blockers.extend(_dependency_reasons(dependencies))
        after_local = graph.point_to_local(
            proposal.after_world, proposal.source.zone_name,
        )
        if after_local is None:
            blockers.append("target_coordinate_frame_unresolved")
        identity = "|".join((
            "vertex_snap",
            proposal.source_vertex_id,
            *(format(value, ".17g") for value in proposal.after_world),
        ))
        plans.append({
            "plan_id": f"preflight:{sha256(identity.encode('utf-8')).hexdigest()[:20]}",
            "kind": "vertex_snap",
            "safe_to_apply": proposal.safe_to_apply and not blockers,
            "blocking_reasons": sorted(set(blockers)),
            "surface_ids": surface_ids,
            "surfaces": [graph.surfaces[row].object_name for row in surface_ids],
            "source_surface_id": source.surface_id,
            "source_object_index": proposal.source_object_index,
            "source_object_type": proposal.source.object_type,
            "source_object_name": proposal.source_object_name,
            "source_vertex_index": proposal.source_vertex_index,
            "source_vertex_id": proposal.source_vertex_id,
            "coordinate_field_indices": list(proposal.source.coordinate_field_indices),
            "before_local": list(proposal.source.local_point),
            "after_local": list(after_local) if after_local is not None else None,
            "before_world": list(proposal.before_world),
            "after_world": list(proposal.after_world),
            "distance_m": proposal.distance_m,
            "supporting_surface_ids": supporting_ids,
            "target_vertex_ids": list(proposal.target_vertex_ids),
            "target_distinct_surface_support": proposal.target_distinct_surface_support,
            "target_total_support": proposal.target_total_support,
            "target_basis": proposal.target_basis,
            "simple_number_score": proposal.simple_number_score,
            "blocking_dependencies": dependencies,
            "geometry_mutated_surface_ids": [source.surface_id],
            "changes": ["replace_exact_vertex_coordinate_fields"],
        })

    plans.sort(key=lambda row: (str(row["kind"]), str(row["plan_id"])))
    issues = build_preflight_issues(plans, analysis)
    direct = sum(row["kind"] == "reciprocal_surface_pair" for row in plans)
    split = sum(row["kind"] == "split_and_pair" for row in plans)
    resegmented = sum(row["kind"] == "resegment_and_pair" for row in plans)
    safe = sum(bool(row["safe_to_apply"]) for row in issues)
    confirmed_review = sum(
        not bool(row["safe_to_apply"]) and row["kind"] != "vertex_snap"
        for row in issues
    )
    excluded_candidates = sum(
        not bool(row["safe_to_apply"]) and row["kind"] == "vertex_snap"
        for row in issues
    )
    air = sum(
        row["kind"] == "canonicalize_air_boundary" or bool(row.get("air_wall_context"))
        for row in plans
    )
    return {
        "schema_version": "idfrepair.model-preflight.v1",
        "derived_copy_only": True,
        "original_input_changed": False,
        "input_sha256": text_sha256(input_text),
        "tolerance_m": tolerance_m,
        "checked_rules": sorted(AUDIT_CHECKS if checks is None else set(checks)),
        "summary": {
            "surfaces_checked": len(graph.surfaces),
            "issue_count": len(issues),
            "audit_findings": audit["summary"]["total"],
            "direct_pair_repairs": direct,
            "split_group_repairs": split,
            "resegmented_overlap_repairs": resegmented,
            "air_wall_context_repairs": air,
            "safe_repairs": safe,
            "review_only_repairs": len(plans) - safe,
            "confirmed_review_repairs": confirmed_review,
            "excluded_candidate_repairs": excluded_candidates,
            "unresolved_overlap_groups": unresolved_components,
        },
        "repair_plans": plans,
        "issues": issues,
        "audit": audit,
    }


def _field_index(
    definition: IDDObject,
    *parts: str,
    excludes: Sequence[str] = (),
) -> int | None:
    wanted = tuple(canonical(value) for value in parts)
    rejected = tuple(canonical(value) for value in excludes)
    for field in definition.fields:
        key = canonical(field.name)
        if all(part in key for part in wanted) and not any(part in key for part in rejected):
            return field.index
    return None


def _set(values: list[str], index: int | None, value: str) -> None:
    if index is None or not 1 <= index <= len(values):
        raise ValueError("preflight_required_field_missing")
    values[index - 1] = value


def _number(value: float) -> str:
    if abs(value) <= 5e-12:
        return "0"
    integer = round(value)
    if abs(value - integer) <= 5e-10:
        return str(integer)
    half = round(value * 2.0) / 2.0
    if abs(value - half) <= 5e-10:
        return f"{half:.1f}"
    return format(value, ".15g")


def _surface_values(
    obj: IDFObject,
    definition: IDDObject,
    surface: SurfaceNode,
    *,
    name: str,
    boundary_object: str,
    construction_after: str | None,
    local_vertices: Sequence[tuple[float, float, float]] | None = None,
    base_values: Sequence[str] | None = None,
) -> list[str]:
    values = list(base_values) if base_values is not None else [
        field.value for field in obj.fields
    ]
    _set(values, _field_index(definition, "name"), name)
    if construction_after:
        _set(values, _field_index(definition, "construction", "name"), construction_after)
    _set(
        values,
        _field_index(definition, "outside", "boundary", "condition", excludes=("object",)),
        "Surface",
    )
    _set(
        values,
        _field_index(definition, "outside", "boundary", "condition", "object"),
        boundary_object,
    )
    _set(values, _field_index(definition, "sun", "exposure"), "NoSun")
    _set(values, _field_index(definition, "wind", "exposure"), "NoWind")
    if local_vertices is not None:
        _set(values, _field_index(definition, "number", "vertices"), str(len(local_vertices)))
        if len(local_vertices) != len(surface.coordinate_field_indices):
            raise ValueError("preflight_vertex_count_change_requires_split_render")
        for indices, point in zip(surface.coordinate_field_indices, local_vertices, strict=True):
            for field_index, value in zip(indices, point, strict=True):
                _set(values, field_index, _number(value))
    return values


def _render(obj: IDFObject, values: Sequence[str], *, include_prefix: bool = True) -> str:
    prefix = obj.raw[:obj.raw.find(obj.object_type)] if include_prefix else ""
    lines = [f"{obj.object_type},"]
    for index, value in enumerate(values):
        delimiter = ";" if index == len(values) - 1 else ","
        lines.append(f"  {value}{delimiter}")
    return prefix + "\n".join(lines)


def _local_vertices(
    graph: GeometryEvidenceGraph,
    target: SurfaceNode,
    source_world: Sequence[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], ...]:
    rows = []
    for point in source_world:
        local = graph.point_to_local(point, target.zone_name)
        if local is None:
            raise ValueError("preflight_target_coordinate_frame_unresolved")
        rows.append(local)
    return tuple(rows)


def _normalized_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _target_closure_key(plan: Mapping[str, Any]) -> tuple[object, ...]:
    """Identify a repair target without parser-order object or surface IDs."""

    kind = str(plan.get("kind") or "")
    if kind == "vertex_snap":
        return (
            kind,
            canonical(str(plan.get("source_object_type") or "")),
            canonical(str(plan.get("source_object_name") or "")),
            int(plan.get("source_vertex_index") or 0),
        )
    if kind == "canonicalize_air_boundary":
        return (
            kind,
            tuple(str(value) for value in plan.get("signature", ())),
            canonical(str(plan.get("canonical_name") or "")),
            tuple(sorted(
                canonical(str(value)) for value in plan.get("duplicate_names", ())
            )),
        )
    identities = plan.get("surface_identities", ())
    return (
        kind,
        tuple(sorted(
            (
                canonical(str(identity.get("object_type") or "")),
                canonical(str(identity.get("name") or "")),
            )
            for identity in identities
            if isinstance(identity, Mapping)
        )),
    )


def target_issue_remains(
    target: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
) -> bool:
    """Match closure identity while tolerating only numeric write round-trip noise."""

    target_key = _target_closure_key(target)
    if target.get("kind") != "vertex_snap":
        return any(_target_closure_key(row) == target_key for row in candidates)
    target_world = target.get("after_world")
    if not isinstance(target_world, Sequence) or isinstance(target_world, (str, bytes)):
        return False
    for candidate in candidates:
        if _target_closure_key(candidate) != target_key:
            continue
        candidate_before = candidate.get("before_world")
        if (
            isinstance(candidate_before, Sequence)
            and not isinstance(candidate_before, (str, bytes))
            and len(candidate_before) == len(target_world)
            and all(
                abs(float(left) - float(right)) <= 1e-12
                for left, right in zip(target_world, candidate_before, strict=True)
            )
            and abs(float(candidate.get("distance_m") or 0.0)) <= 1e-12
        ):
            continue
        return True
    return False


def _audit_error_signature(finding: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    surface = finding.get("surface")
    paired = finding.get("paired_surface")
    left = surface if isinstance(surface, Mapping) else {}
    right = paired if isinstance(paired, Mapping) else {}
    return (
        canonical(str(finding.get("rule_id") or "")),
        canonical(str(left.get("object_type") or "")),
        canonical(str(left.get("name") or left.get("surface_name") or "")),
        canonical(str(right.get("object_type") or "")),
        canonical(str(right.get("name") or right.get("surface_name") or "")),
    )


def _new_audit_error_ids(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> list[str]:
    before_signatures = {
        _audit_error_signature(row)
        for row in before.get("findings", ())
        if isinstance(row, Mapping) and canonical(str(row.get("severity") or "")) == "error"
    }
    return [
        str(row.get("finding_id") or "")
        for row in after.get("findings", ())
        if isinstance(row, Mapping)
        and canonical(str(row.get("severity") or "")) == "error"
        and _audit_error_signature(row) not in before_signatures
    ]


def _non_target_geometry_changes(
    before: GeometryEvidenceGraph,
    after: GeometryEvidenceGraph,
    allowed_identities: set[tuple[str, str]],
) -> tuple[str, ...]:
    def grouped(graph: GeometryEvidenceGraph) -> dict[tuple[str, str], list[SurfaceNode]]:
        rows: dict[tuple[str, str], list[SurfaceNode]] = defaultdict(list)
        for surface in graph.surfaces.values():
            rows[(canonical(surface.object_type), canonical(surface.object_name))].append(surface)
        return rows

    before_rows = grouped(before)
    after_rows = grouped(after)
    changed: list[tuple[str, str]] = []
    allowed = {
        (canonical(object_type), canonical(name))
        for object_type, name in allowed_identities
    }
    for key, surfaces in before_rows.items():
        if key in allowed:
            continue
        counterparts = after_rows.get(key, ())
        if len(surfaces) != 1 or len(counterparts) != 1:
            changed.append(key)
            continue
        if surfaces[0].world_vertices != counterparts[0].world_vertices:
            changed.append(key)
    for key in after_rows:
        if key in before_rows or key in allowed:
            continue
        changed.append(key)
    return tuple(
        f"{object_type}:{name}"
        for object_type, name in sorted(set(changed))
    )


def apply_model_preflight(
    input_text: str,
    idd_text: str,
    preview: Mapping[str, Any],
) -> PreflightApplication:
    """Apply only plans proven safe in a matching preview to a new text copy."""

    if preview.get("input_sha256") != text_sha256(input_text):
        raise ValueError("preflight_input_identity_mismatch")
    tolerance_m = float(preview.get("tolerance_m") or 0.05)
    if not 1e-8 <= tolerance_m <= 0.05:
        raise ValueError("preflight_tolerance_out_of_bounds")
    raw_checks = preview.get("checked_rules")
    checks = (
        tuple(str(row) for row in raw_checks)
        if isinstance(raw_checks, Sequence) and not isinstance(raw_checks, (str, bytes))
        else None
    )
    analysis = GeometryAnalysisContext.from_text(
        input_text, idd_text, tolerance_m=tolerance_m,
    )
    authoritative = build_model_preflight(
        input_text,
        idd_text,
        tolerance_m=tolerance_m,
        checks=checks,
        analysis_context=analysis,
    )
    authoritative_plans = {
        str(row["plan_id"]): row for row in authoritative["repair_plans"]
    }
    selected_plans: list[dict[str, Any]] = []
    for requested in preview.get("repair_plans", ()):
        if not isinstance(requested, Mapping) or requested.get("safe_to_apply") is not True:
            continue
        plan_id = str(requested.get("plan_id") or "")
        proven = authoritative_plans.get(plan_id)
        if proven is None or proven.get("safe_to_apply") is not True:
            raise ValueError("preflight_preview_plan_not_authorized")
        if _normalized_json(requested) != _normalized_json(proven):
            raise ValueError("preflight_preview_plan_mismatch")
        selected_plans.append(dict(proven))
    if not selected_plans:
        raise ValueError("preflight_has_no_safe_repairs")
    for plan in selected_plans:
        _validate_construction_source_surface(
            plan, analysis.graph, analysis.surface_details,
        )

    before_audit = audit_model(
        input_text,
        idd_text,
        checks=AUDIT_CHECKS,
        geometry_tolerance_m=tolerance_m,
        analysis_context=analysis,
    )
    document = analysis.document
    idd: IDDSchema = analysis.idd
    graph = analysis.graph
    objects = dict(analysis.objects_by_index)
    values_by_index = {
        obj.index: [field.value for field in obj.fields]
        for obj in document.objects
    }
    split_replacements: dict[int, str] = {}
    changed_indices: set[int] = set()
    removed_indices: set[int] = set()
    changed_names: set[str] = set()
    applied_plans: list[str] = []

    def apply_pair(left: SurfaceNode, right: SurfaceNode, construction: str | None) -> None:
        left_obj, right_obj = objects[left.object_index], objects[right.object_index]
        left_def, right_def = idd.get(left_obj.object_type), idd.get(right_obj.object_type)
        if left_def is None or right_def is None:
            raise ValueError("preflight_surface_idd_missing")
        right_local = _local_vertices(graph, right, tuple(reversed(left.world_vertices)))
        left_values = _surface_values(
            left_obj, left_def, left,
            name=left.object_name,
            boundary_object=right.object_name,
            construction_after=construction,
            base_values=values_by_index[left.object_index],
        )
        right_values = _surface_values(
            right_obj, right_def, right,
            name=right.object_name,
            boundary_object=left.object_name,
            construction_after=construction,
            local_vertices=right_local,
            base_values=values_by_index[right.object_index],
        )
        values_by_index[left.object_index] = left_values
        values_by_index[right.object_index] = right_values
        changed_indices.update((left.object_index, right.object_index))
        changed_names.update((left.object_name, right.object_name))

    def apply_parts(
        hub: SurfaceNode,
        leaves: Sequence[SurfaceNode],
        names: Sequence[str],
        construction: str | None,
    ) -> None:
        if len(leaves) != len(names):
            raise ValueError("preflight_split_name_count_mismatch")
        hub_obj = objects[hub.object_index]
        hub_def = idd.get(hub_obj.object_type)
        if hub_def is None:
            raise ValueError("preflight_surface_idd_missing")
        rendered_parts = []
        hub_base_values = values_by_index[hub.object_index]
        for index, (leaf, part_name) in enumerate(zip(leaves, names, strict=True)):
            local = _local_vertices(graph, hub, tuple(reversed(leaf.world_vertices)))
            if len(local) != len(hub.coordinate_field_indices):
                fixed_start = min(value[0] for value in hub.coordinate_field_indices) - 1
                values = list(hub_base_values[:fixed_start])
                values.extend(_number(value) for point in local for value in point)
                _set(values, _field_index(hub_def, "name"), part_name)
                if construction:
                    _set(values, _field_index(hub_def, "construction", "name"), construction)
                _set(values, _field_index(hub_def, "outside", "boundary", "condition", excludes=("object",)), "Surface")
                _set(values, _field_index(hub_def, "outside", "boundary", "condition", "object"), leaf.object_name)
                _set(values, _field_index(hub_def, "sun", "exposure"), "NoSun")
                _set(values, _field_index(hub_def, "wind", "exposure"), "NoWind")
                _set(values, _field_index(hub_def, "number", "vertices"), str(len(local)))
                rendered = _render(hub_obj, values, include_prefix=index == 0)
            else:
                values = _surface_values(
                    hub_obj, hub_def, hub,
                    name=part_name,
                    boundary_object=leaf.object_name,
                    construction_after=construction,
                    local_vertices=local,
                    base_values=hub_base_values,
                )
                rendered = _render(hub_obj, values, include_prefix=index == 0)
            rendered_parts.append(rendered)
            leaf_obj = objects[leaf.object_index]
            leaf_def = idd.get(leaf_obj.object_type)
            if leaf_def is None:
                raise ValueError("preflight_surface_idd_missing")
            leaf_values = _surface_values(
                leaf_obj, leaf_def, leaf,
                name=leaf.object_name,
                boundary_object=part_name,
                construction_after=construction,
                base_values=values_by_index[leaf.object_index],
            )
            values_by_index[leaf.object_index] = leaf_values
            changed_indices.add(leaf.object_index)
            changed_names.add(leaf.object_name)
        if rendered_parts:
            split_replacements[hub.object_index] = "\n\n".join(rendered_parts)
        else:
            split_replacements[hub.object_index] = hub_obj.raw[:hub_obj.raw.find(hub_obj.object_type)]
        changed_names.add(hub.object_name)
        changed_names.update(names)

    operation_order = {
        "canonicalize_air_boundary": 0,
        "reciprocal_surface_pair": 1,
        "resegment_and_pair": 2,
        "split_and_pair": 3,
        "vertex_snap": 4,
    }
    for plan in sorted(
        selected_plans,
        key=lambda row: (operation_order.get(str(row.get("kind")), 99), str(row["plan_id"])),
    ):
        kind = plan.get("kind")
        construction_after = (
            str(plan["construction_after"]) if plan.get("construction_after") else None
        )
        if kind == "canonicalize_air_boundary":
            canonical_index = int(plan.get("canonical_object_index") or 0)
            canonical_obj = objects.get(canonical_index)
            if (
                canonical_obj is None
                or not _matches_idf_object_identity(
                    plan.get("canonical_object_identity"), canonical_obj,
                )
            ):
                raise ValueError("preflight_air_boundary_canonical_identity_mismatch")
            duplicate_indices = [
                int(value) for value in plan.get("duplicate_object_indices", ())
            ]
            remove_indices = [
                int(value) for value in plan.get("remove_object_indices", ())
            ]
            duplicate_identities = plan.get("duplicate_object_identities")
            remove_identities = plan.get("remove_object_identities")
            if (
                duplicate_indices != remove_indices
                or not isinstance(duplicate_identities, Sequence)
                or isinstance(duplicate_identities, (str, bytes))
                or not isinstance(remove_identities, Sequence)
                or isinstance(remove_identities, (str, bytes))
                or len(duplicate_identities) != len(duplicate_indices)
                or list(duplicate_identities) != list(remove_identities)
            ):
                raise ValueError("preflight_air_boundary_remove_identity_mismatch")
            for object_index, identity in zip(
                duplicate_indices, duplicate_identities, strict=True,
            ):
                obj = objects.get(object_index)
                if obj is None or not _matches_idf_object_identity(identity, obj):
                    raise ValueError("preflight_air_boundary_remove_identity_mismatch")
            for rewrite in plan.get("reference_rewrites", ()):
                if not isinstance(rewrite, Mapping):
                    raise ValueError("preflight_air_boundary_operation_invalid")
                object_index = int(rewrite["object_index"])
                field_index = int(rewrite["field_index"])
                obj = objects.get(object_index)
                if obj is None or canonical(obj.object_type) != canonical(str(rewrite["object_type"])):
                    raise ValueError("preflight_air_boundary_reference_identity_mismatch")
                if canonical(obj.name) != canonical(str(rewrite["object_name"])):
                    raise ValueError("preflight_air_boundary_reference_identity_mismatch")
                values = values_by_index[object_index]
                if not 1 <= field_index <= len(values):
                    raise ValueError("preflight_air_boundary_reference_field_missing")
                if values[field_index - 1] != str(rewrite["before"]):
                    raise ValueError("preflight_air_boundary_reference_before_mismatch")
                target_index = int(rewrite.get("target_object_index") or 0)
                target = objects.get(target_index)
                if (
                    target is None
                    or not _matches_idf_object_identity(
                        rewrite.get("before_target_identity"), target,
                    )
                    or target.name != str(rewrite["before"])
                ):
                    raise ValueError("preflight_air_boundary_reference_before_mismatch")
                values[field_index - 1] = str(rewrite["after"])
                changed_indices.add(object_index)
                if obj.name:
                    changed_names.add(obj.name)
            for value in plan.get("remove_object_indices", ()):
                object_index = int(value)
                obj = objects.get(object_index)
                if obj is None or canonical(obj.object_type) != "construction:airboundary":
                    raise ValueError("preflight_air_boundary_remove_identity_mismatch")
                removed_indices.add(object_index)
                if obj.name:
                    changed_names.add(obj.name)
        elif kind == "reciprocal_surface_pair":
            left = graph.surfaces[str(plan["anchor_surface_id"])]
            right = graph.surfaces[str(plan["target_surface_id"])]
            apply_pair(left, right, construction_after)
        elif kind == "split_and_pair":
            hub = graph.surfaces[str(plan["large_surface_id"])]
            leaves = [graph.surfaces[str(row)] for row in plan["small_surface_ids"]]
            names = [str(row) for row in plan["part_names"]]
            apply_parts(hub, leaves, names, construction_after)
        elif kind == "resegment_and_pair":
            for pair in plan.get("existing_pairs", ()):
                if not isinstance(pair, Mapping):
                    continue
                left_id, right_id = [str(row) for row in pair["surface_ids"]]
                apply_pair(graph.surfaces[left_id], graph.surfaces[right_id], construction_after)
            cover = graph.surfaces[str(plan["cover_surface_id"])]
            leaves = [graph.surfaces[str(row)] for row in plan["new_piece_surface_ids"]]
            names = [str(row) for row in plan["part_names"]]
            apply_parts(cover, leaves, names, construction_after)
        elif kind == "vertex_snap":
            source = graph.surfaces[str(plan["source_surface_id"])]
            vertex_index = int(plan["source_vertex_index"])
            if (
                source.object_index != int(plan["source_object_index"])
                or source.vertex_ids[vertex_index] != str(plan["source_vertex_id"])
            ):
                raise ValueError("preflight_snap_vertex_identity_mismatch")
            field_indices = tuple(int(row) for row in plan["coordinate_field_indices"])
            if field_indices != source.coordinate_field_indices[vertex_index]:
                raise ValueError("preflight_snap_field_identity_mismatch")
            before_world = tuple(float(row) for row in plan["before_world"])
            if before_world != source.world_vertices[vertex_index]:
                raise ValueError("preflight_snap_before_world_mismatch")
            after_world = tuple(float(row) for row in plan["after_world"])
            after_local = graph.point_to_local(after_world, source.zone_name)
            if after_local is None:
                raise ValueError("preflight_target_coordinate_frame_unresolved")
            values = values_by_index[source.object_index]
            tokens = source.coordinate_tokens[vertex_index]
            for field_index, token in zip(field_indices, tokens, strict=True):
                if values[field_index - 1].strip() != token.strip():
                    raise ValueError("preflight_snap_source_field_changed")
            for field_index, value in zip(field_indices, after_local, strict=True):
                values[field_index - 1] = _number(value)
            changed_indices.add(source.object_index)
            changed_names.add(source.object_name)
        else:
            continue
        applied_plans.append(str(plan["plan_id"]))

    replacements = dict(split_replacements)
    for object_index in changed_indices:
        if object_index in replacements or object_index in removed_indices:
            continue
        replacements[object_index] = _render(
            objects[object_index], values_by_index[object_index],
        )
    for object_index in removed_indices:
        obj = objects[object_index]
        offset = obj.raw.find(obj.object_type)
        replacements[object_index] = obj.raw[:offset] if offset >= 0 else ""
    output = input_text
    for object_index in sorted(replacements, key=lambda row: objects[row].start, reverse=True):
        obj = objects[object_index]
        output = output[:obj.start] + replacements[object_index] + output[obj.end:]
    parsed_output = parse_idf(output)
    if parsed_output.issues:
        raise ValueError("preflight_output_parse_failed")
    after_analysis = GeometryAnalysisContext.from_text(
        output,
        idd_text,
        tolerance_m=tolerance_m,
    )
    after_preview = build_model_preflight(
        output,
        idd_text,
        tolerance_m=tolerance_m,
        checks=AUDIT_CHECKS,
        analysis_context=after_analysis,
    )
    after_audit = after_preview["audit"]
    issue_by_id = {
        str(row["issue_id"]): row for row in authoritative["issues"]
    }
    targeted_issue_ids = [str(plan["plan_id"]) for plan in selected_plans]
    remaining_target_issue_ids = [
        str(plan["plan_id"])
        for plan in selected_plans
        if target_issue_remains(plan, after_preview["repair_plans"])
    ]
    if remaining_target_issue_ids:
        raise ValueError("preflight_target_issues_remain")
    allowed_geometry_identities: set[tuple[str, str]] = set()
    for plan in selected_plans:
        for surface_id in plan.get("geometry_mutated_surface_ids", ()):
            surface = graph.surfaces.get(str(surface_id))
            if surface is not None:
                allowed_geometry_identities.add((
                    surface.object_type, surface.object_name,
                ))
        template_id = plan.get("large_surface_id") or plan.get("cover_surface_id")
        template = graph.surfaces.get(str(template_id)) if template_id else None
        if template is not None:
            allowed_geometry_identities.update(
                (template.object_type, str(name))
                for name in plan.get("part_names", ())
            )
    non_target_changes = _non_target_geometry_changes(
        graph, after_analysis.graph, allowed_geometry_identities,
    )
    if non_target_changes:
        raise ValueError("preflight_non_target_geometry_changed")
    new_audit_error_ids = _new_audit_error_ids(before_audit, after_audit)
    if new_audit_error_ids:
        raise ValueError("preflight_new_audit_errors")
    applied_issues = [issue_by_id[issue_id] for issue_id in targeted_issue_ids]
    report = {
        "schema_version": "idfrepair.model-preflight-application.v1",
        "derived_copy_only": True,
        "original_input_changed": False,
        "parent_input_sha256": text_sha256(input_text),
        "output_sha256": text_sha256(output),
        "applied_plan_ids": applied_plans[:200],
        "applied_plan_count": len(applied_plans),
        "applied_plan_ids_truncated": len(applied_plans) > 200,
        "applied_issues": applied_issues,
        "applied_issue_count": len(applied_issues),
        "changed_object_count": len(changed_names),
        "changed_object_names": sorted(changed_names, key=canonical)[:200],
        "changed_object_names_truncated": len(changed_names) > 200,
        "before": dict(preview.get("summary") or {}),
        "after": {
            "audit_findings": after_audit["summary"]["total"],
            "audit_errors": after_audit["summary"]["errors"],
            "surfaces_checked": after_audit["summary"]["surfaces_checked"],
            "snap_issues": sum(
                row["kind"] == "vertex_snap" for row in after_preview["issues"]
            ),
        },
        "validation": {
            "parsed": True,
            "targeted_issue_ids": targeted_issue_ids,
            "remaining_target_issue_ids": remaining_target_issue_ids,
            "non_target_geometry_unchanged": not non_target_changes,
            "non_target_geometry_changes": list(non_target_changes),
            "new_audit_error_ids": new_audit_error_ids,
        },
        "rollback": {"available": True, "uses_parent_copy": True},
    }
    return PreflightApplication(output_text=output, report=report)


__all__ = [
    "PreflightApplication",
    "air_boundary_signature",
    "apply_model_preflight",
    "build_model_preflight",
]
