from __future__ import annotations

import os
import pytest
from pathlib import Path

from idfrepair.analysis.airport_abm.agents import AgentTrace, Visit
from idfrepair.analysis.airport_abm.model import AgentClass
from idfrepair.analysis.airport_abm.normalization import PersonHourTargets
from idfrepair.analysis.airport_abm.simulation import SimulationResult
from idfrepair.analysis.airport_abm.v31 import (
    BEM_REFERENCE_NORMALIZED,
    annual_cohort_weights,
    select_cohort_weights,
)


def _result() -> SimulationResult:
    return SimulationResult(
        traces={
            "public": AgentTrace(
                "public",
                AgentClass.DOMESTIC_DEPARTURE,
                (Visit("public", AgentClass.DOMESTIC_DEPARTURE, "gate", "wait", 0, 120),),
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


def test_bem_reference_mode_matches_public_and_staff_source_integrals() -> None:
    cohort = select_cohort_weights(
        _result(),
        scale_mode=BEM_REFERENCE_NORMALIZED,
        targets=PersonHourTargets(100.0, 40.0, ()),
        physical_locations={"gate", "office"},
        airport_wide_public_arrivals=146_877.0,
    )

    assert cohort.public_weight == 50.0
    assert cohort.staff_weight == 10.0
    assert cohort.raw_public_person_hours == 2.0
    assert cohort.raw_staff_person_hours == 4.0


def test_bem_reference_mode_rejects_an_unknown_scale() -> None:
    with pytest.raises(ValueError, match="occupancy scale"):
        select_cohort_weights(
            _result(),
            scale_mode="TUNED_AFTER_RESULTS",
            targets=PersonHourTargets(100.0, 40.0, ()),
            physical_locations={"gate", "office"},
            airport_wide_public_arrivals=146_877.0,
        )


def test_annual_bem_reference_matches_the_source_average_day_integrals() -> None:
    cohort = annual_cohort_weights(
        raw_public_person_hours=400.0,
        raw_staff_person_hours=200.0,
        calendar_days=2,
        public_agents_per_day=2,
        targets=PersonHourTargets(100.0, 20.0, ()),
        airport_wide_public_arrivals=1000.0,
        scale_mode=BEM_REFERENCE_NORMALIZED,
    )

    assert cohort.public_weight == 0.5
    assert cohort.staff_weight == 0.2


def test_real_v3_runner_can_select_the_bem_reference_mode() -> None:
    project = Path(__file__).resolve().parents[2]
    mapping_value = os.environ.get("IDFREPAIR_AIRPORT_MAPPING")
    if not mapping_value:
        pytest.skip("IDFREPAIR_AIRPORT_MAPPING is not configured")
    mapping = Path(mapping_value)
    access = project / ".private/occupancy_v3/config/access_registry.json"
    parameters = project / ".private/occupancy_v3/config/parameter_registry.json"
    if not all(path.is_file() for path in (mapping, access, parameters)):
        pytest.skip("private integration inputs are not present")

    from idfrepair.analysis.airport_abm.experiment import (
        load_experiment_context,
        run_seed_matrix,
    )

    context, scenarios = load_experiment_context(
        mapping_path=mapping,
        access_registry_path=access,
        parameter_registry_path=parameters,
    )
    baseline = tuple(
        scenario for scenario in scenarios if scenario.scenario_id == "BASELINE_SPREAD"
    )
    result = run_seed_matrix(
        context,
        baseline,
        seed=40015,
        scale_mode=BEM_REFERENCE_NORMALIZED,
    )[0]

    assert result.summary["public_person_hours_bem"] == pytest.approx(
        context.targets.public_person_hours, rel=1.0e-12
    )
    assert result.summary["staff_person_hours_bem"] == pytest.approx(
        context.targets.staff_person_hours, rel=1.0e-12
    )
