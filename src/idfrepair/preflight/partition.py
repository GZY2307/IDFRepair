"""Fail-closed proof that reversed counterpart polygons exactly partition a face."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import sqrt
from typing import Any, Mapping, Sequence

from idfrepair.knowledge.geometry_graph import (
    Point3D,
    cross,
    dot,
)


Point2D = tuple[float, float]
PROOF_LINEAR_EPSILON_M = 1e-7


@dataclass(frozen=True, slots=True)
class PartitionProof:
    """Measured evidence for one parent and its oppositely wound pieces."""

    passed: bool
    parent_area_m2: float
    pieces_area_m2: float
    overlap_area_m2: float
    uncovered_area_m2: float
    outside_area_m2: float
    maximum_plane_gap_m: float
    parent_plane_gap_m: float
    proof_linear_epsilon_m: float
    area_epsilon_m2: float
    blocking_reasons: tuple[str, ...]

    @property
    def reasons(self) -> tuple[str, ...]:
        return self.blocking_reasons

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "parent_area_m2": self.parent_area_m2,
            "pieces_area_m2": self.pieces_area_m2,
            "overlap_area_m2": self.overlap_area_m2,
            "uncovered_area_m2": self.uncovered_area_m2,
            "outside_area_m2": self.outside_area_m2,
            "maximum_plane_gap_m": self.maximum_plane_gap_m,
            "parent_plane_gap_m": self.parent_plane_gap_m,
            "proof_linear_epsilon_m": self.proof_linear_epsilon_m,
            "area_epsilon_m2": self.area_epsilon_m2,
            "blocking_reasons": list(self.blocking_reasons),
        }


@dataclass(frozen=True, slots=True)
class PolygonOverlap2D:
    """Exact bounded overlap measures for two simple projected polygons."""

    left_area_m2: float
    right_area_m2: float
    intersection_area_m2: float
    proof_linear_epsilon_m: float
    orientation_epsilon_m2: float


def _subtract(left: Point3D, right: Point3D) -> Point3D:
    return (
        left[0] - right[0],
        left[1] - right[1],
        left[2] - right[2],
    )


def _length(point: Point3D) -> float:
    return sqrt(dot(point, point))


def _scale(point: Point3D, factor: float) -> Point3D:
    return (point[0] * factor, point[1] * factor, point[2] * factor)


def _basis(points: Sequence[Point3D], normal: Point3D) -> tuple[Point3D, Point3D]:
    origin = points[0]
    direction = max(
        (
            _subtract(
                _subtract(point, origin),
                _scale(normal, dot(_subtract(point, origin), normal)),
            )
            for point in points[1:]
        ),
        key=_length,
        default=(0.0, 0.0, 0.0),
    )
    length = _length(direction)
    if length <= 1e-15:
        raise ValueError("partition_parent_degenerate")
    first = _scale(direction, 1.0 / length)
    second = cross(normal, first)
    second_length = _length(second)
    if second_length <= 1e-15:
        raise ValueError("partition_parent_degenerate")
    return first, _scale(second, 1.0 / second_length)


def _project(
    points: Sequence[Point3D],
    origin: Point3D,
    first: Point3D,
    second: Point3D,
) -> tuple[Point2D, ...]:
    return tuple(
        (dot(_subtract(point, origin), first), dot(_subtract(point, origin), second))
        for point in points
    )


def _cross_2d(left: Point2D, right: Point2D) -> float:
    return left[0] * right[1] - left[1] * right[0]


def _turn(first: Point2D, second: Point2D, third: Point2D) -> float:
    return _cross_2d(
        (second[0] - first[0], second[1] - first[1]),
        (third[0] - second[0], third[1] - second[1]),
    )


def _signed_area(points: Sequence[Point2D]) -> float:
    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, (*points[1:], points[0]), strict=True)
    )


def _point_distance(left: Point3D, right: Point3D) -> float:
    return _length(_subtract(left, right))


def _normal_and_area(points: Sequence[Point3D]) -> tuple[Point3D | None, float]:
    if len(points) < 3:
        return None, 0.0
    origin = points[0]
    vector = (0.0, 0.0, 0.0)
    for current, following in zip(points, (*points[1:], points[0]), strict=True):
        product = cross(_subtract(current, origin), _subtract(following, origin))
        vector = tuple(vector[axis] + product[axis] for axis in range(3))  # type: ignore[assignment]
    magnitude = _length(vector)
    if magnitude <= 1e-30:
        return None, 0.0
    return _scale(vector, 1.0 / magnitude), 0.5 * magnitude


def _perimeter_2d(points: Sequence[Point2D]) -> float:
    return sum(
        ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5
        for left, right in zip(points, (*points[1:], points[0]), strict=True)
    )


def _has_duplicate(points: Sequence[Point3D], epsilon: float) -> bool:
    return any(
        _point_distance(left, right) <= epsilon
        for left, right in combinations(points, 2)
    )


def _between(value: float, first: float, second: float, epsilon: float) -> bool:
    return min(first, second) - epsilon <= value <= max(first, second) + epsilon


def _segments_intersect(
    left_start: Point2D,
    left_end: Point2D,
    right_start: Point2D,
    right_end: Point2D,
    linear_epsilon: float,
    orientation_epsilon: float,
) -> bool:
    turns = (
        _turn(left_start, left_end, right_start),
        _turn(left_start, left_end, right_end),
        _turn(right_start, right_end, left_start),
        _turn(right_start, right_end, left_end),
    )
    if (
        turns[0] * turns[1] < -(orientation_epsilon * orientation_epsilon)
        and turns[2] * turns[3] < -(orientation_epsilon * orientation_epsilon)
    ):
        return True
    checks = (
        (turns[0], right_start, left_start, left_end),
        (turns[1], right_end, left_start, left_end),
        (turns[2], left_start, right_start, right_end),
        (turns[3], left_end, right_start, right_end),
    )
    return any(
        abs(value) <= orientation_epsilon
        and _between(point[0], start[0], end[0], linear_epsilon)
        and _between(point[1], start[1], end[1], linear_epsilon)
        for value, point, start, end in checks
    )


def _simple(
    points: Sequence[Point2D],
    linear_epsilon: float,
    orientation_epsilon: float,
) -> bool:
    if len(points) < 3:
        return False
    count = len(points)
    for left in range(count):
        left_end = (left + 1) % count
        for right in range(left + 1, count):
            right_end = (right + 1) % count
            if len({left, left_end, right, right_end}) < 4:
                continue
            if _segments_intersect(
                points[left],
                points[left_end],
                points[right],
                points[right_end],
                linear_epsilon,
                orientation_epsilon,
            ):
                return False
    return True


def _without_collinear(
    points: Sequence[Point2D],
    linear_epsilon: float,
    orientation_epsilon: float,
) -> list[Point2D]:
    rows = list(points)
    changed = True
    while changed and len(rows) > 3:
        changed = False
        for index, current in enumerate(rows):
            before = rows[index - 1]
            after = rows[(index + 1) % len(rows)]
            if abs(_turn(before, current, after)) > orientation_epsilon:
                continue
            if not (
                _between(current[0], before[0], after[0], linear_epsilon)
                and _between(current[1], before[1], after[1], linear_epsilon)
            ):
                continue
            del rows[index]
            changed = True
            break
    return rows


def _point_in_triangle(
    point: Point2D,
    first: Point2D,
    second: Point2D,
    third: Point2D,
    orientation_epsilon: float,
) -> bool:
    values = (
        _turn(first, second, point),
        _turn(second, third, point),
        _turn(third, first, point),
    )
    return all(value >= -orientation_epsilon for value in values)


def _triangulate(
    points: Sequence[Point2D],
    linear_epsilon: float,
    orientation_epsilon: float,
) -> tuple[tuple[Point2D, Point2D, Point2D], ...] | None:
    rows = _without_collinear(points, linear_epsilon, orientation_epsilon)
    if len(rows) < 3 or abs(_signed_area(rows)) <= orientation_epsilon:
        return None
    if _signed_area(rows) < 0.0:
        rows.reverse()
    indices = list(range(len(rows)))
    triangles: list[tuple[Point2D, Point2D, Point2D]] = []
    guard = len(rows) * len(rows)
    while len(indices) > 3 and guard:
        guard -= 1
        found = False
        for position, current in enumerate(indices):
            before = indices[position - 1]
            after = indices[(position + 1) % len(indices)]
            triangle = (rows[before], rows[current], rows[after])
            if _turn(*triangle) <= orientation_epsilon:
                continue
            if any(
                _point_in_triangle(rows[index], *triangle, orientation_epsilon)
                for index in indices
                if index not in {before, current, after}
            ):
                continue
            triangles.append(triangle)
            del indices[position]
            found = True
            break
        if not found:
            return None
    if len(indices) != 3:
        return None
    final = (rows[indices[0]], rows[indices[1]], rows[indices[2]])
    if _turn(*final) <= orientation_epsilon:
        return None
    triangles.append(final)
    return tuple(triangles)


def _line_intersection(
    start: Point2D,
    end: Point2D,
    clip_start: Point2D,
    clip_end: Point2D,
    orientation_epsilon: float,
) -> Point2D:
    direction = (end[0] - start[0], end[1] - start[1])
    clip_direction = (clip_end[0] - clip_start[0], clip_end[1] - clip_start[1])
    denominator = _cross_2d(direction, clip_direction)
    if abs(denominator) <= orientation_epsilon:
        return end
    offset = (clip_start[0] - start[0], clip_start[1] - start[1])
    factor = _cross_2d(offset, clip_direction) / denominator
    return (
        start[0] + factor * direction[0],
        start[1] + factor * direction[1],
    )


def _convex_intersection(
    subject: Sequence[Point2D],
    clip: Sequence[Point2D],
    orientation_epsilon: float,
) -> list[Point2D]:
    output = list(subject)
    for clip_start, clip_end in zip(clip, (*clip[1:], clip[0]), strict=True):
        incoming = output
        output = []
        if not incoming:
            break

        def inside(point: Point2D) -> bool:
            return _turn(clip_start, clip_end, point) >= -orientation_epsilon

        previous = incoming[-1]
        previous_inside = inside(previous)
        for current in incoming:
            current_inside = inside(current)
            if current_inside != previous_inside:
                output.append(_line_intersection(
                    previous,
                    current,
                    clip_start,
                    clip_end,
                    orientation_epsilon,
                ))
            if current_inside:
                output.append(current)
            previous = current
            previous_inside = current_inside
    return output


def _intersection_area(
    left: Sequence[tuple[Point2D, Point2D, Point2D]],
    right: Sequence[tuple[Point2D, Point2D, Point2D]],
    orientation_epsilon: float,
) -> float:
    total = 0.0
    for left_triangle in left:
        for right_triangle in right:
            intersection = _convex_intersection(
                left_triangle, right_triangle, orientation_epsilon,
            )
            if len(intersection) >= 3:
                total += abs(_signed_area(intersection))
    return total


def _clean_measure(value: float, epsilon: float) -> float:
    if abs(value) <= epsilon:
        return 0.0
    return round(value, 12)


def measure_polygon_overlap_2d(
    left: Sequence[Point2D],
    right: Sequence[Point2D],
    *,
    linear_epsilon_m: float = PROOF_LINEAR_EPSILON_M,
) -> PolygonOverlap2D | None:
    """Measure two simple polygons after a shared translation; invalid inputs fail closed."""

    if linear_epsilon_m <= 0.0 or len(left) < 3 or len(right) < 3:
        return None
    origin = left[0]
    left_local = tuple(
        (point[0] - origin[0], point[1] - origin[1]) for point in left
    )
    right_local = tuple(
        (point[0] - origin[0], point[1] - origin[1]) for point in right
    )
    perimeter = max(
        _perimeter_2d(left_local),
        _perimeter_2d(right_local),
        linear_epsilon_m,
    )
    orientation_epsilon = max(1e-18, linear_epsilon_m * perimeter)
    if not _simple(left_local, linear_epsilon_m, orientation_epsilon):
        return None
    if not _simple(right_local, linear_epsilon_m, orientation_epsilon):
        return None
    left_triangles = _triangulate(
        left_local, linear_epsilon_m, orientation_epsilon,
    )
    right_triangles = _triangulate(
        right_local, linear_epsilon_m, orientation_epsilon,
    )
    if left_triangles is None or right_triangles is None:
        return None
    left_area = abs(_signed_area(left_local))
    right_area = abs(_signed_area(right_local))
    if min(left_area, right_area) <= orientation_epsilon:
        return None
    return PolygonOverlap2D(
        left_area_m2=left_area,
        right_area_m2=right_area,
        intersection_area_m2=_intersection_area(
            left_triangles, right_triangles, orientation_epsilon,
        ),
        proof_linear_epsilon_m=linear_epsilon_m,
        orientation_epsilon_m2=orientation_epsilon,
    )


def prove_direct_surface_pair(
    left: Sequence[Point3D],
    right: Sequence[Point3D],
    tolerance_m: float,
    *,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute the Task 4 one-to-one proof from building-frame vertices."""

    left_points = tuple(left)
    right_points = tuple(right)
    left_normal, left_area = _normal_and_area(left_points)
    right_normal, right_area = _normal_and_area(right_points)
    normal_dot = (
        dot(left_normal, right_normal)
        if left_normal is not None and right_normal is not None else 1.0
    )
    left_perimeter = sum(
        _length(_subtract(point, left_points[(index + 1) % len(left_points)]))
        for index, point in enumerate(left_points)
    )
    right_perimeter = sum(
        _length(_subtract(point, right_points[(index + 1) % len(right_points)]))
        for index, point in enumerate(right_points)
    )
    area_tolerance = PROOF_LINEAR_EPSILON_M * max(
        left_perimeter, right_perimeter, PROOF_LINEAR_EPSILON_M,
    )
    if evidence is None:
        if left_normal is None or right_normal is None:
            raise ValueError("direct_pair_polygon_invalid")
        dropped_axis = max(range(3), key=lambda axis: abs(left_normal[axis]))
        axes = [axis for axis in range(3) if axis != dropped_axis]
        overlap = measure_polygon_overlap_2d(
            [(point[axes[0]], point[axes[1]]) for point in left_points],
            [(point[axes[0]], point[axes[1]]) for point in right_points],
        )
        if overlap is None:
            raise ValueError("direct_pair_polygon_invalid")
        intersection_area = overlap.intersection_area_m2
        left_projected_area = overlap.left_area_m2
        right_projected_area = overlap.right_area_m2
        left_origin = left_points[0]
        right_origin = right_points[0]
        maximum_gap = max((
            *(
                abs(dot(left_normal, _subtract(point, left_origin)))
                for point in right_points
            ),
            *(
                abs(dot(right_normal, _subtract(point, right_origin)))
                for point in left_points
            ),
        ), default=float("inf"))
    else:
        intersection_area = float(evidence.get("projected_overlap_area_m2") or 0.0)
        left_projected_area = float(
            evidence.get("left_projected_area_m2") or left_area
        )
        right_projected_area = float(
            evidence.get("right_projected_area_m2") or right_area
        )
        raw_gap = evidence.get("maximum_plane_gap_m")
        maximum_gap = (
            float(raw_gap) if isinstance(raw_gap, (int, float)) else float("inf")
        )
    area_delta = abs(left_projected_area - right_projected_area)
    left_missing = max(0.0, left_projected_area - intersection_area)
    right_missing = max(0.0, right_projected_area - intersection_area)
    reversed_left = tuple(reversed(left_points))
    polygon_equivalent = bool(
        len(left_points) == len(right_points)
        and left_points
        and any(
            all(
                _length(_subtract(
                    reversed_left[index],
                    right_points[(index + offset) % len(right_points)],
                )) <= PROOF_LINEAR_EPSILON_M
                for index in range(len(right_points))
            )
            for offset in range(len(right_points))
        )
    )
    checks = {
        "coplanar_within_tolerance": maximum_gap <= PROOF_LINEAR_EPSILON_M,
        "full_bidirectional_overlap": (
            left_missing <= area_tolerance and right_missing <= area_tolerance
        ),
        "area_equal_within_tolerance": area_delta <= area_tolerance,
        "reversed_winding": normal_dot <= -1.0 + 1e-9,
        "polygon_equivalent": polygon_equivalent,
    }
    reason_by_check = {
        "coplanar_within_tolerance": "paired_surfaces_not_coplanar",
        "full_bidirectional_overlap": "surface_overlap_not_bidirectionally_complete",
        "area_equal_within_tolerance": "paired_surface_area_mismatch",
        "reversed_winding": "paired_surface_winding_not_reversed",
        "polygon_equivalent": "paired_polygons_not_equivalent",
    }
    blockers = [reason_by_check[key] for key, passed in checks.items() if not passed]
    return {
        "passed": not blockers,
        **checks,
        "candidate_tolerance_m": tolerance_m,
        "proof_linear_epsilon_m": PROOF_LINEAR_EPSILON_M,
        "normal_dot_product": normal_dot,
        "maximum_plane_gap_m": maximum_gap,
        "area_delta_m2": area_delta,
        "area_tolerance_m2": area_tolerance,
        "projected_overlap_area_m2": intersection_area,
        "left_projected_area_m2": left_projected_area,
        "right_projected_area_m2": right_projected_area,
        "left_uncovered_area_m2": left_missing,
        "right_uncovered_area_m2": right_missing,
        "blocking_reasons": blockers,
    }


