"""Evidence-tiered, role-separated directed access graphs."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

from .model import (
    AccessEdge,
    AgentClass,
    EvidenceLayer,
    PASSENGER_CLASSES,
    RoutePath,
    SpaceNode,
)


class RouteNotFound(ValueError):
    """Raised when no admissible directed path exists."""


class RoleScopeError(ValueError):
    """Raised when a role is sent to the wrong role-specific graph."""


_PASSENGER_FORBIDDEN_FUNCTIONS = frozenset({"office", "breakroom", "info"})


class AccessGraph:
    def __init__(
        self,
        *,
        nodes: Iterable[SpaceNode],
        role_scope: Iterable[AgentClass],
    ) -> None:
        self.nodes = {node.name: node for node in nodes}
        if len(self.nodes) == 0:
            raise ValueError("access graph must contain nodes")
        self.role_scope = frozenset(role_scope)
        if not self.role_scope:
            raise ValueError("role_scope must not be empty")
        self._edges: list[AccessEdge] = []
        self._outgoing: dict[str, list[AccessEdge]] = defaultdict(list)

    @property
    def edges(self) -> tuple[AccessEdge, ...]:
        return tuple(self._edges)

    def add_edge(self, edge: AccessEdge) -> None:
        if edge.source not in self.nodes:
            raise ValueError(f"unknown edge source: {edge.source}")
        if edge.target not in self.nodes:
            raise ValueError(f"unknown edge target: {edge.target}")
        self._edges.append(edge)
        self._outgoing[edge.source].append(edge)

    def audit_counts(self) -> dict[str, int]:
        return {
            "layer_a": sum(
                edge.evidence_layer is EvidenceLayer.A for edge in self._edges
            ),
            "layer_b": sum(
                edge.evidence_layer is EvidenceLayer.B for edge in self._edges
            ),
            "layer_c": sum(
                edge.evidence_layer is EvidenceLayer.C for edge in self._edges
            ),
            "routable": sum(edge.routable for edge in self._edges),
            "blocked": sum(not edge.routable for edge in self._edges),
        }

    def shortest_path(
        self,
        source: str,
        target: str,
        role: AgentClass,
        *,
        forbidden_functions: Iterable[str] = (),
    ) -> RoutePath:
        if role not in self.role_scope:
            raise RoleScopeError(f"role {role.value} is outside this graph")
        if source not in self.nodes or target not in self.nodes:
            raise RouteNotFound(f"unknown route endpoint: {source} -> {target}")
        forbidden = set(forbidden_functions)
        if role in PASSENGER_CLASSES:
            forbidden.update(_PASSENGER_FORBIDDEN_FUNCTIONS)
            if self.nodes[source].function in _PASSENGER_FORBIDDEN_FUNCTIONS:
                raise RouteNotFound(f"passenger source is forbidden: {source}")
            if self.nodes[target].function in forbidden:
                raise RouteNotFound(f"passenger target is forbidden: {target}")
        elif self.nodes[target].function in forbidden:
            raise RouteNotFound(f"target function is forbidden: {target}")
        if source == target:
            return RoutePath(nodes=(source,), edges=())

        previous: dict[str, tuple[str, AccessEdge]] = {}
        visited = {source}
        queue: deque[str] = deque([source])
        while queue:
            current = queue.popleft()
            for edge in self._outgoing.get(current, ()):
                if not edge.routable or role not in edge.role_set:
                    continue
                next_name = edge.target
                next_node = self.nodes[next_name]
                if next_node.function in forbidden:
                    continue
                if next_name in visited:
                    continue
                visited.add(next_name)
                previous[next_name] = (current, edge)
                if next_name == target:
                    return self._reconstruct(source, target, previous)
                queue.append(next_name)
        raise RouteNotFound(f"no admissible route: {source} -> {target}")

    @staticmethod
    def _reconstruct(
        source: str,
        target: str,
        previous: dict[str, tuple[str, AccessEdge]],
    ) -> RoutePath:
        nodes = [target]
        edges: list[AccessEdge] = []
        current = target
        while current != source:
            parent, edge = previous[current]
            nodes.append(parent)
            edges.append(edge)
            current = parent
        nodes.reverse()
        edges.reverse()
        return RoutePath(nodes=tuple(nodes), edges=tuple(edges))


@dataclass(frozen=True, slots=True)
class RoleAccessGraphs:
    passenger: AccessGraph
    staff: AccessGraph


def build_role_graphs(
    nodes: Iterable[SpaceNode], edges: Iterable[AccessEdge]
) -> RoleAccessGraphs:
    node_tuple = tuple(nodes)
    passenger = AccessGraph(nodes=node_tuple, role_scope=PASSENGER_CLASSES)
    staff = AccessGraph(nodes=node_tuple, role_scope={AgentClass.STAFF})
    for edge in edges:
        if edge.role_set.intersection(PASSENGER_CLASSES):
            passenger.add_edge(edge)
        if AgentClass.STAFF in edge.role_set:
            staff.add_edge(edge)
    return RoleAccessGraphs(passenger=passenger, staff=staff)
