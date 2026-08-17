"""Topology-constrained reconstruction of self-intersecting surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Iterable, Mapping, Sequence

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import CandidateEvidence, RepairCandidate, RepairOperation
from idfrepair.io.idf import canonical
from idfrepair.knowledge.geometry_graph import (
    GeometryEvidenceGraph,
    Point3D,
    SurfaceNode,
    build_geometry_graph,
    dot,
    magnitude,
    point_distance,
    polygon_centroid,
    polygon_normal,
)
from idfrepair.validation.geometry import validate_geometry_candidate, validate_polygon


def _canonical_cycle(order: tuple[int, ...]) -> tuple[int, ...]:
    return min(order[index:] + order[:index] for index in range(len(order)))


def _canonical_unoriented_cycle(order: tuple[int, ...]) -> tuple[int, ...]:
    return min(_canonical_cycle(order), _canonical_cycle(tuple(reversed(order))))


def _anchor_first(order: Sequence[int]) -> tuple[int, ...] | None:
    matches = [index for index, value in enumerate(order) if value == 0]
    if len(matches) != 1:
        return None
    offset = matches[0]
    values = tuple(order)
    return values[offset:] + values[:offset]


def unique_untangled_ring(
    points: Sequence[Point3D],
) -> tuple[int, ...] | None:
    """Return the sole simple polygon ring, modulo start and winding."""

    if not 4 <= len(points) <= 8:
        return None
    solutions: dict[tuple[int, ...], tuple[int, ...]] = {}
    for order in permutations(range(len(points))):
        proposed = tuple(points[index] for index in order)
        passed, _ = validate_polygon(proposed)
        if not passed:
            continue
        key = _canonical_unoriented_cycle(order)
        solutions.setdefault(key, order)
        if len(solutions) > 1:
            return None
    if len(solutions) != 1:
        return None
    return next(iter(solutions.values()))


def _candidate_edge_support(
    graph: GeometryEvidenceGraph,
    target: SurfaceNode,
    points: Sequence[Point3D],
) -> tuple[int, tuple[str, ...]]:
    metrics = graph.topology_metrics(
        target.zone_name,
        overrides={target.surface_id: tuple(points)},
        target_surface_id=target.surface_id,
    )
    return metrics.shared_edge_count, metrics.supporting_surface_ids


def _orient_from_pair(
    graph: GeometryEvidenceGraph,
    target: SurfaceNode,
    order: Sequence[int],
) -> tuple[tuple[int, ...], str, tuple[str, ...]] | None:
    pair = graph.paired_surface(target.surface_id)
    if pair is None or not pair.valid or pair.normal is None:
        return None
    direct = tuple(order)
    reverse = tuple(reversed(order))
    direct_normal = polygon_normal(tuple(target.world_vertices[index] for index in direct))
    reverse_normal = polygon_normal(tuple(target.world_vertices[index] for index in reverse))
    if direct_normal is None or reverse_normal is None:
        return None
    direct_dot = dot(direct_normal, pair.normal)
    reverse_dot = dot(reverse_normal, pair.normal)
    if min(direct_dot, reverse_dot) > -1.0 + 1e-7 or abs(direct_dot - reverse_dot) <= 1e-12:
        return None
    selected = direct if direct_dot < reverse_dot else reverse
    anchored = _anchor_first(selected)
    if anchored is None:
        return None
    return anchored, "reciprocal_boundary_surface", (pair.surface_id,)


def _orient_from_zone(
    graph: GeometryEvidenceGraph,
    target: SurfaceNode,
    order: Sequence[int],
) -> tuple[tuple[int, ...], str, tuple[str, ...]] | None:
    reference = graph.zone_reference(target.zone_name, exclude_surface_id=target.surface_id)
    if reference is None:
        return None
    center, support = reference
    direct = tuple(order)
    reverse = tuple(reversed(order))

    def projection(value: tuple[int, ...]) -> float | None:
        points = tuple(target.world_vertices[index] for index in value)
        normal = polygon_normal(points)
        if normal is None:
            return None
        centroid = polygon_centroid(points)
        outward = tuple(centroid[axis] - center[axis] for axis in range(3))
        scale = max(magnitude(outward), 1.0)
        result = dot(normal, outward)
        return result if abs(result) > 1e-8 * scale else None

    direct_projection = projection(direct)
    reverse_projection = projection(reverse)
    if direct_projection is None or reverse_projection is None:
        return None
    selected = direct if direct_projection > reverse_projection else reverse
    if max(direct_projection, reverse_projection) <= 0.0:
        return None
    anchored = _anchor_first(selected)
    if anchored is None:
        return None
    return anchored, "same_zone_trusted_surface_centroid", support


@dataclass(frozen=True, slots=True)
class GeometryReconstructionProposal:
    surface_id: str
    order: tuple[int, ...]
    orientation_mechanism: str
    independent_support_surface_ids: tuple[str, ...]
    before_open_edges: int
    after_open_edges: int
    before_shared_edges: int
    after_shared_edges: int
    strict_zone_closure_improvement: bool
    automatic_eligible: bool
    reasons: tuple[str, ...] = ()


def reconstruct_surface(
    graph: GeometryEvidenceGraph,
    target: SurfaceNode,
) -> GeometryReconstructionProposal | None:
    """Prove one ring, one winding, and a non-regressing zone topology."""

    if target.duplicate_vertices or not target.self_intersecting:
        return None
    order = unique_untangled_ring(target.world_vertices)
    if order is None:
        return None
    pair_orientation = _orient_from_pair(graph, target, order)
    zone_orientation = _orient_from_zone(graph, target, order)
    if pair_orientation is not None and zone_orientation is not None:
        if pair_orientation[0] != zone_orientation[0]:
            return GeometryReconstructionProposal(
                surface_id=target.surface_id,
                order=_anchor_first(order) or tuple(order),
                orientation_mechanism="conflicting_pair_and_zone_evidence",
                independent_support_surface_ids=tuple(sorted(set(pair_orientation[2]) | set(zone_orientation[2]))),
                before_open_edges=0,
                after_open_edges=0,
                before_shared_edges=0,
                after_shared_edges=0,
                strict_zone_closure_improvement=False,
                automatic_eligible=False,
                reasons=("orientation_evidence_conflict",),
            )
        oriented = (
            pair_orientation[0],
            "paired_and_zone_consensus",
            tuple(sorted(set(pair_orientation[2]) | set(zone_orientation[2]))),
        )
    else:
        oriented = pair_orientation or zone_orientation
    if oriented is None:
        return GeometryReconstructionProposal(
            surface_id=target.surface_id,
            order=_anchor_first(order) or tuple(order),
            orientation_mechanism="unproved",
            independent_support_surface_ids=(),
            before_open_edges=0,
            after_open_edges=0,
            before_shared_edges=0,
            after_shared_edges=0,
            strict_zone_closure_improvement=False,
            automatic_eligible=False,
            reasons=("orientation_evidence_missing",),
        )
    selected, mechanism, orientation_support = oriented
    proposed = tuple(target.world_vertices[index] for index in selected)
    before = graph.topology_metrics(target.zone_name, target_surface_id=target.surface_id)
    after = graph.topology_metrics(
        target.zone_name,
        overrides={target.surface_id: proposed},
        target_surface_id=target.surface_id,
    )
    support = tuple(sorted(set(orientation_support) | set(after.supporting_surface_ids)))
    nondegrading = bool(
        after.open_edge_count <= before.open_edge_count
        and after.nonmanifold_edge_count <= before.nonmanifold_edge_count
        and after.degenerate_edge_count <= before.degenerate_edge_count
    )
    strict = bool(
        nondegrading
        and (
            after.open_edge_count < before.open_edge_count
            or after.shared_edge_count > before.shared_edge_count
            or after.degenerate_edge_count < before.degenerate_edge_count
        )
    )
    reasons: list[str] = []
    if not strict:
        reasons.append("zone_closure_not_strictly_improved")
    if len(support) < 2:
        reasons.append("independent_support_surface_count_below_two")
    return GeometryReconstructionProposal(
        surface_id=target.surface_id,
        order=selected,
        orientation_mechanism=mechanism,
        independent_support_surface_ids=support,
        before_open_edges=before.open_edge_count,
        after_open_edges=after.open_edge_count,
        before_shared_edges=before.shared_edge_count,
        after_shared_edges=after.shared_edge_count,
        strict_zone_closure_improvement=strict,
        automatic_eligible=not reasons,
        reasons=tuple(reasons),
    )


@dataclass(frozen=True, slots=True)
class FourPointEvidence:
    point: Point3D
    source: str
    source_identity: str


@dataclass(frozen=True, slots=True)
class FourPointProposal:
    missing_index: int
    point: Point3D
    sources: tuple[str, ...]
    unique: bool
    requires_user_confirmation: bool


def _parallelogram_point(known: Mapping[int, Point3D], missing_index: int) -> Point3D | None:
    if set(known) != ({0, 1, 2, 3} - {missing_index}):
        return None
    previous = known[(missing_index - 1) % 4]
    following = known[(missing_index + 1) % 4]
    opposite = known[(missing_index + 2) % 4]
    return tuple(previous[axis] + following[axis] - opposite[axis] for axis in range(3))  # type: ignore[return-value]


def finite_four_point_reconstruction(
    *,
    known: Mapping[int, Point3D],
    missing_index: int,
    graph: GeometryEvidenceGraph,
    zone_name: str,
    paired_point: Point3D | None = None,
    shared_edge_points: Iterable[Point3D] = (),
    osm_reference_point: Point3D | None = None,
    osm_provenance_verified: bool = False,
) -> tuple[FourPointProposal, ...]:
    """Generate only evidence-bound fourth-point candidates.

    A parallelogram calculation is not accepted on its own.  It must coincide
    with an existing same-zone coordinate cluster or a separate paired/shared/
    provenance-bound OSM observation.
    """

    if missing_index not in range(4) or len(known) != 3:
        return ()
    evidence: list[FourPointEvidence] = []
    if paired_point is not None:
        evidence.append(FourPointEvidence(paired_point, "paired_surface_corresponding_point", "pair"))
    for index, point in enumerate(shared_edge_points):
        evidence.append(FourPointEvidence(point, "adjacent_shared_edge_intersection", f"shared:{index}"))
    if osm_reference_point is not None and osm_provenance_verified:
        evidence.append(FourPointEvidence(osm_reference_point, "provenance_bound_osm_reference", "osm"))
    computed = _parallelogram_point(known, missing_index)
    if computed is not None:
        clusters = graph.matching_clusters(computed, zone_name=zone_name)
        if len(clusters) == 1 and len(set(clusters[0].surface_ids)) >= 2:
            evidence.append(FourPointEvidence(
                clusters[0].representative,
                "parallelogram_and_same_zone_cluster",
                clusters[0].cluster_id,
            ))
    grouped: list[tuple[Point3D, list[FourPointEvidence]]] = []
    for row in evidence:
        matches = [index for index, (point, _) in enumerate(grouped) if graph.tolerance.point_close(point, row.point)]
        if len(matches) == 1:
            grouped[matches[0]][1].append(row)
        elif not matches:
            grouped.append((row.point, [row]))
    proposals: list[FourPointProposal] = []
    unique = len(grouped) == 1
    for point, rows in grouped:
        source_names = tuple(sorted({row.source for row in rows}))
        proposals.append(FourPointProposal(
            missing_index=missing_index,
            point=point,
            sources=source_names,
            unique=unique,
            requires_user_confirmation=not unique,
        ))
    return tuple(sorted(proposals, key=lambda row: (row.point, row.sources)))


def _target_surfaces(
    root,  # type: ignore[no-untyped-def]
    context: CandidateContext,
    graph: GeometryEvidenceGraph,
) -> tuple[SurfaceNode, ...]:
    if root.object_name:
        named = graph.surfaces_by_name(root.object_name)
        return named if len(named) == 1 else ()
    explicit: list[SurfaceNode] = []
    # Search only the causal root message.  The complete ERR may mention many
    # downstream surfaces and is not a safe target-localization scope.
    text = root.message
    for surface in graph.surfaces.values():
        if surface.object_name and canonical(surface.object_name) in canonical(text):
            explicit.append(surface)
    unique_explicit = {surface.surface_id: surface for surface in explicit}
    if len(unique_explicit) == 1:
        return tuple(unique_explicit.values())
    if unique_explicit:
        return ()
    invalid = [
        surface for surface in graph.surfaces.values()
        if surface.self_intersecting and not surface.duplicate_vertices
    ]
    return tuple(invalid) if len(invalid) == 1 else ()


def _replacement_operation(
    context: CandidateContext,
    surface: SurfaceNode,
    proposal: GeometryReconstructionProposal,
) -> RepairOperation:
    obj = context.document.objects[surface.object_index]
    replacement = obj.raw
    flattened = [
        token
        for vertex_index in proposal.order
        for token in surface.coordinate_tokens[vertex_index]
    ]
    fields = [
        obj.fields[index - 1]
        for triplet in surface.coordinate_field_indices
        for index in triplet
    ]
    for field, value in zip(reversed(fields), reversed(flattened), strict=True):
        left = field.start - obj.start
        right = field.end - obj.start
        replacement = replacement[:left] + value + replacement[right:]
    return RepairOperation(
        kind=OperationKind.REPLACE_VERTICES,
        object_type=obj.object_type,
        object_name=obj.name or None,
        object_index=obj.index,
        old_value=obj.raw,
        object_text=replacement,
        vertices=tuple(surface.local_vertices[index] for index in proposal.order),
        metadata={
            "surface_id": surface.surface_id,
            "first_coordinate_field": surface.coordinate_field_indices[0][0],
            "order": proposal.order,
        },
    )


class GeometryReconstructProvider(CandidateProvider):
    """Safe-auto provider gated by graph, orientation, and closure evidence."""

    name = "geometry_graph_reconstruct"
    families = frozenset({"geometry"})

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        graph = build_geometry_graph(context.document, context.idd)
        rows: list[RepairCandidate] = []
        for surface in _target_surfaces(root, context, graph):
            proposal = reconstruct_surface(graph, surface)
            if proposal is None or not proposal.automatic_eligible:
                continue
            operation = _replacement_operation(context, surface, proposal)
            metadata = {
                "mechanism": "unique_ring_graph_reconstruction",
                "automatic_policy": "qualified_graph_invariants",
                "surface_id": surface.surface_id,
                "orientation_mechanism": proposal.orientation_mechanism,
                "zone_closure_policy": "strict_improvement",
                "minimum_independent_support_surfaces": 2,
                "independent_support_surface_ids": proposal.independent_support_surface_ids,
                "before_open_edges": proposal.before_open_edges,
                "after_open_edges": proposal.after_open_edges,
                "before_shared_edges": proposal.before_shared_edges,
                "after_shared_edges": proposal.after_shared_edges,
            }
            identity = candidate_identity(
                provider=self.name,
                root_id=root.root_id,
                input_sha256=context.input_sha256,
                operations=(operation,),
            )
            rows.append(RepairCandidate(
                candidate_id=identity,
                provider=self.name,
                root_id=root.root_id,
                family="geometry",
                operations=(operation,),
                evidence=(
                    CandidateEvidence(
                        kind="unique_cyclic_reverse_geometry_solution",
                        source="geometry_evidence_graph",
                        strength=1.0,
                        details={"order": proposal.order},
                    ),
                    CandidateEvidence(
                        kind="zone_closure_improvement",
                        source="geometry_evidence_graph",
                        strength=1.0,
                        details={
                            "before_open_edges": proposal.before_open_edges,
                            "after_open_edges": proposal.after_open_edges,
                            "before_shared_edges": proposal.before_shared_edges,
                            "after_shared_edges": proposal.after_shared_edges,
                        },
                    ),
                    CandidateEvidence(
                        kind="outward_orientation_consensus",
                        source="geometry_evidence_graph",
                        strength=1.0,
                        details={
                            "mechanism": proposal.orientation_mechanism,
                            "support_surface_ids": proposal.independent_support_surface_ids,
                        },
                    ),
                ),
                risk=RiskLevel.LOW,
                confidence=0.99,
                input_sha256=context.input_sha256,
                idd_sha256=context.idd_sha256,
                version=context.version,
                requires_user_confirmation=False,
                metadata=metadata,
            ))
        return tuple(rows) if len(rows) <= 1 else ()

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        report = validate_geometry_candidate(before, after, candidate, context.idd)
        return report.passed, report.reasons, report.details


__all__ = [
    "FourPointEvidence",
    "FourPointProposal",
    "GeometryReconstructProvider",
    "GeometryReconstructionProposal",
    "finite_four_point_reconstruction",
    "reconstruct_surface",
    "unique_untangled_ring",
]
