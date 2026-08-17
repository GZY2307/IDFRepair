"""Novice-readable, complete issue records projected from repair plans."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from idfrepair.io.idf import canonical
from idfrepair.knowledge.geometry_graph import Point3D
from idfrepair.preflight.analysis import GeometryAnalysisContext


_COPY: dict[str, tuple[str, str]] = {
    "reciprocal_surface_pair": (
        "Pair two matching room surfaces",
        "Two faces occupy the same boundary between rooms. They can reference each other so heat transfer uses the shared indoor boundary.",
    ),
    "split_and_pair": (
        "Split one large surface to match its neighbours",
        "One room face spans several neighbouring faces. It can be divided along the proven shared outlines and each new piece can be paired.",
    ),
    "resegment_and_pair": (
        "Divide overlapping room surfaces into matching pieces",
        "An existing segment covers part of a larger face. The larger face can be replaced only by the exact non-overlapping counterpart regions.",
    ),
    "vertex_snap": (
        "Align a slightly shifted corner",
        "One corner is very close to a coordinate already shared by related surfaces. Aligning it removes the small unintended offset.",
    ),
    "canonicalize_air_boundary": (
        "Use one matching air-boundary construction",
        "Equivalent air-boundary objects describe the same air connection. Explicit references can use one shared object and unused exact duplicates can be removed.",
    ),
}


def _points(points: Sequence[Point3D]) -> list[list[float]]:
    return [list(point) for point in points]


def _surface_ids(plan: Mapping[str, Any]) -> list[str]:
    rows = plan.get("surface_ids")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []
    return [str(row) for row in rows]


def _after_geometries(
    plan: Mapping[str, Any],
    context: GeometryAnalysisContext,
) -> dict[str, list[tuple[Point3D, ...]]]:
    surface_ids = _surface_ids(plan)
    rows = {
        surface_id: [context.graph.surfaces[surface_id].world_vertices]
        for surface_id in surface_ids
        if surface_id in context.graph.surfaces
    }
    kind = str(plan.get("kind") or "")
    if kind == "reciprocal_surface_pair":
        anchor_id = str(plan.get("anchor_surface_id") or "")
        target_id = str(plan.get("target_surface_id") or "")
        if anchor_id in context.graph.surfaces and target_id in rows:
            rows[target_id] = [tuple(reversed(
                context.graph.surfaces[anchor_id].world_vertices
            ))]
    elif kind == "split_and_pair":
        large_id = str(plan.get("large_surface_id") or "")
        pieces = [
            context.graph.surfaces[str(surface_id)]
            for surface_id in plan.get("small_surface_ids", ())
            if str(surface_id) in context.graph.surfaces
        ]
        if large_id in rows:
            rows[large_id] = [tuple(reversed(piece.world_vertices)) for piece in pieces]
    elif kind == "resegment_and_pair":
        cover_id = str(plan.get("cover_surface_id") or "")
        pieces = [
            context.graph.surfaces[str(surface_id)]
            for surface_id in plan.get("new_piece_surface_ids", ())
            if str(surface_id) in context.graph.surfaces
        ]
        if cover_id in rows:
            rows[cover_id] = [tuple(reversed(piece.world_vertices)) for piece in pieces]
        for pair in plan.get("existing_pairs", ()):
            if not isinstance(pair, Mapping):
                continue
            pair_ids = [str(row) for row in pair.get("surface_ids", ())]
            if len(pair_ids) != 2 or pair_ids[0] not in context.graph.surfaces:
                continue
            if pair_ids[1] in rows:
                rows[pair_ids[1]] = [tuple(reversed(
                    context.graph.surfaces[pair_ids[0]].world_vertices
                ))]
    elif kind == "vertex_snap":
        source_id = str(plan.get("source_surface_id") or "")
        if source_id in context.graph.surfaces:
            vertices = list(context.graph.surfaces[source_id].world_vertices)
            vertex_index = int(plan.get("source_vertex_index") or 0)
            after_world = tuple(float(value) for value in plan.get("after_world", ()))
            if 0 <= vertex_index < len(vertices) and len(after_world) == 3:
                vertices[vertex_index] = after_world  # type: ignore[assignment]
                rows[source_id] = [tuple(vertices)]
    return rows


def _geometry_payload(
    surface_ids: Sequence[str],
    geometries: Mapping[str, Sequence[Sequence[Point3D]]],
) -> list[dict[str, Any]]:
    return [
        {
            "surface_id": surface_id,
            "world_vertices": [_points(polygon) for polygon in geometries.get(surface_id, ())],
        }
        for surface_id in surface_ids
        if surface_id in geometries
    ]


def build_preflight_issues(
    plans: Sequence[Mapping[str, Any]],
    context: GeometryAnalysisContext,
) -> list[dict[str, Any]]:
    """Project every plan exactly once without truncating the collection."""

    issues: list[dict[str, Any]] = []
    for plan in plans:
        kind = str(plan.get("kind") or "")
        title, explanation = _COPY.get(kind, (
            "Review a model relationship",
            "The model contains a relationship that needs review before it can be changed safely.",
        ))
        surface_ids = _surface_ids(plan)
        before_geometries = {
            surface_id: [context.graph.surfaces[surface_id].world_vertices]
            for surface_id in surface_ids
            if surface_id in context.graph.surfaces
        }
        after_geometries = _after_geometries(plan, context)
        locator_surfaces = []
        spaces: dict[str, str] = {}
        for surface_id in surface_ids:
            surface = context.graph.surfaces.get(surface_id)
            if surface is None:
                continue
            space = surface.space_name or surface.zone_name
            if space:
                spaces.setdefault(canonical(space), space)
            after_rows = after_geometries.get(surface_id, ())
            rendered_after: object
            if len(after_rows) == 1:
                rendered_after = _points(after_rows[0])
            else:
                rendered_after = [_points(row) for row in after_rows]
            locator_surfaces.append({
                "surface_id": surface_id,
                "object_index": surface.object_index,
                "object_type": surface.object_type,
                "name": surface.object_name,
                "zone_name": surface.zone_name,
                "space_name": surface.space_name,
                "before_world_vertices": _points(surface.world_vertices),
                "after_world_vertices": rendered_after,
            })
        before: dict[str, Any] = {
            "coordinate_system": "world",
            "surface_geometries": _geometry_payload(
                surface_ids, before_geometries,
            ),
        }
        after: dict[str, Any] = {
            "coordinate_system": "world",
            "surface_geometries": _geometry_payload(
                surface_ids, after_geometries,
            ),
        }
        if kind == "vertex_snap":
            before["world_point"] = list(plan.get("before_world", ()))
            after["world_point"] = list(plan.get("after_world", ()))
            before["local_point"] = list(plan.get("before_local", ()))
            after_local = plan.get("after_local")
            after["local_point"] = (
                list(after_local)
                if isinstance(after_local, Sequence) and not isinstance(after_local, (str, bytes))
                else None
            )
        elif kind == "canonicalize_air_boundary":
            before["construction_names"] = [
                str(row) for row in plan.get("duplicate_names", ())
            ]
            after["construction_name"] = str(plan.get("canonical_name") or "")
        issues.append({
            "issue_id": str(plan["plan_id"]),
            "kind": kind,
            "title": title,
            "explanation": explanation,
            "surface_refs": surface_ids,
            "space_refs": [spaces[key] for key in sorted(spaces)],
            "before": before,
            "after": after,
            "locator": {
                "coordinate_system": "world",
                "surface_ids": surface_ids,
                "surfaces": locator_surfaces,
            },
            "safe_to_apply": plan.get("safe_to_apply") is True,
            "blocking_reasons": [str(row) for row in plan.get("blocking_reasons", ())],
        })
    return issues


__all__ = ["build_preflight_issues"]
