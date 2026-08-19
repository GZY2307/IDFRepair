"""Process-stage routing and closed discretionary detours."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .access_graph import AccessGraph, RouteNotFound
from .model import AgentClass, RoutePath


class ProcessRouteError(ValueError):
    """Raised when a mandatory process stage cannot be reached."""


@dataclass(frozen=True, slots=True)
class RouteStage:
    name: str
    candidates: frozenset[str]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("route stage name must not be blank")
        if not self.candidates:
            raise ValueError("route stage candidates must not be empty")


@dataclass(frozen=True, slots=True)
class StagedRoute:
    path: RoutePath
    stage_nodes: tuple[tuple[str, str], ...]


def _join_paths(paths: Iterable[RoutePath]) -> RoutePath:
    nodes: list[str] = []
    edges = []
    for path in paths:
        if not nodes:
            nodes.extend(path.nodes)
        else:
            if nodes[-1] != path.nodes[0]:
                raise ProcessRouteError("route segments do not join")
            nodes.extend(path.nodes[1:])
        edges.extend(path.edges)
    return RoutePath(nodes=tuple(nodes), edges=tuple(edges))


def plan_staged_route(
    graph: AccessGraph,
    *,
    role: AgentClass,
    start: str,
    stages: Iterable[RouteStage],
    forbidden_functions: Iterable[str] = (),
) -> StagedRoute:
    """Resolve each mandatory stage in order, ignoring cross-stage shortcuts."""

    current = start
    segments: list[RoutePath] = []
    selected: list[tuple[str, str]] = []
    forbidden = frozenset(forbidden_functions)
    for stage in stages:
        choices: list[tuple[int, str, RoutePath]] = []
        for candidate in sorted(stage.candidates):
            try:
                path = graph.shortest_path(
                    current,
                    candidate,
                    role,
                    forbidden_functions=forbidden,
                )
            except RouteNotFound:
                continue
            choices.append((len(path.edges), candidate, path))
        if not choices:
            raise ProcessRouteError(
                f"mandatory stage is unreachable: {stage.name} from {current}"
            )
        _, chosen, segment = min(choices, key=lambda item: (item[0], item[1]))
        segments.append(segment)
        selected.append((stage.name, chosen))
        current = chosen
    if not segments:
        return StagedRoute(
            path=RoutePath(nodes=(start,), edges=()), stage_nodes=()
        )
    return StagedRoute(path=_join_paths(segments), stage_nodes=tuple(selected))


def plan_detour_round_trip(
    graph: AccessGraph,
    *,
    role: AgentClass,
    anchor: str,
    destination: str,
    allowed_functions: Iterable[str],
) -> RoutePath:
    """Plan a detour that must return to the exact anchor before resuming."""

    allowed = frozenset(allowed_functions)
    if graph.nodes[destination].function not in allowed:
        raise ProcessRouteError("detour destination function is not allowed")
    outbound = graph.shortest_path(anchor, destination, role)
    inbound = graph.shortest_path(destination, anchor, role)
    combined = _join_paths((outbound, inbound))
    anchor_function = graph.nodes[anchor].function
    for node_name in combined.nodes[1:-1]:
        function = graph.nodes[node_name].function
        if function not in allowed and function != anchor_function:
            raise ProcessRouteError(
                f"detour traverses non-detour function: {function}"
            )
    if combined.nodes[0] != anchor or combined.nodes[-1] != anchor:
        raise ProcessRouteError("detour did not return to its anchor")
    return combined
