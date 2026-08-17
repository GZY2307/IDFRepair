"""Reciprocal Surface boundary alignment and weaker-side reconstruction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from idfrepair.knowledge.geometry_graph import (
    GeometryEvidenceGraph,
    Point3D,
    SurfaceNode,
    dot,
    polygon_area,
    polygon_normal,
)
from idfrepair.validation.geometry import cyclic_equivalent, validate_polygon


@dataclass(frozen=True, slots=True)
class SurfacePairAlignment:
    left_surface_id: str
    right_surface_id: str
    reciprocal_unique: bool
    vertex_correspondence: tuple[int, ...] | None
    cyclic_shift: int | None
    opposite_winding: bool
    coordinates_equal: bool
    normals_opposite: bool
    areas_equal: bool
    edge_sets_equal: bool
    valid: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SurfacePairRepairProposal:
    target_surface_id: str
    source_surface_id: str
    proposed_world_vertices: tuple[Point3D, ...]
    proposed_local_vertices: tuple[Point3D, ...]
    source_order: tuple[int, ...]
    weaker_side_unique: bool
    requires_user_confirmation: bool
    reasons: tuple[str, ...]


def _cycle_alignment(
    left: Sequence[Point3D],
    right: Sequence[Point3D],
    graph: GeometryEvidenceGraph,
) -> tuple[tuple[int, ...], int, bool] | None:
    if len(left) != len(right) or not left:
        return None
    count = len(left)
    matches: list[tuple[tuple[int, ...], int, bool]] = []
    for reverse in (False, True):
        indexes = tuple(reversed(range(count))) if reverse else tuple(range(count))
        candidate = tuple(right[index] for index in indexes)
        for shift in range(count):
            order = indexes[shift:] + indexes[:shift]
            shifted = tuple(right[index] for index in order)
            if all(graph.tolerance.point_close(first, second) for first, second in zip(left, shifted, strict=True)):
                matches.append((order, shift, reverse))
    unique = {(row[0], row[2]): row for row in matches}
    if len(unique) != 1:
        return None
    return next(iter(unique.values()))


def inspect_surface_pair(
    graph: GeometryEvidenceGraph,
    left: SurfaceNode,
    right: SurfaceNode,
) -> SurfacePairAlignment:
    relation = graph.paired_relation(left.surface_id)
    reciprocal_unique = bool(
        relation is not None
        and right.surface_id in {relation.left_surface_id, relation.right_surface_id}
        and relation.reciprocal
    )
    alignment = _cycle_alignment(left.world_vertices, right.world_vertices, graph)
    coordinates_equal = alignment is not None
    normal_left = polygon_normal(left.world_vertices)
    normal_right = polygon_normal(right.world_vertices)
    normals_opposite = bool(
        normal_left is not None
        and normal_right is not None
        and dot(normal_left, normal_right) <= -1.0 + 1e-7
    )
    area_left = polygon_area(left.world_vertices)
    area_right = polygon_area(right.world_vertices)
    area_scale = max(area_left, area_right, 1.0)
    areas_equal = bool(
        abs(area_left - area_right) <= graph.tolerance.absolute
        and abs(area_left - area_right) <= graph.tolerance.relative * area_scale
    )
    edge_sets_equal = left.edge_set == right.edge_set
    reasons: list[str] = []
    if not reciprocal_unique:
        reasons.append("paired_surface_reference_not_unique_reciprocal")
    if not coordinates_equal:
        reasons.append("paired_surface_vertex_correspondence_not_unique")
    if not normals_opposite:
        reasons.append("paired_surface_normals_not_opposite")
    if not areas_equal:
        reasons.append("paired_surface_area_mismatch")
    if not edge_sets_equal:
        reasons.append("paired_surface_edge_set_mismatch")
    return SurfacePairAlignment(
        left_surface_id=left.surface_id,
        right_surface_id=right.surface_id,
        reciprocal_unique=reciprocal_unique,
        vertex_correspondence=alignment[0] if alignment else None,
        cyclic_shift=alignment[1] if alignment else None,
        opposite_winding=alignment[2] if alignment else False,
        coordinates_equal=coordinates_equal,
        normals_opposite=normals_opposite,
        areas_equal=areas_equal,
        edge_sets_equal=edge_sets_equal,
        valid=not reasons,
        reasons=tuple(reasons),
    )


def _surface_strength(graph: GeometryEvidenceGraph, surface: SurfaceNode) -> tuple[int, int, int, int, int]:
    metrics = graph.topology_metrics(
        surface.zone_name,
        target_surface_id=surface.surface_id,
    ) if surface.zone_name else None
    return (
        int(surface.valid),
        int(surface.coplanar),
        int(not surface.duplicate_vertices and not surface.self_intersecting),
        metrics.shared_edge_count if metrics else 0,
        -metrics.open_edge_count if metrics else 0,
    )


def repair_weaker_paired_surface(
    graph: GeometryEvidenceGraph,
    target: SurfaceNode,
) -> SurfacePairRepairProposal | None:
    """Copy reversed counterpart geometry only when one side is strictly weaker."""

    relation = graph.paired_relation(target.surface_id)
    source = graph.paired_surface(target.surface_id)
    if relation is None or source is None or not relation.reciprocal:
        return None
    target_strength = _surface_strength(graph, target)
    source_strength = _surface_strength(graph, source)
    if source_strength <= target_strength or not source.valid:
        return None
    reversed_indexes = tuple(reversed(range(len(source.world_vertices))))
    reversed_world = tuple(source.world_vertices[index] for index in reversed_indexes)
    # Preserve the target's first still-observed vertex as a textual cycle
    # anchor.  Absence or ambiguity means interactive review is required.
    anchors = [
        index for index, point in enumerate(reversed_world)
        if graph.tolerance.point_close(point, target.world_vertices[0])
    ] if target.world_vertices else []
    if len(anchors) != 1:
        return SurfacePairRepairProposal(
            target_surface_id=target.surface_id,
            source_surface_id=source.surface_id,
            proposed_world_vertices=reversed_world,
            proposed_local_vertices=(),
            source_order=reversed_indexes,
            weaker_side_unique=True,
            requires_user_confirmation=True,
            reasons=("faulty_first_vertex_pair_anchor_not_unique",),
        )
    offset = anchors[0]
    order = reversed_indexes[offset:] + reversed_indexes[:offset]
    proposed_world = tuple(source.world_vertices[index] for index in order)
    proposed_local: list[Point3D] = []
    for point in proposed_world:
        local = graph.point_to_local(point, target.zone_name)
        if local is None:
            return SurfacePairRepairProposal(
                target_surface_id=target.surface_id,
                source_surface_id=source.surface_id,
                proposed_world_vertices=proposed_world,
                proposed_local_vertices=(),
                source_order=order,
                weaker_side_unique=True,
                requires_user_confirmation=True,
                reasons=("target_coordinate_frame_unresolved",),
            )
        proposed_local.append(local)
    valid, reasons = validate_polygon(proposed_world, tolerance=graph.tolerance)
    normal = polygon_normal(proposed_world)
    source_normal = polygon_normal(source.world_vertices)
    pair_invariants = bool(
        valid
        and normal is not None
        and source_normal is not None
        and dot(normal, source_normal) <= -1.0 + 1e-7
        and cyclic_equivalent(
            proposed_world,
            source.world_vertices,
            tolerance=graph.tolerance,
            allow_reverse=True,
        )
    )
    final_reasons = list(reasons)
    if not pair_invariants:
        final_reasons.append("paired_surface_invariants_not_restored")
    return SurfacePairRepairProposal(
        target_surface_id=target.surface_id,
        source_surface_id=source.surface_id,
        proposed_world_vertices=proposed_world,
        proposed_local_vertices=tuple(proposed_local),
        source_order=order,
        weaker_side_unique=True,
        requires_user_confirmation=bool(final_reasons),
        reasons=tuple(final_reasons),
    )


__all__ = [
    "SurfacePairAlignment",
    "SurfacePairRepairProposal",
    "inspect_surface_pair",
    "repair_weaker_paired_surface",
]
