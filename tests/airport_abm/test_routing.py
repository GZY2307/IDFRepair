from __future__ import annotations

import importlib


def _modules():
    model = importlib.import_module("idfrepair.analysis.airport_abm.model")
    graph_module = importlib.import_module(
        "idfrepair.analysis.airport_abm.access_graph"
    )
    routing = importlib.import_module("idfrepair.analysis.airport_abm.routing")
    return model, graph_module, routing


def _graph(model, graph_module):
    nodes = (
        model.SpaceNode("entry", "departure_entry", "central"),
        model.SpaceNode("central", "central_hall", "central"),
        model.SpaceNode("gate-a", "domestic_waiting", "east"),
        model.SpaceNode("gate-b", "domestic_waiting", "west"),
        model.SpaceNode("bag", "baggage_claim", "central"),
        model.SpaceNode("exit", "arrival_exit", "central"),
        model.SpaceNode("shop", "commercial", "central"),
        model.SpaceNode("intl-gate", "international_arrival", "south"),
        model.SpaceNode("intl-hall", "international_hall", "south"),
        model.SpaceNode("transfer", "transfer", "south"),
        model.SpaceNode("BOARDING", "boarding_sink", "off_model", True),
        model.SpaceNode("OUT", "out_sink", "off_model", True),
        model.SpaceNode(
            "OFF_MODEL_LEVEL1_IMMIGRATION", "level1_sink", "off_model", True
        ),
    )
    passenger_roles = set(model.PASSENGER_CLASSES)
    edges = (
        model.AccessEdge.functional("entry", "central", passenger_roles, "process"),
        model.AccessEdge.functional("central", "gate-a", passenger_roles, "process"),
        model.AccessEdge.functional("central", "gate-b", passenger_roles, "process"),
        model.AccessEdge.functional("entry", "gate-a", passenger_roles, "bad shortcut"),
        model.AccessEdge.functional("gate-a", "central", passenger_roles, "process"),
        model.AccessEdge.functional("gate-b", "central", passenger_roles, "process"),
        model.AccessEdge.functional("central", "bag", passenger_roles, "process"),
        model.AccessEdge.functional("bag", "exit", passenger_roles, "process"),
        model.AccessEdge.functional("exit", "OUT", passenger_roles, "boundary"),
        model.AccessEdge.functional("gate-a", "exit", passenger_roles, "bad shortcut"),
        model.AccessEdge.functional("bag", "gate-b", passenger_roles, "bad shortcut"),
        model.AccessEdge.functional("gate-a", "BOARDING", passenger_roles, "boarding"),
        model.AccessEdge.functional("gate-b", "BOARDING", passenger_roles, "boarding"),
        model.AccessEdge.functional("central", "shop", passenger_roles, "detour"),
        model.AccessEdge.functional("shop", "central", passenger_roles, "detour return"),
        model.AccessEdge.functional("shop", "gate-a", passenger_roles, "bad shortcut"),
        model.AccessEdge.functional("intl-gate", "intl-hall", passenger_roles, "process"),
        model.AccessEdge.functional("intl-hall", "transfer", passenger_roles, "process"),
        model.AccessEdge.functional(
            "transfer", "OFF_MODEL_LEVEL1_IMMIGRATION", passenger_roles, "boundary"
        ),
        model.AccessEdge.functional("intl-hall", "bag", passenger_roles, "bad leak"),
    )
    graph = graph_module.AccessGraph(nodes=nodes, role_scope=model.PASSENGER_CLASSES)
    for edge in edges:
        graph.add_edge(edge)
    return graph


def test_domestic_departure_stages_override_a_shorter_direct_gate_edge() -> None:
    model, graph_module, routing = _modules()
    graph = _graph(model, graph_module)

    plan = routing.plan_staged_route(
        graph,
        role=model.AgentClass.DOMESTIC_DEPARTURE,
        start="entry",
        stages=(
            routing.RouteStage("public_spine", frozenset({"central"})),
            routing.RouteStage("gate", frozenset({"gate-a"})),
            routing.RouteStage("boarding", frozenset({"BOARDING"})),
        ),
    )

    assert plan.path.nodes == ("entry", "central", "gate-a", "BOARDING")
    assert plan.stage_nodes == (
        ("public_spine", "central"),
        ("gate", "gate-a"),
        ("boarding", "BOARDING"),
    )


def test_domestic_arrival_stages_force_baggage_before_exit() -> None:
    model, graph_module, routing = _modules()
    graph = _graph(model, graph_module)

    plan = routing.plan_staged_route(
        graph,
        role=model.AgentClass.DOMESTIC_ARRIVAL,
        start="gate-a",
        stages=(
            routing.RouteStage("mixed_flow", frozenset({"central"})),
            routing.RouteStage("baggage", frozenset({"bag"})),
            routing.RouteStage("arrival_exit", frozenset({"exit"})),
            routing.RouteStage("out", frozenset({"OUT"})),
        ),
    )

    assert plan.path.nodes == ("gate-a", "central", "bag", "exit", "OUT")


def test_transfer_and_international_routes_exclude_domestic_baggage_leaks() -> None:
    model, graph_module, routing = _modules()
    graph = _graph(model, graph_module)

    transfer = routing.plan_staged_route(
        graph,
        role=model.AgentClass.DOMESTIC_TRANSFER,
        start="gate-a",
        stages=(
            routing.RouteStage("mixed_flow", frozenset({"central"})),
            routing.RouteStage("next_gate", frozenset({"gate-b"})),
            routing.RouteStage("boarding", frozenset({"BOARDING"})),
        ),
        forbidden_functions={"baggage_claim"},
    )
    international = routing.plan_staged_route(
        graph,
        role=model.AgentClass.INTERNATIONAL_ARRIVAL,
        start="intl-gate",
        stages=(
            routing.RouteStage("international_hall", frozenset({"intl-hall"})),
            routing.RouteStage("vertical_transfer", frozenset({"transfer"})),
            routing.RouteStage(
                "level1_boundary", frozenset({"OFF_MODEL_LEVEL1_IMMIGRATION"})
            ),
        ),
        forbidden_functions={
            "baggage_claim",
            "arrival_exit",
            "central_hall",
            "domestic_waiting",
        },
    )

    assert transfer.path.nodes == (
        "gate-a",
        "central",
        "gate-b",
        "BOARDING",
    )
    assert "bag" not in transfer.path.nodes
    assert international.path.nodes == (
        "intl-gate",
        "intl-hall",
        "transfer",
        "OFF_MODEL_LEVEL1_IMMIGRATION",
    )
    assert "bag" not in international.path.nodes


def test_detour_is_a_closed_round_trip_to_the_exact_anchor() -> None:
    model, graph_module, routing = _modules()
    graph = _graph(model, graph_module)

    detour = routing.plan_detour_round_trip(
        graph,
        role=model.AgentClass.DOMESTIC_DEPARTURE,
        anchor="central",
        destination="shop",
        allowed_functions={"commercial"},
    )

    assert detour.nodes == ("central", "shop", "central")
    assert detour.nodes[0] == detour.nodes[-1] == "central"
