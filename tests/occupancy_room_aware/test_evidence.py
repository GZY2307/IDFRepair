"""验证 room-aware 参数证据制度与文献边界。"""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import pytest

from idfrepair.analysis.occupancy_room_aware.evidence import (
    ASHRAE_BREAKROOM_M2_PER_PERSON,
    literature_evidence_records,
    parameter_evidence_records,
    validate_evidence_registry,
)
from idfrepair.analysis.occupancy_room_aware.models import EvidenceStatus


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOM_REGISTRY = (
    PROJECT_ROOT / "reports" / "occupancy_v2" / "room_function_registry.csv"
)
EVIDENCE_REPORT = (
    PROJECT_ROOT / "docs" / "research" / "occupancy" / "room_aware_parameter_evidence.md"
)


def _record(category: str, parameter: str):
    matches = [
        row
        for row in parameter_evidence_records()
        if row.category == category and row.parameter == parameter
    ]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize(
    ("category", "expected_m2_per_person", "source_id"),
    [
        ("office", 6.0, "PROJECT_HVAC_NOTES_SJSM05"),
        ("commerce_retail", 5.0, "PROJECT_HVAC_NOTES_SJSM05"),
        ("dining", 2.5, "PROJECT_HVAC_NOTES_SJSM05"),
        ("breakroom", ASHRAE_BREAKROOM_M2_PER_PERSON, "ASHRAE_62_1_2022_AB"),
    ],
)
def test_only_supported_room_density_values_are_adopted(
    category: str,
    expected_m2_per_person: float,
    source_id: str,
) -> None:
    row = _record(category, "design_density_m2_per_person")

    assert row.value == pytest.approx(expected_m2_per_person)
    assert row.unit == "m2/person"
    assert row.tier is EvidenceStatus.STANDARD_OR_LITERATURE_BACKED
    assert row.source_id == source_id
    assert row.auto_fill_allowed is True
    assert row.use_scope == "BASELINE_R_PEOPLE_ONLY"


def test_breakroom_density_conversion_is_exact() -> None:
    assert ASHRAE_BREAKROOM_M2_PER_PERSON == pytest.approx(92.90304 / 25.0)
    assert 1.0 / ASHRAE_BREAKROOM_M2_PER_PERSON == pytest.approx(
        25.0 / 92.90304
    )


@pytest.mark.parametrize("category", ["terminal_hall", "restroom"])
def test_unsupported_room_density_is_explicitly_rejected(category: str) -> None:
    row = _record(category, "design_density_m2_per_person")

    assert row.value is None
    assert row.tier is EvidenceStatus.DO_NOT_AUTOFILL
    assert row.auto_fill_allowed is False
    assert "unresolved" in row.applicability.lower()


def test_project_outdoor_air_values_are_isolated_from_people_baseline() -> None:
    office = _record("office", "outdoor_air_per_person_m3_s_person")
    commerce = _record("commerce_retail", "outdoor_air_per_person_m3_s_person")
    dining = _record("dining", "outdoor_air_per_person_m3_s_person")

    assert office.value == pytest.approx(30.0 / 3600.0)
    assert commerce.value == pytest.approx(30.0 / 3600.0)
    assert dining.value == pytest.approx(25.0 / 3600.0)
    assert {office.use_scope, commerce.use_scope, dining.use_scope} == {
        "REFERENCE_OA_IDEALLOADS_SENSITIVITY"
    }


def test_restroom_exhaust_evidence_does_not_authorize_topology_synthesis() -> None:
    row = _record("restroom", "exhaust_air_changes_per_hour")

    assert row.value == pytest.approx(15.0)
    assert row.auto_fill_allowed is False
    assert row.use_scope == "DOCUMENTED_NOT_IMPLEMENTED"
    assert "topology" in row.does_not_support.lower()


def test_every_numeric_record_has_complete_provenance() -> None:
    records = parameter_evidence_records()

    validate_evidence_registry(records, literature_evidence_records())
    for row in records:
        if row.value is None:
            continue
        assert row.unit
        assert row.tier
        assert row.source_id
        assert row.locator
        assert row.source_url or row.source_sha256
        assert row.applicability
        assert row.confidence
        assert row.use_scope


def test_invalid_numeric_evidence_fails_closed() -> None:
    records = list(parameter_evidence_records())
    numeric = next(row for row in records if row.value is not None)
    records[records.index(numeric)] = replace(numeric, locator="")

    with pytest.raises(ValueError, match="numeric_evidence_incomplete"):
        validate_evidence_registry(tuple(records), literature_evidence_records())


def test_required_airport_literature_is_complete_and_not_used_as_calibration() -> None:
    literature = literature_evidence_records()
    dois = {row.doi.lower() for row in literature}

    assert {
        "10.26868/25222708.2019.211133",
        "10.1016/j.buildenv.2019.03.011",
        "10.1016/j.buildenv.2021.108147",
        "10.1016/j.scs.2021.103619",
        "10.1177/1420326x221074222",
        "10.1016/j.seta.2024.103790",
        "10.1016/j.buildenv.2025.112781",
        "10.1016/j.buildenv.2025.112829",
        "10.1016/j.rser.2025.116287",
    } <= dois
    assert all(row.transfer_decision == "NO_NUMERIC_TRANSFER" for row in literature)
    assert all(row.supports and row.does_not_support for row in literature)


def test_machine_parameter_registry_contains_no_invented_airport_subfunction() -> None:
    serialized = "\n".join(
        "|".join(
            (
                row.category,
                row.parameter,
                row.applicability,
                row.supports,
                row.does_not_support,
            )
        ).lower()
        for row in parameter_evidence_records()
    )

    for forbidden in (
        "check-in",
        "gate",
        "baggage",
        "security",
        "immigration",
        "arrivals",
        "departures",
    ):
        assert forbidden not in serialized


def test_committed_registry_and_evidence_report_match_machine_records() -> None:
    with ROOM_REGISTRY.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 6
    assert sum(int(row["space_count"]) for row in rows) == 304
    by_category = {row["category"]: row for row in rows}
    assert "6 m2/person" in by_category["office"]["proposed_people_model"]
    assert by_category["terminal_hall"]["auto_fill_allowed"] == "false"
    assert by_category["restroom"]["auto_fill_allowed"] == "false"
    text = EVIDENCE_REPORT.read_text(encoding="utf-8")
    assert "REAL_HVAC_DESIGN_EVIDENCE_PRESENT" in text
    assert "HVAC_TOPOLOGY_UNRESOLVED" in text
    assert "10.1016/j.rser.2025.116287" in text
    assert "/" + "Users/" not in text
