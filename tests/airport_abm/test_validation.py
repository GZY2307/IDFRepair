from __future__ import annotations

from dataclasses import replace
import importlib


def _valid_result():
    model = importlib.import_module("idfrepair.analysis.airport_abm.model")
    dwell = importlib.import_module("idfrepair.analysis.airport_abm.dwell")
    agents = importlib.import_module("idfrepair.analysis.airport_abm.agents")
    simulation = importlib.import_module("idfrepair.analysis.airport_abm.simulation")
    fixed = lambda value: dwell.DwellSpec(  # noqa: E731
        kind="deterministic", minimum=value, maximum=value, value=value
    )
    stop = lambda location, stage, anchor=None: agents.RouteStop(  # noqa: E731
        location, stage, fixed(1), anchor
    )
    plans = (
        agents.AgentPlan(
            "dep",
            model.AgentClass.DOMESTIC_DEPARTURE,
            0,
            (
                stop("entry", "entry"),
                stop("central", "mixed"),
                stop("gate-a", "gate"),
                stop("shop", "detour", "gate-a"),
                stop("gate-a", "detour_return", "gate-a"),
            ),
            "BOARDING",
            10,
        ),
        agents.AgentPlan(
            "arr",
            model.AgentClass.DOMESTIC_ARRIVAL,
            0,
            (
                stop("gate-a", "deplane"),
                stop("central", "mixed"),
                stop("bag", "baggage"),
                stop("exit", "exit"),
            ),
            "OUT",
        ),
        agents.AgentPlan(
            "transfer-agent",
            model.AgentClass.DOMESTIC_TRANSFER,
            0,
            (
                stop("gate-a", "deplane"),
                stop("central", "mixed"),
                stop("gate-b", "gate"),
            ),
            "BOARDING",
            10,
        ),
        agents.AgentPlan(
            "intl-agent",
            model.AgentClass.INTERNATIONAL_ARRIVAL,
            0,
            (
                stop("intl-gate", "deplane"),
                stop("intl-hall", "international_hall"),
                stop("transfer", "vertical_transfer"),
            ),
            "OFF_MODEL_LEVEL1_IMMIGRATION",
        ),
        agents.AgentPlan(
            "staff-agent",
            model.AgentClass.STAFF,
            0,
            (stop("staff-entry", "staff_entry"), stop("office", "work")),
            "STAFF_EXIT_BOUNDARY",
        ),
    )
    result = simulation.simulate_agents(plans, seed=40015)
    functions = {
        "entry": "departure_entry",
        "central": "central_hall",
        "gate-a": "domestic_waiting",
        "gate-b": "domestic_waiting",
        "shop": "commercial",
        "bag": "baggage_claim",
        "exit": "arrival_exit",
        "intl-gate": "international_arrival",
        "intl-hall": "international_hall",
        "transfer": "transfer",
        "staff-entry": "staff_entry_sink",
        "office": "office",
    }
    allowed = {
        agent_class: {
            (flow.source, flow.target)
            for trace in result.traces.values()
            if trace.agent_class is agent_class
            for flow in trace.flows
        }
        for agent_class in model.AgentClass
    }
    return model, agents, result, functions, allowed


def test_validator_accepts_all_five_lifecycles_and_a_closed_detour() -> None:
    _, _, result, functions, allowed = _valid_result()
    module = importlib.import_module("idfrepair.analysis.airport_abm.validation")

    report = module.validate_simulation(result, functions, allowed)

    assert report.status == "PASS"
    assert report.violation_count == 0
    assert report.violations == ()
    assert report.validated_agents == 5


def test_validator_rejects_passenger_office_and_absent_staff_edge() -> None:
    model, agents, result, functions, allowed = _valid_result()
    module = importlib.import_module("idfrepair.analysis.airport_abm.validation")
    dep = result.traces["dep"]
    office_visit = replace(
        dep.visits[1],
        location="office",
        stage="illegal_shortcut",
    )
    result.traces["dep"] = replace(
        dep, visits=(dep.visits[0], office_visit, *dep.visits[2:])
    )
    allowed[model.AgentClass.STAFF] = set()

    report = module.validate_simulation(result, functions, allowed)

    assert "dep:PASSENGER_FORBIDDEN_FUNCTION:office" in report.violations
    assert any(
        item.startswith("staff-agent:EDGE_NOT_IN_ROLE_GRAPH")
        for item in report.violations
    )


def test_validator_rejects_wrong_arrival_order_international_leak_and_open_detour() -> None:
    _, _, result, functions, allowed = _valid_result()
    module = importlib.import_module("idfrepair.analysis.airport_abm.validation")
    arrival = result.traces["arr"]
    result.traces["arr"] = replace(
        arrival,
        visits=(
            arrival.visits[0],
            arrival.visits[1],
            arrival.visits[3],
            arrival.visits[2],
        ),
    )
    international = result.traces["intl-agent"]
    result.traces["intl-agent"] = replace(
        international,
        visits=(international.visits[0], replace(international.visits[1], location="bag"), international.visits[2]),
    )
    departure = result.traces["dep"]
    result.traces["dep"] = replace(departure, visits=departure.visits[:-1])

    report = module.validate_simulation(result, functions, allowed)

    assert "arr:ARRIVAL_BAGGAGE_NOT_BEFORE_EXIT" in report.violations
    assert "intl-agent:INTERNATIONAL_DOMESTIC_PROCESS_LEAK" in report.violations
    assert "dep:DETOUR_DID_NOT_RETURN:gate-a" in report.violations
