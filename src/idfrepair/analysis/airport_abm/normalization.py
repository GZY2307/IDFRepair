"""Transparent throughput-context and source-staff cohort normalization."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping

from .model import AgentClass, PASSENGER_CLASSES
from .simulation import SimulationResult
from .source import SourceSpace


class NormalizationError(ValueError):
    """Raised when a source or cohort integral cannot be reconciled."""


@dataclass(frozen=True, slots=True)
class PersonHourTargets:
    public_person_hours: float
    staff_person_hours: float
    flow_only_spaces: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (self.public_person_hours, self.staff_person_hours):
            if not math.isfinite(value) or value <= 0:
                raise NormalizationError("person-hour targets must be finite and positive")

    @property
    def total_person_hours(self) -> float:
        return self.public_person_hours + self.staff_person_hours


@dataclass(frozen=True, slots=True)
class CohortWeights:
    public_weight: float
    staff_weight: float
    raw_public_person_hours: float
    raw_staff_person_hours: float
    evidence_status: str = "CONTROLLED_NOT_MEASURED"

    def __post_init__(self) -> None:
        for value in (
            self.public_weight,
            self.staff_weight,
            self.raw_public_person_hours,
            self.raw_staff_person_hours,
        ):
            if not math.isfinite(value) or value <= 0:
                raise NormalizationError("cohort values must be finite and positive")
        if self.evidence_status != "CONTROLLED_NOT_MEASURED":
            raise NormalizationError("cohort scaling must remain controlled")


def source_person_hour_targets(
    spaces: Iterable[SourceSpace],
    *,
    equivalent_full_load_hours: Mapping[str, float],
    staff_functions: Iterable[str],
) -> PersonHourTargets:
    staff_set = frozenset(staff_functions)
    public = 0.0
    staff = 0.0
    flow_only: list[str] = []
    for space in spaces:
        capacity = space.source_design_people
        if capacity is None:
            flow_only.append(space.name)
            continue
        if space.function not in equivalent_full_load_hours:
            raise NormalizationError(
                f"missing source schedule integral for function: {space.function}"
            )
        hours = float(equivalent_full_load_hours[space.function])
        if not math.isfinite(hours) or hours < 0 or hours > 24:
            raise NormalizationError(
                f"invalid source schedule integral for function: {space.function}"
            )
        value = capacity * hours
        if space.function in staff_set:
            staff += value
        else:
            public += value
    return PersonHourTargets(public, staff, tuple(sorted(flow_only)))


def derive_cohort_weights(
    result: SimulationResult,
    *,
    targets: PersonHourTargets,
    physical_locations: Iterable[str],
) -> CohortWeights:
    admitted = frozenset(physical_locations)
    raw_public = 0.0
    raw_staff = 0.0
    for trace in result.traces.values():
        hours = sum(
            max(0.0, visit.end_minute - visit.start_minute) / 60.0
            for visit in trace.visits
            if visit.location in admitted
        )
        if trace.agent_class in PASSENGER_CLASSES:
            raw_public += hours
        elif trace.agent_class is AgentClass.STAFF:
            raw_staff += hours
        else:  # pragma: no cover - the enum is exhaustive
            raise NormalizationError(f"unsupported agent class: {trace.agent_class}")
    if raw_public <= 0 or raw_staff <= 0:
        raise NormalizationError("both public and staff cohorts must have positive hours")
    return CohortWeights(
        public_weight=targets.public_person_hours / raw_public,
        staff_weight=targets.staff_person_hours / raw_staff,
        raw_public_person_hours=raw_public,
        raw_staff_person_hours=raw_staff,
    )


def derive_throughput_cohort_weights(
    result: SimulationResult,
    *,
    target_public_arrivals: float,
    targets: PersonHourTargets,
    physical_locations: Iterable[str],
) -> CohortWeights:
    """Scale public agents to an external daily throughput context.

    The external total is an airport-wide reporting context mapped onto this
    simplified Level-2 experiment as an explicit controlled assumption.  It is
    not treated as a measured floor, route, gate, or 15-minute count.  Staff
    remains normalized to the source-model schedule integral.
    """

    if not math.isfinite(target_public_arrivals) or target_public_arrivals <= 0:
        raise NormalizationError("public arrival target must be finite and positive")
    admitted = frozenset(physical_locations)
    raw_public = 0.0
    raw_staff = 0.0
    public_agents = 0
    for trace in result.traces.values():
        hours = sum(
            max(0.0, visit.end_minute - visit.start_minute) / 60.0
            for visit in trace.visits
            if visit.location in admitted
        )
        if trace.agent_class in PASSENGER_CLASSES:
            public_agents += 1
            raw_public += hours
        elif trace.agent_class is AgentClass.STAFF:
            raw_staff += hours
    if public_agents <= 0 or raw_public <= 0 or raw_staff <= 0:
        raise NormalizationError("throughput cohort requires public and staff activity")
    return CohortWeights(
        public_weight=target_public_arrivals / public_agents,
        staff_weight=targets.staff_person_hours / raw_staff,
        raw_public_person_hours=raw_public,
        raw_staff_person_hours=raw_staff,
    )


def weights_by_agent(
    result: SimulationResult, cohort: CohortWeights
) -> dict[str, float]:
    return {
        agent_id: (
            cohort.public_weight
            if trace.agent_class in PASSENGER_CLASSES
            else cohort.staff_weight
        )
        for agent_id, trace in result.traces.items()
    }
