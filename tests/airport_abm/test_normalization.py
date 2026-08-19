from __future__ import annotations

from idfrepair.analysis.airport_abm.agents import AgentTrace, Visit
from idfrepair.analysis.airport_abm.model import AgentClass
from idfrepair.analysis.airport_abm.normalization import (
    PersonHourTargets,
    derive_cohort_weights,
    derive_throughput_cohort_weights,
    source_person_hour_targets,
    weights_by_agent,
)
from idfrepair.analysis.airport_abm.simulation import SimulationResult
from idfrepair.analysis.airport_abm.source import SourceSpace


def _space(name: str, function: str, capacity: float | None) -> SourceSpace:
    return SourceSpace(
        name,
        f"zone-{name}",
        "region",
        function,
        function,
        function,
        100,
        None if capacity is None else 100 / capacity,
        capacity,
        None,
        None,
        None,
    )


def test_source_targets_separate_public_and_staff_from_existing_schedules() -> None:
    targets = source_person_hour_targets(
        (
            _space("gate", "domestic_waiting", 100),
            _space("shop", "commercial", 20),
            _space("office", "office", 10),
            _space("restroom", "restroom", None),
        ),
        equivalent_full_load_hours={
            "domestic_waiting": 10,
            "commercial": 5,
            "office": 8,
        },
        staff_functions={"office"},
    )

    assert targets.public_person_hours == 1100
    assert targets.staff_person_hours == 80
    assert targets.total_person_hours == 1180
    assert targets.flow_only_spaces == ("restroom",)


def test_cohort_weights_match_public_and_staff_person_hour_targets() -> None:
    departure = AgentTrace(
        "dep",
        AgentClass.DOMESTIC_DEPARTURE,
        (
            Visit(
                "dep",
                AgentClass.DOMESTIC_DEPARTURE,
                "gate",
                "wait",
                0,
                120,
            ),
        ),
        (),
        "BOARDING",
        120,
    )
    staff = AgentTrace(
        "staff",
        AgentClass.STAFF,
        (
            Visit("staff", AgentClass.STAFF, "boundary", "entry", 0, 10),
            Visit("staff", AgentClass.STAFF, "office", "work", 10, 250),
        ),
        (),
        "STAFF_EXIT_BOUNDARY",
        250,
    )
    result = SimulationResult(
        traces={"dep": departure, "staff": staff},
        spawned_count=2,
        terminal_count=2,
        active_count=0,
        missing_agent_ids=(),
    )

    cohort = derive_cohort_weights(
        result,
        targets=PersonHourTargets(100, 40, ()),
        physical_locations={"gate", "office"},
    )

    assert cohort.public_weight == 50
    assert cohort.staff_weight == 10
    assert cohort.evidence_status == "CONTROLLED_NOT_MEASURED"
    assert weights_by_agent(result, cohort) == {"dep": 50, "staff": 10}


def test_throughput_cohort_uses_airport_context_for_arrivals_but_source_hours_for_staff() -> None:
    departure = AgentTrace(
        "dep",
        AgentClass.DOMESTIC_DEPARTURE,
        (Visit("dep", AgentClass.DOMESTIC_DEPARTURE, "gate", "wait", 0, 120),),
        (),
        "BOARDING",
        120,
    )
    staff = AgentTrace(
        "staff",
        AgentClass.STAFF,
        (Visit("staff", AgentClass.STAFF, "office", "work", 0, 240),),
        (),
        "STAFF_EXIT_BOUNDARY",
        240,
    )
    result = SimulationResult(
        traces={"dep": departure, "staff": staff},
        spawned_count=2,
        terminal_count=2,
        active_count=0,
        missing_agent_ids=(),
    )

    cohort = derive_throughput_cohort_weights(
        result,
        target_public_arrivals=146_877,
        targets=PersonHourTargets(999_999, 40, ()),
        physical_locations={"gate", "office"},
    )

    assert cohort.public_weight == 146_877
    assert cohort.staff_weight == 10
    assert cohort.raw_public_person_hours == 2
