from __future__ import annotations

import importlib

import pytest


def _fixture():
    model = importlib.import_module("idfrepair.analysis.airport_abm.model")
    graph_module = importlib.import_module(
        "idfrepair.analysis.airport_abm.access_graph"
    )
    nodes = (
        model.SpaceNode("entry", "departure_entry", "central"),
        model.SpaceNode("central", "central_hall", "central"),
        model.SpaceNode("gate", "domestic_waiting", "east"),
        model.SpaceNode("office", "office", "east"),
        model.SpaceNode("BOARDING", "boarding_sink", "off", True),
    )
    edges = (
        model.AccessEdge.functional(
            "entry", "central", {model.AgentClass.DOMESTIC_DEPARTURE}, "process"
        ),
        model.AccessEdge.functional(
            "central", "gate", {model.AgentClass.DOMESTIC_DEPARTURE}, "process"
        ),
        model.AccessEdge.functional(
            "gate", "BOARDING", {model.AgentClass.DOMESTIC_DEPARTURE}, "boundary"
        ),
        model.AccessEdge.functional(
            "entry", "office", {model.AgentClass.STAFF}, "staff process"
        ),
    )
    graphs = graph_module.build_role_graphs(nodes, edges)
    groups = {
        "entries": ("entry",),
        "central": ("central",),
        "gates": ("gate",),
        "boarding": ("BOARDING",),
        "offices": ("office",),
    }
    return model, graphs, groups


def test_graph_checks_validate_reachability_unreachability_and_stage_order() -> None:
    model, graphs, groups = _fixture()
    module = importlib.import_module("idfrepair.analysis.airport_abm.graph_checks")
    checks = (
        {
            "id": "departure_process",
            "kind": "staged_route",
            "graph": "passenger",
            "role": "DOMESTIC_DEPARTURE",
            "sources_group": "entries",
            "stages": [
                {"name": "central", "group": "central"},
                {"name": "gate", "group": "gates"},
                {"name": "boarding", "group": "boarding"},
            ],
        },
        {
            "id": "staff_office",
            "kind": "reachability",
            "graph": "staff",
            "role": "STAFF",
            "sources_group": "entries",
            "targets_group": "offices",
            "mode": "each_source_each_target",
        },
        {
            "id": "passenger_office_forbidden",
            "kind": "unreachable",
            "graph": "passenger",
            "role": "DOMESTIC_DEPARTURE",
            "sources_group": "entries",
            "targets_group": "offices",
        },
    )

    result = module.validate_graph_checks(graphs, groups, checks)

    assert result == {
        "status": "PASS",
        "check_count": 3,
        "checks": [
            {"id": "departure_process", "status": "PASS", "route_count": 1},
            {"id": "staff_office", "status": "PASS", "route_count": 1},
            {
                "id": "passenger_office_forbidden",
                "status": "PASS",
                "route_count": 0,
            },
        ],
    }


def test_graph_checks_fail_closed_with_the_requirement_id() -> None:
    _, graphs, groups = _fixture()
    module = importlib.import_module("idfrepair.analysis.airport_abm.graph_checks")
    checks = (
        {
            "id": "wrongly_blocked_gate",
            "kind": "unreachable",
            "graph": "passenger",
            "role": "DOMESTIC_DEPARTURE",
            "sources_group": "entries",
            "targets_group": "gates",
        },
    )

    with pytest.raises(module.GraphCheckError, match="wrongly_blocked_gate"):
        module.validate_graph_checks(graphs, groups, checks)
