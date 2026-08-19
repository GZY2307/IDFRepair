from __future__ import annotations

from idfrepair.analysis.airport_abm.agents import AgentTrace, Visit
from idfrepair.analysis.airport_abm.model import AgentClass
from idfrepair.analysis.airport_abm.normalization import PersonHourTargets
from idfrepair.analysis.airport_abm.simulation import SimulationResult
from idfrepair.analysis.airport_abm.v31 import (
    AIRPORT_WIDE_STRESS_CONTEXT,
    BEM_REFERENCE_NORMALIZED,
    compare_occupancy_scales,
    select_cohort_weights,
)


def _result() -> SimulationResult:
    return SimulationResult(
        traces={
            "p1": AgentTrace(
                "p1",
                AgentClass.DOMESTIC_DEPARTURE,
                (Visit("p1", AgentClass.DOMESTIC_DEPARTURE, "gate", "wait", 0, 60),),
                (),
                "BOARDING",
                60,
            ),
            "p2": AgentTrace(
                "p2",
                AgentClass.DOMESTIC_ARRIVAL,
                (Visit("p2", AgentClass.DOMESTIC_ARRIVAL, "hall", "walk", 0, 180),),
                (),
                "OUT",
                180,
            ),
            "staff": AgentTrace(
                "staff",
                AgentClass.STAFF,
                (Visit("staff", AgentClass.STAFF, "office", "work", 0, 120),),
                (),
                "STAFF_EXIT_BOUNDARY",
                120,
            ),
        },
        spawned_count=3,
        terminal_count=3,
        active_count=0,
        missing_agent_ids=(),
    )


def test_airport_stress_and_bem_reference_are_distinct_named_scales() -> None:
    targets = PersonHourTargets(40.0, 10.0, ())
    common = {
        "targets": targets,
        "physical_locations": {"gate", "hall", "office"},
        "airport_wide_public_arrivals": 100.0,
    }
    stress = select_cohort_weights(
        _result(), scale_mode=AIRPORT_WIDE_STRESS_CONTEXT, **common
    )
    bem = select_cohort_weights(
        _result(), scale_mode=BEM_REFERENCE_NORMALIZED, **common
    )

    # Stress maps 100 movements onto two representative passengers.
    assert stress.public_weight == 50.0
    # BEM normalization maps 40 person-hours onto four raw person-hours.
    assert bem.public_weight == 10.0
    comparison = compare_occupancy_scales(
        bem_public_person_hours=40.0,
        stress_public_person_hours=200.0,
    )
    assert comparison == {
        "primary_scale": BEM_REFERENCE_NORMALIZED,
        "secondary_scale": AIRPORT_WIDE_STRESS_CONTEXT,
        "bem_public_person_hours": 40.0,
        "stress_public_person_hours": 200.0,
        "bem_to_stress_ratio": 0.2,
    }
