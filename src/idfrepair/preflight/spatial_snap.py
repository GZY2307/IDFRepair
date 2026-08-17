"""Linear-time observed-coordinate snapping over a shared analysis context."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import floor

from idfrepair.io.idf import canonical
from idfrepair.knowledge.geometry_graph import Point3D, point_distance
from idfrepair.preflight.analysis import GeometryAnalysisContext, IndexedVertex


@dataclass(frozen=True, slots=True)
class SnapVertex:
    surface_id: str
    object_index: int
    object_type: str
    object_name: str
    vertex_index: int
    vertex_id: str
    zone_name: str
    local_point: Point3D
    world_point: Point3D
    coordinate_field_indices: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class SnapProposal:
    source: SnapVertex
    before_world: Point3D
    after_world: Point3D
    distance_m: float
    target_distinct_surface_support: int
    target_total_support: int
    supporting_surface_ids: tuple[str, ...]
    target_vertex_ids: tuple[str, ...]
    target_basis: str
    simple_number_score: int
    safe_to_apply: bool
    rejection_reasons: tuple[str, ...]

    @property
    def source_surface_id(self) -> str:
        return self.source.surface_id

    @property
    def source_object_index(self) -> int:
        return self.source.object_index

    @property
    def source_object_name(self) -> str:
        return self.source.object_name

    @property
    def source_vertex_index(self) -> int:
        return self.source.vertex_index

    @property
    def source_vertex_id(self) -> str:
        return self.source.vertex_id

    @property
    def target_support(self) -> int:
        return self.target_distinct_surface_support

    @property
    def supporting_surfaces(self) -> tuple[str, ...]:
        return self.supporting_surface_ids

    @property
    def distance(self) -> float:
        return self.distance_m


@dataclass(frozen=True, slots=True)
class _ObservedTarget:
    point: Point3D
    vertices: tuple[IndexedVertex, ...]
    supporting_surface_ids: tuple[str, ...]
    distinct_surface_support: int
    total_support: int
    simple_number_score: int
    distance_m: float


def _cell(point: Point3D, tolerance_m: float) -> tuple[int, int, int]:
    return tuple(floor(value / tolerance_m) for value in point)  # type: ignore[return-value]


def _simple_number_score(point: Point3D) -> int:
    epsilon = 1e-9
    if all(abs(value - round(value)) <= epsilon for value in point):
        return 0
    if all(abs(value * 2.0 - round(value * 2.0)) <= epsilon for value in point):
        return 1
    return 2


def _source_vertex(vertex: IndexedVertex) -> SnapVertex:
    return SnapVertex(
        surface_id=vertex.surface_id,
        object_index=vertex.object_index,
        object_type=vertex.object_type,
        object_name=vertex.object_name,
        vertex_index=vertex.vertex_index,
        vertex_id=vertex.vertex_id,
        zone_name=vertex.zone_name,
        local_point=vertex.local_point,
        world_point=vertex.world_point,
        coordinate_field_indices=vertex.coordinate_field_indices,
    )


def _target_groups(
    context: GeometryAnalysisContext,
    source: IndexedVertex,
) -> tuple[_ObservedTarget, ...]:
    source_cell = _cell(source.world_point, context.vertex_cell_size_m)
    nearby = {
        vertex.vertex_id: vertex
        for delta in product((-1, 0, 1), repeat=3)
        for vertex in context.vertex_cells.get(tuple(
            source_cell[axis] + delta[axis] for axis in range(3)
        ), ())
        if vertex.vertex_id != source.vertex_id
    }
    by_point: dict[Point3D, list[IndexedVertex]] = {}
    for vertex in nearby.values():
        if vertex.world_point == source.world_point:
            continue
        by_point.setdefault(vertex.world_point, []).append(vertex)
    current_vertices = context.observed_coordinates[source.world_point]
    current_quality = (
        len({vertex.surface_id for vertex in current_vertices}),
        len(current_vertices),
        -_simple_number_score(source.world_point),
    )
    rows = []
    for point, vertices in by_point.items():
        supporting = tuple(sorted({
            vertex.surface_id for vertex in vertices
            if vertex.surface_id != source.surface_id
            and context.graph.surfaces[vertex.surface_id].valid
        }))
        supporting_vertices = tuple(sorted(
            (
                vertex for vertex in vertices
                if vertex.surface_id != source.surface_id
                and context.graph.surfaces[vertex.surface_id].valid
            ),
            key=lambda row: (row.surface_id, row.vertex_index, row.vertex_id),
        ))
        if len(supporting) < 2:
            continue
        target_quality = (
            len(supporting),
            len(supporting_vertices),
            -_simple_number_score(point),
        )
        if target_quality <= current_quality:
            continue
        rows.append(_ObservedTarget(
            point=point,
            vertices=supporting_vertices,
            supporting_surface_ids=supporting,
            distinct_surface_support=len(supporting),
            total_support=len(supporting_vertices),
            simple_number_score=_simple_number_score(point),
            distance_m=point_distance(source.world_point, point),
        ))
    return tuple(rows)


def _target_rank(target: _ObservedTarget) -> tuple[object, ...]:
    return (
        -target.distinct_surface_support,
        -target.total_support,
        target.simple_number_score,
        target.distance_m,
        target.point,
    )


def _ambiguous_top(rows: tuple[_ObservedTarget, ...]) -> bool:
    if len(rows) < 2:
        return False
    left, right = rows[:2]
    return bool(
        left.distinct_surface_support == right.distinct_surface_support
        and left.total_support == right.total_support
        and left.simple_number_score == right.simple_number_score
        and abs(left.distance_m - right.distance_m) <= 1e-12
    )


def _edge_collapses(
    context: GeometryAnalysisContext,
    source: IndexedVertex,
    target: Point3D,
) -> bool:
    surface = context.graph.surfaces[source.surface_id]
    preceding = surface.world_vertices[source.vertex_index - 1]
    following = surface.world_vertices[(source.vertex_index + 1) % len(surface.world_vertices)]
    epsilon = max(context.graph.tolerance.absolute, 1e-9)
    return bool(
        point_distance(target, preceding) <= epsilon
        or point_distance(target, following) <= epsilon
    )


def _related_to_support(
    context: GeometryAnalysisContext,
    source: IndexedVertex,
    target: _ObservedTarget,
) -> bool:
    source_zone = canonical(source.zone_name)
    neighbours = context.surface_neighbors.get(source.surface_id, frozenset())
    return bool(target.supporting_surface_ids) and all(
        (
            source_zone
            and canonical(context.graph.surfaces[surface_id].zone_name) == source_zone
        )
        or surface_id in neighbours
        for surface_id in target.supporting_surface_ids
    )


def build_snap_proposals(
    context: GeometryAnalysisContext,
    tolerance_m: float,
) -> tuple[SnapProposal, ...]:
    """Choose one ranked observed target per drifted vertex in linear time."""

    if not 1e-8 <= tolerance_m <= 0.05:
        raise ValueError("spatial_snap_tolerance_out_of_bounds")
    if tolerance_m != context.vertex_cell_size_m:
        raise ValueError("spatial_snap_context_tolerance_mismatch")
    proposals: list[SnapProposal] = []
    for cell in sorted(context.vertex_cells):
        for source in context.vertex_cells[cell]:
            targets = tuple(sorted(_target_groups(context, source), key=_target_rank))
            if not targets:
                continue
            target = targets[0]
            reasons = []
            if target.distance_m > tolerance_m:
                reasons.append("move_over_tolerance")
            if _edge_collapses(context, source, target.point):
                reasons.append("polygon_edge_collapse")
            if not _related_to_support(context, source, target):
                reasons.append("cross_story_or_unrelated_cluster")
            if _ambiguous_top(targets):
                reasons.append("ambiguous_top_ranked_targets")
            proposals.append(SnapProposal(
                source=_source_vertex(source),
                before_world=source.world_point,
                after_world=target.point,
                distance_m=target.distance_m,
                target_distinct_surface_support=target.distinct_surface_support,
                target_total_support=target.total_support,
                supporting_surface_ids=target.supporting_surface_ids,
                target_vertex_ids=tuple(vertex.vertex_id for vertex in target.vertices),
                target_basis=(
                    "observed_coordinate_ranked_by_surface_support_total_support_"
                    "simple_number_distance_lexicographic"
                ),
                simple_number_score=target.simple_number_score,
                safe_to_apply=not reasons,
                rejection_reasons=tuple(reasons),
            ))
    return tuple(sorted(
        proposals,
        key=lambda row: (
            row.source.surface_id,
            row.source.vertex_index,
            row.after_world,
        ),
    ))


__all__ = ["SnapProposal", "SnapVertex", "build_snap_proposals"]
