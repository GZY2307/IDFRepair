import pytest

from idfrepair.analysis.airport_abm.reporting import (
    ReportingError,
    paired_energy_statistics,
)


def test_five_seed_paired_statistics_are_hand_checkable() -> None:
    rows = []
    for seed, baseline, comparison in (
        (40003, 10.0, 11.0),
        (40009, 20.0, 18.0),
        (40015, 30.0, 33.0),
        (40021, 40.0, 44.0),
        (40027, 50.0, 45.0),
    ):
        rows.extend(
            [
                {"scenario_id": "BASELINE_SPREAD", "seed": seed, "value": baseline},
                {"scenario_id": "MIDDAY_BANK", "seed": seed, "value": comparison},
            ]
        )

    result = paired_energy_statistics(
        rows,
        baseline_scenario="BASELINE_SPREAD",
        comparison_scenario="MIDDAY_BANK",
        identity_fields=("seed",),
    )

    assert result["n"] == 5
    assert result["difference_mean"] == pytest.approx(0.2)
    assert result["difference_median"] == pytest.approx(1.0)
    assert result["difference_minimum"] == pytest.approx(-5.0)
    assert result["difference_maximum"] == pytest.approx(4.0)
    assert result["difference_p10"] == pytest.approx(-3.8)
    assert result["difference_p90"] == pytest.approx(3.6)
    assert result["percent_n"] == 5


def test_zero_reference_keeps_absolute_pair_and_omits_only_percent() -> None:
    rows = [
        {"scenario_id": "BASE", "seed": 1, "value": 0.0},
        {"scenario_id": "SHIFT", "seed": 1, "value": 2.0},
    ]

    result = paired_energy_statistics(
        rows,
        baseline_scenario="BASE",
        comparison_scenario="SHIFT",
        identity_fields=("seed",),
    )

    assert result["n"] == 1
    assert result["difference_mean"] == 2.0
    assert result["percent_n"] == 0
    assert result["percent_mean"] is None


def test_paired_statistics_reject_an_incomplete_preregistered_denominator() -> None:
    with pytest.raises(ReportingError, match="paired identities"):
        paired_energy_statistics(
            [
                {"scenario_id": "BASE", "seed": 40003, "value": 1.0},
                {"scenario_id": "SHIFT", "seed": 40009, "value": 2.0},
            ],
            baseline_scenario="BASE",
            comparison_scenario="SHIFT",
            identity_fields=("seed",),
        )
