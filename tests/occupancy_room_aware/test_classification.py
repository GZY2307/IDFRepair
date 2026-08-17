"""验证房间功能分类严格依赖 ``OS:Space.Name`` 明确 token。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from idfrepair.analysis.occupancy_room_aware.classification import (
    classify_space_name,
)
from idfrepair.analysis.occupancy_room_aware.models import (
    ClassificationStatus,
    RoomCategory,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("P1-hall-001", RoomCategory.TERMINAL_HALL),
        ("north OFFICE 2", RoomCategory.OFFICE),
        ("z_u-commerce-8", RoomCategory.COMMERCE_RETAIL),
        ("P2 dining 03", RoomCategory.DINING),
        ("x-restroom2", RoomCategory.RESTROOM),
        ("south_breakroom_9", RoomCategory.BREAKROOM),
    ],
)
def test_exact_tokens_accept_digit_space_hyphen_and_underscore_boundaries(
    name: str,
    expected: RoomCategory,
) -> None:
    decision = classify_space_name(name)

    assert decision.status is ClassificationStatus.CLASSIFIED
    assert decision.category is expected
    assert len(decision.matched_tokens) == 1


@pytest.mark.parametrize(
    "name",
    [
        "smalloffice",
        "hallway",
        "commercial",
        "diningroom",
        "restroomsuite",
        "breakroomsuite",
        "P1-gate-001",
        "P2-check-in-002",
    ],
)
def test_unknown_or_embedded_tokens_fail_closed(name: str) -> None:
    decision = classify_space_name(name)

    assert decision.status is ClassificationStatus.UNKNOWN
    assert decision.category is None
    assert decision.matched_tokens == ()
    assert decision.reason == "NO_EXPLICIT_ROOM_TOKEN"


def test_multiple_room_tokens_are_rejected_instead_of_prioritized() -> None:
    decision = classify_space_name("P2-hall-office-ambiguous")

    assert decision.status is ClassificationStatus.MULTIPLE
    assert decision.category is None
    assert decision.matched_tokens == ("hall", "office")
    assert decision.reason == "MULTIPLE_EXPLICIT_ROOM_TOKENS"


def test_decision_is_immutable() -> None:
    decision = classify_space_name("office-1")

    with pytest.raises(FrozenInstanceError):
        decision.reason = "changed"  # type: ignore[misc]


def test_no_airport_subfunction_is_in_classifier_vocabulary() -> None:
    labels = {
        classify_space_name(name).category
        for name in ("check-in", "gate", "baggage", "security", "arrivals")
    }

    assert labels == {None}

