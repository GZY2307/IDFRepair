"""Fault-side geometry evidence graph for conservative IDF repair.

The graph deliberately keeps geometric identity separate from textual object
identity.  Coordinates are compared with an absolute *and* relative tolerance,
while every repair operation remains bound to one parsed object and its exact
field spans.  No oracle, clean counterpart, or EnergyPlus result is consulted
when this graph is built.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
from itertools import combinations, product
from math import cos, floor, isfinite, radians, sin, sqrt
from typing import Iterable, Mapping, Sequence

from idfrepair.io.idf import IDFDocument, IDFObject, canonical
from idfrepair.knowledge.idd import IDDObject, IDDSchema


Point3D = tuple[float, float, float]
Plane = tuple[float, float, float, float]
ClusterEdge = tuple[str, str]


def _vector(left: Point3D, right: Point3D) -> Point3D:
    return (right[0] - left[0], right[1] - left[1], right[2] - left[2])


def _add(left: Point3D, right: Point3D) -> Point3D:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def _scale(point: Point3D, value: float) -> Point3D:
    return (point[0] * value, point[1] * value, point[2] * value)


def dot(left: Point3D, right: Point3D) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def cross(left: Point3D, right: Point3D) -> Point3D:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def magnitude(point: Point3D) -> float:
    return sqrt(dot(point, point))


def unit(point: Point3D) -> Point3D | None:
    length = magnitude(point)
    if length <= 1e-15:
        return None
    return _scale(point, 1.0 / length)


def point_distance(left: Point3D, right: Point3D) -> float:
    return magnitude(_vector(left, right))


@dataclass(frozen=True, slots=True)
class GeometryTolerance:
    """Coordinate tolerance whose absolute and relative gates must both pass."""

    absolute: float = 1e-7
    relative: float = 1e-9

    def scalar_limit(self, left: float, right: float) -> float:
        return min(self.absolute, self.relative * max(abs(left), abs(right), 1.0))

    def scalar_close(self, left: float, right: float) -> bool:
        return abs(left - right) <= self.scalar_limit(left, right)

    def point_close(self, left: Point3D, right: Point3D) -> bool:
        distance = point_distance(left, right)
        building_scale = max(magnitude(left), magnitude(right), 1.0)
        return bool(
            distance <= self.absolute
            and distance <= building_scale * self.relative
        )

    def document_bucket_size(self, points: Sequence[Point3D]) -> float:
        return max(self.absolute, 1e-12)


@dataclass(frozen=True, slots=True)
class VertexNode:
    vertex_id: str
    surface_id: str
    local_index: int
    local_point: Point3D
    world_point: Point3D
    tokens: tuple[str, str, str]
    field_indices: tuple[int, int, int]
    cluster_id: str | None = None


@dataclass(frozen=True, slots=True)
class VertexCluster:
    cluster_id: str
    representative: Point3D
    vertex_ids: tuple[str, ...]
    surface_ids: tuple[str, ...]
    zone_names: tuple[str, ...]
    maximum_member_distance: float


@dataclass(frozen=True, slots=True)
class EdgeNode:
    edge_id: str
    surface_id: str
    local_index: int
    start_vertex_id: str
    end_vertex_id: str
    start_cluster_id: str
    end_cluster_id: str
    length: float

    @property
    def cluster_pair(self) -> ClusterEdge:
        return tuple(sorted((self.start_cluster_id, self.end_cluster_id)))  # type: ignore[return-value]

    @property
    def degenerate(self) -> bool:
        return self.start_cluster_id == self.end_cluster_id


@dataclass(frozen=True, slots=True)
class SurfaceNode:
    surface_id: str
    stable_identity: str
    object_index: int
    object_type: str
    object_name: str
    zone_name: str
    space_name: str
    surface_type: str
    outside_boundary_condition: str
    outside_boundary_object: str
    local_vertices: tuple[Point3D, ...]
    world_vertices: tuple[Point3D, ...]
    coordinate_tokens: tuple[tuple[str, str, str], ...]
    coordinate_field_indices: tuple[tuple[int, int, int], ...]
    vertex_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    plane: Plane | None
    normal: Point3D | None
    area: float
    centroid: Point3D
    edge_set: frozenset[ClusterEdge]
    coplanar: bool
    self_intersecting: bool
    duplicate_vertices: bool
    legal_vertex_count: bool
    object_raw_sha256: str

    @property
    def valid(self) -> bool:
        return bool(
            self.legal_vertex_count
            and not self.duplicate_vertices
            and not self.self_intersecting
            and self.coplanar
            and self.area > 1e-10
            and self.normal is not None
        )


@dataclass(frozen=True, slots=True)
class ZoneNode:
    zone_id: str
    zone_name: str
    surface_ids: tuple[str, ...]
    unique_vertex_count: int
    open_edge_count: int
    nonmanifold_edge_count: int
    degenerate_edge_count: int
    signed_volume: float
    absolute_volume: float


@dataclass(frozen=True, slots=True)
class PairedSurfaceEdge:
    relation_id: str
    left_surface_id: str
    right_surface_id: str
    reciprocal: bool
    same_vertex_set: bool
    opposite_normals: bool
    equal_area: bool
    same_edge_set: bool


@dataclass(frozen=True, slots=True)
class SharedVertexEdge:
    relation_id: str
    cluster_id: str
    left_surface_id: str
    right_surface_id: str


@dataclass(frozen=True, slots=True)
class SharedEdgeRelation:
    relation_id: str
    cluster_pair: ClusterEdge
    surface_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoundaryConditionRelation:
    relation_id: str
    source_surface_id: str
    boundary_condition: str
    referenced_name: str
    target_surface_ids: tuple[str, ...]
    reference_unique: bool
    reciprocal: bool


@dataclass(frozen=True, slots=True)
class TopologyMetrics:
    open_edge_count: int
    nonmanifold_edge_count: int
    degenerate_edge_count: int
    shared_edge_count: int
    supporting_surface_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeometryEvidenceGraph:
    document_sha256: str
    coordinate_system: str
    tolerance: GeometryTolerance
    vertices: Mapping[str, VertexNode]
    clusters: Mapping[str, VertexCluster]
    edges: Mapping[str, EdgeNode]
    surfaces: Mapping[str, SurfaceNode]
    zones: Mapping[str, ZoneNode]
    paired_surface_edges: tuple[PairedSurfaceEdge, ...]
    shared_vertex_edges: tuple[SharedVertexEdge, ...]
    shared_edge_relations: tuple[SharedEdgeRelation, ...]
    boundary_condition_relations: tuple[BoundaryConditionRelation, ...]
    ambiguous_vertex_ids: tuple[str, ...] = ()
    zone_frames: Mapping[str, tuple[float, Point3D]] = field(default_factory=dict, repr=False)
    _surface_name_index: Mapping[str, tuple[str, ...]] = field(default_factory=dict, repr=False)
    surface_ids_by_zone: Mapping[str, tuple[str, ...]] = field(default_factory=dict, repr=False)

    def surface_by_id(self, surface_id: str) -> SurfaceNode | None:
        return self.surfaces.get(surface_id)

    def surfaces_by_name(self, name: str) -> tuple[SurfaceNode, ...]:
        return tuple(
            self.surfaces[surface_id]
            for surface_id in self._surface_name_index.get(canonical(name), ())
        )

    def unique_surface(self, name: str) -> SurfaceNode | None:
        rows = self.surfaces_by_name(name)
        return rows[0] if len(rows) == 1 else None

    def paired_relation(self, surface_id: str) -> PairedSurfaceEdge | None:
        rows = [
            relation for relation in self.paired_surface_edges
            if surface_id in {relation.left_surface_id, relation.right_surface_id}
        ]
        return rows[0] if len(rows) == 1 else None

    def paired_surface(self, surface_id: str) -> SurfaceNode | None:
        relation = self.paired_relation(surface_id)
        if relation is None:
            return None
        other = (
            relation.right_surface_id
            if relation.left_surface_id == surface_id
            else relation.left_surface_id
        )
        return self.surfaces.get(other)

    def point_to_local(self, point: Point3D, zone_name: str) -> Point3D | None:
        """Transform a building-frame point into one surface's zone frame."""

        if canonical(self.coordinate_system) == "world":
            return point
        frame = self.zone_frames.get(canonical(zone_name))
        if frame is None:
            return None
        north, origin = frame
        angle = radians(north)
        cosine, sine = cos(angle), sin(angle)
        x_value = point[0] - origin[0]
        y_value = point[1] - origin[1]
        return (
            x_value * cosine - y_value * sine,
            x_value * sine + y_value * cosine,
            point[2] - origin[2],
        )

    def matching_clusters(
        self,
        point: Point3D,
        *,
        zone_name: str | None = None,
        exclude_surface_id: str | None = None,
    ) -> tuple[VertexCluster, ...]:
        rows = []
        zone_key = canonical(zone_name or "")
        for cluster in self.clusters.values():
            if not self.tolerance.point_close(point, cluster.representative):
                continue
            if zone_name is not None and zone_key not in {canonical(value) for value in cluster.zone_names}:
                continue
            remaining = set(cluster.surface_ids) - ({exclude_surface_id} if exclude_surface_id else set())
            if exclude_surface_id and not remaining:
                continue
            rows.append(cluster)
        return tuple(sorted(rows, key=lambda row: row.cluster_id))

    def cluster_ids_for_points(
        self,
        points: Sequence[Point3D],
        *,
        zone_name: str | None = None,
    ) -> tuple[str, ...] | None:
        result: list[str] = []
        for point in points:
            matches = self.matching_clusters(point, zone_name=zone_name)
            if len(matches) != 1:
                return None
            result.append(matches[0].cluster_id)
        return tuple(result)

    def topology_metrics(
        self,
        zone_name: str,
        *,
        overrides: Mapping[str, Sequence[Point3D]] | None = None,
        target_surface_id: str | None = None,
    ) -> TopologyMetrics:
        """Return zone edge incidence, optionally replacing selected surfaces.

        Candidate coordinates must map uniquely to already observed clusters.
        Unresolved coordinates are represented by stable candidate-local keys;
        this can only increase, never hide, an opening.
        """

        overrides = overrides or {}
        zone_key = canonical(zone_name)
        counts: dict[ClusterEdge, list[str]] = defaultdict(list)
        degenerate = 0
        for surface_id in self.surface_ids_by_zone.get(zone_key, ()):
            surface = self.surfaces[surface_id]
            points = tuple(overrides.get(surface.surface_id, surface.world_vertices))
            cluster_ids: list[str] = []
            for index, point in enumerate(points):
                matches = self.matching_clusters(point)
                if len(matches) == 1:
                    cluster_ids.append(matches[0].cluster_id)
                else:
                    digest = sha256(repr((surface.surface_id, index, point)).encode("utf-8")).hexdigest()[:12]
                    cluster_ids.append(f"candidate:{digest}")
            for index, start in enumerate(cluster_ids):
                end = cluster_ids[(index + 1) % len(cluster_ids)]
                if start == end:
                    degenerate += 1
                    continue
                counts[tuple(sorted((start, end)))].append(surface.surface_id)
        open_edges = sum(1 for rows in counts.values() if len(rows) == 1)
        nonmanifold = sum(1 for rows in counts.values() if len(rows) > 2)
        supporting: set[str] = set()
        shared = 0
        if target_surface_id is not None:
            for rows in counts.values():
                if target_surface_id in rows and len(set(rows)) >= 2:
                    shared += 1
                    supporting.update(row for row in rows if row != target_surface_id)
        return TopologyMetrics(
            open_edge_count=open_edges,
            nonmanifold_edge_count=nonmanifold,
            degenerate_edge_count=degenerate,
            shared_edge_count=shared,
            supporting_surface_ids=tuple(sorted(supporting)),
        )

    def trusted_zone_surfaces(
        self,
        zone_name: str,
        *,
        exclude_surface_id: str | None = None,
    ) -> tuple[SurfaceNode, ...]:
        key = canonical(zone_name)
        return tuple(sorted(
            (
                self.surfaces[surface_id]
                for surface_id in self.surface_ids_by_zone.get(key, ())
                if self.surfaces[surface_id].surface_id != exclude_surface_id
                and self.surfaces[surface_id].valid
            ),
            key=lambda row: row.surface_id,
        ))

    def zone_reference(
        self,
        zone_name: str,
        *,
        exclude_surface_id: str | None = None,
    ) -> tuple[Point3D, tuple[str, ...]] | None:
        trusted = self.trusted_zone_surfaces(zone_name, exclude_surface_id=exclude_surface_id)
        if len(trusted) < 2:
            return None
        points: dict[tuple[float, float, float], Point3D] = {}
        for surface in trusted:
            for point in surface.world_vertices:
                key = tuple(round(value, 12) for value in point)
                points.setdefault(key, point)
        if len(points) < 4:
            return None
        values = tuple(points.values())
        center = tuple(sum(point[axis] for point in values) / len(values) for axis in range(3))
        return center, tuple(surface.surface_id for surface in trusted)


