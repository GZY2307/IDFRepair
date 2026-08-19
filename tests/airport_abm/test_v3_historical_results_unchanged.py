from __future__ import annotations

from idfrepair.analysis.airport_abm.agents import AgentTrace, Visit
from idfrepair.analysis.airport_abm.model import AgentClass
from idfrepair.analysis.airport_abm.normalization import PersonHourTargets
from idfrepair.analysis.airport_abm.simulation import SimulationResult
from idfrepair.analysis.airport_abm.v31 import (
    AIRPORT_WIDE_STRESS_CONTEXT,
    select_cohort_weights,
)


def test_legacy_default_keeps_airport_wide_arrival_scaling_behavior() -> None:
    result = SimulationResult(
        traces={
            "passenger": AgentTrace(
                "passenger",
                AgentClass.DOMESTIC_DEPARTURE,
                (Visit("passenger", AgentClass.DOMESTIC_DEPARTURE, "gate", "wait", 0, 120),),
                (),
                "BOARDING",
                120,
            ),
            "staff": AgentTrace(
                "staff",
                AgentClass.STAFF,
                (Visit("staff", AgentClass.STAFF, "office", "work", 0, 240),),
                (),
                "STAFF_EXIT_BOUNDARY",
                240,
            ),
        },
        spawned_count=2,
        terminal_count=2,
        active_count=0,
        missing_agent_ids=(),
    )

    cohort = select_cohort_weights(
        result,
        targets=PersonHourTargets(999_999.0, 40.0, ()),
        physical_locations={"gate", "office"},
        airport_wide_public_arrivals=146_877.0,
    )

    assert cohort.public_weight == 146_877.0
    assert cohort.staff_weight == 10.0
    assert cohort.evidence_status == "CONTROLLED_NOT_MEASURED"
    assert AIRPORT_WIDE_STRESS_CONTEXT == "AIRPORT_WIDE_STRESS_CONTEXT"
