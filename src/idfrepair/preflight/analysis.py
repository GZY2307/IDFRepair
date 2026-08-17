"""One-pass geometry metadata and spatial indexes for model analysis."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import product
from math import ceil, floor
from statistics import median
from types import MappingProxyType
from typing import Any, Iterator, Mapping

from idfrepair.io.idf import IDFDocument, IDFObject, canonical, parse_idf
from idfrepair.knowledge.geometry_graph import (
    ClusterEdge,
    GeometryEvidenceGraph,
    Point3D,
    SurfaceNode,
    build_geometry_graph,
    dot,
)
from idfrepair.knowledge.idd import IDDSchema, parse_idd


Cell3D = tuple[int, int, int]
PlaneBucket = tuple[int, int, int, int]
_NORMAL_DOT_MIN = 0.999
_NORMAL_QUANTUM = 0.05
_NORMAL_DIFFERENCE_LIMIT = (2.0 * (1.0 - _NORMAL_DOT_MIN)) ** 0.5
_SUBSURFACE_OBJECT_TYPES = frozenset({
    "door",
    "door:interzone",
    "fenestrationsurface:detailed",
    "glazeddoor",
    "glazeddoor:interzone",
    "window",
    "window:interzone",
})
_SUBSURFACE_PARENT_FIELDS = frozenset({
    "base surface name",
    "building surface name",
})


@dataclass(frozen=True, slots=True)
class TypedReverseReference:
    """One IDD-typed field that resolves to a named target object."""

    source_object_index: int
    source_object_type: str
    source_object_name: str
    field_index: int
    field_name: str
    role: str
    target_object_index: int


@dataclass(frozen=True, slots=True)
class SurfaceAABB:
    minimum: Point3D
    maximum: Point3D
    expanded_minimum: Point3D
    expanded_maximum: Point3D


@dataclass(frozen=True, slots=True)
class SurfacePlaneKey:
    normal: Point3D
    offset: float
    bucket: PlaneBucket


@dataclass(frozen=True, slots=True)
class IndexedVertex:
    surface_id: str
    object_index: int
    object_type: str
    object_name: str
    zone_name: str
    vertex_id: str
    vertex_index: int
    local_point: Point3D
    world_point: Point3D
    coordinate_field_indices: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class GeometryAnalysisContext:
    """Parsed model, graph, metadata, and immutable spatial indexes.

    The accepted snap tolerance is part of the context identity: vertex cells
    use exactly that value and downstream consumers reuse them without a
    second graph or object-map build.
    """

    document: IDFDocument
    idd: IDDSchema
    graph: GeometryEvidenceGraph
    tolerance_m: float
    objects_by_index: Mapping[int, IDFObject]
    surface_details: Mapping[str, Mapping[str, Any]]
    reverse_references: Mapping[int, tuple[TypedReverseReference, ...]]
    surface_plane_keys: Mapping[str, SurfacePlaneKey]
    surface_aabbs: Mapping[str, SurfaceAABB]
    plane_buckets: Mapping[PlaneBucket, tuple[str, ...]]
    plane_offset_quantum_m: float
    overlap_grid_size_m: float
    overlap_cells: Mapping[Cell3D, tuple[str, ...]]
    surface_overlap_cells: Mapping[str, tuple[Cell3D, ...]]
    vertex_cell_size_m: float
    vertex_cells: Mapping[Cell3D, tuple[IndexedVertex, ...]]
    observed_coordinates: Mapping[Point3D, tuple[IndexedVertex, ...]]
    surface_neighbors: Mapping[str, frozenset[str]]
    zone_z_bounds: Mapping[str, tuple[float, float]]
    surface_edge_pairs: Mapping[str, tuple[ClusterEdge | None, ...]]
    edge_surface_ids: Mapping[ClusterEdge, frozenset[str]]
    zone_edge_incidence: Mapping[str, Mapping[ClusterEdge, int]]

    @classmethod
    def from_text(
        cls,
        input_text: str,
        idd_text: str,
        *,
        tolerance_m: float = 0.05,
    ) -> "GeometryAnalysisContext":
        if not 1e-8 <= tolerance_m <= 0.05:
            raise ValueError("geometry_analysis_tolerance_out_of_bounds")
        document = parse_idf(input_text)
        idd = parse_idd(idd_text)
        graph = build_geometry_graph(document, idd)
        objects = {obj.index: obj for obj in document.objects}
        details = {
            surface.surface_id: _surface_details(surface, objects, idd)
            for surface in graph.surfaces.values()
        }
        reverse = _typed_reverse_references(document, idd, graph)
        aabbs = {
            surface.surface_id: _surface_aabb(surface, tolerance_m)
            for surface in graph.surfaces.values()
        }
        model_radius = max((
            sum(value * value for value in vertex.world_point) ** 0.5
            for vertex in graph.vertices.values()
        ), default=0.0)
        plane_offset_quantum = (
            tolerance_m + _NORMAL_DIFFERENCE_LIMIT * model_radius
        )
        plane_keys = {
            surface.surface_id: key
            for surface in graph.surfaces.values()
            if (key := _surface_plane_key(surface, plane_offset_quantum)) is not None
        }
        plane_buckets: dict[PlaneBucket, set[str]] = defaultdict(set)
        for surface_id, key in plane_keys.items():
            plane_buckets[key.bucket].add(surface_id)
            plane_buckets[_plane_bucket(
                tuple(-value for value in key.normal),
                -key.offset,
                plane_offset_quantum,
            )].add(surface_id)
        overlap_grid_size = _overlap_grid_size(tuple(aabbs.values()), tolerance_m)
        overlap_cells: dict[Cell3D, list[str]] = defaultdict(list)
        surface_overlap_cells: dict[str, tuple[Cell3D, ...]] = {}
        for surface_id, aabb in aabbs.items():
            cells = tuple(_aabb_cells(aabb, overlap_grid_size))
            surface_overlap_cells[surface_id] = cells
            for cell in cells:
                overlap_cells[cell].append(surface_id)

        indexed_vertices: list[IndexedVertex] = []
        for vertex in graph.vertices.values():
            surface = graph.surfaces[vertex.surface_id]
            indexed_vertices.append(IndexedVertex(
                surface_id=surface.surface_id,
                object_index=surface.object_index,
                object_type=surface.object_type,
                object_name=surface.object_name,
                zone_name=surface.zone_name,
                vertex_id=vertex.vertex_id,
                vertex_index=vertex.local_index,
                local_point=vertex.local_point,
                world_point=vertex.world_point,
                coordinate_field_indices=vertex.field_indices,
            ))
        indexed_vertices.sort(key=lambda row: (row.surface_id, row.vertex_index, row.vertex_id))
        vertex_cells: dict[Cell3D, list[IndexedVertex]] = defaultdict(list)
        observed: dict[Point3D, list[IndexedVertex]] = defaultdict(list)
        for vertex in indexed_vertices:
            vertex_cells[_point_cell(vertex.world_point, tolerance_m)].append(vertex)
            observed[vertex.world_point].append(vertex)

        neighbours: dict[str, set[str]] = defaultdict(set)
        for relation in graph.shared_vertex_edges:
            neighbours[relation.left_surface_id].add(relation.right_surface_id)
            neighbours[relation.right_surface_id].add(relation.left_surface_id)
        for relation in graph.paired_surface_edges:
            neighbours[relation.left_surface_id].add(relation.right_surface_id)
            neighbours[relation.right_surface_id].add(relation.left_surface_id)
        zone_points: dict[str, list[float]] = defaultdict(list)
        for zone_key, surface_ids in graph.surface_ids_by_zone.items():
            for surface_id in surface_ids:
                surface = graph.surfaces[surface_id]
                zone_points[zone_key].extend(
                    point[2] for point in surface.world_vertices
                )
        surface_edge_pairs = {
            surface_id: tuple(
                None if graph.edges[edge_id].degenerate else graph.edges[edge_id].cluster_pair
                for edge_id in surface.edge_ids
            )
            for surface_id, surface in graph.surfaces.items()
        }
        edge_surface_ids: dict[ClusterEdge, set[str]] = defaultdict(set)
        for surface_id, pairs in surface_edge_pairs.items():
            for pair in pairs:
                if pair is not None:
                    edge_surface_ids[pair].add(surface_id)
        zone_edge_incidence: dict[str, dict[ClusterEdge, int]] = {}
        for zone_key, surface_ids in graph.surface_ids_by_zone.items():
            counts: dict[ClusterEdge, int] = defaultdict(int)
            for surface_id in surface_ids:
                for pair in surface_edge_pairs[surface_id]:
                    if pair is not None:
                        counts[pair] += 1
            zone_edge_incidence[zone_key] = counts

        return cls(
            document=document,
            idd=idd,
            graph=graph,
            tolerance_m=float(tolerance_m),
            objects_by_index=MappingProxyType(objects),
            surface_details=MappingProxyType({
                key: MappingProxyType(value) for key, value in details.items()
            }),
            reverse_references=MappingProxyType({
                key: tuple(sorted(value, key=_reference_sort_key))
                for key, value in reverse.items()
            }),
            surface_plane_keys=MappingProxyType(plane_keys),
            surface_aabbs=MappingProxyType(aabbs),
            plane_buckets=MappingProxyType({
                key: tuple(sorted(value)) for key, value in plane_buckets.items()
            }),
            plane_offset_quantum_m=plane_offset_quantum,
            overlap_grid_size_m=overlap_grid_size,
            overlap_cells=MappingProxyType({
                key: tuple(sorted(value)) for key, value in overlap_cells.items()
            }),
            surface_overlap_cells=MappingProxyType(surface_overlap_cells),
            vertex_cell_size_m=float(tolerance_m),
            vertex_cells=MappingProxyType({key: tuple(value) for key, value in vertex_cells.items()}),
            observed_coordinates=MappingProxyType({key: tuple(value) for key, value in observed.items()}),
            surface_neighbors=MappingProxyType({
                surface_id: frozenset(neighbours.get(surface_id, ()))
                for surface_id in graph.surfaces
            }),
            zone_z_bounds=MappingProxyType({
                key: (min(values), max(values)) for key, values in zone_points.items()
            }),
            surface_edge_pairs=MappingProxyType(surface_edge_pairs),
            edge_surface_ids=MappingProxyType({
                key: frozenset(value) for key, value in edge_surface_ids.items()
            }),
            zone_edge_incidence=MappingProxyType({
                key: MappingProxyType(dict(value))
                for key, value in zone_edge_incidence.items()
            }),
        )

    build = from_text


def _field_by_name(
    obj: IDFObject,
    definition: Any,
    *parts: str,
    excludes: tuple[str, ...] = (),
) -> str:
    if definition is None:
        return ""
    wanted = tuple(canonical(part) for part in parts)
    rejected = tuple(canonical(part) for part in excludes)
    for field in definition.fields:
        name = canonical(field.name)
        if all(part in name for part in wanted) and not any(part in name for part in rejected):
            if field.index <= len(obj.fields):
                return obj.fields[field.index - 1].value.strip()
    return ""


def _surface_details(
    surface: SurfaceNode,
    objects: Mapping[int, IDFObject],
    idd: IDDSchema,
) -> dict[str, Any]:
    obj = objects[surface.object_index]
    definition = idd.get(obj.object_type)
    return {
        "surface_id": surface.surface_id,
        "stable_identity": surface.stable_identity,
        "object_index": surface.object_index,
        "object_type": surface.object_type,
        "name": surface.object_name,
        "zone": surface.zone_name,
        "space": surface.space_name,
        "surface_type": surface.surface_type,
        "construction": _field_by_name(obj, definition, "construction", "name"),
        "boundary_condition": surface.outside_boundary_condition,
        "boundary_object": surface.outside_boundary_object,
        "sun_exposure": _field_by_name(obj, definition, "sun", "exposure"),
        "wind_exposure": _field_by_name(obj, definition, "wind", "exposure"),
        "area": surface.area,
        "normal": list(surface.normal) if surface.normal is not None else None,
        "vertices": [list(point) for point in surface.world_vertices],
    }


def _typed_reverse_references(
    document: IDFDocument,
    idd: IDDSchema,
    graph: GeometryEvidenceGraph,
) -> dict[int, list[TypedReverseReference]]:
    by_name: dict[str, list[tuple[IDFObject, frozenset[str]]]] = defaultdict(list)
    all_by_name: dict[str, list[IDFObject]] = defaultdict(list)
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        name_field = definition.field_at(1) if definition is not None else None
        target_references = frozenset(
            canonical(value) for value in (name_field.references if name_field else ())
        )
        if obj.name:
            all_by_name[canonical(obj.name)].append(obj)
            if target_references:
                by_name[canonical(obj.name)].append((obj, target_references))
    base_surface_indices = {
        surface.object_index
        for surface in graph.surfaces.values()
        if surface.zone_name
        and canonical(surface.object_type) not in _SUBSURFACE_OBJECT_TYPES
    }
    rows: dict[int, list[TypedReverseReference]] = defaultdict(list)
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        for field in obj.fields:
            field_def = definition.field_at(field.index)
            if field_def is None or not field.value.strip():
                continue
            source_lists = frozenset(canonical(value) for value in field_def.object_lists)
            resolved_targets: set[int] = set()
            for target, target_references in by_name.get(canonical(field.value), ()):
                if not source_lists.intersection(target_references):
                    continue
                resolved_targets.add(target.index)
                rows[target.index].append(TypedReverseReference(
                    source_object_index=obj.index,
                    source_object_type=obj.object_type,
                    source_object_name=obj.name,
                    field_index=field.index,
                    field_name=field_def.name,
                    role=field_def.role,
                    target_object_index=target.index,
                ))
            if (
                canonical(obj.object_type) not in _SUBSURFACE_OBJECT_TYPES
                or canonical(field_def.name) not in _SUBSURFACE_PARENT_FIELDS
            ):
                continue
            for target in all_by_name.get(canonical(field.value), ()):
                if (
                    target.index in resolved_targets
                    or target.index not in base_surface_indices
                ):
                    continue
                rows[target.index].append(TypedReverseReference(
                    source_object_index=obj.index,
                    source_object_type=obj.object_type,
                    source_object_name=obj.name,
                    field_index=field.index,
                    field_name=field_def.name,
                    role="subsurface_parent_fallback",
                    target_object_index=target.index,
                ))
    return rows


def _reference_sort_key(row: TypedReverseReference) -> tuple[int, int, int]:
    return (row.target_object_index, row.source_object_index, row.field_index)


def _surface_aabb(surface: SurfaceNode, tolerance_m: float) -> SurfaceAABB:
    minimum = tuple(min(point[axis] for point in surface.world_vertices) for axis in range(3))
    maximum = tuple(max(point[axis] for point in surface.world_vertices) for axis in range(3))
    return SurfaceAABB(
        minimum=minimum,  # type: ignore[arg-type]
        maximum=maximum,  # type: ignore[arg-type]
        expanded_minimum=tuple(value - tolerance_m for value in minimum),  # type: ignore[arg-type]
        expanded_maximum=tuple(value + tolerance_m for value in maximum),  # type: ignore[arg-type]
    )


def _canonical_plane(surface: SurfaceNode) -> tuple[Point3D, float] | None:
    if surface.normal is None or not surface.world_vertices:
        return None
    normal = surface.normal
    dominant_axis = max(range(3), key=lambda axis: (abs(normal[axis]), -axis))
    sign = 1.0 if normal[dominant_axis] >= 0.0 else -1.0
    canonical_normal = tuple(sign * value for value in normal)
    offset = -dot(canonical_normal, surface.world_vertices[0])
    return canonical_normal, offset  # type: ignore[return-value]


def _plane_bucket(
    normal: Point3D,
    offset: float,
    offset_quantum_m: float,
) -> PlaneBucket:
    return (
        *(floor(value / _NORMAL_QUANTUM) for value in normal),
        floor(offset / offset_quantum_m),
    )


def _surface_plane_key(
    surface: SurfaceNode,
    offset_quantum_m: float,
) -> SurfacePlaneKey | None:
    plane = _canonical_plane(surface)
    if plane is None:
        return None
    normal, offset = plane
    bucket = _plane_bucket(normal, offset, offset_quantum_m)
    return SurfacePlaneKey(normal=normal, offset=offset, bucket=bucket)  # type: ignore[arg-type]


def _overlap_grid_size(aabbs: tuple[SurfaceAABB, ...], tolerance_m: float) -> float:
    spans = [
        max(aabb.maximum[axis] - aabb.minimum[axis] for axis in range(3))
        for aabb in aabbs
    ]
    positive = sorted(value for value in spans if value > tolerance_m)
    return max(tolerance_m, median(positive) if positive else tolerance_m)


def _aabb_cells(aabb: SurfaceAABB, cell_size: float) -> Iterator[Cell3D]:
    starts = tuple(floor(value / cell_size) for value in aabb.expanded_minimum)
    stops = tuple(floor(value / cell_size) for value in aabb.expanded_maximum)
    for x_value in range(starts[0], stops[0] + 1):
        for y_value in range(starts[1], stops[1] + 1):
            for z_value in range(starts[2], stops[2] + 1):
                yield (x_value, y_value, z_value)


def _point_cell(point: Point3D, cell_size: float) -> Cell3D:
    return tuple(floor(value / cell_size) for value in point)  # type: ignore[return-value]


def _aabbs_overlap(left: SurfaceAABB, right: SurfaceAABB) -> bool:
    return all(
        left.expanded_minimum[axis] <= right.expanded_maximum[axis]
        and right.expanded_minimum[axis] <= left.expanded_maximum[axis]
        for axis in range(3)
    )


def _maximum_plane_gap(left: SurfaceNode, right: SurfaceNode) -> float:
    if left.normal is None or right.normal is None:
        return float("inf")
    gaps = [
        abs(dot(left.normal, tuple(
            point[axis] - left.centroid[axis] for axis in range(3)
        )))
        for point in right.world_vertices
    ]
    gaps.extend(
        abs(dot(right.normal, tuple(
            point[axis] - right.centroid[axis] for axis in range(3)
        )))
        for point in left.world_vertices
    )
    return max(gaps, default=float("inf"))


def _nearby_plane_buckets(key: PlaneBucket) -> Iterator[PlaneBucket]:
    normal_radius = ceil(_NORMAL_DIFFERENCE_LIMIT / _NORMAL_QUANTUM)
    for delta in product(range(-normal_radius, normal_radius + 1), repeat=3):
        for plane_delta in (-1, 0, 1):
            yield (
                key[0] + delta[0],
                key[1] + delta[1],
                key[2] + delta[2],
                key[3] + plane_delta,
            )


def candidate_overlap_pairs(
    context: GeometryAnalysisContext,
    tolerance_m: float,
) -> Iterator[tuple[str, str]]:
    """Yield deterministic plane/AABB candidates for exact polygon checks."""

    if not 1e-8 <= tolerance_m <= 0.05:
        raise ValueError("geometry_analysis_tolerance_out_of_bounds")
    if tolerance_m > context.tolerance_m:
        raise ValueError("geometry_analysis_context_tolerance_too_small")
    pairs: set[tuple[str, str]] = set()
    for left_id in sorted(context.surface_plane_keys):
        key = context.surface_plane_keys[left_id]
        spatial = {
            surface_id
            for cell in context.surface_overlap_cells.get(left_id, ())
            for surface_id in context.overlap_cells.get(cell, ())
        }
        coplanar = {
            surface_id
            for bucket in _nearby_plane_buckets(key.bucket)
            for surface_id in context.plane_buckets.get(bucket, ())
        }
        for right_id in sorted(spatial & coplanar):
            if right_id <= left_id:
                continue
            left = context.graph.surfaces[left_id]
            right = context.graph.surfaces[right_id]
            if left.normal is None or right.normal is None:
                continue
            if abs(dot(left.normal, right.normal)) < _NORMAL_DOT_MIN:
                continue
            if not _aabbs_overlap(
                context.surface_aabbs[left_id], context.surface_aabbs[right_id],
            ):
                continue
            if _maximum_plane_gap(left, right) > tolerance_m:
                continue
            pairs.add((left_id, right_id))
    yield from sorted(pairs)


def build_geometry_analysis_context(
    input_text: str,
    idd_text: str,
    *,
    tolerance_m: float = 0.05,
) -> GeometryAnalysisContext:
    return GeometryAnalysisContext.from_text(
        input_text, idd_text, tolerance_m=tolerance_m,
    )


__all__ = [
    "GeometryAnalysisContext",
    "IndexedVertex",
    "SurfaceAABB",
    "SurfacePlaneKey",
    "TypedReverseReference",
    "build_geometry_analysis_context",
    "candidate_overlap_pairs",
]
