"""Evidence-first, read-only consistency checks for IDF surface models."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Iterable

from idfrepair.io.idf import canonical, text_sha256
from idfrepair.knowledge.geometry_graph import (
    GeometryEvidenceGraph, SurfaceNode, maximum_plane_distance,
)

if TYPE_CHECKING:
    from idfrepair.preflight.analysis import GeometryAnalysisContext


AUDIT_CHECKS = frozenset({
    "topology", "pairing", "boundary", "construction", "orphan_reference", "airboundary",
})


def _finding(
    rule_id: str,
    severity: str,
    surface: dict[str, Any],
    *,
    paired_surface: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    repair_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = "|".join((
        rule_id,
        str(surface.get("stable_identity", "")),
        str((paired_surface or {}).get("stable_identity", "")),
    ))
    return {
        "finding_id": f"audit:{sha256(identity.encode('utf-8')).hexdigest()[:20]}",
        "rule_id": rule_id,
        "message_id": f"audit.{rule_id}",
        "severity": severity,
        "surface": surface,
        "paired_surface": paired_surface,
        "evidence": evidence or {},
        "repair_preview": repair_preview,
        "read_only": True,
        "automatic_change_authorized": False,
    }


Point2D = tuple[float, float]


def _project_surface(surface: SurfaceNode, dropped_axis: int) -> list[Point2D]:
    axes = [axis for axis in range(3) if axis != dropped_axis]
    return [
        (point[axes[0]], point[axes[1]])
        for point in surface.world_vertices
    ]


def _plane_gap(left: SurfaceNode, right: SurfaceNode) -> float:
    if left.normal is None or right.normal is None:
        return float("inf")
    gaps = [
        abs(sum(
            left.normal[axis] * (point[axis] - left.centroid[axis])
            for axis in range(3)
        ))
        for point in right.world_vertices
    ]
    gaps.extend(
        abs(sum(
            right.normal[axis] * (point[axis] - right.centroid[axis])
            for axis in range(3)
        ))
        for point in left.world_vertices
    )
    return max(gaps, default=float("inf"))


def _coincident_outdoor_findings(
    context: GeometryAnalysisContext,
    graph: GeometryEvidenceGraph,
    details: dict[str, dict[str, Any]],
    *,
    geometry_tolerance_m: float,
) -> list[dict[str, Any]]:
    """Find high-overlap opposing faces that were left exterior or adiabatic."""

    from idfrepair.preflight.analysis import candidate_overlap_pairs
    from idfrepair.preflight.partition import measure_polygon_overlap_2d

    def usable(surface: SurfaceNode) -> bool:
        return bool(
            surface.legal_vertex_count
            and not surface.duplicate_vertices
            and not surface.self_intersecting
            and surface.normal is not None
            and surface.area > 1e-10
            and maximum_plane_distance(surface.world_vertices, surface.plane)
            <= geometry_tolerance_m
        )

    candidates: list[tuple[SurfaceNode, SurfaceNode, dict[str, float]]] = []
    outdoors = {
        surface.surface_id: surface for surface in graph.surfaces.values()
        if canonical(surface.outside_boundary_condition) in {"outdoors", "adiabatic"}
        and usable(surface)
        and surface.zone_name
    }
    for left_id, right_id in candidate_overlap_pairs(context, geometry_tolerance_m):
        left = outdoors.get(left_id)
        right = outdoors.get(right_id)
        if left is None or right is None:
            continue
        if canonical(left.zone_name) == canonical(right.zone_name):
            continue
        if left.normal is None or right.normal is None:
            continue
        normal_dot = sum(
            left.normal[axis] * right.normal[axis] for axis in range(3)
        )
        if normal_dot > -0.999:
            continue
        maximum_gap = _plane_gap(left, right)
        if maximum_gap > geometry_tolerance_m:
            continue
        dropped_axis = max(range(3), key=lambda axis: abs(left.normal[axis]))
        left_points = _project_surface(left, dropped_axis)
        right_points = _project_surface(right, dropped_axis)
        overlap = measure_polygon_overlap_2d(left_points, right_points)
        if overlap is None:
            continue
        left_area = overlap.left_area_m2
        right_area = overlap.right_area_m2
        intersection_area = overlap.intersection_area_m2
        smaller_ratio = intersection_area / min(left_area, right_area)
        if smaller_ratio < 0.95:
            continue
        candidates.append((left, right, {
            "normal_dot_product": normal_dot,
            "maximum_plane_gap_m": maximum_gap,
            "projected_overlap_area_m2": intersection_area,
            "left_projected_area_m2": left_area,
            "right_projected_area_m2": right_area,
            "left_overlap_ratio": intersection_area / left_area,
            "right_overlap_ratio": intersection_area / right_area,
            "smaller_surface_overlap_ratio": smaller_ratio,
        }))

    match_counts = Counter(
        surface.surface_id
        for left, right, _ in candidates
        for surface in (left, right)
    )
    findings = []
    for left, right, overlap in candidates:
        direct = bool(
            match_counts[left.surface_id] == 1
            and match_counts[right.surface_id] == 1
            and overlap["left_overlap_ratio"] >= 0.95
            and overlap["right_overlap_ratio"] >= 0.95
        )
        preview_surfaces = []
        for surface, paired in ((left, right), (right, left)):
            detail = details[surface.surface_id]
            preview_surfaces.append({
                "surface_name": surface.object_name,
                "zone_name": surface.zone_name,
                "global_vertices": detail["vertices"],
                "before": {
                    "boundary_condition": surface.outside_boundary_condition,
                    "boundary_object": surface.outside_boundary_object,
                    "construction": detail["construction"],
                    "sun_exposure": detail["sun_exposure"],
                    "wind_exposure": detail["wind_exposure"],
                },
                "after": ({
                    "boundary_condition": "Surface",
                    "boundary_object": paired.object_name,
                    "sun_exposure": "NoSun",
                    "wind_exposure": "NoWind",
                } if direct else None),
            })
        findings.append(_finding(
            "coincident_outdoor_surfaces",
            "error",
            details[left.surface_id],
            paired_surface=details[right.surface_id],
            evidence={
                "coordinate_system": "global",
                **overlap,
                "opposing_zone_names": [left.zone_name, right.zone_name],
                "construction_name_used_for_detection": False,
                "candidate_multiplicity": {
                    left.object_name: match_counts[left.surface_id],
                    right.object_name: match_counts[right.surface_id],
                },
            },
            repair_preview={
                "direct_reciprocal_pair": direct,
                "repair_strategy": (
                    "reciprocal_surface_boundary"
                    if direct else "surface_split_or_resegment_required"
                ),
                "surfaces": preview_surfaces,
                "construction_after": None,
                "construction_choice_required": True,
                "requires_user_confirmation": True,
                "candidate_generated": False,
                "automatic_apply_available": False,
            },
        ))
    return findings


def _pairing_findings(
    graph: GeometryEvidenceGraph,
    details: dict[str, dict[str, Any]],
    *,
    include_orphans: bool,
    include_pairing: bool,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    relations = {row.source_surface_id: row for row in graph.boundary_condition_relations}
    for surface in graph.surfaces.values():
        if canonical(surface.outside_boundary_condition) != "surface":
            continue
        relation = relations.get(surface.surface_id)
        if relation is None or not relation.target_surface_ids:
            if include_orphans:
                findings.append(_finding(
                    "surface_reference_missing", "error", details[surface.surface_id],
                    evidence={"referenced_name": surface.outside_boundary_object, "target_count": 0},
                ))
            continue
        if not relation.reference_unique:
            if include_orphans:
                findings.append(_finding(
                    "surface_reference_ambiguous", "error", details[surface.surface_id],
                    evidence={
                        "referenced_name": relation.referenced_name,
                        "target_count": len(relation.target_surface_ids),
                    },
                ))
            continue
        target_id = relation.target_surface_ids[0]
        if include_pairing and not relation.reciprocal:
            findings.append(_finding(
                "surface_reference_not_reciprocal", "error", details[surface.surface_id],
                paired_surface=details[target_id],
                evidence={
                    "referenced_name": relation.referenced_name,
                    "target_boundary_object": graph.surfaces[target_id].outside_boundary_object,
                },
            ))

    if not include_pairing:
        return findings
    for relation in graph.paired_surface_edges:
        if not relation.reciprocal:
            continue
        mismatches = [
            name for name, matches in (
                ("vertex_set", relation.same_vertex_set),
                ("edge_set", relation.same_edge_set),
                ("area", relation.equal_area),
                ("normal", relation.opposite_normals),
            )
            if not matches
        ]
        if not mismatches:
            continue
        left = graph.surfaces[relation.left_surface_id]
        right = graph.surfaces[relation.right_surface_id]
        findings.append(_finding(
            "paired_geometry_mismatch", "warning", details[left.surface_id],
            paired_surface=details[right.surface_id],
            evidence={
                "mismatches": mismatches,
                "left_area": left.area,
                "right_area": right.area,
                "area_delta": abs(left.area - right.area),
            },
        ))
    return findings


def _topology_findings(
    graph: GeometryEvidenceGraph,
    details: dict[str, dict[str, Any]],
    *,
    geometry_tolerance_m: float,
) -> list[dict[str, Any]]:
    rows = []
    for surface in graph.surfaces.values():
        planarity_deviation = maximum_plane_distance(surface.world_vertices, surface.plane)
        failures = [
            name for name, passed in (
                ("legal_vertex_count", surface.legal_vertex_count),
                ("unique_vertices", not surface.duplicate_vertices),
                ("simple_polygon", not surface.self_intersecting),
                ("coplanar", surface.coplanar or planarity_deviation <= geometry_tolerance_m),
                ("positive_area", surface.area > 1e-10),
            )
            if not passed
        ]
        if failures:
            details_by_check: dict[str, Any] = {}
            if "legal_vertex_count" in failures:
                details_by_check["legal_vertex_count"] = {
                    "measured": len(surface.world_vertices), "allowed": [3, 120],
                }
            if "unique_vertices" in failures:
                details_by_check["unique_vertices"] = {
                    "vertex_count": len(surface.world_vertices),
                    "unique_vertex_count": len(set(surface.world_vertices)),
                }
            if "simple_polygon" in failures:
                details_by_check["simple_polygon"] = {"self_intersection_detected": True}
            if "coplanar" in failures:
                details_by_check["coplanar"] = {
                    "measured_m": planarity_deviation,
                    "allowed_m": geometry_tolerance_m,
                }
            if "positive_area" in failures:
                details_by_check["positive_area"] = {
                    "measured_m2": surface.area, "minimum_m2": 1e-10,
                }
            rows.append(_finding(
                "surface_topology_invalid", "error", details[surface.surface_id],
                evidence={
                    "failed_checks": failures,
                    "failed_check_details": details_by_check,
                    "geometry_tolerance_m": geometry_tolerance_m,
                },
            ))
    return rows


def _boundary_findings(
    graph: GeometryEvidenceGraph,
    details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    internal = {"surface", "zone", "adiabatic"}
    for surface in graph.surfaces.values():
        detail = details[surface.surface_id]
        boundary = canonical(surface.outside_boundary_condition)
        exposures = (canonical(detail["sun_exposure"]), canonical(detail["wind_exposure"]))
        if boundary in internal and any(value not in {"", "nosun", "nowind"} for value in exposures):
            rows.append(_finding(
                "internal_surface_exposure", "warning", detail,
                evidence={
                    "boundary_condition": surface.outside_boundary_condition,
                    "sun_exposure": detail["sun_exposure"],
                    "wind_exposure": detail["wind_exposure"],
                },
            ))
    return rows


def _construction_findings(
    graph: GeometryEvidenceGraph,
    details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    exterior_markers = ("extwall", "exterior", "external")
    interior_markers = ("interior", "intwall")
    for surface in graph.surfaces.values():
        detail = details[surface.surface_id]
        construction = canonical(detail["construction"]).replace(" ", "")
        boundary = canonical(surface.outside_boundary_condition)
        direction = None
        if boundary == "surface" and any(marker in construction for marker in exterior_markers):
            direction = "exterior_name_on_paired_surface"
        elif boundary == "outdoors" and any(marker in construction for marker in interior_markers):
            direction = "interior_name_on_outdoor_surface"
        if direction:
            rows.append(_finding(
                "construction_context_review", "review", detail,
                evidence={
                    "signal": direction,
                    "construction_name_is_weak_evidence": True,
                    "boundary_condition_is_direct_evidence": True,
                },
            ))
    return rows


def _airboundary_findings(
    graph: GeometryEvidenceGraph,
    details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for surface in graph.surfaces.values():
        detail = details[surface.surface_id]
        construction = canonical(detail["construction"]).replace(" ", "")
        if "airboundary" not in construction and "airwall" not in construction:
            continue
        if canonical(surface.outside_boundary_condition) not in {"surface", "zone"}:
            rows.append(_finding(
                "airboundary_context_review", "review", detail,
                evidence={"support_status": "evidence-only", "candidate_generated": False},
            ))
    return rows


def audit_model(
    input_text: str,
    idd_text: str,
    *,
    checks: Iterable[str] | None = None,
    geometry_tolerance_m: float = 0.05,
    analysis_context: GeometryAnalysisContext | None = None,
    context: GeometryAnalysisContext | None = None,
) -> dict[str, Any]:
    """Return deterministic findings without changing input text or candidate eligibility."""

    selected = frozenset(AUDIT_CHECKS if checks is None else checks)
    unknown = selected - AUDIT_CHECKS
    if unknown:
        raise ValueError(f"audit_check_unknown:{','.join(sorted(unknown))}")
    if not 1e-8 <= geometry_tolerance_m <= 0.05:
        raise ValueError("audit_geometry_tolerance_out_of_bounds")
    if analysis_context is not None and context is not None:
        raise ValueError("audit_geometry_context_duplicate")
    analysis = analysis_context or context
    if analysis is None:
        from idfrepair.preflight.analysis import GeometryAnalysisContext

        analysis = GeometryAnalysisContext.from_text(
            input_text, idd_text, tolerance_m=geometry_tolerance_m,
        )
    elif analysis.document.text != input_text or analysis.idd.text != idd_text:
        raise ValueError("audit_geometry_context_mismatch")
    graph = analysis.graph
    details = {
        surface_id: dict(detail)
        for surface_id, detail in analysis.surface_details.items()
    }
    findings: list[dict[str, Any]] = []
    if "topology" in selected:
        findings.extend(_topology_findings(
            graph, details, geometry_tolerance_m=geometry_tolerance_m,
        ))
    if selected & {"pairing", "orphan_reference"}:
        findings.extend(_pairing_findings(
            graph,
            details,
            include_orphans=bool(selected & {"pairing", "orphan_reference"}),
            include_pairing="pairing" in selected,
        ))
    if "boundary" in selected:
        findings.extend(_boundary_findings(graph, details))
        findings.extend(_coincident_outdoor_findings(
            analysis, graph, details, geometry_tolerance_m=geometry_tolerance_m,
        ))
    if "construction" in selected:
        findings.extend(_construction_findings(graph, details))
    if "airboundary" in selected:
        findings.extend(_airboundary_findings(graph, details))
    findings.sort(key=lambda row: (
        {"error": 0, "warning": 1, "review": 2}[str(row["severity"])],
        str(row["rule_id"]),
        str(row["finding_id"]),
    ))
    counts = Counter(str(row["severity"]) for row in findings)
    identity = text_sha256(input_text)
    return {
        "schema_version": "idfrepair.model-audit.v1",
        "read_only": True,
        "input_sha256": identity,
        "output_sha256": identity,
        "checked_rules": sorted(selected),
        "geometry_tolerance_m": geometry_tolerance_m,
        "summary": {
            "total": len(findings),
            "errors": counts["error"],
            "warnings": counts["warning"],
            "review": counts["review"],
            "surfaces_checked": len(graph.surfaces),
        },
        "findings": findings,
        "proposed_operations": [],
        "production_enabled": False,
        "automatic_change_authorized": False,
    }


__all__ = ["AUDIT_CHECKS", "audit_model"]
