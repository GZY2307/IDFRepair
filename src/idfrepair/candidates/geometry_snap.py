"""Conservative single-vertex snapping against trusted geometry clusters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from idfrepair.knowledge.geometry_graph import (
    GeometryEvidenceGraph,
    GeometryTolerance,
    Point3D,
    SurfaceNode,
    point_distance,
)
from idfrepair.validation.geometry import validate_polygon


@dataclass(frozen=True, slots=True)
class CoordinateSnapProposal:
    surface_id: str
    vertex_index: int
    original_point: Point3D
    snapped_point: Point3D
    target_cluster_id: str
    target_vertex_id: str
    target_support_count: int
    target_selection_basis: str
    target_half_grid_axes: int
    snapped_to_observed_coordinate: bool
    supporting_surface_ids: tuple[str, ...]
    before_open_edges: int
    after_open_edges: int
    before_shared_edges: int
    after_shared_edges: int
    coplanar_after: bool
    shared_edge_consistent: bool
    zone_closure_improved: bool
    no_equal_competitor: bool
    automatic_eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _TrustedAnchor:
    vertex_id: str
    point: Point3D
    supporting_surface_ids: tuple[str, ...]
    exact_supporting_surface_ids: tuple[str, ...]
    exact_support_count: int
    half_grid_axes: int
    selection_basis: str


def _half_grid_axes(point: Point3D) -> int:
    """Count coordinates already expressed on a clean 0.5 m world grid."""

    return sum(
        abs(value * 2.0 - round(value * 2.0)) <= max(1e-9, abs(value) * 1e-12)
        for value in point
    )


def _decimal_complexity(point: Point3D) -> int:
    """Prefer observed coordinates with fewer meaningful decimal places."""

    total = 0
    for value in point:
        token = f"{value:.12f}".rstrip("0").rstrip(".")
        total += len(token.rsplit(".", 1)[1]) if "." in token else 0
    return total


def _within_snap_tolerance(
    left: Point3D,
    right: Point3D,
    tolerance: GeometryTolerance,
) -> bool:
    return tolerance.point_close(left, right)


def _trusted_cluster_members(
    graph: GeometryEvidenceGraph,
    surface: SurfaceNode,
    cluster_id: str,
) -> _TrustedAnchor | None:
    cluster = graph.clusters[cluster_id]
    trusted = {
        member_surface_id
        for member_surface_id in cluster.surface_ids
        if member_surface_id != surface.surface_id
        and member_surface_id in graph.surfaces
        and graph.surfaces[member_surface_id].valid
        and graph.surfaces[member_surface_id].zone_name.casefold() == surface.zone_name.casefold()
    }
    if len(trusted) < 2:
        return None
    members = [
        graph.vertices[vertex_id]
        for vertex_id in cluster.vertex_ids
        if graph.vertices[vertex_id].surface_id in trusted
    ]
    if not members:
        return None
    # Reuse a real observed coordinate. Prefer the exact multi-surface mode;
    # ties go to a clean half-grid world coordinate, then a stable token.
    point_members: dict[Point3D, list[object]] = {}
    for member in members:
        point_members.setdefault(member.world_point, []).append(member)
    ranked = sorted(
        point_members.items(),
        key=lambda item: (
            -len({member.surface_id for member in item[1]}),
            -_half_grid_axes(item[0]),
            _decimal_complexity(item[0]),
            item[0],
        ),
    )
    selected_point, selected_members = ranked[0]
    selected = min(
        selected_members,
        key=lambda row: (row.surface_id, row.local_index, row.vertex_id),
    )
    exact_support = tuple(sorted({member.surface_id for member in selected_members}))
    half_grid_axes = _half_grid_axes(selected_point)
    if len(exact_support) >= 2:
        basis = "exact_multi_surface_mode"
    elif half_grid_axes:
        basis = "clean_observed_half_grid"
    else:
        basis = "stable_observed_coordinate"
    return _TrustedAnchor(
        vertex_id=selected.vertex_id,
        point=selected_point,
        supporting_surface_ids=tuple(sorted(trusted)),
        exact_supporting_surface_ids=exact_support,
        exact_support_count=len(exact_support),
        half_grid_axes=half_grid_axes,
        selection_basis=basis,
    )


def coordinate_snap_candidates(
    graph: GeometryEvidenceGraph,
    surface: SurfaceNode,
    *,
    snap_tolerance: GeometryTolerance | None = None,
) -> tuple[CoordinateSnapProposal, ...]:
    """Find one evidence-bound replacement for one anomalous vertex.

    Candidates are same-zone only.  A cluster is eligible only when at least
    two valid, independent surfaces use it, the candidate becomes a valid
    polygon, and zone edge incidence strictly improves without a new opening.
    """

    snap_tolerance = snap_tolerance or GeometryTolerance(absolute=1e-4, relative=1e-6)
    if not surface.zone_name or surface.duplicate_vertices or surface.self_intersecting:
        return ()
    before = graph.topology_metrics(surface.zone_name, target_surface_id=surface.surface_id)
    rows: list[CoordinateSnapProposal] = []
    for vertex_index, original in enumerate(surface.world_vertices):
        candidates: list[tuple[float, str, _TrustedAnchor]] = []
        for cluster in graph.clusters.values():
            if not _within_snap_tolerance(original, cluster.representative, snap_tolerance):
                continue
            if graph.tolerance.point_close(original, cluster.representative):
                continue
            trusted = _trusted_cluster_members(graph, surface, cluster.cluster_id)
            if trusted is None:
                continue
            candidates.append((
                point_distance(original, trusted.point),
                cluster.cluster_id,
                trusted,
            ))
        candidates.sort(key=lambda row: (
            row[0], -row[2].exact_support_count, -row[2].half_grid_axes, row[1],
        ))
        if not candidates:
            continue
        minimum = candidates[0][0]
        distance_limit = min(snap_tolerance.absolute, snap_tolerance.relative * max(minimum, 1.0))
        equally_close = [row for row in candidates if abs(row[0] - minimum) <= distance_limit]
        no_competitor = len(equally_close) == 1
        for distance, cluster_id, anchor in candidates[:1]:
            snapped = anchor.point
            support = anchor.supporting_surface_ids
            proposed = list(surface.world_vertices)
            proposed[vertex_index] = snapped
            valid, validation_reasons = validate_polygon(proposed, tolerance=graph.tolerance)
            after = graph.topology_metrics(
                surface.zone_name,
                overrides={surface.surface_id: tuple(proposed)},
                target_surface_id=surface.surface_id,
            )
            nondegrading = bool(
                after.open_edge_count <= before.open_edge_count
                and after.nonmanifold_edge_count <= before.nonmanifold_edge_count
                and after.degenerate_edge_count <= before.degenerate_edge_count
            )
            improved = bool(
                nondegrading
                and (
                    after.open_edge_count < before.open_edge_count
                    or after.shared_edge_count > before.shared_edge_count
                )
            )
            shared_consistent = after.shared_edge_count >= before.shared_edge_count
            reasons = list(validation_reasons)
            if not no_competitor:
                reasons.append("equal_distance_competing_cluster")
            if not shared_consistent:
                reasons.append("shared_edge_regression")
            if not improved:
                reasons.append("zone_closure_not_improved")
            if len(support) < 2:
                reasons.append("trusted_surface_support_below_two")
            rows.append(CoordinateSnapProposal(
                surface_id=surface.surface_id,
                vertex_index=vertex_index,
                original_point=original,
                snapped_point=snapped,
                target_cluster_id=cluster_id,
                target_vertex_id=anchor.vertex_id,
                target_support_count=anchor.exact_support_count,
                target_selection_basis=anchor.selection_basis,
                target_half_grid_axes=anchor.half_grid_axes,
                snapped_to_observed_coordinate=True,
                supporting_surface_ids=support,
                before_open_edges=before.open_edge_count,
                after_open_edges=after.open_edge_count,
                before_shared_edges=before.shared_edge_count,
                after_shared_edges=after.shared_edge_count,
                coplanar_after=valid and "not_coplanar" not in validation_reasons,
                shared_edge_consistent=shared_consistent,
                zone_closure_improved=improved,
                no_equal_competitor=no_competitor,
                automatic_eligible=not reasons,
                reasons=tuple(reasons),
            ))
    # More than one repairable vertex is not a single-anomaly proof.
    eligible = [row for row in rows if row.automatic_eligible]
    if len(eligible) > 1:
        return tuple(
            CoordinateSnapProposal(
                surface_id=row.surface_id,
                vertex_index=row.vertex_index,
                original_point=row.original_point,
                snapped_point=row.snapped_point,
                target_cluster_id=row.target_cluster_id,
                target_vertex_id=row.target_vertex_id,
                target_support_count=row.target_support_count,
                target_selection_basis=row.target_selection_basis,
                target_half_grid_axes=row.target_half_grid_axes,
                snapped_to_observed_coordinate=row.snapped_to_observed_coordinate,
                supporting_surface_ids=row.supporting_surface_ids,
                before_open_edges=row.before_open_edges,
                after_open_edges=row.after_open_edges,
                before_shared_edges=row.before_shared_edges,
                after_shared_edges=row.after_shared_edges,
                coplanar_after=row.coplanar_after,
                shared_edge_consistent=row.shared_edge_consistent,
                zone_closure_improved=row.zone_closure_improved,
                no_equal_competitor=row.no_equal_competitor,
                automatic_eligible=False,
                reasons=tuple(sorted(set(row.reasons) | {"multiple_anomalous_vertices"})),
            )
            for row in rows
        )
    return tuple(rows)


__all__ = ["CoordinateSnapProposal", "coordinate_snap_candidates"]
