from __future__ import annotations

import csv
import json

import pytest

from idfrepair.analysis.airport_abm.seasonal_schedule import (
    SeasonalScheduleError,
    write_repeated_daily_schedule,
)
from idfrepair.analysis.airport_abm.source import SourceSpace


def _space(name: str, design_people: float | None) -> SourceSpace:
    return SourceSpace(
        name=name,
        thermal_zone=f"zone-{name}",
        region="north",
        function="domestic_waiting",
        source_function="domestic_waiting",
        original_space_type="fixture",
        area_m2=100.0,
        people_m2_per_person=(10.0 if design_people is not None else None),
        source_design_people=design_people,
        public_air_loop="N-VAV",
        office_doas=None,
        zone_hvac=None,
    )


def test_repeated_daily_schedule_has_full_calendar_and_preserves_values(tmp_path) -> None:
    detail = {
        "schema_version": "idfrepair.airport-abm-seed-detail.v3",
        "scenario_id": "MORNING_BANK",
        "seed": 40003,
        "interval_minutes": 15,
        "interval_labels": [f"step-{index}" for index in range(96)],
        "space_counts": {
            "gate": [float(index) for index in range(96)],
            "restroom": [1.0] * 96,
        },
        "summary": {
            "public_person_hours_bem": 1000.0,
            "staff_person_hours_bem": 100.0,
            "whole_building_peak_occupancy": 95.0,
        },
    }

    artifact = write_repeated_daily_schedule(
        spaces=(_space("gate", 10.0), _space("restroom", None)),
        detail=detail,
        output_dir=tmp_path,
    )

    assert artifact.row_count == 365 * 96
    with artifact.schedule_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["gate"]
    assert float(rows[1][0]) == 0.0
    assert float(rows[96][0]) == pytest.approx(9.5)
    assert float(rows[97][0]) == 0.0
    manifest = json.loads(artifact.manifest_path.read_text())
    assert manifest["calendar_days"] == 365
    assert manifest["spaces"][0]["source_space_name"] == "gate"
    summary = json.loads(artifact.summary_path.read_text())
    assert summary["seasonal_use_only"] is True
    assert summary["daily_profile_repetitions"] == 365


def test_repeated_daily_schedule_rejects_unknown_space(tmp_path) -> None:
    detail = {
        "schema_version": "idfrepair.airport-abm-seed-detail.v3",
        "scenario_id": "BASELINE_SPREAD",
        "seed": 40003,
        "interval_minutes": 15,
        "interval_labels": [f"step-{index}" for index in range(96)],
        "space_counts": {},
        "summary": {},
    }
    with pytest.raises(SeasonalScheduleError, match="missing Space"):
        write_repeated_daily_schedule(
            spaces=(_space("gate", 10.0),),
            detail=detail,
            output_dir=tmp_path,
        )
