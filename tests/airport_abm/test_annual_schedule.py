from __future__ import annotations

import json
from pathlib import Path

import pytest

from idfrepair.analysis.airport_abm.annual_schedule import (
    AnnualScheduleError,
    annual_day_seed,
    write_people_manifest,
)
from idfrepair.analysis.airport_abm.source import SourceSpace


def _space(name: str, capacity: float | None) -> SourceSpace:
    return SourceSpace(
        name,
        f"zone-{name}",
        "region",
        "domestic_waiting" if capacity is not None else "restroom",
        "domestic_waiting" if capacity is not None else "restroom",
        "type",
        100.0,
        None if capacity is None else 100.0 / capacity,
        capacity,
        "loop",
        None,
        None,
    )


def test_annual_master_seed_creates_365_distinct_deterministic_day_streams() -> None:
    first = tuple(annual_day_seed(40015, index) for index in range(365))
    second = tuple(annual_day_seed(40015, index) for index in range(365))

    assert first == second
    assert len(set(first)) == 365
    with pytest.raises(AnnualScheduleError, match="day index"):
        annual_day_seed(40015, 365)


def test_people_manifest_columns_match_sorted_supported_spaces(tmp_path: Path) -> None:
    schedule = tmp_path / "annual.csv"
    schedule.write_text("a,b\n", encoding="utf-8")
    output = write_people_manifest(
        tmp_path / "manifest.json",
        schedule_path=schedule,
        spaces=(_space("b", 20), _space("restroom", None), _space("a", 10)),
        days=365,
        interval_minutes=15,
    )

    payload = json.loads(output.read_text())
    assert payload["schema_version"] == "idfrepair.airport-abm-people-manifest.v3"
    assert payload["spaces"] == [
        {
            "source_space_name": "a",
            "schedule_column": 1,
            "source_design_people": 10,
            "source_design_people_tolerance": pytest.approx(0.000050001),
        },
        {
            "source_space_name": "b",
            "schedule_column": 2,
            "source_design_people": 20,
            "source_design_people_tolerance": pytest.approx(0.000100001),
        },
    ]
