from __future__ import annotations

import csv
from pathlib import Path

import pytest

from idfrepair.analysis.airport_abm.agents import AgentTrace, FlowEvent, Visit
from idfrepair.analysis.airport_abm.model import AgentClass


def _trace(
    agent_id: str,
    agent_class: AgentClass,
    visits: tuple[Visit, ...],
    flows: tuple[FlowEvent, ...] = (),
) -> AgentTrace:
    return AgentTrace(
        agent_id=agent_id,
        agent_class=agent_class,
        visits=visits,
        flows=flows,
        terminal_state="OUT",
        terminal_minute=max(visit.end_minute for visit in visits),
    )


def test_interval_aggregation_conserves_person_hours_and_classes() -> None:
    from idfrepair.analysis.airport_abm.schedule_compiler import compile_traces

    departure = _trace(
        "dep-1",
        AgentClass.DOMESTIC_DEPARTURE,
        (
            Visit(
                "dep-1",
                AgentClass.DOMESTIC_DEPARTURE,
                "entry",
                "entry",
                0,
                10,
            ),
            Visit(
                "dep-1",
                AgentClass.DOMESTIC_DEPARTURE,
                "gate",
                "gate_wait",
                10,
                30,
            ),
        ),
        (
            FlowEvent(
                "dep-1",
                AgentClass.DOMESTIC_DEPARTURE,
                "entry",
                "gate",
                10,
            ),
        ),
    )
    staff = _trace(
        "staff-1",
        AgentClass.STAFF,
        (
            Visit(
                "staff-1",
                AgentClass.STAFF,
                "gate",
                "work",
                0,
                15,
            ),
        ),
    )

    compiled = compile_traces(
        {"dep-1": departure, "staff-1": staff},
        space_areas_m2={"entry": 20.0, "gate": 40.0},
        interval_minutes=15,
        horizon_minutes=30,
        agent_weights={"dep-1": 2.0, "staff-1": 1.0},
    )

    assert compiled.interval_labels == ("00:00-00:15", "00:15-00:30")
    assert compiled.space_counts["entry"] == pytest.approx((4 / 3, 0))
    assert compiled.space_counts["gate"] == pytest.approx((5 / 3, 2))
    assert compiled.space_density["gate"] == pytest.approx((1 / 24, 0.05))
    assert compiled.class_counts["gate"][AgentClass.STAFF.value] == pytest.approx(
        (1, 0)
    )
    assert compiled.class_counts["gate"][
        AgentClass.DOMESTIC_DEPARTURE.value
    ] == pytest.approx((2 / 3, 2))
    assert compiled.person_hours == pytest.approx(1.25)
    assert compiled.class_person_hours[AgentClass.DOMESTIC_DEPARTURE.value] == pytest.approx(
        1.0
    )
    assert compiled.class_person_hours[AgentClass.STAFF.value] == pytest.approx(0.25)
    assert compiled.flow_counts[("entry", "gate")][0] == pytest.approx(2.0)


def test_boundary_flow_belongs_to_next_interval() -> None:
    from idfrepair.analysis.airport_abm.schedule_compiler import compile_traces

    trace = _trace(
        "arr-1",
        AgentClass.DOMESTIC_ARRIVAL,
        (
            Visit(
                "arr-1",
                AgentClass.DOMESTIC_ARRIVAL,
                "gate",
                "deplane",
                0,
                30,
            ),
        ),
        (
            FlowEvent(
                "arr-1",
                AgentClass.DOMESTIC_ARRIVAL,
                "gate",
                "bag",
                15,
            ),
        ),
    )

    compiled = compile_traces(
        {"arr-1": trace},
        space_areas_m2={"gate": 10.0},
        interval_minutes=15,
        horizon_minutes=30,
    )

    assert compiled.flow_counts[("gate", "bag")] == pytest.approx((0, 1))


def test_periodic_day_wraps_late_visits_and_flows_into_start_of_day() -> None:
    from idfrepair.analysis.airport_abm.schedule_compiler import compile_traces

    trace = _trace(
        "late",
        AgentClass.INTERNATIONAL_ARRIVAL,
        (
            Visit(
                "late",
                AgentClass.INTERNATIONAL_ARRIVAL,
                "gate",
                "deplane",
                1435,
                1455,
            ),
        ),
        (
            FlowEvent(
                "late",
                AgentClass.INTERNATIONAL_ARRIVAL,
                "gate",
                "boundary",
                1455,
            ),
        ),
    )
    compiled = compile_traces(
        {"late": trace},
        space_areas_m2={"gate": 10.0},
        periodic=True,
    )

    assert compiled.space_counts["gate"][95] == pytest.approx(1 / 3)
    assert compiled.space_counts["gate"][0] == pytest.approx(1.0)
    assert compiled.person_hours == pytest.approx(1 / 3)
    assert compiled.flow_counts[("gate", "boundary")][1] == pytest.approx(1.0)


def test_schedule_fraction_preserves_over_capacity_values() -> None:
    from idfrepair.analysis.airport_abm.schedule_compiler import counts_to_fractions

    fractions = counts_to_fractions(
        {"gate": (0.0, 5.0, 12.0)},
        source_design_capacity={"gate": 10.0},
    )

    assert fractions["gate"] == pytest.approx((0.0, 0.5, 1.2))


def test_flow_only_space_cannot_be_silently_compiled_to_people() -> None:
    from idfrepair.analysis.airport_abm.schedule_compiler import (
        ScheduleCompilationError,
        counts_to_fractions,
    )

    with pytest.raises(ScheduleCompilationError, match="no source People capacity"):
        counts_to_fractions(
            {"restroom": (1.0, 0.0)},
            source_design_capacity={"restroom": None},
        )


def test_annual_schedule_requires_actual_365_by_96_rows(tmp_path: Path) -> None:
    from idfrepair.analysis.airport_abm.schedule_compiler import (
        ScheduleCompilationError,
        write_schedule_file,
    )

    with pytest.raises(ScheduleCompilationError, match="35040"):
        write_schedule_file(
            tmp_path / "bad.csv",
            {"gate": [0.25] * 96},
            days=365,
            interval_minutes=15,
        )

    values = [float(index % 96) / 95.0 for index in range(365 * 96)]
    output = write_schedule_file(
        tmp_path / "annual.csv",
        {"gate": values},
        days=365,
        interval_minutes=15,
    )

    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["gate"]
    assert len(rows) == 1 + 365 * 96
    assert float(rows[1][0]) == pytest.approx(0.0)
    assert float(rows[-1][0]) == pytest.approx(1.0)


def test_schedule_writer_rejects_mismatched_spaces_and_nonfinite_values(
    tmp_path: Path,
) -> None:
    from idfrepair.analysis.airport_abm.schedule_compiler import (
        ScheduleCompilationError,
        write_schedule_file,
    )

    with pytest.raises(ScheduleCompilationError, match="same row count"):
        write_schedule_file(
            tmp_path / "bad.csv",
            {"a": [0.0] * 96, "b": [0.0] * 95},
            days=1,
            interval_minutes=15,
        )
    with pytest.raises(ScheduleCompilationError, match="finite"):
        write_schedule_file(
            tmp_path / "nan.csv",
            {"a": [0.0] * 95 + [float("nan")]},
            days=1,
            interval_minutes=15,
        )