def prove_surface_partition(
    parent: Sequence[Point3D],
    pieces: Sequence[Sequence[Point3D]],
    tolerance_m: float,
) -> PartitionProof:
    """Prove an exact disjoint union; numerical tolerance never conceals gaps."""

    if not 1e-8 <= tolerance_m <= 0.05:
        raise ValueError("surface_partition_tolerance_out_of_bounds")
    reasons: list[str] = []
    parent_points = tuple(parent)
    piece_points = tuple(tuple(piece) for piece in pieces)
    linear_epsilon = PROOF_LINEAR_EPSILON_M
    parent_normal, parent_vector_area = _normal_and_area(parent_points)
    if parent_normal is None or parent_vector_area <= 1e-18 or len(parent_points) < 3:
        reasons.append("parent_polygon_invalid")
        return PartitionProof(
            passed=False,
            parent_area_m2=parent_vector_area,
            pieces_area_m2=sum(_normal_and_area(piece)[1] for piece in piece_points),
            overlap_area_m2=0.0,
            uncovered_area_m2=parent_vector_area,
            outside_area_m2=0.0,
            maximum_plane_gap_m=float("inf"),
            parent_plane_gap_m=float("inf"),
            proof_linear_epsilon_m=linear_epsilon,
            area_epsilon_m2=0.0,
            blocking_reasons=tuple(reasons),
        )
    first, second = _basis(parent_points, parent_normal)
    origin = parent_points[0]
    parent_plane_gap = max(
        (abs(dot(parent_normal, _subtract(point, origin))) for point in parent_points),
        default=float("inf"),
    )
    if parent_plane_gap > linear_epsilon:
        reasons.append("parent_polygon_not_planar")
    parent_2d = _project(parent_points, origin, first, second)
    parent_area = abs(_signed_area(parent_2d))
    parent_perimeter = _perimeter_2d(parent_2d)
    orientation_epsilon = max(
        1e-18,
        linear_epsilon * max(parent_perimeter, linear_epsilon),
    )
    area_epsilon = orientation_epsilon
    if parent_area <= area_epsilon:
        reasons.append("parent_polygon_invalid")
    if _has_duplicate(parent_points, linear_epsilon):
        reasons.append("parent_duplicate_point")
    if not _simple(parent_2d, linear_epsilon, orientation_epsilon):
        reasons.append("parent_polygon_not_simple")
    parent_triangles = _triangulate(
        parent_2d, linear_epsilon, orientation_epsilon,
    )
    if parent_triangles is None:
        reasons.append("parent_polygon_not_triangulable")

    maximum_gap = 0.0
    triangulated_pieces: list[tuple[tuple[Point2D, Point2D, Point2D], ...]] = []
    pieces_area = 0.0
    for index, piece in enumerate(piece_points):
        prefix = f"piece_{index + 1}"
        normal, _ = _normal_and_area(piece)
        projected = _project(piece, origin, first, second)
        piece_area = abs(_signed_area(projected))
        pieces_area += piece_area
        if len(piece) < 3 or piece_area <= area_epsilon:
            reasons.append(f"{prefix}_polygon_invalid")
        if _has_duplicate(piece, linear_epsilon):
            reasons.append("piece_duplicate_point")
        gaps = tuple(abs(dot(parent_normal, _subtract(point, origin))) for point in piece)
        maximum_gap = max(maximum_gap, max(gaps, default=0.0))
        if any(gap > linear_epsilon for gap in gaps):
            reasons.append("piece_off_parent_plane")
        if normal is None or dot(parent_normal, normal) >= -1.0 + 1e-8:
            reasons.append("piece_winding_not_reversed")
        if not _simple(projected, linear_epsilon, orientation_epsilon):
            reasons.append("piece_polygon_not_simple")
        triangles = _triangulate(
            projected, linear_epsilon, orientation_epsilon,
        )
        if triangles is None:
            reasons.append(f"{prefix}_polygon_not_triangulable")
        else:
            triangulated_pieces.append(triangles)

    overlap_area = 0.0
    inside_area = 0.0
    if parent_triangles is not None and len(triangulated_pieces) == len(piece_points):
        inside_area = sum(
            _intersection_area(triangles, parent_triangles, orientation_epsilon)
            for triangles in triangulated_pieces
        )
        overlap_area = sum(
            _intersection_area(
                triangulated_pieces[left],
                triangulated_pieces[right],
                orientation_epsilon,
            )
            for left, right in combinations(range(len(triangulated_pieces)), 2)
        )
    outside_area = max(0.0, pieces_area - inside_area)
    covered_area = max(0.0, inside_area - overlap_area)
    uncovered_area = max(0.0, parent_area - covered_area)
    overlap_area = _clean_measure(overlap_area, area_epsilon)
    outside_area = _clean_measure(outside_area, area_epsilon)
    uncovered_area = _clean_measure(uncovered_area, area_epsilon)
    if outside_area > area_epsilon:
        reasons.append("piece_outside_parent")
    if overlap_area > area_epsilon:
        reasons.append("piece_overlap")
    if uncovered_area > area_epsilon:
        reasons.append("partition_gap")
    if abs((pieces_area - overlap_area) - parent_area) > area_epsilon:
        reasons.append("partition_union_mismatch")
    unique_reasons = tuple(dict.fromkeys(reasons))
    return PartitionProof(
        passed=not unique_reasons,
        parent_area_m2=_clean_measure(parent_area, area_epsilon),
        pieces_area_m2=_clean_measure(pieces_area, area_epsilon),
        overlap_area_m2=overlap_area,
        uncovered_area_m2=uncovered_area,
        outside_area_m2=outside_area,
        maximum_plane_gap_m=max(parent_plane_gap, maximum_gap),
        parent_plane_gap_m=parent_plane_gap,
        proof_linear_epsilon_m=linear_epsilon,
        area_epsilon_m2=area_epsilon,
        blocking_reasons=unique_reasons,
    )


__all__ = [
    "PROOF_LINEAR_EPSILON_M",
    "PartitionProof",
    "PolygonOverlap2D",
    "measure_polygon_overlap_2d",
    "prove_direct_surface_pair",
    "prove_surface_partition",
]
