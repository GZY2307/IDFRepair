"""Preview geometry evidence without modifying IDF or public release policy."""

from __future__ import annotations

from typing import Any, Iterable

from idfrepair.capabilities.registry import load_support_registry
from idfrepair.capabilities.release_profile import load_release_profile
from idfrepair.candidates.geometry_pair import inspect_surface_pair, repair_weaker_paired_surface
from idfrepair.candidates.geometry_reconstruct import finite_four_point_reconstruction
from idfrepair.io.idf import canonical, text_sha256
from idfrepair.knowledge.geometry_graph import (
    GeometryEvidenceGraph, GeometryTolerance, SurfaceNode,
)
from idfrepair.preflight.analysis import GeometryAnalysisContext
from idfrepair.preflight.spatial_snap import SnapProposal, build_snap_proposals


EXPERIMENTAL_MECHANISMS = (
    "geometry_snap",
    "geometry_pair",
    "geometry_four_point",
    "kg623_reference",
    "osm_reference",
    "airboundary",
)

_ENTRY_IDS = {
    "geometry_snap": "geometry_snap_disabled",
    "geometry_pair": "geometry_pair_disabled",
    "geometry_four_point": "geometry_four_point_disabled",
    "kg623_reference": "kg623_reference_evidence_only",
    "osm_reference": "osm_reference_evidence_only",
    "airboundary": "airboundary_evidence_only",
}
_RELEASE_FLAGS = {
    "geometry_snap": "geometry_snap_enabled",
    "geometry_pair": "paired_geometry_enabled",
    "geometry_four_point": "geometry_four_point_enabled",
}
_MAX_PREVIEWS = 50
_MAX_TRIANGLES_SCANNED = 200


def _surface(surface: SurfaceNode) -> dict[str, Any]:
    return {
        "surface_id": surface.surface_id,
        "stable_identity": surface.stable_identity,
        "object_index": surface.object_index,
        "object_type": surface.object_type,
        "name": surface.object_name,
        "zone": surface.zone_name,
        "space": surface.space_name,
        "surface_type": surface.surface_type,
        "vertices": [list(point) for point in surface.world_vertices],
    }


def _shadow(*, geometry_passed: bool, reasons: Iterable[str]) -> dict[str, Any]:
    return {
        "static_geometry_passed": geometry_passed,
        "reasons": list(reasons),
        "semantic_run": False,
        "energyplus_run": False,
        "input_written": False,
        "final_idf_changed": False,
        "status": "PREVIEW_ONLY",
    }


def _half_grid_axes(point: tuple[float, float, float]) -> int:
    return sum(
        abs(value * 2.0 - round(value * 2.0)) <= max(1e-9, abs(value) * 1e-12)
        for value in point
    )


def _cluster_pair(left: str, right: str) -> tuple[str, str] | None:
    if not left or not right or left == right:
        return None
    return tuple(sorted((left, right)))  # type: ignore[return-value]


def _shared_edge_count(
    context: GeometryAnalysisContext,
    surface_id: str,
    pairs: Iterable[tuple[str, str] | None],
) -> int:
    return sum(
        any(other != surface_id for other in context.edge_surface_ids.get(pair, ()))
        for pair in {row for row in pairs if row is not None}
    )


def _snap_topology_evidence(
    context: GeometryAnalysisContext,
    proposal: SnapProposal,
) -> tuple[int, int, int, int]:
    graph = context.graph
    surface_id = proposal.source.surface_id
    surface = graph.surfaces[surface_id]
    vertex_index = proposal.source.vertex_index
    preceding_index = (vertex_index - 1) % len(surface.vertex_ids)
    following_index = (vertex_index + 1) % len(surface.vertex_ids)
    cluster_ids = tuple(
        graph.vertices[vertex_id].cluster_id or "" for vertex_id in surface.vertex_ids
    )
    target_cluster_id = graph.vertices[proposal.target_vertex_ids[0]].cluster_id or ""
    before_pairs = context.surface_edge_pairs[surface_id]
    after_pairs = list(before_pairs)
    after_pairs[preceding_index] = _cluster_pair(
        cluster_ids[preceding_index], target_cluster_id,
    )
    after_pairs[vertex_index] = _cluster_pair(
        target_cluster_id, cluster_ids[following_index],
    )
    before_shared = _shared_edge_count(context, surface_id, before_pairs)
    after_shared = _shared_edge_count(context, surface_id, after_pairs)

    zone_key = canonical(surface.zone_name)
    zone = graph.zones.get(zone_key)
    if zone is None:
        return 0, 0, before_shared, after_shared
    incidence = context.zone_edge_incidence.get(zone_key, {})
    deltas: dict[tuple[str, str], int] = {}
    for pair in (before_pairs[preceding_index], before_pairs[vertex_index]):
        if pair is not None:
            deltas[pair] = deltas.get(pair, 0) - 1
    for pair in (after_pairs[preceding_index], after_pairs[vertex_index]):
        if pair is not None:
            deltas[pair] = deltas.get(pair, 0) + 1
    after_open = zone.open_edge_count
    for pair, delta in deltas.items():
        before_count = incidence.get(pair, 0)
        after_count = before_count + delta
        after_open += int(after_count == 1) - int(before_count == 1)
    return zone.open_edge_count, after_open, before_shared, after_shared


