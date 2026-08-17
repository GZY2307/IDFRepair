"""Bounded, read-only projections for the browser engineering workbench."""

from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any

from idfrepair.io.idf import IDFDocument, IDFObject, canonical, parse_idf
from idfrepair.knowledge.idd import IDDField, parse_idd
from idfrepair.knowledge.object_graph import ObjectGraph, build_object_graph


MAX_CONTEXT_LINES = 20
MAX_CONTEXT_CHARS = 64_000
MAX_GRAPH_NODES = 30


def _line_number(text: str, offset: int) -> int:
    prefix = text[:max(0, offset)]
    return 1 + prefix.count("\n") + prefix.count("\r") - prefix.count("\r\n")


def _line_start(text: str, offset: int) -> int:
    lf = text.rfind("\n", 0, max(0, offset))
    cr = text.rfind("\r", 0, max(0, offset))
    return max(lf, cr) + 1


def _line_end(text: str, offset: int) -> int:
    candidates = [value for value in (text.find("\n", offset), text.find("\r", offset)) if value >= 0]
    return min(candidates) if candidates else len(text)


def _object_type_offset(text: str, obj: IDFObject) -> int:
    match = re.search(
        rf"(?im)^\s*{re.escape(obj.object_type)}\s*,",
        text[obj.start:obj.end],
    )
    if match is None:
        return obj.start
    line = text.find(obj.object_type, obj.start + match.start(), obj.start + match.end())
    return line if line >= 0 else obj.start + match.start()


def _bounded_index(document: IDFDocument, object_index: int) -> IDFObject:
    if not 0 <= object_index < len(document.objects):
        raise ValueError("object_index_out_of_range")
    return document.objects[object_index]


def source_context(
    text: str,
    object_index: int,
    field_index: int | None = None,
    before_lines: int = 2,
    after_lines: int = 2,
) -> dict[str, Any]:
    """Return a small parser-span context instead of the full IDF."""

    if not 0 <= before_lines <= MAX_CONTEXT_LINES or not 0 <= after_lines <= MAX_CONTEXT_LINES:
        raise ValueError("source_context_line_limit")
    document = parse_idf(text)
    obj = _bounded_index(document, object_index)
    field = None
    if field_index is not None:
        if not 1 <= field_index <= len(obj.fields):
            raise ValueError("field_index_out_of_range")
        field = obj.fields[field_index - 1]

    object_offset = _object_type_offset(text, obj)
    object_line_start = _line_start(text, object_offset)
    object_line_end = _line_end(text, max(obj.start, obj.end - 1))
    context_start = object_line_start
    for _ in range(before_lines):
        if context_start <= 0:
            break
        context_start = _line_start(text, max(0, context_start - 1))
    context_end = object_line_end
    for _ in range(after_lines):
        if context_end >= len(text):
            break
        next_start = context_end
        while next_start < len(text) and text[next_start] in "\r\n":
            next_start += 1
        context_end = _line_end(text, next_start)

    snippet = text[context_start:context_end]
    truncated = len(snippet) > MAX_CONTEXT_CHARS
    if truncated:
        snippet = snippet[:MAX_CONTEXT_CHARS]

    field_line = None
    field_column_start = None
    field_column_end = None
    if field is not None:
        field_line = _line_number(text, field.start)
        field_line_offset = _line_start(text, field.start)
        field_column_start = field.start - field_line_offset + 1
        field_column_end = field.end - field_line_offset + 1

    return {
        "schema_version": "idfrepair.source-context.v1",
        "object_index": obj.index,
        "object_type": obj.object_type,
        "object_name": obj.name or None,
        "line_start": _line_number(text, object_line_start),
        "line_end": _line_number(text, max(object_line_start, obj.end - 1)),
        "context_line_start": _line_number(text, context_start),
        "context_line_end": _line_number(text, max(context_start, context_end - 1)),
        "field_line": field_line,
        "field_index": field_index,
        "field_value": field.value if field is not None else None,
        "field_column_start": field_column_start,
        "field_column_end": field_column_end,
        "text": snippet,
        "truncated": truncated,
    }


def _field_payload(field: IDDField | None) -> dict[str, Any]:
    if field is None:
        return {
            "field_name": None,
            "definition_available": False,
            "data_type": None,
            "required": False,
            "default": None,
            "units": None,
            "minimum": None,
            "maximum": None,
            "keys": [],
            "object_lists": [],
            "references": [],
            "role": None,
            "extensible": False,
        }
    return {
        "field_name": field.name,
        "definition_available": True,
        "data_type": field.data_type,
        "required": field.required,
        "default": field.default,
        "units": field.units,
        "minimum": field.minimum,
        "maximum": field.maximum,
        "keys": list(field.keys),
        "object_lists": list(field.object_lists),
        "references": list(field.references),
        "role": field.role,
        "extensible": field.extensible,
    }


