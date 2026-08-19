from idfrepair.analysis.airport_abm.v31 import (
    SEASONAL_SEEDS,
    TIMING_SCENARIOS,
    seasonal_period_identities,
)


def test_preregistered_seasonal_registry_has_75_dynamic_and_3_static_periods() -> None:
    identities = seasonal_period_identities()

    assert SEASONAL_SEEDS == (40003, 40009, 40015, 40021, 40027)
    assert TIMING_SCENARIOS == (
        "BASELINE_SPREAD",
        "MORNING_BANK",
        "MIDDAY_BANK",
        "EVENING_BANK",
        "DOUBLE_BANK",
    )
    assert len(identities) == 78
    assert len({row.identity for row in identities}) == 78
    assert sum(row.seed is None for row in identities) == 3
    assert sum(row.seed is not None for row in identities) == 75
