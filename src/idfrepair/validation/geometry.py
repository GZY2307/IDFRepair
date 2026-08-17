"""Independent semantic checks for geometry repair candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from idfrepair.domain.models import RepairCandidate
from idfrepair.io.idf import canonical, parse_idf
from idfrepair.knowledge.geometry_graph import (
    GeometryEvidenceGraph,
    GeometryTolerance,
    Point3D,
    SurfaceNode,
    build_geometry_graph,
    dot,
    magnitude,
    points_coplanar,
    polygon_area,
    polygon_centroid,
    polygon_normal,
    polygon_self_intersects,
)
from idfrepair.knowledge.idd import IDDSchema


def _unique_matching(
    left: Sequence[Point3D],
    right: Sequence[Point3D],
    tolerance: GeometryTolerance,
) -> tuple[int, ...] | None:
    if len(left) != len(right):
        return None
    available = set(range(len(right)))
    result: list[int] = []
    for point in left:
        matches = [index for index in available if tolerance.point_close(point, right[index])]
        if len(matches) != 1:
            return None
        selected = matches[0]
        available.remove(selected)
        result.append(selected)
    return tuple(result) if not available else None


def cyclic_equivalent(
    left: Sequence[Point3D],
    right: Sequence[Point3D],
    *,
    tolerance: GeometryTolerance | None = None,
    allow_reverse: bool = False,
) -> bool:
    """Compare polygon cycles without treating the start vertex as semantic."""

    tolerance = tolerance or GeometryTolerance()
    if len(left) != len(right) or not left:
        return False
    count = len(left)
    for reverse in (False, True) if allow_reverse else (False,):
        candidate = tuple(reversed(right)) if reverse else tuple(right)
        for offset in range(count):
            rotated = candidate[offset:] + candidate[:offset]
            if all(tolerance.point_close(first, second) for first, second in zip(left, rotated, strict=True)):
                return True
    return False


def orientation_correct(
    surface: SurfaceNode,
    *,
    reference_point: Point3D | None = None,
    paired_surface: SurfaceNode | None = None,
    minimum_projection: float = 1e-8,
) -> bool:
    if surface.normal is None:
        return False
    if paired_surface is not None:
        return bool(
            paired_surface.normal is not None
            and dot(surface.normal, paired_surface.normal) <= -1.0 + 1e-7
        )
    if reference_point is None:
        return False
    outward = tuple(surface.centroid[axis] - reference_point[axis] for axis in range(3))
    scale = max(magnitude(outward), 1.0)
    return dot(surface.normal, outward) > minimum_projection * scale


def shared_boundary_correct(
    before_graph: GeometryEvidenceGraph,
    after_graph: GeometryEvidenceGraph,
    target_before: SurfaceNode,
    target_after: SurfaceNode,
) -> bool:
    """Require every previously shared, nondegenerate edge to remain shared."""

    before_relations = {
        relation.cluster_pair
        for relation in before_graph.shared_edge_relations
        if target_before.surface_id in relation.surface_ids
    }
    after_relations = {
        relation.cluster_pair
        for relation in after_graph.shared_edge_relations
        if target_after.surface_id in relation.surface_ids
    }
    return before_relations <= after_relations


@dataclass(frozen=True, slots=True)
class GeometryValidationReport:
    passed: bool
    reasons: tuple[str, ...]
    details: Mapping[str, object]


def _unchanged_other_objects(before: str, after: str, target_index: int) -> bool:
    left = parse_idf(before)
    right = parse_idf(after)
    if len(left.objects) != len(right.objects):
        return False
    for old, new in zip(left.objects, right.objects, strict=True):
        if old.index == target_index:
            continue
        if old.raw != new.raw:
            return False
    return True


def validate_geometry_candidate(
    before: str,
    after: str,
    candidate: RepairCandidate,
    idd: IDDSchema,
) -> GeometryValidationReport:
    """Recompute every claimed invariant from candidate output bytes."""

    reasons: list[str] = []
    if len(candidate.operations) != 1:
        return GeometryValidationReport(False, ("geometry_requires_one_operation",), {})
    operation = candidate.operations[0]
    if operation.object_index is None:
        return GeometryValidationReport(False, ("geometry_target_index_missing",), {})
    before_graph = build_geometry_graph(parse_idf(before), idd)
    after_graph = build_geometry_graph(parse_idf(after), idd, tolerance=before_graph.tolerance)
    target_id = str(operation.metadata.get("surface_id") or f"surface:{operation.object_index:08d}")
    target_before = before_graph.surface_by_id(target_id)
    target_after = after_graph.surface_by_id(target_id)
    if target_before is None or target_after is None:
        return GeometryValidationReport(False, ("geometry_target_not_resolved",), {"surface_id": target_id})
    if canonical(target_before.object_type) != canonical(target_after.object_type):
        reasons.append("geometry_target_type_changed")
    if canonical(target_before.object_name) != canonical(target_after.object_name):
        reasons.append("geometry_target_name_changed")
    if not _unchanged_other_objects(before, after, operation.object_index):
        reasons.append("geometry_non_target_object_changed")
    vertex_mapping = _unique_matching(
        target_after.world_vertices,
        target_before.world_vertices,
        before_graph.tolerance,
    )
    if vertex_mapping is None:
        reasons.append("geometry_vertex_multiset_changed")
    if not target_after.legal_vertex_count:
        reasons.append("geometry_illegal_vertex_count")
    if target_after.duplicate_vertices:
        reasons.append("geometry_duplicate_vertices")
    if target_after.self_intersecting:
        reasons.append("geometry_self_intersection_remains")
    if not target_after.coplanar:
        reasons.append("geometry_not_coplanar")
    if target_after.area <= 1e-10 or target_after.normal is None:
        reasons.append("geometry_degenerate_area")
    if not shared_boundary_correct(before_graph, after_graph, target_before, target_after):
        reasons.append("geometry_shared_boundary_lost")

    orientation_mechanism = str(candidate.metadata.get("orientation_mechanism") or "")
    orientation_passed = False
    orientation_support: tuple[str, ...] = ()
    if orientation_mechanism == "reciprocal_boundary_surface":
        pair = after_graph.paired_surface(target_after.surface_id)
        orientation_passed = pair is not None and orientation_correct(target_after, paired_surface=pair)
        if pair is not None:
            orientation_support = (pair.surface_id,)
    elif orientation_mechanism == "same_zone_trusted_surface_centroid":
        reference = after_graph.zone_reference(
            target_after.zone_name,
            exclude_surface_id=target_after.surface_id,
        )
        if reference is not None:
            orientation_passed = orientation_correct(target_after, reference_point=reference[0])
            orientation_support = reference[1]
    elif orientation_mechanism == "paired_and_zone_consensus":
        pair = after_graph.paired_surface(target_after.surface_id)
        reference = after_graph.zone_reference(
            target_after.zone_name,
            exclude_surface_id=target_after.surface_id,
        )
        pair_passed = pair is not None and orientation_correct(target_after, paired_surface=pair)
        zone_passed = reference is not None and orientation_correct(target_after, reference_point=reference[0])
        orientation_passed = pair_passed and zone_passed
        orientation_support = tuple(
            sorted(({pair.surface_id} if pair else set()) | (set(reference[1]) if reference else set()))
        )
    if not orientation_passed:
        reasons.append("geometry_orientation_unproved")

    before_metrics = before_graph.topology_metrics(
        target_before.zone_name,
        target_surface_id=target_before.surface_id,
    )
    after_metrics = after_graph.topology_metrics(
        target_after.zone_name,
        target_surface_id=target_after.surface_id,
    )
    closure_policy = str(candidate.metadata.get("zone_closure_policy") or "nondegrading")
    closure_passed = bool(
        after_metrics.open_edge_count <= before_metrics.open_edge_count
        and after_metrics.nonmanifold_edge_count <= before_metrics.nonmanifold_edge_count
        and after_metrics.degenerate_edge_count <= before_metrics.degenerate_edge_count
    )
    if closure_policy == "strict_improvement":
        closure_passed = closure_passed and (
            after_metrics.open_edge_count < before_metrics.open_edge_count
            or after_metrics.degenerate_edge_count < before_metrics.degenerate_edge_count
            or after_metrics.shared_edge_count > before_metrics.shared_edge_count
        )
    if not closure_passed:
        reasons.append("geometry_zone_closure_not_improved")

    pair_consistent = True
    relation = after_graph.paired_relation(target_after.surface_id)
    if relation is not None and relation.reciprocal:
        pair_consistent = bool(
            relation.same_vertex_set
            and relation.opposite_normals
            and relation.equal_area
            and relation.same_edge_set
        )
        if not pair_consistent:
            reasons.append("geometry_pair_inconsistent")

    minimum_support = int(candidate.metadata.get("minimum_independent_support_surfaces", 2))
    evidence_support = set(orientation_support) | set(after_metrics.supporting_surface_ids)
    if len(evidence_support) < minimum_support:
        reasons.append("geometry_independent_support_insufficient")

    details: dict[str, object] = {
        "surface_id": target_id,
        "vertex_count": len(target_after.world_vertices),
        "vertex_multiset_preserved": vertex_mapping is not None,
        "cyclic_equivalent_unoriented": cyclic_equivalent(
            target_before.world_vertices,
            target_after.world_vertices,
            tolerance=before_graph.tolerance,
            allow_reverse=True,
        ),
        "orientation_correct": orientation_passed,
        "orientation_mechanism": orientation_mechanism,
        "independent_support_surface_ids": sorted(evidence_support),
        "minimum_independent_support_surfaces": minimum_support,
        "shared_boundary_correct": shared_boundary_correct(
            before_graph, after_graph, target_before, target_after,
        ),
        "pair_consistent": pair_consistent,
        "before_open_edges": before_metrics.open_edge_count,
        "after_open_edges": after_metrics.open_edge_count,
        "before_shared_edges": before_metrics.shared_edge_count,
        "after_shared_edges": after_metrics.shared_edge_count,
        "zone_closure_policy": closure_policy,
        "other_objects_unchanged": _unchanged_other_objects(before, after, operation.object_index),
    }
    return GeometryValidationReport(not reasons, tuple(reasons), details)


def validate_polygon(
    points: Sequence[Point3D],
    *,
    tolerance: GeometryTolerance | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Small reusable polygon gate used by geometry providers."""

    tolerance = tolerance or GeometryTolerance()
    reasons = []
    if not 3 <= len(points) <= 120:
        reasons.append("illegal_vertex_count")
    if _unique_matching(points, points, tolerance) is None:
        reasons.append("ambiguous_or_duplicate_vertices")
    if not points_coplanar(points, tolerance):
        reasons.append("not_coplanar")
    if polygon_area(points) <= 1e-10 or polygon_normal(points) is None:
        reasons.append("degenerate_area")
    if polygon_self_intersects(points, tolerance):
        reasons.append("self_intersection")
    return not reasons, tuple(reasons)


__all__ = [
    "GeometryValidationReport",
    "cyclic_equivalent",
    "orientation_correct",
    "shared_boundary_correct",
    "validate_geometry_candidate",
    "validate_polygon",
]
