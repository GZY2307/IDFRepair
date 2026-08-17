"""Entrance-seeded, source-geometry occupancy-flow tests."""

from __future__ import annotations

from collections import defaultdict

import pytest

from idfrepair.analysis.occupancy_room_aware.flow import (
    ENTRANCE_SPACES,
    assign_flow_topology,
)
from idfrepair.analysis.occupancy_room_aware.profiles import (
    PUBLIC_DYNAMIC_CATEGORIES,
    STAFF_CATEGORIES,
    apply_entrance_phase_profiles,
    build_category_profiles,
    build_entrance_region_scenarios,
)


def _synthetic_topology() -> dict:
    zone_by_space = {
        "z-u-hall-2": "entry-a",
        "z-u-hall-3": "entry-b",
        "hall-a-near": "a1",
        "commerce-a-mid": "a2",
        "dining-a-far": "a3",
        "hall-b-near": "b1",
        "restroom-b-mid": "b2",
        "commerce-b-far": "b3",
        "office-a": "oa",
        "breakroom-b": "bb",
    }
    category_by_space = {
        "z-u-hall-2": "terminal_hall",
        "z-u-hall-3": "terminal_hall",
        "hall-a-near": "terminal_hall",
        "commerce-a-mid": "commerce_retail",
        "dining-a-far": "dining",
        "hall-b-near": "terminal_hall",
        "restroom-b-mid": "restroom",
        "commerce-b-far": "commerce_retail",
        "office-a": "office",
        "breakroom-b": "breakroom",
    }
    centroids = {
        "entry-a": (0.0, 0.0, 0.0),
        "a1": (1.0, 0.0, 0.0),
        "a2": (2.0, 0.0, 0.0),
        "a3": (3.0, 0.0, 0.0),
        "oa": (2.0, 1.0, 0.0),
        "entry-b": (10.0, 0.0, 0.0),
        "b1": (9.0, 0.0, 0.0),
        "b2": (8.0, 0.0, 0.0),
        "b3": (7.0, 0.0, 0.0),
        "bb": (8.0, 1.0, 0.0),
    }
    adjacency: dict[str, set[str]] = defaultdict(set)
    for left, right in (
        ("entry-a", "a1"),
        ("a1", "a2"),
        ("a2", "a3"),
        ("a2", "oa"),
        ("a3", "b3"),
        ("b3", "b2"),
        ("b2", "b1"),
        ("b2", "bb"),
        ("b1", "entry-b"),
    ):
        adjacency[left].add(right)
        adjacency[right].add(left)
    return assign_flow_topology(
        zone_by_space=zone_by_space,
        category_by_space=category_by_space,
        zone_centroids=centroids,
        zone_adjacency=adjacency,
    )


def test_two_declared_entrances_seed_distinct_connected_regions() -> None:
    topology = _synthetic_topology()
    spaces = topology["spaces"]

    assert topology["entrance_spaces"] == list(ENTRANCE_SPACES)
    assert topology["space_count"] == 10
    assert topology["topology_connected"] is True
    for entrance in ENTRANCE_SPACES:
        row = spaces[entrance]
        assert row["is_flow_entrance"] is True
        assert row["nearest_entrance_space"] == entrance
        assert row["adjacency_hops"] == 0
        assert row["flow_phase_steps"] == 0
    assert spaces["hall-a-near"]["nearest_entrance_space"] == "z-u-hall-2"
    assert spaces["hall-b-near"]["nearest_entrance_space"] == "z-u-hall-3"
    assert {
        row["nearest_entrance_space"] for row in spaces.values()
    } == set(ENTRANCE_SPACES)


def test_public_response_is_phased_but_staff_is_not_flow_delayed() -> None:
    topology = _synthetic_topology()
    spaces = topology["spaces"]

    for name, row in spaces.items():
        if row["category"] in PUBLIC_DYNAMIC_CATEGORIES and name not in ENTRANCE_SPACES:
            assert row["flow_distance_band"] in {1, 2, 3}
            assert row["flow_phase_steps"] == row["flow_distance_band"]
            assert row["flow_phase_minutes"] in {15, 30, 45}
        if row["category"] in STAFF_CATEGORIES:
            assert row["flow_phase_steps"] == 0
            assert row["flow_phase_minutes"] == 0


def test_nearest_entrance_tie_break_is_deterministic() -> None:
    topology = assign_flow_topology(
        zone_by_space={
            "z-u-hall-2": "a",
            "z-u-hall-3": "b",
            "middle": "m",
        },
        category_by_space={
            "z-u-hall-2": "terminal_hall",
            "z-u-hall-3": "terminal_hall",
            "middle": "terminal_hall",
        },
        zone_centroids={
            "a": (0.0, 0.0, 0.0),
            "b": (2.0, 0.0, 0.0),
            "m": (1.0, 0.0, 0.0),
        },
        zone_adjacency={"a": {"m"}, "m": {"a", "b"}, "b": {"m"}},
    )

    assert topology["spaces"]["middle"]["nearest_entrance_space"] == "z-u-hall-2"


def test_phase_profiles_and_region_leads_preserve_every_space_person_hours() -> None:
    topology = _synthetic_topology()
    category_by_space = {
        name: row["category"] for name, row in topology["spaces"].items()
    }
    category_profiles = build_category_profiles()
    baseline = apply_entrance_phase_profiles(
        category_profiles,
        category_by_space,
        topology,
    )
    scenarios = build_entrance_region_scenarios(
        baseline,
        category_by_space,
        topology,
    )

    assert set(scenarios) == {"entrance_2_lead", "entrance_3_lead"}
    assert len(set(baseline.values())) > len(category_profiles)
    for name, profile in baseline.items():
        assert sum(profile) == pytest.approx(
            sum(category_profiles[category_by_space[name]]), abs=1e-12
        )
    for scenario in scenarios.values():
        for name, profile in scenario.items():
            assert sum(profile) == pytest.approx(sum(baseline[name]), abs=1e-12)
            if category_by_space[name] in STAFF_CATEGORIES:
                assert profile is baseline[name]
    assert (
        scenarios["entrance_2_lead"]["hall-a-near"]
        != scenarios["entrance_3_lead"]["hall-a-near"]
    )
    assert (
        scenarios["entrance_2_lead"]["hall-b-near"]
        != scenarios["entrance_3_lead"]["hall-b-near"]
    )


def test_invalid_entrance_category_is_rejected() -> None:
    with pytest.raises(ValueError, match="flow_entrance_not_terminal_hall"):
        assign_flow_topology(
            zone_by_space={"z-u-hall-2": "a", "z-u-hall-3": "b"},
            category_by_space={"z-u-hall-2": "office", "z-u-hall-3": "terminal_hall"},
            zone_centroids={"a": (0.0, 0.0, 0.0), "b": (1.0, 0.0, 0.0)},
            zone_adjacency={"a": {"b"}, "b": {"a"}},
        )
