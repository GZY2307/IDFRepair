"""验证六类 profile、occupant class 与守恒反事实。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from idfrepair.analysis.occupancy_room_aware.profiles import (
    PUBLIC_DYNAMIC_CATEGORIES,
    STAFF_CATEGORIES,
    SpaceCapacity,
    allocate_spatial_counts,
    apply_public_volume,
    build_category_profiles,
    build_temporal_scenarios,
    person_hours,
    profile_digest,
    render_protocol,
)


DESIGN_PEOPLE = {
    "terminal_hall": 8000.0,
    "office": 1000.0,
    "commerce_retail": 1800.0,
    "dining": 500.0,
    "restroom": 700.0,
    "breakroom": 100.0,
}


def test_six_profiles_are_distinct_bounded_and_deterministic() -> None:
    first = build_category_profiles()
    second = build_category_profiles()

    assert set(first) == set(DESIGN_PEOPLE)
    assert first == second
    assert len(set(first.values())) == 6
    assert len({profile_digest(values) for values in first.values()}) == 6
    for values in first.values():
        assert len(values) == 96
        assert all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values)
        assert len(profile_digest(values)) == 64


def test_restroom_profile_is_bounded_and_public_linked_without_dwell_claim() -> None:
    profiles = build_category_profiles()
    restroom = profiles["restroom"]
    public_signal = tuple(
        0.70 * hall + 0.15 * commerce + 0.15 * dining
        for hall, commerce, dining in zip(
            profiles["terminal_hall"],
            profiles["commerce_retail"],
            profiles["dining"],
            strict=True,
        )
    )

    assert max(restroom) <= 0.35
    assert min(restroom) >= 0.01
    assert restroom[public_signal.index(max(public_signal))] > restroom[0]


def test_temporal_public_redistributions_preserve_hours_and_staff_bitwise() -> None:
    baseline = build_category_profiles()
    scenarios = build_temporal_scenarios(baseline)
    reference_public = person_hours(
        baseline,
        DESIGN_PEOPLE,
        categories=PUBLIC_DYNAMIC_CATEGORIES,
    )
    reference_staff = person_hours(
        baseline,
        DESIGN_PEOPLE,
        categories=STAFF_CATEGORIES,
    )

    assert set(scenarios) == {"public_morning", "public_midday", "public_evening"}
    for profiles in scenarios.values():
        assert person_hours(
            profiles,
            DESIGN_PEOPLE,
            categories=PUBLIC_DYNAMIC_CATEGORIES,
        ) == pytest.approx(reference_public, abs=1e-9)
        assert person_hours(
            profiles,
            DESIGN_PEOPLE,
            categories=STAFF_CATEGORIES,
        ) == reference_staff
        for category in STAFF_CATEGORIES:
            assert profiles[category] is baseline[category]
        for category in PUBLIC_DYNAMIC_CATEGORIES:
            assert sum(profiles[category]) == pytest.approx(
                sum(baseline[category]), abs=1e-12
            )
    assert scenarios["public_morning"] != scenarios["public_evening"]


@pytest.mark.parametrize("multiplier", [0.5, 0.75, 1.0, 1.25, 1.5])
def test_volume_multiplier_changes_terminal_public_only(multiplier: float) -> None:
    baseline = build_category_profiles()
    scaled = apply_public_volume(baseline, multiplier)

    for category in set(baseline) - {"terminal_hall"}:
        assert scaled[category] is baseline[category]
    assert scaled["terminal_hall"] == pytest.approx(
        tuple(value * multiplier for value in baseline["terminal_hall"]),
        abs=1e-12,
    )
    assert max(scaled["terminal_hall"]) <= 1.0


def test_spatial_allocation_stays_within_category_and_capacity() -> None:
    spaces = (
        SpaceCapacity("hall-perimeter", "terminal_hall", 100.0, 80.0, 100.0),
        SpaceCapacity("hall-core", "terminal_hall", 100.0, 5.0, 100.0),
        SpaceCapacity("commerce-perimeter", "commerce_retail", 30.0, 30.0, 50.0),
        SpaceCapacity("commerce-core", "commerce_retail", 30.0, 0.0, 50.0),
        SpaceCapacity("office-fixed", "office", 20.0, 20.0, 40.0),
    )
    totals = {"terminal_hall": 120.0, "commerce_retail": 40.0}

    perimeter = allocate_spatial_counts(totals, spaces, mode="perimeter")
    core = allocate_spatial_counts(totals, spaces, mode="core")

    for allocation in (perimeter, core):
        assert set(allocation) == {
            "hall-perimeter",
            "hall-core",
            "commerce-perimeter",
            "commerce-core",
        }
        assert sum(
            allocation[name] for name in ("hall-perimeter", "hall-core")
        ) == pytest.approx(120.0, abs=1e-9)
        assert sum(
            allocation[name]
            for name in ("commerce-perimeter", "commerce-core")
        ) == pytest.approx(40.0, abs=1e-9)
        for space in spaces:
            if space.space_name in allocation:
                assert 0.0 <= allocation[space.space_name] <= space.design_people
    assert perimeter["hall-perimeter"] > core["hall-perimeter"]
    assert core["hall-core"] > perimeter["hall-core"]


def test_spatial_allocation_rejects_over_capacity() -> None:
    spaces = (
        SpaceCapacity("hall-one", "terminal_hall", 10.0, 1.0, 10.0),
    )

    with pytest.raises(ValueError, match="category_capacity_exceeded"):
        allocate_spatial_counts(
            {"terminal_hall": 10.01}, spaces, mode="perimeter"
        )


def test_protocol_records_controlled_boundary_and_annual_gate(tmp_path: Path) -> None:
    output = tmp_path / "room_aware_protocol.md"

    render_protocol(output)

    text = output.read_text(encoding="utf-8")
    assert "CONTROLLED_NOT_MEASURED" in text
    assert "public-facing-unsplit" in text
    assert "person-hours" in text
    assert "staff fixed" in text.lower()
    assert "Winter" in text and "Summer" in text and "Shoulder" in text
    assert "ANNUAL_RUNTIME_GATE" in text
    assert "geometry is not used for room-function classification" in text.lower()