def _snap_previews(
    context: GeometryAnalysisContext,
) -> tuple[list[dict[str, Any]], bool]:
    previews: list[dict[str, Any]] = []
    graph = context.graph
    proposals = build_snap_proposals(context, context.tolerance_m)
    for proposal in proposals:
        surface = graph.surfaces[proposal.source.surface_id]
        target_vertex_id = proposal.target_vertex_ids[0]
        target_cluster_id = graph.vertices[target_vertex_id].cluster_id
        before_open, after_open, before_shared, after_shared = _snap_topology_evidence(
            context, proposal,
        )
        previews.append({
            "preview_id": (
                f"geometry_snap:{surface.surface_id}:{proposal.source.vertex_index}"
            ),
            "preview_kind": "candidate" if proposal.safe_to_apply else "evidence",
            "preview_only": True,
            "surface": _surface(surface),
            "paired_surface": None,
            "preview_operation": {
                "kind": "replace_vertex",
                "coordinate_system": "global",
                "vertex_index": proposal.source.vertex_index,
                "before": list(proposal.before_world),
                "after": list(proposal.after_world),
            },
            "evidence": {
                "source_surface_id": proposal.source.surface_id,
                "source_object_index": proposal.source.object_index,
                "source_object_name": proposal.source.object_name,
                "source_vertex_id": proposal.source.vertex_id,
                "target_cluster_id": target_cluster_id,
                "target_vertex_id": target_vertex_id,
                "target_support_count": proposal.target_distinct_surface_support,
                "target_total_support": proposal.target_total_support,
                "target_selection_basis": proposal.target_basis,
                "target_half_grid_axes": _half_grid_axes(proposal.after_world),
                "snapped_to_observed_coordinate": True,
                "supporting_surface_ids": list(proposal.supporting_surface_ids),
                "before_open_edges": before_open,
                "after_open_edges": after_open,
                "before_shared_edges": before_shared,
                "after_shared_edges": after_shared,
                "detector_automatic_eligible": proposal.safe_to_apply,
                "distance_m": proposal.distance_m,
                "rejection_reasons": list(proposal.rejection_reasons),
            },
            "shadow_validation": _shadow(
                geometry_passed=proposal.safe_to_apply,
                reasons=proposal.rejection_reasons,
            ),
            "apply_authorized": False,
        })
        if len(previews) >= _MAX_PREVIEWS:
            return previews, len(proposals) > _MAX_PREVIEWS
    return previews, False


def _pair_previews(graph: GeometryEvidenceGraph) -> tuple[list[dict[str, Any]], bool]:
    previews: list[dict[str, Any]] = []
    for relation in graph.paired_surface_edges:
        left = graph.surfaces[relation.left_surface_id]
        right = graph.surfaces[relation.right_surface_id]
        alignment = inspect_surface_pair(graph, left, right)
        if alignment.valid:
            continue
        proposal = repair_weaker_paired_surface(graph, left)
        if proposal is None:
            proposal = repair_weaker_paired_surface(graph, right)
        target = graph.surfaces[proposal.target_surface_id] if proposal else left
        source = graph.surfaces[proposal.source_surface_id] if proposal else right
        operation = None
        if proposal is not None:
            operation = {
                "kind": "replace_vertices",
                "coordinate_system": "global",
                "before": [list(point) for point in target.world_vertices],
                "after": [list(point) for point in proposal.proposed_world_vertices],
                "technical_local_after": [
                    list(point) for point in proposal.proposed_local_vertices
                ],
            }
        reasons = tuple(alignment.reasons) + (proposal.reasons if proposal else ())
        previews.append({
            "preview_id": f"geometry_pair:{relation.relation_id}",
            "preview_kind": "candidate" if proposal else "evidence",
            "preview_only": True,
            "surface": _surface(target),
            "paired_surface": _surface(source),
            "preview_operation": operation,
            "evidence": {
                "reciprocal_unique": alignment.reciprocal_unique,
                "coordinates_equal": alignment.coordinates_equal,
                "normals_opposite": alignment.normals_opposite,
                "areas_equal": alignment.areas_equal,
                "edge_sets_equal": alignment.edge_sets_equal,
                "weaker_side_uniquely_identified": proposal is not None,
            },
            "shadow_validation": _shadow(
                geometry_passed=bool(proposal and not proposal.reasons),
                reasons=reasons,
            ),
            "apply_authorized": False,
        })
        if len(previews) >= _MAX_PREVIEWS:
            return previews, True
    return previews, False


