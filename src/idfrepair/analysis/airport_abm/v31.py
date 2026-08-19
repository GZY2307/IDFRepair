"""Airport Occupancy V3.1 evidence-closure registries and scale contracts."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from .normalization import (
    CohortWeights,
    PersonHourTargets,
    derive_cohort_weights,
    derive_throughput_cohort_weights,
)
from .simulation import SimulationResult


BEM_REFERENCE_NORMALIZED = "BEM_REFERENCE_NORMALIZED"
AIRPORT_WIDE_STRESS_CONTEXT = "AIRPORT_WIDE_STRESS_CONTEXT"
TIMING_SCENARIOS = (
    "BASELINE_SPREAD",
    "MORNING_BANK",
    "MIDDAY_BANK",
    "EVENING_BANK",
    "DOUBLE_BANK",
)
SEASONAL_SEEDS = (40003, 40009, 40015, 40021, 40027)
SEASONAL_PERIODS = ("winter", "summer", "shoulder")
ANNUAL_MASTER_SEED = 40015


@dataclass(frozen=True, slots=True)
class PersonHourConservation:
    status: str
    public_relative_error: float
    staff_relative_error: float
    relative_tolerance: float


@dataclass(frozen=True, slots=True)
class ExperimentIdentity:
    scenario_id: str
    seed: int | None
    period_id: str

    @property
    def identity(self) -> tuple[str, int | None, str]:
        return self.scenario_id, self.seed, self.period_id


def select_cohort_weights(
    result: SimulationResult,
    *,
    targets: PersonHourTargets,
    physical_locations: Iterable[str],
    airport_wide_public_arrivals: float,
    scale_mode: str = AIRPORT_WIDE_STRESS_CONTEXT,
) -> CohortWeights:
    if scale_mode == BEM_REFERENCE_NORMALIZED:
        return derive_cohort_weights(
            result,
            targets=targets,
            physical_locations=physical_locations,
        )
    if scale_mode == AIRPORT_WIDE_STRESS_CONTEXT:
        return derive_throughput_cohort_weights(
            result,
            target_public_arrivals=airport_wide_public_arrivals,
            targets=targets,
            physical_locations=physical_locations,
        )
    raise ValueError(f"unsupported occupancy scale: {scale_mode}")


def annual_cohort_weights(
    *,
    raw_public_person_hours: float,
    raw_staff_person_hours: float,
    calendar_days: int,
    public_agents_per_day: int,
    targets: PersonHourTargets,
    airport_wide_public_arrivals: float,
    scale_mode: str = AIRPORT_WIDE_STRESS_CONTEXT,
) -> CohortWeights:
    values = (
        raw_public_person_hours,
        raw_staff_person_hours,
        airport_wide_public_arrivals,
    )
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("annual cohort inputs must be finite and positive")
    if calendar_days <= 0 or public_agents_per_day <= 0:
        raise ValueError("annual calendar and agent counts must be positive")
    if scale_mode == BEM_REFERENCE_NORMALIZED:
        public_weight = (
            targets.public_person_hours * calendar_days / raw_public_person_hours
        )
    elif scale_mode == AIRPORT_WIDE_STRESS_CONTEXT:
        public_weight = airport_wide_public_arrivals / public_agents_per_day
    else:
        raise ValueError(f"unsupported occupancy scale: {scale_mode}")
    return CohortWeights(
        public_weight=public_weight,
        staff_weight=(
            targets.staff_person_hours * calendar_days / raw_staff_person_hours
        ),
        raw_public_person_hours=raw_public_person_hours,
        raw_staff_person_hours=raw_staff_person_hours,
    )


def compare_occupancy_scales(
    *, bem_public_person_hours: float, stress_public_person_hours: float
) -> dict[str, float | str]:
    for value in (bem_public_person_hours, stress_public_person_hours):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("occupancy scale person-hours must be finite and positive")
    return {
        "primary_scale": BEM_REFERENCE_NORMALIZED,
        "secondary_scale": AIRPORT_WIDE_STRESS_CONTEXT,
        "bem_public_person_hours": bem_public_person_hours,
        "stress_public_person_hours": stress_public_person_hours,
        "bem_to_stress_ratio": bem_public_person_hours / stress_public_person_hours,
    }


def person_hour_conservation(
    *,
    target_public: float,
    actual_public: float,
    target_staff: float,
    actual_staff: float,
    relative_tolerance: float = 1.0e-8,
) -> PersonHourConservation:
    if not math.isfinite(relative_tolerance) or relative_tolerance <= 0:
        raise ValueError("relative tolerance must be finite and positive")
    values = (target_public, actual_public, target_staff, actual_staff)
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("person-hours must be finite and positive")
    public_error = abs(actual_public - target_public) / target_public
    staff_error = abs(actual_staff - target_staff) / target_staff
    return PersonHourConservation(
        status=(
            "PASS"
            if public_error <= relative_tolerance and staff_error <= relative_tolerance
            else "FAIL"
        ),
        public_relative_error=public_error,
        staff_relative_error=staff_error,
        relative_tolerance=relative_tolerance,
    )


def seasonal_period_identities() -> tuple[ExperimentIdentity, ...]:
    dynamic = tuple(
        ExperimentIdentity(scenario, seed, period)
        for period in SEASONAL_PERIODS
        for scenario in TIMING_SCENARIOS
        for seed in SEASONAL_SEEDS
    )
    static = tuple(
        ExperimentIdentity("SOURCE_STATIC", None, period)
        for period in SEASONAL_PERIODS
    )
    return dynamic + static


def require_annual_master_seed(seed: int) -> int:
    if seed != ANNUAL_MASTER_SEED:
        raise ValueError(
            f"annual master seed must remain {ANNUAL_MASTER_SEED}: received {seed}"
        )
    return seed


def annual_case_identities() -> tuple[ExperimentIdentity, ...]:
    return (
        ExperimentIdentity("SOURCE_STATIC", None, "annual"),
        *(
            ExperimentIdentity(scenario, ANNUAL_MASTER_SEED, "annual")
            for scenario in TIMING_SCENARIOS
        ),
    )
