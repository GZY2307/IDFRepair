"""Assisted-only preview of a polar-order self-intersection candidate.

Polar ordering proves neither the intended winding nor shared-boundary and
zone-closure invariants.  It therefore remains visible for review but is never
eligible for safe-auto execution.
"""

from __future__ import annotations

from itertools import permutations
from math import atan2

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import CandidateEvidence, RepairCandidate, RepairOperation
from idfrepair.io.idf import canonical, parse_idf


Point = tuple[float, float, float]


def _project(points: tuple[Point, ...]) -> tuple[tuple[float, float], ...]:
    ranges = [max(point[index] for point in points) - min(point[index] for point in points) for index in range(3)]
    drop = min(range(3), key=lambda index: ranges[index])
    indexes = [index for index in range(3) if index != drop]
    return tuple((point[indexes[0]], point[indexes[1]]) for point in points)


def _orientation(a, b, c):  # type: ignore[no-untyped-def]
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(a, b, c, d):  # type: ignore[no-untyped-def]
    return _orientation(a, b, c) * _orientation(a, b, d) < 0 and _orientation(c, d, a) * _orientation(c, d, b) < 0


def _self_intersects(points: tuple[Point, ...]) -> bool:
    projected = _project(points)
    count = len(projected)
    for first in range(count):
        a, b = projected[first], projected[(first + 1) % count]
        for second in range(first + 1, count):
            if second in {first, (first + 1) % count} or (second + 1) % count in {first, (first + 1) % count}:
                continue
            c, d = projected[second], projected[(second + 1) % count]
            if _segments_cross(a, b, c, d):
                return True
    return False


def _candidate_orders(points: tuple[Point, ...]) -> tuple[tuple[int, ...], ...]:
    if len(points) < 4 or len(points) > 8 or len(set(points)) != len(points):
        return ()
    projected = _project(points)
    center_x = sum(point[0] for point in projected) / len(projected)
    center_y = sum(point[1] for point in projected) / len(projected)
    base = tuple(sorted(range(len(points)), key=lambda index: atan2(projected[index][1] - center_y, projected[index][0] - center_x)))
    orders = []
    for order in (base, tuple(reversed(base))):
        pivot = order.index(0)
        rotated = order[pivot:] + order[:pivot]
        candidate = tuple(points[index] for index in rotated)
        if not _self_intersects(candidate):
            orders.append(rotated)
    unique = sorted(set(orders), key=lambda order: (sum(index != value for index, value in enumerate(order)), order))
    if not unique:
        return ()
    minimum = sum(index != value for index, value in enumerate(unique[0]))
    return tuple(order for order in unique if sum(index != value for index, value in enumerate(order)) == minimum)


def _vertices(obj, definition):  # type: ignore[no-untyped-def]
    start = next((field.index for field in definition.fields if field.role == "vertex_coordinate"), None)
    if start is None or start > len(obj.fields):
        return None
    values = obj.fields[start - 1:]
    if len(values) % 3:
        return None
    try:
        points = tuple(tuple(float(values[offset + axis].value) for axis in range(3)) for offset in range(0, len(values), 3))
    except ValueError:
        return None
    return start, values, points


class GeometryProvider(CandidateProvider):
    name = "geometry_topology"
    families = frozenset({"geometry"})

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        rows = []
        for obj in context.document.objects:
            definition = context.idd.get(obj.object_type)
            if definition is None:
                continue
            extracted = _vertices(obj, definition)
            if extracted is None:
                continue
            start, fields, points = extracted
            if not _self_intersects(points):
                continue
            orders = _candidate_orders(points)
            for order in orders:
                replacement = obj.raw
                patches = []
                flattened = [fields[index * 3 + axis].value for index in order for axis in range(3)]
                for field, value in zip(reversed(fields), reversed(flattened)):
                    relative_start = field.start - obj.start
                    relative_end = field.end - obj.start
                    patches.append((relative_start, relative_end, value))
                for left, right, value in patches:
                    replacement = replacement[:left] + value + replacement[right:]
                operation = RepairOperation(
                    kind=OperationKind.REPLACE_VERTICES,
                    object_type=obj.object_type,
                    object_name=obj.name or None,
                    object_index=obj.index,
                    object_text=replacement,
                    old_value=obj.raw,
                    vertices=tuple(points[index] for index in order),
                    metadata={"first_coordinate_field": start, "order": order},
                )
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
                    evidence=(CandidateEvidence(
                        kind="unqualified_polar_polygon_order",
                        source="local_vertex_set_only",
                        strength=0.55,
                        details={
                            "automatic_policy": "forbidden",
                            "candidate_order_count": len(orders),
                            "missing_invariants": [
                                "orientation",
                                "outward_normal",
                                "paired_surface_consistency",
                                "shared_edge_consistency",
                                "zone_closure",
                            ],
                            "vertex_multiset_preserved": True,
                            "self_intersection_removed": True,
                        },
                    ),),
                    risk=RiskLevel.HIGH,
                    confidence=0.55,
                    input_sha256=context.input_sha256,
                    idd_sha256=context.idd_sha256,
                    version=context.version,
                    requires_user_confirmation=True,
                    metadata={
                        "automatic_policy": "forbidden",
                        "mechanism": "polar_angle_vertex_order_preview",
                    },
                ))
        return tuple(rows) if len(rows) <= 2 else ()

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        operation = candidate.operations[0]
        document = parse_idf(after)
        obj = document.objects[operation.object_index or 0]
        definition = context.idd.get(obj.object_type)
        extracted = _vertices(obj, definition) if definition else None
        passed = bool(extracted and set(extracted[2]) == set(operation.vertices) and not _self_intersects(extracted[2]))
        return passed, (() if passed else ("geometry_topology_validation_failed",)), {
            "vertex_count": len(operation.vertices),
            "vertex_multiset_preserved": bool(extracted and set(extracted[2]) == set(operation.vertices)),
        }