def _four_point_previews(graph: GeometryEvidenceGraph) -> tuple[list[dict[str, Any]], bool]:
    previews: list[dict[str, Any]] = []
    triangles = [surface for surface in graph.surfaces.values() if len(surface.world_vertices) == 3]
    for surface in triangles[:_MAX_TRIANGLES_SCANNED]:
        for missing_index in range(4):
            slots = [index for index in range(4) if index != missing_index]
            known = dict(zip(slots, surface.world_vertices, strict=True))
            proposals = finite_four_point_reconstruction(
                known=known,
                missing_index=missing_index,
                graph=graph,
                zone_name=surface.zone_name,
            )
            for index, proposal in enumerate(proposals):
                previews.append({
                    "preview_id": f"geometry_four_point:{surface.surface_id}:{missing_index}:{index}",
                    "preview_kind": "candidate",
                    "preview_only": True,
                    "surface": _surface(surface),
                    "paired_surface": None,
                    "preview_operation": {
                        "kind": "insert_vertex",
                        "coordinate_system": "global",
                        "missing_index": missing_index,
                        "after": list(proposal.point),
                    },
                    "evidence": {
                        "sources": list(proposal.sources),
                        "unique": proposal.unique,
                        "requires_user_confirmation": proposal.requires_user_confirmation,
                    },
                    "shadow_validation": _shadow(
                        geometry_passed=proposal.unique and not proposal.requires_user_confirmation,
                        reasons=(() if proposal.unique else ("four_point_not_unique",)),
                    ),
                    "apply_authorized": False,
                })
                if len(previews) >= _MAX_PREVIEWS:
                    return previews, True
    return previews, len(triangles) > _MAX_TRIANGLES_SCANNED


def _evidence_previews(
    mechanism_id: str,
    context: GeometryAnalysisContext,
    input_text: str,
) -> tuple[list[dict[str, Any]], bool]:
    graph = context.graph
    if mechanism_id == "airboundary":
        rows = []
        for surface in graph.surfaces.values():
            construction = str(
                context.surface_details[surface.surface_id].get("construction") or ""
            )
            construction_key = canonical(construction).replace(" ", "")
            if "airboundary" not in construction_key and "airwall" not in construction_key:
                continue
            rows.append({
                "preview_id": f"airboundary:{surface.surface_id}",
                "preview_kind": "evidence",
                "preview_only": True,
                "surface": _surface(surface),
                "paired_surface": None,
                "preview_operation": None,
                "evidence": {"construction": construction, "provenance": "bound_idd_field"},
                "shadow_validation": _shadow(
                    geometry_passed=surface.valid,
                    reasons=("evidence_only_no_candidate",),
                ),
                "apply_authorized": False,
            })
            if len(rows) >= _MAX_PREVIEWS:
                return rows, True
        return rows, False
    marker = "kg623" if mechanism_id == "kg623_reference" else "openstudio"
    count = input_text.casefold().count(marker)
    if not count:
        return [], False
    return [{
        "preview_id": f"{mechanism_id}:document-marker",
        "preview_kind": "evidence",
        "preview_only": True,
        "surface": None,
        "paired_surface": None,
        "preview_operation": None,
        "evidence": {"marker": marker, "occurrences": count, "provenance_verified": False},
        "shadow_validation": _shadow(
            geometry_passed=False,
            reasons=("explicit_object_provenance_missing",),
        ),
        "apply_authorized": False,
    }], False


