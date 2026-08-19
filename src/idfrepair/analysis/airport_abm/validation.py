"""Independent hard-gate validation for simulated agent lifecycles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Set, Tuple

from .model import AgentClass, PASSENGER_CLASSES
from .simulation import SimulationResult


@dataclass(frozen=True, slots=True)
class SimulationValidationReport:
    status: str
    violation_count: int
    violations: tuple[str, ...]
    validated_agents: int


def validate_simulation(
    result: SimulationResult,
    location_functions: Mapping[str, str],
    allowed_edges: Mapping[AgentClass, Set[Tuple[str, str]]],
) -> SimulationValidationReport:
    violations: list[str] = []

    def add(value: str) -> None:
        if value not in violations:
            violations.append(value)

    if result.missing_agent_ids:
        for agent_id in result.missing_agent_ids:
            add(f"{agent_id}:MISSING_AGENT")
    if result.active_count:
        add(f"ACTIVE_AGENTS_REMAIN:{result.active_count}")

    for agent_id in sorted(result.traces):
        trace = result.traces[agent_id]
        functions: list[str] = []
        for visit in trace.visits:
            function = location_functions.get(visit.location)
            if function is None:
                add(f"{agent_id}:UNKNOWN_LOCATION:{visit.location}")
                function = "UNKNOWN"
            functions.append(function)
            if visit.start_minute < 0 or visit.end_minute < visit.start_minute:
                add(f"{agent_id}:NEGATIVE_OR_REVERSED_VISIT")
            if (
                trace.agent_class in PASSENGER_CLASSES
                and function in {"office", "breakroom", "info"}
            ):
                add(f"{agent_id}:PASSENGER_FORBIDDEN_FUNCTION:{function}")

        for left, right in zip(trace.visits, trace.visits[1:]):
            if left.end_minute > right.start_minute + 1e-9:
                add(f"{agent_id}:MULTIPLE_SIMULTANEOUS_LOCATIONS")

        admitted = allowed_edges.get(trace.agent_class, set())
        for flow in trace.flows:
            if (flow.source, flow.target) not in admitted:
                add(
                    f"{agent_id}:EDGE_NOT_IN_ROLE_GRAPH:"
                    f"{flow.source}->{flow.target}"
                )

        _validate_flow_sequence(agent_id, trace, add)
        _validate_detours(agent_id, trace, add)
        _validate_lifecycle(agent_id, trace.agent_class, functions, trace.terminal_state, add)

    status = "PASS" if not violations else "FAIL"
    return SimulationValidationReport(
        status=status,
        violation_count=len(violations),
        violations=tuple(violations),
        validated_agents=len(result.traces),
    )


def _validate_flow_sequence(agent_id, trace, add) -> None:
    expected_count = len(trace.visits)
    if len(trace.flows) != expected_count:
        add(f"{agent_id}:FLOW_VISIT_COUNT_MISMATCH")
        return
    for index, flow in enumerate(trace.flows):
        source = trace.visits[index].location
        target = (
            trace.visits[index + 1].location
            if index + 1 < len(trace.visits)
            else trace.terminal_state
        )
        if flow.source != source or flow.target != target:
            add(f"{agent_id}:FLOW_VISIT_SEQUENCE_MISMATCH")
            return


def _validate_detours(agent_id, trace, add) -> None:
    open_anchor: str | None = None
    for visit in trace.visits:
        marker = visit.detour_anchor
        if marker is None:
            if open_anchor is not None:
                add(f"{agent_id}:DETOUR_DID_NOT_RETURN:{open_anchor}")
                open_anchor = None
            continue
        if open_anchor is None:
            if visit.location == marker:
                continue
            open_anchor = marker
        elif marker != open_anchor:
            add(f"{agent_id}:DETOUR_ANCHOR_CHANGED:{open_anchor}->{marker}")
            open_anchor = marker
        if open_anchor is not None and visit.location == open_anchor:
            open_anchor = None
    if open_anchor is not None:
        add(f"{agent_id}:DETOUR_DID_NOT_RETURN:{open_anchor}")


def _validate_lifecycle(agent_id, agent_class, functions, terminal_state, add) -> None:
    if not functions:
        add(f"{agent_id}:NO_VISITS")
        return
    if agent_class is AgentClass.DOMESTIC_DEPARTURE:
        if terminal_state != "BOARDING":
            add(f"{agent_id}:DEPARTURE_WRONG_TERMINAL")
        if functions[-1] != "domestic_waiting":
            add(f"{agent_id}:DEPARTURE_NOT_AT_DOMESTIC_GATE")
    elif agent_class is AgentClass.DOMESTIC_ARRIVAL:
        if terminal_state != "OUT":
            add(f"{agent_id}:ARRIVAL_WRONG_TERMINAL")
        baggage = _first(functions, "baggage_claim")
        exit_index = _first(functions, "arrival_exit")
        if baggage is None or exit_index is None or baggage >= exit_index:
            add(f"{agent_id}:ARRIVAL_BAGGAGE_NOT_BEFORE_EXIT")
    elif agent_class is AgentClass.DOMESTIC_TRANSFER:
        if terminal_state != "BOARDING":
            add(f"{agent_id}:TRANSFER_WRONG_TERMINAL")
        if "baggage_claim" in functions:
            add(f"{agent_id}:TRANSFER_USED_BAGGAGE")
        if functions[-1] != "domestic_waiting":
            add(f"{agent_id}:TRANSFER_NOT_AT_DOMESTIC_GATE")
    elif agent_class is AgentClass.INTERNATIONAL_ARRIVAL:
        if terminal_state != "OFF_MODEL_LEVEL1_IMMIGRATION":
            add(f"{agent_id}:INTERNATIONAL_WRONG_TERMINAL")
        if any(
            function
            in {"baggage_claim", "arrival_exit", "central_hall", "domestic_waiting"}
            for function in functions
        ):
            add(f"{agent_id}:INTERNATIONAL_DOMESTIC_PROCESS_LEAK")
    elif agent_class is AgentClass.STAFF:
        if terminal_state != "STAFF_EXIT_BOUNDARY":
            add(f"{agent_id}:STAFF_WRONG_TERMINAL")


def _first(values: list[str], target: str) -> int | None:
    try:
        return values.index(target)
    except ValueError:
        return None
