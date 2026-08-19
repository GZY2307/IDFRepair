from __future__ import annotations

import importlib

import pytest


def _modules():
    model = importlib.import_module("idfrepair.analysis.airport_abm.model")
    dwell = importlib.import_module("idfrepair.analysis.airport_abm.dwell")
    events = importlib.import_module("idfrepair.analysis.airport_abm.events")
    agents = importlib.import_module("idfrepair.analysis.airport_abm.agents")
    simulation = importlib.import_module("idfrepair.analysis.airport_abm.simulation")
    return model, dwell, events, agents, simulation


def test_priority_queue_keeps_insertion_order_for_equal_times() -> None:
    _, _, events, _, _ = _modules()
    queue = events.EventQueue()
    queue.push(30, "advance", "agent-b", {"value": 2})
    queue.push(30, "advance", "agent-a", {"value": 1})
    queue.push(15, "spawn", "agent-c", {})

    assert [(item.time, item.agent_id) for item in queue] == [
        (15, "agent-c"),
        (30, "agent-b"),
        (30, "agent-a"),
    ]


def test_discrete_event_simulation_conserves_agents_and_records_directed_flows() -> None:
    model, dwell, _, agents, simulation = _modules()
    fixed = lambda minutes: dwell.DwellSpec(  # noqa: E731
        kind="deterministic",
        minimum=minutes,
        maximum=minutes,
        value=minutes,
    )
    plans = (
        agents.AgentPlan(
            agent_id="dep-1",
            agent_class=model.AgentClass.DOMESTIC_DEPARTURE,
            spawn_minute=60,
            stops=(
                agents.RouteStop("entry", "departure_entry", fixed(5)),
                agents.RouteStop("central", "mixed_flow", fixed(10)),
                agents.RouteStop("gate", "gate_wait", fixed(30)),
            ),
            terminal_state="BOARDING",
            deadline_minute=110,
        ),
        agents.AgentPlan(
            agent_id="arr-1",
            agent_class=model.AgentClass.DOMESTIC_ARRIVAL,
            spawn_minute=60,
            stops=(
                agents.RouteStop("gate", "deplane", fixed(5)),
                agents.RouteStop("central", "mixed_flow", fixed(5)),
                agents.RouteStop("bag", "baggage", fixed(15)),
                agents.RouteStop("exit", "arrival_exit", fixed(1)),
            ),
            terminal_state="OUT",
        ),
    )

    result = simulation.simulate_agents(plans, seed=40015)

    assert result.spawned_count == 2
    assert result.terminal_count == 2
    assert result.active_count == 0
    assert result.missing_agent_ids == ()
    dep = result.traces["dep-1"]
    assert [(visit.location, visit.start_minute, visit.end_minute) for visit in dep.visits] == [
        ("entry", 60, 65),
        ("central", 65, 75),
        ("gate", 75, 105),
    ]
    assert dep.terminal_state == "BOARDING"
    assert dep.terminal_minute == 105
    assert [(flow.source, flow.target, flow.minute) for flow in dep.flows] == [
        ("entry", "central", 65),
        ("central", "gate", 75),
        ("gate", "BOARDING", 105),
    ]
    assert all(
        left.end_minute <= right.start_minute
        for trace in result.traces.values()
        for left, right in zip(trace.visits, trace.visits[1:])
    )


def test_boarding_deadline_violation_fails_the_scenario() -> None:
    model, dwell, _, agents, simulation = _modules()
    wait = dwell.DwellSpec(
        kind="deterministic", minimum=30, maximum=30, value=30
    )
    plan = agents.AgentPlan(
        agent_id="late",
        agent_class=model.AgentClass.DOMESTIC_DEPARTURE,
        spawn_minute=100,
        stops=(agents.RouteStop("gate", "gate_wait", wait),),
        terminal_state="BOARDING",
        deadline_minute=120,
    )

    with pytest.raises(simulation.SimulationError, match="boarding deadline"):
        simulation.simulate_agents((plan,), seed=40015)


def test_duplicate_agent_ids_fail_before_events_are_processed() -> None:
    model, dwell, _, agents, simulation = _modules()
    stop = agents.RouteStop(
        "office",
        "work",
        dwell.DwellSpec(kind="deterministic", minimum=1, maximum=1, value=1),
    )
    first = agents.AgentPlan("same", model.AgentClass.STAFF, 0, (stop,), "STAFF_EXIT_BOUNDARY")
    second = agents.AgentPlan("same", model.AgentClass.STAFF, 5, (stop,), "STAFF_EXIT_BOUNDARY")

    with pytest.raises(simulation.SimulationError, match="duplicate agent id"):
        simulation.simulate_agents((first, second), seed=1)