def newell_vector(points: Sequence[Point3D]) -> Point3D:
    if len(points) < 3:
        return (0.0, 0.0, 0.0)
    x_value = y_value = z_value = 0.0
    for index, current in enumerate(points):
        following = points[(index + 1) % len(points)]
        x_value += (current[1] - following[1]) * (current[2] + following[2])
        y_value += (current[2] - following[2]) * (current[0] + following[0])
        z_value += (current[0] - following[0]) * (current[1] + following[1])
    return (x_value, y_value, z_value)


def polygon_normal(points: Sequence[Point3D]) -> Point3D | None:
    return unit(newell_vector(points))


def polygon_area(points: Sequence[Point3D]) -> float:
    return 0.5 * magnitude(newell_vector(points))


def polygon_centroid(points: Sequence[Point3D]) -> Point3D:
    if not points:
        return (0.0, 0.0, 0.0)
    return tuple(sum(point[axis] for point in points) / len(points) for axis in range(3))  # type: ignore[return-value]


def polygon_plane(points: Sequence[Point3D]) -> Plane | None:
    normal = polygon_normal(points)
    if normal is None or not points:
        return None
    return (normal[0], normal[1], normal[2], -dot(normal, points[0]))


def maximum_plane_distance(points: Sequence[Point3D], plane: Plane | None) -> float:
    if plane is None:
        return float("inf")
    normal = (plane[0], plane[1], plane[2])
    return max((abs(dot(normal, point) + plane[3]) for point in points), default=float("inf"))


