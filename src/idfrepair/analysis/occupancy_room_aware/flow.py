"""Source-geometry entrance seeds for controlled room-aware occupancy phases.

The topology deliberately does not claim passenger trajectories, doors, walking
times, or measured operations.  Reciprocal paired surfaces provide a stable
Zone-adjacency relation; source geometry centroids only break equal-hop ties.
The resulting 15-minute offsets are controlled occupancy-response phases.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence, Set
import csv
import json
import math
from pathlib import Path
from typing import Any

from idfrepair.analysis.occupancy_room_aware.profiles import (
    PUBLIC_DYNAMIC_CATEGORIES,
    STAFF_CATEGORIES,
)
from idfrepair.io.idf import canonical, parse_idf
from idfrepair.knowledge.geometry_graph import Point3D, build_geometry_graph
from idfrepair.knowledge.idd import IDDSchema


FLOW_TOPOLOGY_SCHEMA = "idfrepair.room-aware-flow-topology.v1"
ENTRANCE_SPACES = ("z-u-hall-2", "z-u-hall-3")
PHASE_SEMANTICS = "controlled_occupancy_response_not_travel_time"


def _distance(left: Point3D, right: Point3D) -> float:
    return math.sqrt(math.fsum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def _bfs(adjacency: Mapping[str, Set[str]], start: str) -> dict[str, int]:
    distances = {start: 0}
    queue = deque((start,))
    while queue:
        current = queue.popleft()
        for neighbor in sorted(adjacency.get(current, ())):
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            queue.append(neighbor)
    return distances


def _tercile_thresholds(values: Sequence[int]) -> tuple[int, int]:
    if not values:
        return (0, 0)
    ordered = sorted(values)
    one_third = ordered[max(0, math.ceil(len(ordered) / 3) - 1)]
    two_thirds = ordered[max(0, math.ceil(2 * len(ordered) / 3) - 1)]
    return one_third, two_thirds


def _band(hops: int, thresholds: tuple[int, int]) -> int:
    if hops <= thresholds[0]:
        return 1
    if hops <= thresholds[1]:
        return 2
    return 3


def assign_flow_topology(
    *,
    zone_by_space: Mapping[str, str],
    category_by_space: Mapping[str, str],
    zone_centroids: Mapping[str, Point3D],
    zone_adjacency: Mapping[str, Set[str]],
    entrance_spaces: Sequence[str] = ENTRANCE_SPACES,
) -> dict[str, Any]:
    """Assign every Space to an entrance region and a controlled response phase."""

    if set(zone_by_space) != set(category_by_space):
        raise ValueError("flow_space_category_coverage_mismatch")
    if len(set(zone_by_space.values())) != len(zone_by_space):
        raise ValueError("flow_zone_not_unique_per_space")
    entrance_spaces = tuple(entrance_spaces)
    if entrance_spaces != ENTRANCE_SPACES:
        raise ValueError("flow_entrance_identity_mismatch")
    for entrance in entrance_spaces:
        if entrance not in zone_by_space:
            raise ValueError(f"flow_entrance_space_missing:{entrance}")
        if category_by_space[entrance] != "terminal_hall":
            raise ValueError(f"flow_entrance_not_terminal_hall:{entrance}")

    normalized_zone_by_space = {
        space: canonical(zone) for space, zone in zone_by_space.items()
    }
    required_zones = set(normalized_zone_by_space.values())
    normalized_centroids = {
        canonical(zone): tuple(float(value) for value in point)
        for zone, point in zone_centroids.items()
    }
    if required_zones - set(normalized_centroids):
        missing = "|".join(sorted(required_zones - set(normalized_centroids)))
        raise ValueError(f"flow_zone_centroid_missing:{missing}")
    normalized_adjacency: dict[str, set[str]] = defaultdict(set)
    for zone, neighbors in zone_adjacency.items():
        zone_key = canonical(zone)
        for neighbor in neighbors:
            neighbor_key = canonical(neighbor)
            if zone_key == neighbor_key:
                continue
            normalized_adjacency[zone_key].add(neighbor_key)
            normalized_adjacency[neighbor_key].add(zone_key)
    for zone in required_zones:
        normalized_adjacency.setdefault(zone, set())

    entrance_zones = {
        entrance: normalized_zone_by_space[entrance] for entrance in entrance_spaces
    }
    hops_by_entrance = {
        entrance: _bfs(normalized_adjacency, zone)
        for entrance, zone in entrance_zones.items()
    }
    for entrance, distances in hops_by_entrance.items():
        missing = required_zones - set(distances)
        if missing:
            raise ValueError(
                f"flow_topology_disconnected_from:{entrance}:{'|'.join(sorted(missing))}"
            )

    provisional: dict[str, dict[str, Any]] = {}
    for space in sorted(zone_by_space, key=str.casefold):
        zone_key = normalized_zone_by_space[space]
        point = normalized_centroids[zone_key]
        candidates = []
        for entrance in entrance_spaces:
            entrance_zone = entrance_zones[entrance]
            hops = hops_by_entrance[entrance][zone_key]
            straight_distance = _distance(point, normalized_centroids[entrance_zone])
            candidates.append((hops, straight_distance, entrance))
        hops, straight_distance, nearest = min(candidates)
        provisional[space] = {
            "source_space_name": space,
            "zone_name": zone_by_space[space],
            "category": category_by_space[space],
            "nearest_entrance_space": nearest,
            "adjacency_hops": int(hops),
            "centroid_distance_m": round(float(straight_distance), 6),
            "centroid_m": [round(float(value), 6) for value in point],
            "is_flow_entrance": space in entrance_spaces,
        }

    thresholds_by_entrance: dict[str, tuple[int, int]] = {}
    for entrance in entrance_spaces:
        public_hops = [
            int(row["adjacency_hops"])
            for name, row in provisional.items()
            if name not in entrance_spaces
            and row["nearest_entrance_space"] == entrance
            and row["category"] in PUBLIC_DYNAMIC_CATEGORIES
        ]
        thresholds_by_entrance[entrance] = _tercile_thresholds(public_hops)

    spaces: dict[str, dict[str, Any]] = {}
    for name, row in provisional.items():
        category = str(row["category"])
        if row["is_flow_entrance"]:
            distance_band = 0
            phase_steps = 0
            phase_basis = "declared_entrance_seed"
        else:
            distance_band = _band(
                int(row["adjacency_hops"]),
                thresholds_by_entrance[str(row["nearest_entrance_space"])],
            )
            if category in PUBLIC_DYNAMIC_CATEGORIES:
                phase_steps = distance_band
                phase_basis = "public_dynamic_adjacency_tercile"
            elif category in STAFF_CATEGORIES:
                phase_steps = 0
                phase_basis = "staff_fixed_not_entrance_delayed"
            else:
                raise ValueError(f"flow_category_unknown:{name}:{category}")
        spaces[name] = {
            **row,
            "flow_distance_band": distance_band,
            "flow_phase_steps": phase_steps,
            "flow_phase_minutes": phase_steps * 15,
            "phase_basis": phase_basis,
        }

    edges = {
        tuple(sorted((left, right)))
        for left, neighbors in normalized_adjacency.items()
        for right in neighbors
        if left in required_zones and right in required_zones and left != right
    }
    return {
        "schema_version": FLOW_TOPOLOGY_SCHEMA,
        "topology_method": "reciprocal_paired_surface_zone_adjacency_with_centroid_tie_break",
        "phase_semantics": PHASE_SEMANTICS,
        "walking_route_claim": False,
        "measured_flow_claim": False,
        "entrance_evidence": "USER_CONFIRMED_MODEL_SPACE_ANNOTATION_2026-08-18",
        "entrance_spaces": list(entrance_spaces),
        "space_count": len(spaces),
        "zone_count": len(required_zones),
        "zone_adjacency_edge_count": len(edges),
        "topology_connected": all(
            required_zones <= set(distances) for distances in hops_by_entrance.values()
        ),
        "region_counts": dict(
            sorted(Counter(row["nearest_entrance_space"] for row in spaces.values()).items())
        ),
        "phase_counts": dict(
            sorted(Counter(str(row["flow_phase_steps"]) for row in spaces.values()).items())
        ),
        "region_public_hop_tercile_thresholds": {
            entrance: list(thresholds_by_entrance[entrance])
            for entrance in entrance_spaces
        },
        "spaces": spaces,
    }


def build_source_flow_topology(
    audit: Mapping[str, Any],
    idf_path: Path,
    idd: IDDSchema,
) -> dict[str, Any]:
    """Extract exact Space/Zone centroids and paired-surface adjacency from an IDF."""

    path = Path(idf_path)
    document = parse_idf(path.read_text(encoding="utf-8"))
    graph = build_geometry_graph(document, idd)
    zone_by_space = {
        str(row["source_space_name"]): str(row["thermal_zone"])
        for row in audit["spaces"]
    }
    category_by_space = {
        str(row["source_space_name"]): str(row["room_category"])
        for row in audit["spaces"]
    }
    surfaces_by_zone: dict[str, list[Any]] = defaultdict(list)
    for surface in graph.surfaces.values():
        if surface.zone_name and surface.area > 0.0:
            surfaces_by_zone[canonical(surface.zone_name)].append(surface)
    centroids: dict[str, Point3D] = {}
    for zone in set(zone_by_space.values()):
        zone_key = canonical(zone)
        surfaces = [
            surface
            for surface in surfaces_by_zone.get(zone_key, ())
            if canonical(surface.surface_type) == "floor"
        ]
        if not surfaces:
            surfaces = surfaces_by_zone.get(zone_key, [])
        total_area = math.fsum(surface.area for surface in surfaces)
        if total_area <= 0.0:
            raise ValueError(f"flow_zone_surfaces_missing:{zone}")
        centroids[zone_key] = tuple(
            math.fsum(surface.centroid[index] * surface.area for surface in surfaces)
            / total_area
            for index in range(3)
        )  # type: ignore[assignment]

    adjacency: dict[str, set[str]] = defaultdict(set)
    for relation in graph.paired_surface_edges:
        if not relation.reciprocal:
            continue
        left = graph.surfaces[relation.left_surface_id]
        right = graph.surfaces[relation.right_surface_id]
        left_zone = canonical(left.zone_name)
        right_zone = canonical(right.zone_name)
        if left_zone and right_zone and left_zone != right_zone:
            adjacency[left_zone].add(right_zone)
            adjacency[right_zone].add(left_zone)
    topology = assign_flow_topology(
        zone_by_space=zone_by_space,
        category_by_space=category_by_space,
        zone_centroids=centroids,
        zone_adjacency=adjacency,
    )
    return {
        **topology,
        "source_idf_sha256": document.sha256,
        "geometry_coordinate_system": graph.coordinate_system,
        "paired_surface_relation_count": len(graph.paired_surface_edges),
    }


def write_flow_artifacts(
    topology: Mapping[str, Any],
    *,
    private_json_path: Path,
    public_mapping_path: Path,
) -> tuple[Path, Path]:
    """Write a private exact topology and a coordinate-free review mapping."""

    private_path = Path(private_json_path)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(
        json.dumps(topology, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    public_path = Path(public_mapping_path)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "source_space_name",
        "category",
        "nearest_entrance_space",
        "adjacency_hops",
        "flow_distance_band",
        "flow_phase_steps",
        "flow_phase_minutes",
        "is_flow_entrance",
        "phase_basis",
        "phase_semantics",
    )
    with public_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for name, row in sorted(topology["spaces"].items(), key=lambda item: item[0].casefold()):
            writer.writerow(
                {
                    **{field: row.get(field) for field in fieldnames if field != "phase_semantics"},
                    "phase_semantics": topology["phase_semantics"],
                }
            )
    return private_path, public_path


__all__ = [
    "ENTRANCE_SPACES",
    "FLOW_TOPOLOGY_SCHEMA",
    "PHASE_SEMANTICS",
    "assign_flow_topology",
    "build_source_flow_topology",
    "write_flow_artifacts",
]
