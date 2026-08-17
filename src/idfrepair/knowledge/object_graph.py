"""IDD-directed object reference graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from idfrepair.io.idf import IDFDocument, canonical
from idfrepair.knowledge.idd import IDDSchema


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    object_index: int
    object_type: str
    object_name: str


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    field_index: int
    field_name: str
    role: str


@dataclass(frozen=True, slots=True)
class ObjectGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    def neighbors(self, node_id: str) -> tuple[GraphNode, ...]:
        ids = {
            edge.target if edge.source == node_id else edge.source
            for edge in self.edges
            if edge.source == node_id or edge.target == node_id
        }
        return tuple(node for node in self.nodes if node.node_id in ids)


def build_object_graph(document: IDFDocument, idd: IDDSchema) -> ObjectGraph:
    nodes = tuple(
        GraphNode(
            node_id=f"{obj.index}:{canonical(obj.object_type)}:{canonical(obj.name)}",
            object_index=obj.index,
            object_type=obj.object_type,
            object_name=obj.name,
        )
        for obj in document.objects
    )
    by_name: dict[str, list[GraphNode]] = {}
    for node in nodes:
        if node.object_name:
            by_name.setdefault(canonical(node.object_name), []).append(node)
    edges: list[GraphEdge] = []
    for obj, source in zip(document.objects, nodes):
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        for field in obj.fields:
            field_def = definition.field_at(field.index)
            if field_def is None or not field.value.strip():
                continue
            if not (field_def.object_lists or field_def.role.endswith("reference")):
                continue
            matches = by_name.get(canonical(field.value), [])
            if len(matches) != 1:
                continue
            edges.append(GraphEdge(
                source=source.node_id,
                target=matches[0].node_id,
                field_index=field.index,
                field_name=field_def.name,
                role=field_def.role,
            ))
    return ObjectGraph(nodes=nodes, edges=tuple(edges))
