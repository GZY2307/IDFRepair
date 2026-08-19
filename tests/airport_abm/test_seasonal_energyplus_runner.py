from pathlib import Path

import pytest

from idfrepair.analysis.airport_abm.energyplus_runner import (
    EnergyPlusCase,
    parse_energyplus_error_summary,
    seasonal_case_registry,
)


def test_error_summary_uses_energyplus_terminal_counts() -> None:
    text = (
        "** Warning ** one warning\n"
        "** Severe  ** an error\n"
        "EnergyPlus Warmup Error Summary. During Warmup: 0 Warning; 0 Severe Errors.\n"
        "EnergyPlus Completed Successfully-- 17 Warning; 0 Severe Errors; "
        "Elapsed Time=00hr 00min 10.00sec\n"
    )

    summary = parse_energyplus_error_summary(text)

    assert summary.warning_count == 17
    assert summary.severe_count == 0
    assert summary.fatal_count == 0
    assert summary.completed_successfully is True
    assert summary.elapsed_seconds == pytest.approx(10.0)


def test_seasonal_registry_has_52_processes_and_78_period_identities(
    tmp_path: Path,
) -> None:
    cases = seasonal_case_registry(tmp_path)

    assert len(cases) == 52
    assert sum(len(case.expected_periods) for case in cases) == 78
    assert sum(case.scenario_id == "SOURCE_STATIC" for case in cases) == 2
    assert sum(case.seed is None for case in cases) == 2
    assert {case.run_kind for case in cases} == {"design_days", "shoulder"}
    assert all(isinstance(case, EnergyPlusCase) for case in cases)