def field_context(
    text: str,
    idd_text: str,
    object_index: int,
    field_index: int,
) -> dict[str, Any]:
    """Project one current IDF field and its version-bound IDD definition."""

    document = parse_idf(text)
    obj = _bounded_index(document, object_index)
    if not 1 <= field_index <= len(obj.fields):
        raise ValueError("field_index_out_of_range")
    schema = parse_idd(idd_text)
    definition = schema.get(obj.object_type)
    field_definition = definition.field_at(field_index) if definition else None
    related: list[dict[str, Any]] = []
    if definition and field_definition:
        for candidate in definition.fields:
            if candidate.index == field_definition.index:
                continue
            if set(candidate.object_lists) & set(field_definition.object_lists):
                related.append({"field_index": candidate.index, "field_name": candidate.name})
    return {
        "schema_version": "idfrepair.field-context.v1",
        "object_index": obj.index,
        "object_type": obj.object_type,
        "object_name": obj.name or None,
        "field_index": field_index,
        **_field_payload(field_definition),
        "current_value": obj.fields[field_index - 1].value,
        "related_fields": related,
    }


def _node_payload(node: Any, *, kind: str, depth: int) -> dict[str, Any]:
    return {
        "node_id": node.node_id,
        "object_index": node.object_index,
        "object_type": node.object_type,
        "object_name": node.object_name or None,
        "label": node.object_name or node.object_type,
        "kind": kind,
        "depth": depth,
    }


def _missing_edges(
    document: IDFDocument,
    idd: Any,
    graph: ObjectGraph,
    actual_node_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    existing = {(edge.source, edge.field_index) for edge in graph.edges}
    by_id = {node.node_id: node for node in graph.nodes}
    missing_nodes: list[dict[str, Any]] = []
    missing_edges: list[dict[str, Any]] = []
    for node_id in sorted(actual_node_ids):
        node = by_id[node_id]
        obj = document.objects[node.object_index]
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        for field in obj.fields:
            field_definition = definition.field_at(field.index)
            if (
                field_definition is None
                or not field.value.strip()
                or not (field_definition.object_lists or field_definition.role.endswith("reference"))
                or (node_id, field.index) in existing
            ):
                continue
            missing_id = f"missing:{obj.index}:{field.index}:{canonical(field.value)}"
            missing_nodes.append({
                "node_id": missing_id,
                "object_index": None,
                "object_type": None,
                "object_name": field.value,
                "label": field.value,
                "kind": "missing_reference",
                "depth": 1,
            })
            missing_edges.append({
                "source": node_id,
                "target": missing_id,
                "field_index": field.index,
                "field_name": field_definition.name,
                "role": field_definition.role,
                "state": "missing",
            })
    return missing_nodes, missing_edges


def object_context(
    text: str,
    idd_text: str,
    object_index: int,
    depth: int = 1,
    limit: int = MAX_GRAPH_NODES,
) -> dict[str, Any]:
    """Return a deterministic, bounded ego graph around one IDF object."""

    if depth not in {1, 2}:
        raise ValueError("object_context_depth")
    if not 1 <= limit <= MAX_GRAPH_NODES:
        raise ValueError("object_context_limit")
    document = parse_idf(text)
    selected_obj = _bounded_index(document, object_index)
    idd = parse_idd(idd_text)
    graph = build_object_graph(document, idd)
    by_index = {node.object_index: node for node in graph.nodes}
    selected = by_index[selected_obj.index]

    distances = {selected.node_id: 0}
    frontier = {selected.node_id}
    for current_depth in range(1, depth + 1):
        next_frontier: set[str] = set()
        for edge in graph.edges:
            if edge.source in frontier and edge.target not in distances:
                distances[edge.target] = current_depth
                next_frontier.add(edge.target)
            if edge.target in frontier and edge.source not in distances:
                distances[edge.source] = current_depth
                next_frontier.add(edge.source)
        frontier = next_frontier

    actual_nodes = [node for node in graph.nodes if node.node_id in distances]
    actual_nodes.sort(key=lambda node: (distances[node.node_id], canonical(node.object_name), node.object_index))
    missing_nodes, missing_edges = _missing_edges(document, idd, graph, set(distances))
    all_nodes = [
        _node_payload(
            node,
            kind="selected" if node.node_id == selected.node_id else "valid_reference",
            depth=distances[node.node_id],
        )
        for node in actual_nodes
    ] + sorted(missing_nodes, key=lambda row: (canonical(str(row["label"])), str(row["node_id"])))
    truncated = len(all_nodes) > limit
    all_nodes = all_nodes[:limit]
    included_ids = {str(row["node_id"]) for row in all_nodes}
    edges = [
        {
            **asdict(edge),
            "state": "valid",
        }
        for edge in graph.edges
        if edge.source in included_ids and edge.target in included_ids
    ]
    edges.extend(
        row for row in missing_edges
        if row["source"] in included_ids and row["target"] in included_ids
    )
    edges.sort(key=lambda row: (str(row["source"]), int(row["field_index"]), str(row["target"])))
    return {
        "schema_version": "idfrepair.object-context.v1",
        "selected_node_id": selected.node_id,
        "depth": depth,
        "nodes": all_nodes,
        "edges": edges,
        "truncated": truncated,
        "limit": limit,
    }


__all__ = ["field_context", "object_context", "source_context"]
