from __future__ import annotations

import importlib


def test_configured_graph_preserves_door_instances_and_blocks_all_surface_candidates() -> None:
    model = importlib.import_module("idfrepair.analysis.airport_abm.model")
    module = importlib.import_module("idfrepair.analysis.airport_abm.config_graph")
    nodes = (
        model.SpaceNode("gate", "domestic_waiting", "east"),
        model.SpaceNode("shop", "commercial", "east"),
        model.SpaceNode("office", "office", "east"),
        model.SpaceNode("intl", "international_hall", "south"),
    )
    door_connections = (
        {
            "space_names": ["gate", "shop"],
            "physical_door_pairs": [["door-a1", "door-a2"], ["door-b1", "door-b2"]],
        },
        {
            "space_names": ["gate", "office"],
            "physical_door_pairs": [["door-c1", "door-c2"]],
        },
    )
    surface_candidates = (
        {
            "space_names": ["gate", "intl"],
            "physical_surface_pairs": [["wall-a", "wall-b"]],
        },
    )
    config = {
        "schema_version": "idfrepair.airport-abm-access-config.v3",
        "default_door_roles": ["STAFF"],
        "door_rules": [
            {
                "function_pair": ["commercial", "domestic_waiting"],
                "roles": ["DOMESTIC_DEPARTURE", "DOMESTIC_TRANSFER", "STAFF"],
                "scenario_condition": "time_budgeted_detour_only",
            }
        ],
        "functional_edges": [
            {
                "from": "shop",
                "to": "gate",
                "roles": ["DOMESTIC_DEPARTURE"],
                "evidence_ref": "return to detour anchor",
                "scenario_condition": "detour_return_only",
            }
        ],
        "blocked_surface_pairs": [
            {
                "space_pair": ["gate", "intl"],
                "blocked_reason": "FORBIDDEN_DOMESTIC_INTERNATIONAL_CROSSING",
            }
        ],
    }

    built = module.build_configured_graphs(
        nodes=nodes,
        door_connections=door_connections,
        surface_candidates=surface_candidates,
        config=config,
    )

    gate_to_shop = built.graphs.passenger.shortest_path(
        "gate", "shop", model.AgentClass.DOMESTIC_DEPARTURE
    )
    assert gate_to_shop.edges[0].door_instances == (
        "door-a1|door-a2",
        "door-b1|door-b2",
    )
    assert gate_to_shop.edges[0].scenario_condition == "time_budgeted_detour_only"
    assert built.graphs.staff.shortest_path(
        "gate", "office", model.AgentClass.STAFF
    ).nodes == ("gate", "office")
    assert built.audit == {
        "physical_door_pairs": 3,
        "unique_space_door_connections": 2,
        "directed_layer_a_edges": 4,
        "paired_surface_space_candidates": 1,
        "directed_layer_c_edges": 2,
        "layer_c_routing_input_count": 0,
        "functional_layer_b_edges": 1,
        "blocked_surface_pairs": 1,
    }
    candidate_edges = [
        edge
        for edge in built.graphs.passenger.edges
        if edge.evidence_layer is model.EvidenceLayer.C
    ]
    assert len(candidate_edges) == 2
    assert {edge.blocked_reason for edge in candidate_edges} == {
        "FORBIDDEN_DOMESTIC_INTERNATIONAL_CROSSING"
    }
    assert all(not edge.routable for edge in candidate_edges)
