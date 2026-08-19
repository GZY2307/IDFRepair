from __future__ import annotations

import pytest


def test_zone_results_aggregate_extensive_and_state_metrics_without_peak_summing() -> None:
    from scripts.airport_abm.aggregate_zone_energy import aggregate_mapped_runs

    mapping = {
        "zone-a": {
            "function": "domestic_waiting",
            "region": "pier-a",
            "hvac_group": "pier-a-vav",
            "area_m2": 10.0,
        },
        "zone-b": {
            "function": "domestic_waiting",
            "region": "pier-a",
            "hvac_group": "pier-a-vav",
            "area_m2": 30.0,
        },
    }
    rows = []
    values = {
        "sensible_cooling_kwh": (10.0, 20.0, "kWh"),
        "sensible_cooling_interval_peak_kw": (5.0, 7.0, "kW"),
        "air_temperature_mean_c": (20.0, 24.0, "C"),
        "air_temperature_maximum_c": (25.0, 27.0, "C"),
        "outdoor_air_mean_m3_s": (1.0, 2.0, "m3/s"),
    }
    for metric, (first, second, unit) in values.items():
        groups = (
            ("ZONE-A-VAV", first),
            ("ZONE-B-DOAS", second),
        ) if metric == "outdoor_air_mean_m3_s" else (
            ("ZONE-A", first),
            ("ZONE-B", second),
        )
        for group, value in groups:
            rows.append(
                {
                    "scenario_id": "BASELINE_SPREAD",
                    "seed": 40015,
                    "run_kind": "design_days",
                    "period_id": "summer",
                    "scope": "thermal_zone",
                    "group": group,
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                }
            )

    result = aggregate_mapped_runs(rows, mapping)
    function_rows = {
        row["metric"]: row
        for row in result
        if row["scope"] == "function" and row["group"] == "domestic_waiting"
    }

    assert function_rows["sensible_cooling_kwh"]["value"] == 30.0
    assert function_rows["maximum_zone_sensible_cooling_interval_peak_kw"]["value"] == 7.0
    assert function_rows["air_temperature_mean_c"]["value"] == pytest.approx(23.0)
    assert function_rows["air_temperature_maximum_c"]["value"] == 27.0
    assert function_rows["outdoor_air_mean_m3_s"]["value"] == 3.0


def test_zone_timing_effects_support_an_explicit_one_seed_demo() -> None:
    from scripts.airport_abm.aggregate_zone_energy import maximum_timing_effects

    rows = [
        {
            "scenario_id": scenario,
            "seed": 40015,
            "run_kind": "shoulder",
            "period_id": "shoulder",
            "scope": "function",
            "group": "domestic_waiting",
            "metric": "sensible_cooling_kwh",
            "value": value,
            "unit": "kWh",
            "aggregation": "sum",
        }
        for scenario, value in (("BASELINE_SPREAD", 100.0), ("MORNING_BANK", 112.0))
    ]

    effects = maximum_timing_effects(rows)

    assert len(effects) == 1
    assert effects[0]["paired_seed_count"] == 1
    assert effects[0]["difference_p50"] == 12.0
    assert effects[0]["percent_p50"] == pytest.approx(12.0)
