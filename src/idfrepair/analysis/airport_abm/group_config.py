"""Expand private source-group selectors into exact access-edge registries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .model import SpaceNode


@dataclass(frozen=True, slots=True)
class ExpandedGroupConfig:
    nodes: tuple[SpaceNode, ...]
    groups: dict[str, tuple[str, ...]]
    access_config: dict[str, Any]


def _pair(values: Sequence[str]) -> tuple[str, str]:
    if len(values) != 2 or values[0] == values[1]:
        raise ValueError("candidate pair must contain two distinct spaces")
    return tuple(sorted(values))


def _matches(node: SpaceNode, selector: Mapping[str, Any]) -> bool:
    names = selector.get("names")
    if names is not None and node.name not in names:
        return False
    functions = selector.get("functions")
    if functions is not None and node.function not in functions:
        return False
    regions = selector.get("regions")
    if regions is not None and node.region not in regions:
        return False
    prefixes = selector.get("name_prefixes")
    if prefixes is not None and not any(node.name.startswith(item) for item in prefixes):
        return False
    excluded = selector.get("exclude_names", ())
    return node.name not in excluded


def expand_group_config(
    *,
    nodes: Iterable[SpaceNode],
    surface_candidates: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> ExpandedGroupConfig:
    if config.get("schema_version") != "idfrepair.airport-abm-group-config.v3":
        raise ValueError("invalid group config schema")
    expanded_nodes = list(nodes)
    names = {node.name for node in expanded_nodes}
    for raw in config.get("virtual_nodes", ()):
        name = raw["name"]
        if name in names:
            raise ValueError(f"duplicate virtual node: {name}")
        expanded_nodes.append(
            SpaceNode(
                name=name,
                function=raw["function"],
                region=raw["region"],
                is_virtual=True,
            )
        )
        names.add(name)

    groups: dict[str, tuple[str, ...]] = {}
    for group_name in sorted(config.get("groups", {})):
        selector = config["groups"][group_name]
        selected = tuple(
            sorted(node.name for node in expanded_nodes if _matches(node, selector))
        )
        if not selected:
            raise ValueError(f"group is empty: {group_name}")
        groups[group_name] = selected

    functional_edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, tuple[str, ...]]] = set()
    for template in config.get("edge_templates", ()):
        from_group = template["from_group"]
        to_group = template["to_group"]
        if from_group not in groups or to_group not in groups:
            raise ValueError("edge template references an unknown group")
        roles = tuple(template["roles"])
        for source in groups[from_group]:
            for target in groups[to_group]:
                if source == target:
                    continue
                key = (source, target, roles)
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                row: dict[str, Any] = {
                    "from": source,
                    "to": target,
                    "roles": list(roles),
                    "evidence_ref": template["evidence_ref"],
                }
                for optional in ("scenario_condition", "blocked_reason"):
                    if optional in template:
                        row[optional] = template[optional]
                functional_edges.append(row)

    candidates = {
        _pair(candidate["space_names"]) for candidate in surface_candidates
    }
    blocked_surface_pairs: list[dict[str, Any]] = []
    seen_blocks: set[tuple[str, str]] = set()
    for rule in config.get("blocked_surface_rules", ()):
        left = groups.get(rule["left_group"])
        right = groups.get(rule["right_group"])
        if left is None or right is None:
            raise ValueError("blocked surface rule references an unknown group")
        for left_name in left:
            for right_name in right:
                if left_name == right_name:
                    continue
                pair = tuple(sorted((left_name, right_name)))
                if pair not in candidates or pair in seen_blocks:
                    continue
                seen_blocks.add(pair)
                blocked_surface_pairs.append(
                    {
                        "space_pair": list(pair),
                        "blocked_reason": rule["blocked_reason"],
                    }
                )
    blocked_surface_pairs.sort(key=lambda row: tuple(row["space_pair"]))

    return ExpandedGroupConfig(
        nodes=tuple(expanded_nodes),
        groups=groups,
        access_config={
            "schema_version": "idfrepair.airport-abm-access-config.v3",
            "default_door_roles": list(config.get("default_door_roles", ())),
            "door_rules": list(config.get("door_rules", ())),
            "functional_edges": functional_edges,
            "blocked_surface_pairs": blocked_surface_pairs,
        },
    )
