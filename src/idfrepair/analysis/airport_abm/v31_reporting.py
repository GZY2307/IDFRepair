"""Evidence gates used by the Airport ABM V3.1 public reports."""

from __future__ import annotations

from typing import Iterable, Mapping

from .v31 import SEASONAL_PERIODS, SEASONAL_SEEDS


class EnergyEvidenceError(ValueError):
    """Raised when a preregistered energy-evidence denominator is incomplete."""


def validate_source_static_energy_baseline(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    materialized = tuple(rows)
    static = [row for row in materialized if row.get("scenario_id") == "SOURCE_STATIC"]
    dynamic = [
        row for row in materialized if row.get("scenario_id") == "BASELINE_SPREAD"
    ]
    if any(row.get("seed") is not None for row in static):
        raise EnergyEvidenceError("SOURCE_STATIC must not have an ABM seed")
    static_ids = {(str(row.get("period_id")), bool(row.get("passed"))) for row in static}
    if static_ids != {(period, True) for period in SEASONAL_PERIODS}:
        raise EnergyEvidenceError("SOURCE_STATIC seasonal periods are incomplete")
    dynamic_ids = {
        (str(row.get("period_id")), int(row["seed"]), bool(row.get("passed")))
        for row in dynamic
        if row.get("seed") is not None
    }
    expected_dynamic = {
        (period, seed, True)
        for period in SEASONAL_PERIODS
        for seed in SEASONAL_SEEDS
    }
    if dynamic_ids != expected_dynamic:
        raise EnergyEvidenceError("dynamic baseline seasonal periods are incomplete")
    return {
        "source_static_periods": len(static_ids),
        "dynamic_baseline_periods": len(dynamic_ids),
        "status": "PASS",
    }
