"""Machine-checkable access and process-graph admission requirements."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .access_graph import RoleAccessGraphs, RouteNotFound
from .model import AgentClass
from .routing import RouteStage, plan_staged_route


class GraphCheckError(ValueError):
    """Raised when a named access requirement is violated."""


def _graph(graphs: RoleAccessGraphs, name: str):
    if name == "passenger":
        return graphs.passenger
    if name == "staff":
        return graphs.staff
    raise GraphCheckError(f"unknown graph: {name}")


def _group(
    groups: Mapping[str, Sequence[str]], name: str, check_id: str
) -> Sequence[str]:
    values = groups.get(name)
    if not values:
        raise GraphCheckError(f"{check_id}: missing or empty group {name}")
    return values


def validate_graph_checks(
    graphs: RoleAccessGraphs,
    groups: Mapping[str, Sequence[str]],
    checks: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for check in checks:
        check_id = check["id"]
        if check_id in seen_ids:
            raise GraphCheckError(f"duplicate check id: {check_id}")
        seen_ids.add(check_id)
        graph = _graph(graphs, check["graph"])
        role = AgentClass(check["role"])
        sources = _group(groups, check["sources_group"], check_id)
        forbidden = check.get("forbidden_functions", ())
        kind = check["kind"]

        try:
            if kind == "staged_route":
                stages = tuple(
                    RouteStage(
                        item["name"],
                        frozenset(_group(groups, item["group"], check_id)),
                    )
                    for item in check["stages"]
                )
                for source in sources:
                    plan_staged_route(
                        graph,
                        role=role,
                        start=source,
                        stages=stages,
                        forbidden_functions=forbidden,
                    )
                route_count = len(sources)
            elif kind == "reachability":
                targets = _group(groups, check["targets_group"], check_id)
                mode = check.get("mode", "each_source_each_target")
                route_count = 0
                for source in sources:
                    if mode == "each_source_each_target":
                        for target in targets:
                            graph.shortest_path(
                                source,
                                target,
                                role,
                                forbidden_functions=forbidden,
                            )
                            route_count += 1
                    elif mode == "each_source_any_target":
                        found = False
                        for target in targets:
                            try:
                                graph.shortest_path(
                                    source,
                                    target,
                                    role,
                                    forbidden_functions=forbidden,
                                )
                            except RouteNotFound:
                                continue
                            route_count += 1
                            found = True
                            break
                        if not found:
                            raise RouteNotFound(
                                f"no target in {check['targets_group']} is reachable"
                            )
                    else:
                        raise GraphCheckError(f"unknown reachability mode: {mode}")
            elif kind == "unreachable":
                targets = _group(groups, check["targets_group"], check_id)
                for source in sources:
                    for target in targets:
                        try:
                            graph.shortest_path(
                                source,
                                target,
                                role,
                                forbidden_functions=forbidden,
                            )
                        except RouteNotFound:
                            continue
                        raise GraphCheckError(
                            f"unexpected route exists: {source} -> {target}"
                        )
                route_count = 0
            else:
                raise GraphCheckError(f"unknown check kind: {kind}")
        except (RouteNotFound, ValueError) as exc:
            if isinstance(exc, GraphCheckError) and check_id in str(exc):
                raise
            raise GraphCheckError(f"{check_id}: {exc}") from exc

        rows.append(
            {"id": check_id, "status": "PASS", "route_count": route_count}
        )

    return {"status": "PASS", "check_count": len(rows), "checks": rows}
