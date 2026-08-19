from __future__ import annotations

import importlib

import pytest


def _modules():
    model = importlib.import_module("idfrepair.analysis.airport_abm.model")
    graph = importlib.import_module("idfrepair.analysis.airport_abm.access_graph")
    return model, graph


def _nodes(model):
    return (
        model.SpaceNode("entry", "departure_entry", "central"),
        model.SpaceNode("central", "central_hall", "central"),
        model.SpaceNode("gate", "domestic_waiting", "east"),
        model.SpaceNode("shop", "commercial", "east"),
        model.SpaceNode("office", "office", "east"),
        model.SpaceNode("it", "info", "central"),
    )


def test_layer_c_candidates_are_audit_only_and_never_routable() -> None:
    model, graph_module = _modules()
    graph = graph_module.AccessGraph(
        nodes=_nodes(model),
        role_scope={model.AgentClass.DOMESTIC_DEPARTURE},
    )
    graph.add_edge(
        model.AccessEdge(
            source="entry",
            target="gate",
            role_set=frozenset({model.AgentClass.DOMESTIC_DEPARTURE}),
            direction="DIRECTED",
            evidence_layer=model.EvidenceLayer.C,
            evidence_ref="paired thermal surface",
            abstraction_flag=False,
            scenario_condition=None,
            blocked_reason="CANDIDATE_NOT_WALKABLE_BY_DEFAULT",
        )
    )

    assert graph.audit_counts() == {
        "layer_a": 0,
        "layer_b": 0,
        "layer_c": 1,
        "routable": 0,
        "blocked": 1,
    }
    with pytest.raises(graph_module.RouteNotFound):
        graph.shortest_path("entry", "gate", model.AgentClass.DOMESTIC_DEPARTURE)


def test_layer_b_edges_are_directional_and_explicitly_labelled_as_abstractions() -> None:
    model, graph_module = _modules()
    graph = graph_module.AccessGraph(
        nodes=_nodes(model),
        role_scope={model.AgentClass.DOMESTIC_DEPARTURE},
    )
    graph.add_edge(
        model.AccessEdge.functional(
            "entry",
            "central",
            {model.AgentClass.DOMESTIC_DEPARTURE},
            evidence_ref="user route annotation",
        )
    )
    graph.add_edge(
        model.AccessEdge.functional(
            "central",
            "gate",
            {model.AgentClass.DOMESTIC_DEPARTURE},
            evidence_ref="official departure process",
        )
    )

    path = graph.shortest_path(
        "entry", "gate", model.AgentClass.DOMESTIC_DEPARTURE
    )
    assert path.nodes == ("entry", "central", "gate")
    assert [edge.evidence_label for edge in path.edges] == [
        "functional route abstraction",
        "functional route abstraction",
    ]
    with pytest.raises(graph_module.RouteNotFound):
        graph.shortest_path("gate", "entry", model.AgentClass.DOMESTIC_DEPARTURE)


def test_passenger_and_staff_use_separate_graphs_and_office_is_never_a_shortcut() -> None:
    model, graph_module = _modules()
    roles = {
        model.AgentClass.DOMESTIC_DEPARTURE,
        model.AgentClass.STAFF,
    }
    edges = (
        model.AccessEdge.functional("entry", "central", roles, "process"),
        model.AccessEdge.functional("central", "gate", roles, "process"),
        model.AccessEdge.strong_door("entry", "office", roles, "door-1"),
        model.AccessEdge.strong_door("office", "gate", roles, "door-2"),
    )

    graphs = graph_module.build_role_graphs(_nodes(model), edges)

    passenger_path = graphs.passenger.shortest_path(
        "entry", "gate", model.AgentClass.DOMESTIC_DEPARTURE
    )
    assert passenger_path.nodes == ("entry", "central", "gate")
    with pytest.raises(graph_module.RouteNotFound):
        graphs.passenger.shortest_path(
            "entry", "office", model.AgentClass.DOMESTIC_DEPARTURE
        )
    assert graphs.staff.shortest_path(
        "entry", "office", model.AgentClass.STAFF
    ).nodes == ("entry", "office")
    with pytest.raises(graph_module.RoleScopeError):
        graphs.staff.shortest_path(
            "entry", "gate", model.AgentClass.DOMESTIC_DEPARTURE
        )


def test_strong_door_helper_preserves_physical_instances_on_one_space_edge() -> None:
    model, graph_module = _modules()
    edge = model.AccessEdge.strong_door(
        "gate",
        "shop",
        {model.AgentClass.DOMESTIC_DEPARTURE},
        evidence_ref="OSM reciprocal Door",
        door_instances=("door-pair-a", "door-pair-b"),
    )
    graph = graph_module.AccessGraph(
        nodes=_nodes(model),
        role_scope={model.AgentClass.DOMESTIC_DEPARTURE},
    )
    graph.add_edge(edge)

    assert graph.shortest_path(
        "gate", "shop", model.AgentClass.DOMESTIC_DEPARTURE
    ).edges[0].door_instances == ("door-pair-a", "door-pair-b")
    assert edge.evidence_label == "STRONG_ACCESS_EDGE"