def preview_geometry_lab(
    input_text: str,
    idd_text: str,
    *,
    mechanisms: Iterable[str] | None = None,
    snap_absolute_m: float = 0.05,
    snap_relative: float = 0.001,
    analysis_context: GeometryAnalysisContext | None = None,
    context: GeometryAnalysisContext | None = None,
) -> dict[str, Any]:
    """Run selected detectors under an immutable PREVIEW_ONLY boundary."""

    selected = tuple(EXPERIMENTAL_MECHANISMS if mechanisms is None else mechanisms)
    if len(selected) != len(set(selected)):
        raise ValueError("experimental_mechanism_duplicate")
    unknown = set(selected) - set(EXPERIMENTAL_MECHANISMS)
    if unknown:
        raise ValueError(f"experimental_mechanism_unknown:{','.join(sorted(unknown))}")
    if not 1e-8 <= snap_absolute_m <= 0.05:
        raise ValueError("experimental_snap_absolute_out_of_bounds")
    if not 1e-10 <= snap_relative <= 0.001:
        raise ValueError("experimental_snap_relative_out_of_bounds")
    snap_tolerance = GeometryTolerance(
        absolute=float(snap_absolute_m), relative=float(snap_relative),
    )
    profile = load_release_profile()
    registry = load_support_registry()
    if analysis_context is not None and context is not None:
        raise ValueError("experimental_geometry_context_duplicate")
    analysis = analysis_context or context
    if analysis is None:
        analysis = GeometryAnalysisContext.from_text(
            input_text, idd_text, tolerance_m=snap_tolerance.absolute,
        )
    elif analysis.document.text != input_text or analysis.idd.text != idd_text:
        raise ValueError("experimental_geometry_context_mismatch")
    if analysis.tolerance_m != snap_tolerance.absolute:
        raise ValueError("experimental_geometry_context_tolerance_mismatch")
    graph = analysis.graph
    rows: list[dict[str, Any]] = []
    for mechanism_id in selected:
        if mechanism_id == "geometry_snap":
            previews, truncated = _snap_previews(analysis)
        elif mechanism_id == "geometry_pair":
            previews, truncated = _pair_previews(graph)
        elif mechanism_id == "geometry_four_point":
            previews, truncated = _four_point_previews(graph)
        else:
            previews, truncated = _evidence_previews(
                mechanism_id, analysis, input_text,
            )
        entry = registry.entry(_ENTRY_IDS[mechanism_id])
        release_flag = _RELEASE_FLAGS.get(mechanism_id)
        rows.append({
            "mechanism_id": mechanism_id,
            "registry_entry_id": entry.entry_id,
            "support_status": entry.support_status.value,
            "qualification_status": (
                "NOT_QUALIFIED" if entry.support_status.value == "disabled" else "EVIDENCE_ONLY"
            ),
            "public_enabled": entry.public_enabled,
            "automatic_policy": entry.automatic_policy,
            "release_flag": release_flag,
            "release_flag_enabled": bool(profile.payload.get(release_flag, False)) if release_flag else False,
            "checkbox_changes_registry": False,
            "detector_status": "COMPLETED",
            "preview_count": len(previews),
            "previews": previews,
            "truncated": truncated,
            "repair_candidates_generated": 0,
            "apply_authorized": False,
            "notes_zh": entry.notes_zh,
            "notes_en": entry.notes_en,
            "required_evidence": list(entry.required_evidence),
            "rejection_conditions": list(entry.rejection_conditions),
        })
    identity = text_sha256(input_text)
    return {
        "schema_version": "idfrepair.experimental-geometry.v1",
        "preview_only": True,
        "production_enabled": False,
        "apply_authorized": False,
        "input_sha256": identity,
        "output_sha256": identity,
        "release_profile_id": profile.release_profile_id,
        "release_profile_sha256": profile.sha256,
        "support_registry_sha256": registry.sha256,
        "selected_mechanisms": list(selected),
        "thresholds": {
            "snap_absolute_m": snap_tolerance.absolute,
            "snap_relative": snap_tolerance.relative,
            "bounds": {
                "snap_absolute_m": [1e-8, 0.05],
                "snap_relative": [1e-10, 0.001],
            },
        },
        "surfaces_scanned": len(graph.surfaces),
        "mechanisms": rows,
        "repair_candidates": [],
        "proposed_operations": [],
    }


__all__ = ["EXPERIMENTAL_MECHANISMS", "preview_geometry_lab"]
