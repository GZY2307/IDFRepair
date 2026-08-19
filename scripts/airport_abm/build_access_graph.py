#!/usr/bin/env python3
"""Expand a private group config into an exact, private V3 access registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from idfrepair.analysis.airport_abm.config_graph import build_configured_graphs
from idfrepair.analysis.airport_abm.group_config import expand_group_config
from idfrepair.analysis.airport_abm.graph_checks import validate_graph_checks
from idfrepair.analysis.airport_abm.model import AccessEdge, SpaceNode
from idfrepair.analysis.airport_abm.source import load_space_mapping


def _edge_record(edge: AccessEdge) -> dict[str, Any]:
    return {
        "from": edge.source,
        "to": edge.target,
        "roles": sorted(role.value for role in edge.role_set),
        "direction": edge.direction,
        "evidence_layer": edge.evidence_layer.value,
        "evidence_label": edge.evidence_label,
        "evidence_ref": edge.evidence_ref,
        "abstraction_flag": edge.abstraction_flag,
        "scenario_condition": edge.scenario_condition,
        "blocked_reason": edge.blocked_reason,
        "door_instances": list(edge.door_instances),
        "routable": edge.routable,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--model-audit", type=Path, required=True)
    parser.add_argument("--group-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_spaces = load_space_mapping(args.mapping)
    nodes = tuple(
        SpaceNode(space.name, space.function, space.region)
        for space in source_spaces
    )
    model_audit = json.loads(args.model_audit.read_text(encoding="utf-8"))
    group_config = json.loads(args.group_config.read_text(encoding="utf-8"))
    doors = model_audit["door_audit"]["space_connections"]
    candidates = model_audit["surface_audit"]["candidate_space_connections"]
    expanded = expand_group_config(
        nodes=nodes,
        surface_candidates=candidates,
        config=group_config,
    )
    built = build_configured_graphs(
        nodes=expanded.nodes,
        door_connections=doors,
        surface_candidates=candidates,
        config=expanded.access_config,
    )
    validation = validate_graph_checks(
        built.graphs,
        expanded.groups,
        group_config.get("checks", ()),
    )

    payload = {
        "schema_version": "idfrepair.airport-abm-access-registry.v3",
        "node_count": len(expanded.nodes),
        "groups": {name: list(values) for name, values in expanded.groups.items()},
        "audit": built.audit,
        "passenger_graph": built.graphs.passenger.audit_counts(),
        "staff_graph": built.graphs.staff.audit_counts(),
        "validation": validation,
        "nodes": [
            {
                "name": node.name,
                "function": node.function,
                "region": node.region,
                "is_virtual": node.is_virtual,
            }
            for node in expanded.nodes
        ],
        "passenger_edges": [
            _edge_record(edge) for edge in built.graphs.passenger.edges
        ],
        "staff_edges": [_edge_record(edge) for edge in built.graphs.staff.edges],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "access_registry_complete",
                "node_count": payload["node_count"],
                "audit": payload["audit"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
