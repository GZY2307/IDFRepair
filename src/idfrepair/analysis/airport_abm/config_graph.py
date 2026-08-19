"""Build role-specific graphs from a private, evidence-backed route config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .access_graph import RoleAccessGraphs, build_role_graphs
from .model import AccessEdge, AgentClass, EvidenceLayer, SpaceNode


@dataclass(frozen=True, slots=True)
class ConfiguredGraphs:
    graphs: RoleAccessGraphs
    audit: dict[str, int]


def _roles(values: Iterable[str]) -> frozenset[AgentClass]:
    try:
        roles = frozenset(AgentClass(value) for value in values)
    except ValueError as exc:
        raise ValueError(f"unknown agent role: {exc}") from exc
    if not roles:
        raise ValueError("configured edge has no roles")
    return roles


def _space_pair(values: Sequence[str]) -> tuple[str, str]:
    if len(values) != 2 or values[0] == values[1]:
        raise ValueError("space pair must contain two distinct names")
    return tuple(sorted((values[0], values[1])))


def build_configured_graphs(
    *,
    nodes: Iterable[SpaceNode],
    door_connections: Iterable[Mapping[str, Any]],
    surface_candidates: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> ConfiguredGraphs:
    if config.get("schema_version") != "idfrepair.airport-abm-access-config.v3":
        raise ValueError("invalid access config schema")
    node_tuple = tuple(nodes)
    node_by_name = {node.name: node for node in node_tuple}
    if len(node_by_name) != len(node_tuple):
        raise ValueError("duplicate graph node")

    default_door_roles = _roles(config.get("default_door_roles", ()))
    door_rules: dict[
        tuple[str, str], tuple[frozenset[AgentClass], str | None]
    ] = {}
    for raw_rule in config.get("door_rules", ()):
        function_pair = _space_pair(raw_rule["function_pair"])
        if function_pair in door_rules:
            raise ValueError(f"duplicate door rule: {function_pair}")
        door_rules[function_pair] = (
            _roles(raw_rule["roles"]),
            raw_rule.get("scenario_condition"),
        )

    edges: list[AccessEdge] = []
    physical_door_pairs = 0
    unique_door_connections = 0
    for connection in door_connections:
        source, target = _space_pair(connection["space_names"])
        if source not in node_by_name or target not in node_by_name:
            raise ValueError(f"door connection references unknown node: {source}, {target}")
        function_pair = tuple(
            sorted((node_by_name[source].function, node_by_name[target].function))
        )
        roles, condition = door_rules.get(
            function_pair, (default_door_roles, None)
        )
        instances = tuple(
            "|".join(sorted(pair))
            for pair in connection.get("physical_door_pairs", ())
        )
        physical_door_pairs += len(instances)
        unique_door_connections += 1
        reference = "OSM reciprocal Door"
        edges.append(
            AccessEdge.strong_door(
                source,
                target,
                roles,
                reference,
                door_instances=instances,
                scenario_condition=condition,
            )
        )
        edges.append(
            AccessEdge.strong_door(
                target,
                source,
                roles,
                reference,
                door_instances=instances,
                scenario_condition=condition,
            )
        )

    blocked_pairs = {
        _space_pair(row["space_pair"]): row["blocked_reason"]
        for row in config.get("blocked_surface_pairs", ())
    }
    all_roles = frozenset(AgentClass)
    surface_count = 0
    blocked_count = 0
    for candidate in surface_candidates:
        source, target = _space_pair(candidate["space_names"])
        if source not in node_by_name or target not in node_by_name:
            raise ValueError(
                f"surface candidate references unknown node: {source}, {target}"
            )
        pair = (source, target)
        reason = blocked_pairs.get(pair, "CANDIDATE_NOT_WALKABLE_BY_DEFAULT")
        if pair in blocked_pairs:
            blocked_count += 1
        for edge_source, edge_target in ((source, target), (target, source)):
            edges.append(
                AccessEdge(
                    source=edge_source,
                    target=edge_target,
                    role_set=all_roles,
                    direction="DIRECTED",
                    evidence_layer=EvidenceLayer.C,
                    evidence_ref="paired thermal surface",
                    abstraction_flag=False,
                    scenario_condition=None,
                    blocked_reason=reason,
                )
            )
        surface_count += 1

    functional_count = 0
    for raw_edge in config.get("functional_edges", ()):
        source = raw_edge["from"]
        target = raw_edge["to"]
        if source not in node_by_name or target not in node_by_name:
            raise ValueError(
                f"functional edge references unknown node: {source}, {target}"
            )
        edges.append(
            AccessEdge.functional(
                source,
                target,
                _roles(raw_edge["roles"]),
                raw_edge["evidence_ref"],
                scenario_condition=raw_edge.get("scenario_condition"),
                blocked_reason=raw_edge.get("blocked_reason"),
            )
        )
        functional_count += 1

    return ConfiguredGraphs(
        graphs=build_role_graphs(node_tuple, edges),
        audit={
            "physical_door_pairs": physical_door_pairs,
            "unique_space_door_connections": unique_door_connections,
            "directed_layer_a_edges": unique_door_connections * 2,
            "paired_surface_space_candidates": surface_count,
            "directed_layer_c_edges": surface_count * 2,
            "layer_c_routing_input_count": 0,
            "functional_layer_b_edges": functional_count,
            "blocked_surface_pairs": blocked_count,
        },
    )