def points_coplanar(points: Sequence[Point3D], tolerance: GeometryTolerance) -> bool:
    plane = polygon_plane(points)
    if plane is None:
        return False
    scale = max((magnitude(point) for point in points), default=1.0)
    limit = min(tolerance.absolute, tolerance.relative * max(scale, 1.0))
    return maximum_plane_distance(points, plane) <= limit


def _project_2d(points: Sequence[Point3D]) -> tuple[tuple[float, float], ...]:
    normal = polygon_normal(points)
    if normal is None:
        ranges = [max((point[axis] for point in points), default=0.0) - min((point[axis] for point in points), default=0.0) for axis in range(3)]
        drop = min(range(3), key=lambda axis: ranges[axis])
    else:
        drop = max(range(3), key=lambda axis: abs(normal[axis]))
    axes = [axis for axis in range(3) if axis != drop]
    return tuple((point[axes[0]], point[axes[1]]) for point in points)


def _orientation_2d(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> float:
    return (
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    )


def _between(value: float, left: float, right: float, epsilon: float) -> bool:
    return min(left, right) - epsilon <= value <= max(left, right) + epsilon


def _segments_intersect(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
    fourth: tuple[float, float],
    epsilon: float,
) -> bool:
    rows = (
        _orientation_2d(first, second, third),
        _orientation_2d(first, second, fourth),
        _orientation_2d(third, fourth, first),
        _orientation_2d(third, fourth, second),
    )
    if rows[0] * rows[1] < -(epsilon * epsilon) and rows[2] * rows[3] < -(epsilon * epsilon):
        return True
    checks = (
        (rows[0], third, first, second),
        (rows[1], fourth, first, second),
        (rows[2], first, third, fourth),
        (rows[3], second, third, fourth),
    )
    return any(
        abs(value) <= epsilon
        and _between(point[0], start[0], end[0], epsilon)
        and _between(point[1], start[1], end[1], epsilon)
        for value, point, start, end in checks
    )


def polygon_self_intersects(points: Sequence[Point3D], tolerance: GeometryTolerance | None = None) -> bool:
    if len(points) < 4:
        return False
    tolerance = tolerance or GeometryTolerance()
    projected = _project_2d(points)
    scale = max((abs(value) for point in projected for value in point), default=1.0)
    epsilon = min(tolerance.absolute, tolerance.relative * max(scale, 1.0))
    count = len(projected)
    for first in range(count):
        first_end = (first + 1) % count
        for second in range(first + 1, count):
            second_end = (second + 1) % count
            if len({first, first_end, second, second_end}) < 4:
                continue
            if _segments_intersect(
                projected[first], projected[first_end],
                projected[second], projected[second_end], epsilon,
            ):
                return True
    return False


def _field_by_name(
    obj: IDFObject,
    definition: IDDObject,
    *names: str,
    excludes: Sequence[str] = (),
) -> str:
    wanted = tuple(canonical(value) for value in names)
    excluded = tuple(canonical(value) for value in excludes)
    for field in definition.fields:
        name = canonical(field.name)
        if all(value in name for value in wanted) and not any(value in name for value in excluded):
            if field.index <= len(obj.fields):
                return obj.fields[field.index - 1].value.strip()
    return ""


def _coordinate_system(document: IDFDocument, idd: IDDSchema) -> str:
    rows = document.find_objects("GlobalGeometryRules")
    if len(rows) != 1:
        return "Relative"
    obj = rows[0]
    definition = idd.get(obj.object_type)
    value = _field_by_name(obj, definition, "coordinate", "system") if definition else ""
    if not value and len(obj.fields) >= 3:
        value = obj.fields[2].value.strip()
    return value or "Relative"


def _zone_frames(document: IDFDocument, idd: IDDSchema) -> dict[str, tuple[float, Point3D]]:
    rows: dict[str, tuple[float, Point3D]] = {}
    for obj in document.find_objects("Zone"):
        definition = idd.get(obj.object_type)
        try:
            north_text = _field_by_name(obj, definition, "direction", "relative", "north") if definition else ""
            x_text = _field_by_name(obj, definition, "x", "origin") if definition else ""
            y_text = _field_by_name(obj, definition, "y", "origin") if definition else ""
            z_text = _field_by_name(obj, definition, "z", "origin") if definition else ""
            north = float(north_text or (obj.fields[1].value if len(obj.fields) >= 2 else 0.0))
            origin = (
                float(x_text or (obj.fields[2].value if len(obj.fields) >= 3 else 0.0)),
                float(y_text or (obj.fields[3].value if len(obj.fields) >= 4 else 0.0)),
                float(z_text or (obj.fields[4].value if len(obj.fields) >= 5 else 0.0)),
            )
        except ValueError:
            continue
        if isfinite(north) and all(isfinite(value) for value in origin):
            rows[canonical(obj.name)] = (north, origin)
    return rows


def _space_zones(document: IDFDocument, idd: IDDSchema) -> dict[str, str]:
    rows: dict[str, str] = {}
    for obj in document.find_objects("Space"):
        definition = idd.get(obj.object_type)
        zone = _field_by_name(obj, definition, "zone", "name") if definition else ""
        if obj.name and zone:
            rows[canonical(obj.name)] = zone
    return rows


def _to_world(point: Point3D, frame: tuple[float, Point3D] | None, coordinate_system: str) -> Point3D:
    if canonical(coordinate_system) == "world" or frame is None:
        return point
    north, origin = frame
    angle = radians(north)
    cosine, sine = cos(angle), sin(angle)
    return (
        origin[0] + point[0] * cosine + point[1] * sine,
        origin[1] - point[0] * sine + point[1] * cosine,
        origin[2] + point[2],
    )


def _surface_fields(
    obj: IDFObject,
    definition: IDDObject,
) -> tuple[
    tuple[Point3D, ...],
    tuple[tuple[str, str, str], ...],
    tuple[tuple[int, int, int], ...],
] | None:
    first = next((field.index for field in definition.fields if field.role == "vertex_coordinate"), None)
    if first is None or first > len(obj.fields):
        return None
    fields = obj.fields[first - 1:]
    if len(fields) < 9 or len(fields) % 3:
        return None
    points: list[Point3D] = []
    tokens: list[tuple[str, str, str]] = []
    indices: list[tuple[int, int, int]] = []
    for offset in range(0, len(fields), 3):
        triplet = fields[offset:offset + 3]
        try:
            point = tuple(float(row.value) for row in triplet)
        except ValueError:
            return None
        if not all(isfinite(value) for value in point):
            return None
        points.append(point)  # type: ignore[arg-type]
        tokens.append(tuple(row.value for row in triplet))  # type: ignore[arg-type]
        indices.append(tuple(row.index for row in triplet))  # type: ignore[arg-type]
    return tuple(points), tuple(tokens), tuple(indices)


def _is_surface_definition(definition: IDDObject) -> bool:
    return sum(field.role == "vertex_coordinate" for field in definition.fields) >= 3


@dataclass(slots=True)
class _SurfaceDraft:
    surface_id: str
    stable_identity: str
    obj: IDFObject
    zone_name: str
    space_name: str
    surface_type: str
    boundary_condition: str
    boundary_object: str
    local_vertices: tuple[Point3D, ...]
    world_vertices: tuple[Point3D, ...]
    tokens: tuple[tuple[str, str, str], ...]
    field_indices: tuple[tuple[int, int, int], ...]
    vertex_ids: tuple[str, ...]


def _cluster_vertices(
    drafts: Sequence[_SurfaceDraft],
    tolerance: GeometryTolerance,
) -> tuple[dict[str, VertexNode], dict[str, VertexCluster], tuple[str, ...]]:
    raw: list[tuple[str, str, int, Point3D, Point3D, tuple[str, str, str], tuple[int, int, int], str]] = []
    for draft in drafts:
        for index, (local, world, tokens, indices, vertex_id) in enumerate(zip(
            draft.local_vertices,
            draft.world_vertices,
            draft.tokens,
            draft.field_indices,
            draft.vertex_ids,
            strict=True,
        )):
            raw.append((vertex_id, draft.surface_id, index, local, world, tokens, indices, draft.zone_name))
    bucket_size = tolerance.document_bucket_size([row[4] for row in raw])
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    cluster_rows: list[dict[str, object]] = []
    assignments: dict[str, int] = {}
    ambiguous: list[str] = []
    for vertex_id, surface_id, _, _, point, _, _, zone_name in raw:
        bucket = tuple(floor(value / bucket_size) for value in point)
        candidates: list[int] = []
        for delta in product((-1, 0, 1), repeat=3):
            neighbour = tuple(bucket[axis] + delta[axis] for axis in range(3))
            for cluster_index in buckets.get(neighbour, ()):
                representative = cluster_rows[cluster_index]["representative"]
                if tolerance.point_close(point, representative):  # type: ignore[arg-type]
                    candidates.append(cluster_index)
        candidates = sorted(set(candidates))
        if len(candidates) > 1:
            ambiguous.append(vertex_id)
        if candidates:
            selected = min(
                candidates,
                key=lambda index: (
                    point_distance(point, cluster_rows[index]["representative"]),  # type: ignore[arg-type]
                    index,
                ),
            )
        else:
            selected = len(cluster_rows)
            cluster_rows.append({
                "representative": point,
                "members": [],
                "surfaces": set(),
                "zones": set(),
                "maximum": 0.0,
            })
            buckets[bucket].append(selected)
        row = cluster_rows[selected]
        row["members"].append(vertex_id)  # type: ignore[union-attr]
        row["surfaces"].add(surface_id)  # type: ignore[union-attr]
        if zone_name:
            row["zones"].add(zone_name)  # type: ignore[union-attr]
        row["maximum"] = max(
            float(row["maximum"]),
            point_distance(point, row["representative"]),  # type: ignore[arg-type]
        )
        assignments[vertex_id] = selected
    clusters: dict[str, VertexCluster] = {}
    cluster_ids: dict[int, str] = {}
    for index, row in enumerate(cluster_rows):
        cluster_id = f"cluster:{index:08d}"
        cluster_ids[index] = cluster_id
        clusters[cluster_id] = VertexCluster(
            cluster_id=cluster_id,
            representative=row["representative"],  # type: ignore[arg-type]
            vertex_ids=tuple(row["members"]),  # type: ignore[arg-type]
            surface_ids=tuple(sorted(row["surfaces"])),  # type: ignore[arg-type]
            zone_names=tuple(sorted(row["zones"], key=canonical)),  # type: ignore[arg-type]
            maximum_member_distance=float(row["maximum"]),
        )
    vertices: dict[str, VertexNode] = {}
    for vertex_id, surface_id, index, local, world, tokens, indices, _ in raw:
        vertices[vertex_id] = VertexNode(
            vertex_id=vertex_id,
            surface_id=surface_id,
            local_index=index,
            local_point=local,
            world_point=world,
            tokens=tokens,
            field_indices=indices,
            cluster_id=cluster_ids[assignments[vertex_id]],
        )
    return vertices, clusters, tuple(sorted(ambiguous))


def _point_sets_equal(
    left: Sequence[Point3D],
    right: Sequence[Point3D],
    tolerance: GeometryTolerance,
) -> bool:
    if len(left) != len(right):
        return False
    available = set(range(len(right)))
    for point in left:
        matches = [index for index in available if tolerance.point_close(point, right[index])]
        if len(matches) != 1:
            return False
        available.remove(matches[0])
    return not available


def _zone_volume(surfaces: Iterable[SurfaceNode]) -> tuple[float, float]:
    signed = 0.0
    absolute = 0.0
    for surface in surfaces:
        points = surface.world_vertices
        if len(points) < 3:
            continue
        anchor = points[0]
        for index in range(1, len(points) - 1):
            value = dot(anchor, cross(points[index], points[index + 1])) / 6.0
            signed += value
            absolute += abs(value)
    return signed, absolute


def build_geometry_graph(
    document: IDFDocument,
    idd: IDDSchema,
    *,
    tolerance: GeometryTolerance | None = None,
) -> GeometryEvidenceGraph:
    """Build a deterministic graph from the current fault-side document."""

    tolerance = tolerance or GeometryTolerance()
    coordinate_system = _coordinate_system(document, idd)
    frames = _zone_frames(document, idd)
    space_zones = _space_zones(document, idd)
    drafts: list[_SurfaceDraft] = []
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None or not _is_surface_definition(definition):
            continue
        extracted = _surface_fields(obj, definition)
        if extracted is None:
            continue
        points, tokens, indices = extracted
        zone_name = _field_by_name(obj, definition, "zone", "name", excludes=("zone multiplier",))
        space_name = _field_by_name(obj, definition, "space", "name")
        if not zone_name and space_name:
            zone_name = space_zones.get(canonical(space_name), "")
        surface_type = _field_by_name(obj, definition, "surface", "type")
        boundary_condition = _field_by_name(
            obj, definition, "outside", "boundary", "condition", excludes=("object",),
        )
        boundary_object = _field_by_name(obj, definition, "outside", "boundary", "condition", "object")
        frame = frames.get(canonical(zone_name))
        world = tuple(_to_world(point, frame, coordinate_system) for point in points)
        surface_id = f"surface:{obj.index:08d}"
        stable_identity = sha256(
            "|".join((canonical(obj.object_type), canonical(obj.name), str(obj.index))).encode("utf-8")
        ).hexdigest()[:20]
        vertex_ids = tuple(f"{surface_id}:vertex:{index:04d}" for index in range(len(points)))
        drafts.append(_SurfaceDraft(
            surface_id=surface_id,
            stable_identity=stable_identity,
            obj=obj,
            zone_name=zone_name,
            space_name=space_name,
            surface_type=surface_type,
            boundary_condition=boundary_condition,
            boundary_object=boundary_object,
            local_vertices=points,
            world_vertices=world,
            tokens=tokens,
            field_indices=indices,
            vertex_ids=vertex_ids,
        ))
    vertices, clusters, ambiguous = _cluster_vertices(drafts, tolerance)
    edges: dict[str, EdgeNode] = {}
    surfaces: dict[str, SurfaceNode] = {}
    for draft in drafts:
        edge_ids: list[str] = []
        edge_set: set[ClusterEdge] = set()
        for index, start_id in enumerate(draft.vertex_ids):
            end_id = draft.vertex_ids[(index + 1) % len(draft.vertex_ids)]
            edge_id = f"{draft.surface_id}:edge:{index:04d}"
            start_cluster = vertices[start_id].cluster_id or ""
            end_cluster = vertices[end_id].cluster_id or ""
            edge = EdgeNode(
                edge_id=edge_id,
                surface_id=draft.surface_id,
                local_index=index,
                start_vertex_id=start_id,
                end_vertex_id=end_id,
                start_cluster_id=start_cluster,
                end_cluster_id=end_cluster,
                length=point_distance(vertices[start_id].world_point, vertices[end_id].world_point),
            )
            edges[edge_id] = edge
            edge_ids.append(edge_id)
            if not edge.degenerate:
                edge_set.add(edge.cluster_pair)
        normal = polygon_normal(draft.world_vertices)
        plane = polygon_plane(draft.world_vertices)
        duplicate = len({vertices[vertex_id].cluster_id for vertex_id in draft.vertex_ids}) != len(draft.vertex_ids)
        surfaces[draft.surface_id] = SurfaceNode(
            surface_id=draft.surface_id,
            stable_identity=draft.stable_identity,
            object_index=draft.obj.index,
            object_type=draft.obj.object_type,
            object_name=draft.obj.name,
            zone_name=draft.zone_name,
            space_name=draft.space_name,
            surface_type=draft.surface_type,
            outside_boundary_condition=draft.boundary_condition,
            outside_boundary_object=draft.boundary_object,
            local_vertices=draft.local_vertices,
            world_vertices=draft.world_vertices,
            coordinate_tokens=draft.tokens,
            coordinate_field_indices=draft.field_indices,
            vertex_ids=draft.vertex_ids,
            edge_ids=tuple(edge_ids),
            plane=plane,
            normal=normal,
            area=polygon_area(draft.world_vertices),
            centroid=polygon_centroid(draft.world_vertices),
            edge_set=frozenset(edge_set),
            coplanar=points_coplanar(draft.world_vertices, tolerance),
            self_intersecting=polygon_self_intersects(draft.world_vertices, tolerance),
            duplicate_vertices=duplicate,
            legal_vertex_count=3 <= len(draft.world_vertices) <= 120,
            object_raw_sha256=sha256(draft.obj.raw.encode("utf-8")).hexdigest(),
        )
    name_index: dict[str, list[str]] = defaultdict(list)
    for surface in surfaces.values():
        if surface.object_name:
            name_index[canonical(surface.object_name)].append(surface.surface_id)
    shared_vertices: list[SharedVertexEdge] = []
    for cluster in clusters.values():
        for left, right in combinations(sorted(set(cluster.surface_ids)), 2):
            relation_id = sha256(f"vertex|{cluster.cluster_id}|{left}|{right}".encode("utf-8")).hexdigest()[:20]
            shared_vertices.append(SharedVertexEdge(relation_id, cluster.cluster_id, left, right))
    by_edge: dict[ClusterEdge, set[str]] = defaultdict(set)
    for edge in edges.values():
        if not edge.degenerate:
            by_edge[edge.cluster_pair].add(edge.surface_id)
    shared_edges = tuple(
        SharedEdgeRelation(
            relation_id=sha256(f"edge|{pair}|{'|'.join(sorted(surface_ids))}".encode("utf-8")).hexdigest()[:20],
            cluster_pair=pair,
            surface_ids=tuple(sorted(surface_ids)),
        )
        for pair, surface_ids in sorted(by_edge.items())
        if len(surface_ids) >= 2
    )
    boundary_relations: list[BoundaryConditionRelation] = []
    for surface in surfaces.values():
        if canonical(surface.outside_boundary_condition) != "surface" or not surface.outside_boundary_object:
            continue
        targets = tuple(name_index.get(canonical(surface.outside_boundary_object), ()))
        reciprocal = bool(
            len(targets) == 1
            and canonical(surfaces[targets[0]].outside_boundary_condition) == "surface"
            and canonical(surfaces[targets[0]].outside_boundary_object) == canonical(surface.object_name)
        )
        boundary_relations.append(BoundaryConditionRelation(
            relation_id=sha256(f"boundary|{surface.surface_id}|{surface.outside_boundary_object}".encode("utf-8")).hexdigest()[:20],
            source_surface_id=surface.surface_id,
            boundary_condition=surface.outside_boundary_condition,
            referenced_name=surface.outside_boundary_object,
            target_surface_ids=targets,
            reference_unique=len(targets) == 1,
            reciprocal=reciprocal,
        ))
    paired: list[PairedSurfaceEdge] = []
    seen_pairs: set[tuple[str, str]] = set()
    for relation in boundary_relations:
        if not relation.reference_unique:
            continue
        pair = tuple(sorted((relation.source_surface_id, relation.target_surface_ids[0])))
        if pair in seen_pairs or pair[0] == pair[1]:
            continue
        seen_pairs.add(pair)
        left, right = surfaces[pair[0]], surfaces[pair[1]]
        same_set = _point_sets_equal(left.world_vertices, right.world_vertices, tolerance)
        area_limit = min(tolerance.absolute, tolerance.relative * max(left.area, right.area, 1.0))
        opposite = bool(left.normal and right.normal and dot(left.normal, right.normal) <= -1.0 + 1e-7)
        paired.append(PairedSurfaceEdge(
            relation_id=sha256(f"pair|{pair[0]}|{pair[1]}".encode("utf-8")).hexdigest()[:20],
            left_surface_id=pair[0],
            right_surface_id=pair[1],
            reciprocal=relation.reciprocal and any(
                row.source_surface_id == pair[1] and row.reciprocal for row in boundary_relations
            ),
            same_vertex_set=same_set,
            opposite_normals=opposite,
            equal_area=abs(left.area - right.area) <= area_limit,
            same_edge_set=left.edge_set == right.edge_set,
        ))
    zones: dict[str, ZoneNode] = {}
    grouped_zones: dict[str, list[SurfaceNode]] = defaultdict(list)
    zone_names: dict[str, str] = {}
    for surface in surfaces.values():
        if surface.zone_name:
            key = canonical(surface.zone_name)
            grouped_zones[key].append(surface)
            zone_names.setdefault(key, surface.zone_name)
    for key, zone_surfaces in sorted(grouped_zones.items()):
        counts: dict[ClusterEdge, int] = defaultdict(int)
        degenerate = 0
        cluster_ids: set[str] = set()
        for surface in zone_surfaces:
            for vertex_id in surface.vertex_ids:
                cluster_ids.add(vertices[vertex_id].cluster_id or "")
            for edge_id in surface.edge_ids:
                edge = edges[edge_id]
                if edge.degenerate:
                    degenerate += 1
                else:
                    counts[edge.cluster_pair] += 1
        signed, absolute = _zone_volume(zone_surfaces)
        zone_id = f"zone:{sha256(key.encode('utf-8')).hexdigest()[:16]}"
        zones[key] = ZoneNode(
            zone_id=zone_id,
            zone_name=zone_names[key],
            surface_ids=tuple(sorted(surface.surface_id for surface in zone_surfaces)),
            unique_vertex_count=len(cluster_ids - {""}),
            open_edge_count=sum(1 for value in counts.values() if value == 1),
            nonmanifold_edge_count=sum(1 for value in counts.values() if value > 2),
            degenerate_edge_count=degenerate,
            signed_volume=signed,
            absolute_volume=absolute,
        )
    return GeometryEvidenceGraph(
        document_sha256=document.sha256,
        coordinate_system=coordinate_system,
        tolerance=tolerance,
        vertices=vertices,
        clusters=clusters,
        edges=edges,
        surfaces=surfaces,
        zones=zones,
        paired_surface_edges=tuple(sorted(paired, key=lambda row: row.relation_id)),
        shared_vertex_edges=tuple(sorted(shared_vertices, key=lambda row: row.relation_id)),
        shared_edge_relations=tuple(sorted(shared_edges, key=lambda row: row.relation_id)),
        boundary_condition_relations=tuple(sorted(boundary_relations, key=lambda row: row.relation_id)),
        ambiguous_vertex_ids=ambiguous,
        zone_frames=frames,
        _surface_name_index={key: tuple(value) for key, value in name_index.items()},
        surface_ids_by_zone={
            key: tuple(sorted(surface.surface_id for surface in zone_surfaces))
            for key, zone_surfaces in grouped_zones.items()
        },
    )


__all__ = [
    "BoundaryConditionRelation",
    "EdgeNode",
    "GeometryEvidenceGraph",
    "GeometryTolerance",
    "PairedSurfaceEdge",
    "Point3D",
    "SharedEdgeRelation",
    "SharedVertexEdge",
    "SurfaceNode",
    "TopologyMetrics",
    "VertexCluster",
    "VertexNode",
    "ZoneNode",
    "build_geometry_graph",
    "cross",
    "dot",
    "magnitude",
    "maximum_plane_distance",
    "newell_vector",
    "point_distance",
    "points_coplanar",
    "polygon_area",
    "polygon_centroid",
    "polygon_normal",
    "polygon_plane",
    "polygon_self_intersects",
    "unit",
]
