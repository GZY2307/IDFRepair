from __future__ import annotations

import importlib


def test_group_config_expands_only_declared_source_groups_and_existing_surface_blocks() -> None:
    model = importlib.import_module("idfrepair.analysis.airport_abm.model")
    module = importlib.import_module("idfrepair.analysis.airport_abm.group_config")
    nodes = (
        model.SpaceNode("entry", "departure_entry", "central"),
        model.SpaceNode("gate-east-1", "domestic_waiting", "east"),
        model.SpaceNode("gate-east-2", "domestic_waiting", "east"),
        model.SpaceNode("gate-west", "domestic_waiting", "west"),
        model.SpaceNode("intl", "international_hall", "south"),
    )
    candidates = (
        {"space_names": ["gate-east-1", "intl"]},
        {"space_names": ["entry", "intl"]},
    )
    config = {
        "schema_version": "idfrepair.airport-abm-group-config.v3",
        "virtual_nodes": [
            {
                "name": "BOARDING",
                "function": "boarding_sink",
                "region": "off_model",
            }
        ],
        "groups": {
            "entries": {"names": ["entry"]},
            "east_gates": {
                "functions": ["domestic_waiting"],
                "regions": ["east"],
                "name_prefixes": ["gate-east-"],
            },
            "international": {"names": ["intl"]},
            "boarding": {"names": ["BOARDING"]},
        },
        "edge_templates": [
            {
                "from_group": "entries",
                "to_group": "east_gates",
                "roles": ["DOMESTIC_DEPARTURE"],
                "evidence_ref": "declared process",
            },
            {
                "from_group": "east_gates",
                "to_group": "boarding",
                "roles": ["DOMESTIC_DEPARTURE"],
                "evidence_ref": "boarding boundary",
            },
        ],
        "blocked_surface_rules": [
            {
                "left_group": "east_gates",
                "right_group": "international",
                "blocked_reason": "FORBIDDEN_DOMESTIC_INTERNATIONAL_CROSSING",
            }
        ],
        "default_door_roles": ["STAFF"],
        "door_rules": [],
    }

    expanded = module.expand_group_config(
        nodes=nodes,
        surface_candidates=candidates,
        config=config,
    )

    assert [node.name for node in expanded.nodes][-1] == "BOARDING"
    assert expanded.groups == {
        "boarding": ("BOARDING",),
        "east_gates": ("gate-east-1", "gate-east-2"),
        "entries": ("entry",),
        "international": ("intl",),
    }
    assert expanded.access_config["functional_edges"] == [
        {
            "from": "entry",
            "to": "gate-east-1",
            "roles": ["DOMESTIC_DEPARTURE"],
            "evidence_ref": "declared process",
        },
        {
            "from": "entry",
            "to": "gate-east-2",
            "roles": ["DOMESTIC_DEPARTURE"],
            "evidence_ref": "declared process",
        },
        {
            "from": "gate-east-1",
            "to": "BOARDING",
            "roles": ["DOMESTIC_DEPARTURE"],
            "evidence_ref": "boarding boundary",
        },
        {
            "from": "gate-east-2",
            "to": "BOARDING",
            "roles": ["DOMESTIC_DEPARTURE"],
            "evidence_ref": "boarding boundary",
        },
    ]
    assert expanded.access_config["blocked_surface_pairs"] == [
        {
            "space_pair": ["gate-east-1", "intl"],
            "blocked_reason": "FORBIDDEN_DOMESTIC_INTERNATIONAL_CROSSING",
        }
    ]
