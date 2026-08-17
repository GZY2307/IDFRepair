"""Compact report-table and effect-ranking contracts."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from idfrepair.analysis.occupancy_room_aware.reporting import (
    assert_same_person_hours,
    combine_result_tables,
    evaluate_paper_admission,
    ranked_effects,
)


def _row(
    scenario: str,
    *,
    category: str = "dining",
    person_hours: float = 100.0,
    heating_kwh: float = 20.0,
    cooling_peak_kw: float = 10.0,
) -> dict[str, str]:
    return {
        "scenario_id": scenario,
        "period_id": "summer",
        "category": category,
        "space_name": "",
        "person_hours": str(person_hours),
        "heating_kwh": str(heating_kwh),
        "cooling_peak_kw": str(cooling_peak_kw),
    }


def test_same_person_hours_and_ranked_effects_are_baseline_relative() -> None:
    rows = [
        _row("baseline_r"),
        _row("public_morning", heating_kwh=18.0, cooling_peak_kw=12.0),
        _row("public_evening", heating_kwh=21.0, cooling_peak_kw=15.0),
    ]

    assert_same_person_hours(
        rows,
        scenario_ids=("public_morning", "public_evening"),
        tolerance=1e-9,
    )
    effects = ranked_effects(
        rows,
        scenario_ids=("public_morning", "public_evening"),
        metrics=("heating_kwh", "cooling_peak_kw"),
    )

    assert effects[0]["scenario_id"] == "public_evening"
    assert effects[0]["metric"] == "cooling_peak_kw"
    assert effects[0]["delta"] == pytest.approx(5.0)
    assert effects[0]["delta_pct"] == pytest.approx(50.0)


def test_same_person_hours_rejects_nonconserving_counterfactual() -> None:
    rows = [_row("baseline_r"), _row("public_morning", person_hours=99.0)]

    with pytest.raises(ValueError, match="report_person_hours_not_conserved"):
        assert_same_person_hours(
            rows,
            scenario_ids=("public_morning",),
            tolerance=1e-9,
        )


def test_combine_result_tables_adds_simulation_scope(tmp_path: Path) -> None:
    header = ["scenario_id", "period_id", "person_hours"]
    seasonal = tmp_path / "seasonal.csv"
    annual = tmp_path / "annual.csv"
    for path, values in (
        (seasonal, ["baseline_r", "winter", "100"]),
        (annual, ["baseline_r", "annual", "36500"]),
    ):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerow(values)

    destination = tmp_path / "combined.csv"
    count = combine_result_tables(seasonal, annual, destination)

    rows = list(csv.DictReader(destination.open(encoding="utf-8")))
    assert count == 2
    assert [row["simulation_scope"] for row in rows] == ["seasonal", "annual"]
    assert rows[1]["person_hours"] == "36500"
    assert b"\r\n" not in destination.read_bytes()


def _effect(
    *,
    scenario: str = "public_evening",
    absolute: float = 25.0,
    relative: float = 12.0,
) -> dict[str, object]:
    return {
        "analysis_scope": "seasonal_category",
        "scenario_id": scenario,
        "period_id": "summer",
        "category": "dining",
        "space_name": "",
        "zone_name": "",
        "metric": "cooling_peak_kw",
        "baseline": 100.0,
        "value": 100.0 + absolute,
        "delta": absolute,
        "delta_pct": relative,
    }


def test_paper_admission_requires_absolute_and_relative_non_volume_effect() -> None:
    strong = evaluate_paper_admission([_effect()], evidence_valid=True)
    assert strong["status"] == "OCCUPANCY_CASE_PAPER_READY"
    assert len(strong["qualifying_effects"]) == 1

    weak_absolute = evaluate_paper_admission(
        [_effect(absolute=19.9, relative=30.0)], evidence_valid=True
    )
    weak_relative = evaluate_paper_admission(
        [_effect(absolute=30.0, relative=9.9)], evidence_valid=True
    )
    assert weak_absolute["status"] == "OCCUPANCY_CASE_DEMO_ONLY"
    assert weak_relative["status"] == "OCCUPANCY_CASE_DEMO_ONLY"


def test_paper_admission_treats_ordinary_volume_sensitivity_as_demo_only() -> None:
    decision = evaluate_paper_admission(
        [_effect(scenario="public_volume_1_50", absolute=100.0, relative=50.0)],
        evidence_valid=True,
    )
    assert decision["status"] == "OCCUPANCY_CASE_DEMO_ONLY"


def test_paper_admission_rejects_missing_or_malformed_evidence() -> None:
    assert (
        evaluate_paper_admission(None, evidence_valid=True)["status"]
        == "OCCUPANCY_CASE_NOT_ADMISSIBLE"
    )
    assert (
        evaluate_paper_admission([{"scenario_id": "public_evening"}], evidence_valid=True)[
            "status"
        ]
        == "OCCUPANCY_CASE_NOT_ADMISSIBLE"
    )
    assert (
        evaluate_paper_admission([_effect()], evidence_valid=False)["status"]
        == "OCCUPANCY_CASE_NOT_ADMISSIBLE"
    )
