"""验证 occupancy 结果汇总和 admission gate。"""

from __future__ import annotations

import pytest

from idfrepair.analysis.occupancy.models import MetricRow
from idfrepair.analysis.occupancy.reporting import (
    OccupancyAdmissionEvidence,
    decide_occupancy_status,
    summarize_metric_rows,
)


def _row(
    timestamp: str,
    key: str,
    variable: str,
    value: float,
    *,
    mechanism: str,
    unit: str,
) -> MetricRow:
    return MetricRow(
        timestamp=timestamp,
        key_name=key,
        variable_name=variable,
        unit=unit,
        frequency="TimeStep",
        mechanism=mechanism,
        availability="available",
        value=value,
    )


def test_metric_summary_aggregates_daily_energy_and_simultaneous_peak() -> None:
    """日能量按 zone/time 累加，峰值先按同一时刻聚合再取最大。"""

    rows = (
        _row("00:15", "Z1", "Zone People Occupant Count", 10, mechanism="occupancy", unit="person"),
        _row("00:15", "Z2", "Zone People Occupant Count", 20, mechanism="occupancy", unit="person"),
        _row("00:30", "Z1", "Zone People Occupant Count", 15, mechanism="occupancy", unit="person"),
        _row("00:30", "Z2", "Zone People Occupant Count", 5, mechanism="occupancy", unit="person"),
        _row("00:15", "Z1", "Zone Ideal Loads Supply Air Total Cooling Energy", 3_600_000, mechanism="ideal_loads", unit="J"),
        _row("00:15", "Z2", "Zone Ideal Loads Supply Air Total Cooling Energy", 1_800_000, mechanism="ideal_loads", unit="J"),
        _row("00:15", "Z1", "Zone Ideal Loads Supply Air Total Cooling Rate", 2_000, mechanism="ideal_loads", unit="W"),
        _row("00:15", "Z2", "Zone Ideal Loads Supply Air Total Cooling Rate", 3_000, mechanism="ideal_loads", unit="W"),
        _row("00:30", "Z1", "Zone Ideal Loads Supply Air Total Cooling Rate", 1_000, mechanism="ideal_loads", unit="W"),
        _row("00:30", "Z2", "Zone Ideal Loads Supply Air Total Cooling Rate", 2_000, mechanism="ideal_loads", unit="W"),
    )

    summary = summarize_metric_rows(
        scenario_name="fixture",
        kind="temporal_redistribution",
        rows=rows,
        compiled_passenger_hours=12.5,
        reference_passenger_hours=12.5,
        minutes_per_step=15.0,
        run_status="PASS",
    )

    assert summary.occupant_peak == 30.0
    assert summary.occupant_peak_time == "00:15"
    assert summary.occupant_hours_from_output == pytest.approx(12.5)
    assert summary.synthetic_cooling_kwh == pytest.approx(1.5)
    assert summary.synthetic_cooling_peak_kw == pytest.approx(5.0)
    assert summary.synthetic_cooling_peak_time == "00:15"


def test_admission_gate_never_promotes_synthetic_hvac_demo() -> None:
    """无原始 HVAC/年度基线时，即便受控场景稳定也只能 Demo。"""

    evidence = OccupancyAdmissionEvidence(
        provenance_clear=True,
        annual_baseline_stable=False,
        spatial_people_difference=True,
        original_real_hvac=False,
        same_person_hours_reproducible=True,
        interpretable_distribution_response=True,
        frozen_method_unchanged=True,
        controlled_demo_stable=True,
        only_commonplace_volume_result=False,
    )

    assert decide_occupancy_status(evidence) == "OCCUPANCY_DEMO_ONLY"


def test_admission_gate_distinguishes_case_and_no_go() -> None:
    """全部真实门禁可 admit；连受控链都不稳定则 no-go。"""

    admitted = OccupancyAdmissionEvidence(
        provenance_clear=True,
        annual_baseline_stable=True,
        spatial_people_difference=True,
        original_real_hvac=True,
        same_person_hours_reproducible=True,
        interpretable_distribution_response=True,
        frozen_method_unchanged=True,
        controlled_demo_stable=True,
        only_commonplace_volume_result=False,
    )
    failed = OccupancyAdmissionEvidence(
        provenance_clear=True,
        annual_baseline_stable=False,
        spatial_people_difference=True,
        original_real_hvac=False,
        same_person_hours_reproducible=False,
        interpretable_distribution_response=False,
        frozen_method_unchanged=True,
        controlled_demo_stable=False,
        only_commonplace_volume_result=True,
    )

    assert decide_occupancy_status(admitted) == "OCCUPANCY_CASE_ADMIT"
    assert decide_occupancy_status(failed) == "OCCUPANCY_NO_GO"
