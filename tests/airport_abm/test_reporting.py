from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def test_linear_quantiles_are_hand_checkable() -> None:
    from idfrepair.analysis.airport_abm.reporting import quantile

    values = [0, 10, 20, 30, 40]
    assert quantile(values, 0.1) == pytest.approx(4)
    assert quantile(values, 0.5) == pytest.approx(20)
    assert quantile(values, 0.9) == pytest.approx(36)


def test_seed_summary_and_matched_person_hours() -> None:
    from idfrepair.analysis.airport_abm.reporting import (
        assert_matched_person_hours,
        summarize_seed_metric,
    )

    rows = [
        {"scenario_id": "MORNING_BANK", "seed": 1, "person_hours": 100, "peak": 10},
        {"scenario_id": "MORNING_BANK", "seed": 2, "person_hours": 100, "peak": 20},
        {"scenario_id": "EVENING_BANK", "seed": 1, "person_hours": 100, "peak": 12},
        {"scenario_id": "EVENING_BANK", "seed": 2, "person_hours": 100, "peak": 22},
    ]

    assert_matched_person_hours(
        rows,
        scenario_ids=("MORNING_BANK", "EVENING_BANK"),
        value_field="person_hours",
        tolerance=1e-9,
    )
    summary = summarize_seed_metric(rows, metric="peak")
    assert summary["MORNING_BANK"] == pytest.approx(
        {"mean": 15, "p10": 11, "p50": 15, "p90": 19, "minimum": 10, "maximum": 20}
    )


def test_person_hour_mismatch_is_a_hard_failure() -> None:
    from idfrepair.analysis.airport_abm.reporting import (
        ReportingError,
        assert_matched_person_hours,
    )

    rows = [
        {"scenario_id": "A", "seed": 1, "person_hours": 100},
        {"scenario_id": "B", "seed": 1, "person_hours": 101},
    ]
    with pytest.raises(ReportingError, match="person-hours"):
        assert_matched_person_hours(
            rows,
            scenario_ids=("A", "B"),
            value_field="person_hours",
            tolerance=0.01,
        )


def test_paired_energy_deltas_and_uncertainty_are_hand_checkable() -> None:
    from idfrepair.analysis.airport_abm.reporting import (
        paired_deltas,
        summarize_delta_rows,
    )

    rows = [
        {"scenario_id": "BASE", "seed": 1, "period": "summer", "group": "loop-a", "value": 100},
        {"scenario_id": "BASE", "seed": 2, "period": "summer", "group": "loop-a", "value": 200},
        {"scenario_id": "SHIFT", "seed": 1, "period": "summer", "group": "loop-a", "value": 110},
        {"scenario_id": "SHIFT", "seed": 2, "period": "summer", "group": "loop-a", "value": 180},
    ]

    deltas = paired_deltas(
        rows,
        baseline_scenario="BASE",
        comparison_scenario="SHIFT",
        identity_fields=("seed", "period", "group"),
    )

    assert [row["difference"] for row in deltas] == [10, -20]
    assert [row["percent_difference"] for row in deltas] == pytest.approx([10, -10])
    summary = summarize_delta_rows(deltas)
    assert summary == pytest.approx(
        {
            "count": 2,
            "difference_p10": -17,
            "difference_p50": -5,
            "difference_p90": 7,
            "percent_p10": -8,
            "percent_p50": 0,
            "percent_p90": 8,
        }
    )


def test_paired_energy_deltas_reject_missing_or_zero_baselines() -> None:
    from idfrepair.analysis.airport_abm.reporting import ReportingError, paired_deltas

    with pytest.raises(ReportingError, match="paired identities"):
        paired_deltas(
            [
                {"scenario_id": "BASE", "seed": 1, "value": 10},
                {"scenario_id": "SHIFT", "seed": 2, "value": 12},
            ],
            baseline_scenario="BASE",
            comparison_scenario="SHIFT",
            identity_fields=("seed",),
        )
    with pytest.raises(ReportingError, match="zero baseline"):
        paired_deltas(
            [
                {"scenario_id": "BASE", "seed": 1, "value": 0},
                {"scenario_id": "SHIFT", "seed": 1, "value": 12},
            ],
            baseline_scenario="BASE",
            comparison_scenario="SHIFT",
            identity_fields=("seed",),
        )


def test_occupancy_report_timing_table_uses_current_run_person_hours() -> None:
    script = Path(__file__).parents[2] / "scripts" / "airport_abm" / "generate_occupancy_reports.py"
    spec = importlib.util.spec_from_file_location("generate_occupancy_reports", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    peak = {
        scenario: {"p10": 1.0, "p50": 2.0, "p90": 3.0}
        for scenario in module.TIMING
    }
    public_person_hours = {
        scenario: {"p50": 151_895.577}
        for scenario in module.TIMING
    }

    table = module.timing_table(peak, public_person_hours)

    assert "151,895.6" in table
    assert "585,765.8" not in table


def test_energy_report_supports_explicit_single_seed_demo_without_inventing_five_pairs(
    tmp_path: Path,
) -> None:
    script = Path(__file__).parents[2] / "scripts" / "airport_abm" / "generate_energy_reports.py"
    spec = importlib.util.spec_from_file_location("generate_energy_reports", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    rows = []
    for scenario, value in (("BASELINE_SPREAD", 100.0), ("MORNING_BANK", 110.0)):
        rows.append(
            {
                "scenario_id": scenario,
                "seed": 40015,
                "run_kind": "shoulder",
                "period_id": "shoulder",
                "scope": "building",
                "group": "whole_building",
                "metric": "facility_electricity_kwh",
                "value": value,
                "unit": "kWh",
            }
        )

    effects = module.timing_effects(rows)

    assert len(effects) == 1
    assert effects[0]["paired_seed_count"] == 1
    assert effects[0]["difference_p50"] == 10.0
    assert effects[0]["percent_p50"] == pytest.approx(10.0)

    report = tmp_path / "energy.md"
    module.write_markdown(
        report,
        summary_rows=module.grouped_summary(
            rows,
            fields=("scenario_id", "run_kind", "period_id", "scope", "group", "metric"),
        ),
        effects=effects,
        loop_effects=[],
        annual_person_hours={},
    )
    text = report.read_text()
    assert "PASS_CONTROLLED_REPRESENTATIVE_DAY_DEMO" in text
    assert "PASS_SEASONAL`" not in text
    assert "Fixed-seed paired timing effect" in text
