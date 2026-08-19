import pytest

from idfrepair.analysis.airport_abm.v31_reporting import (
    EnergyEvidenceError,
    validate_source_static_energy_baseline,
)


def _rows() -> list[dict[str, object]]:
    rows = [
        {"scenario_id": "SOURCE_STATIC", "seed": None, "period_id": period, "passed": True}
        for period in ("winter", "summer", "shoulder")
    ]
    rows.extend(
        {
            "scenario_id": "BASELINE_SPREAD",
            "seed": seed,
            "period_id": period,
            "passed": True,
        }
        for period in ("winter", "summer", "shoulder")
        for seed in (40003, 40009, 40015, 40021, 40027)
    )
    return rows


def test_source_static_is_one_deterministic_case_per_seasonal_period() -> None:
    result = validate_source_static_energy_baseline(_rows())

    assert result == {
        "source_static_periods": 3,
        "dynamic_baseline_periods": 15,
        "status": "PASS",
    }


def test_source_static_must_not_be_assigned_an_abm_seed() -> None:
    rows = _rows()
    rows[0]["seed"] = 40015

    with pytest.raises(EnergyEvidenceError, match="SOURCE_STATIC"):
        validate_source_static_energy_baseline(rows)
