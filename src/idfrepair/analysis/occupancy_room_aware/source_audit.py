"""校验并渲染 OpenStudio room-function 源审计。"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import csv
import json
from pathlib import Path
from typing import Any

from idfrepair.analysis.occupancy_room_aware.models import RoomCategory


AUDIT_SCHEMA = "idfrepair.room-aware-source-audit.v1"
ROOM_CATEGORIES = tuple(category.value for category in RoomCategory)


def _rows(audit: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = audit.get("spaces")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("audit_spaces_invalid")
    return rows


def validate_source_audit(audit: Mapping[str, Any]) -> None:
    """检查源 hash、分类总数、唯一身份与 metadata 计数。"""

    if audit.get("schema_version") != AUDIT_SCHEMA:
        raise ValueError("audit_schema_invalid")
    if audit.get("source_sha256_before") != audit.get("source_sha256_after"):
        raise ValueError("source_hash_changed")
    if audit.get("source_unchanged") is not True:
        raise ValueError("source_not_marked_unchanged")
    if audit.get("classification_rejections") != []:
        raise ValueError("classification_rejections_present")

    rows = _rows(audit)
    if int(audit.get("space_count", -1)) != len(rows):
        raise ValueError("space_count_mismatch")
    names = [str(row.get("source_space_name", "")) for row in rows]
    handles = [str(row.get("source_handle", "")) for row in rows]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("space_name_identity_invalid")
    if any(not handle for handle in handles) or len(set(handles)) != len(handles):
        raise ValueError("space_handle_identity_invalid")

    categories = Counter(str(row.get("room_category", "")) for row in rows)
    if set(categories) - set(ROOM_CATEGORIES):
        raise ValueError("room_category_invalid")
    stated = {str(key): int(value) for key, value in audit.get("category_counts", {}).items()}
    if dict(categories) != stated:
        raise ValueError("category_count_mismatch")
    if sum(stated.values()) != len(rows):
        raise ValueError("category_sum_mismatch")

    conflict_count = sum(
        row.get("metadata_status") == "SOURCE_METADATA_CONFLICT" for row in rows
    )
    if conflict_count != int(audit.get("metadata_conflict_count", -1)):
        raise ValueError("metadata_conflict_count_mismatch")


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def _unique(values: Sequence[Any]) -> str:
    return " | ".join(sorted({str(value) for value in values if value not in (None, "")}))


def _md_cell(value: Any) -> str:
    """避免源名称中的分隔符破坏 Markdown table。"""

    return str(value).replace("|", "<br>").replace("\n", " ")


def _people_values(row: Mapping[str, Any], key: str) -> list[Any]:
    result: list[Any] = []
    for source in row.get("people_sources", []):
        if not isinstance(source, Mapping):
            continue
        if key.startswith("definition."):
            definition = source.get("definition", {})
            if isinstance(definition, Mapping):
                result.append(definition.get(key.split(".", 1)[1]))
        else:
            result.append(source.get(key))
    return result


def _category_summary(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for category in ROOM_CATEGORIES:
        selected = [row for row in rows if row.get("room_category") == category]
        if not selected:
            continue
        area = sum(float(row.get("floor_area_m2") or 0.0) for row in selected)
        people = sum(float(row.get("design_people") or 0.0) for row in selected)
        result[category] = {
            "space_count": len(selected),
            "floor_area_m2": area,
            "design_people": people,
            "people_per_m2": people / area if area > 0 else None,
            "m2_per_person": area / people if people > 0 else None,
            "defaulted_space_type_count": sum(
                bool(row.get("space_type_defaulted")) for row in selected
            ),
            "explicit_space_types": _unique(
                [row.get("explicit_space_type") for row in selected]
            ),
            "effective_space_types": _unique(
                [row.get("effective_space_type") for row in selected]
            ),
            "people_methods": _unique(
                [value for row in selected for value in _people_values(row, "definition.method")]
            ),
            "people_schedules": _unique(
                [value for row in selected for value in _people_values(row, "count_schedule")]
            ),
            "activity_schedules": _unique(
                [value for row in selected for value in _people_values(row, "activity_schedule")]
            ),
            "oa_definitions": _unique(
                [
                    row.get("oa", {}).get("name")
                    for row in selected
                    if isinstance(row.get("oa"), Mapping)
                ]
            ),
        }
    return result


CSV_FIELDS = (
    "source_space_name",
    "room_category",
    "matched_token",
    "classification_status",
    "thermal_zone",
    "floor_area_m2",
    "exterior_area_m2",
    "design_people",
    "people_per_m2",
    "m2_per_person",
    "space_type_defaulted",
    "explicit_space_type",
    "effective_space_type",
    "metadata_status",
    "metadata_conflicts",
    "people_source_kinds",
    "people_source_names",
    "people_definition_names",
    "people_calculation_methods",
    "people_definition_values",
    "number_schedules",
    "activity_schedules",
    "fraction_radiant_values",
    "sensible_heat_fraction_values",
    "co2_generation_rate_m3_s_person_values",
    "oa_defaulted",
    "oa_name",
    "oa_method",
    "oa_flow_per_person_m3_s_person",
    "oa_flow_per_area_m3_s_m2",
    "oa_flow_rate_m3_s",
    "oa_ach_per_h",
    "oa_schedule",
    "source_handle",
)


def _csv_row(row: Mapping[str, Any]) -> dict[str, Any]:
    oa = row.get("oa") if isinstance(row.get("oa"), Mapping) else {}
    return {
        "source_space_name": row.get("source_space_name"),
        "room_category": row.get("room_category"),
        "matched_token": row.get("matched_token"),
        "classification_status": row.get("classification_status"),
        "thermal_zone": row.get("thermal_zone"),
        "floor_area_m2": _fmt(row.get("floor_area_m2")),
        "exterior_area_m2": _fmt(row.get("exterior_area_m2")),
        "design_people": _fmt(row.get("design_people")),
        "people_per_m2": _fmt(row.get("people_per_m2")),
        "m2_per_person": _fmt(row.get("m2_per_person")),
        "space_type_defaulted": _fmt(row.get("space_type_defaulted")),
        "explicit_space_type": row.get("explicit_space_type"),
        "effective_space_type": row.get("effective_space_type"),
        "metadata_status": row.get("metadata_status"),
        "metadata_conflicts": _unique(row.get("metadata_conflicts", [])),
        "people_source_kinds": _unique(_people_values(row, "source_kind")),
        "people_source_names": _unique(_people_values(row, "source_name")),
        "people_definition_names": _unique(_people_values(row, "definition.name")),
        "people_calculation_methods": _unique(_people_values(row, "definition.method")),
        "people_definition_values": _unique(_people_values(row, "definition.value")),
        "number_schedules": _unique(_people_values(row, "count_schedule")),
        "activity_schedules": _unique(_people_values(row, "activity_schedule")),
        "fraction_radiant_values": _unique(_people_values(row, "definition.fraction_radiant")),
        "sensible_heat_fraction_values": _unique(
            _people_values(row, "definition.sensible_heat_fraction")
        ),
        "co2_generation_rate_m3_s_person_values": _unique(
            _people_values(row, "definition.co2_generation_rate_m3_s_person")
        ),
        "oa_defaulted": _fmt(row.get("oa_defaulted")),
        "oa_name": oa.get("name"),
        "oa_method": oa.get("method"),
        "oa_flow_per_person_m3_s_person": _fmt(
            oa.get("flow_per_person_m3_s_person")
        ),
        "oa_flow_per_area_m3_s_m2": _fmt(oa.get("flow_per_area_m3_s_m2")),
        "oa_flow_rate_m3_s": _fmt(oa.get("flow_rate_m3_s")),
        "oa_ach_per_h": _fmt(oa.get("ach_per_h")),
        "oa_schedule": oa.get("schedule"),
        "source_handle": row.get("source_handle"),
    }


def _markdown(audit: Mapping[str, Any], summary: Mapping[str, Any]) -> str:
    category = summary["categories"]
    conflicts = [
        row
        for row in _rows(audit)
        if row.get("metadata_status") == "SOURCE_METADATA_CONFLICT"
    ]
    equipment = [
        item
        for zone in audit.get("zones", [])
        if isinstance(zone, Mapping)
        for item in zone.get("equipment", [])
    ]
    lines = [
        "# Source room-function and People audit",
        "",
        "**Audit status:** `SOURCE_ROOM_MAPPING_VALIDATED`",
        "",
        "## Source-preserving audit boundary",
        "",
        "This is a source-preserving audit of **Terminal Model A**. The OSM was",
        "loaded read-only through OpenStudio; its SHA-256 was identical before and",
        "after the audit. No source or derived OSM is distributed with this report.",
        "",
        "## Identity and completeness",
        "",
        f"- Source SHA-256: `{audit['source_sha256_after']}`",
        f"- Runtime: OpenStudio {audit.get('openstudio_version')} / OSM {audit.get('osm_schema_version')}",
        f"- Spaces: **{audit.get('space_count')}**",
        f"- ThermalZones: **{audit.get('thermal_zone_count')}**",
        f"- Orphan zones: **{len(audit.get('orphan_zones', []))}** ({_unique(audit.get('orphan_zones', [])) or 'none'})",
        "- Unknown or multi-token Spaces: **0**",
        f"- Metadata conflicts: **{audit.get('metadata_conflict_count')}**",
        f"- Non-People source snapshot: `{audit.get('non_people_snapshot_sha256')}` ({audit.get('non_people_snapshot_object_count')} objects)",
        "",
        "## Six source-name categories",
        "",
        "| Category | Spaces | Floor area (m²) | Design people | people/m² | m²/person | Defaulted SpaceType |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ROOM_CATEGORIES:
        if name not in category:
            continue
        row = category[name]
        lines.append(
            f"| {name} | {row['space_count']} | {_fmt(row['floor_area_m2'], 3)} | "
            f"{_fmt(row['design_people'], 3)} | {_fmt(row['people_per_m2'], 6)} | "
            f"{_fmt(row['m2_per_person'], 3)} | {row['defaulted_space_type_count']} |"
        )
    lines.extend(
        [
            "",
            "Classification uses only the case-insensitive `hall`, `office`,",
            "`commerce`, `dining`, `restroom`, and `breakroom` tokens in",
            "`OS:Space.Name`. Geometry and airport conventions do not create",
            "check-in, gate, baggage, security, arrivals, or departures labels.",
            "",
            "## Why the historical translated grouping is not a room-function result",
            "",
            f"The Building default SpaceType is `{audit.get('building_default_space_type')}`.",
            f"It is inherited by **{summary['default_archetype_mixed_space_count']}** Spaces",
            "whose source-name room functions are mixed. Therefore a translated People",
            "group based on this archetype is not an airport room-function group.",
            "",
            "| Category | Effective SpaceTypes | People method(s) | Number schedule(s) | Activity schedule(s) | OA definition(s) |",
            "|---|---|---|---|---|---|",
        ]
    )
    for name in ROOM_CATEGORIES:
        if name not in category:
            continue
        row = category[name]
        lines.append(
            f"| {name} | {_md_cell(row['effective_space_types'] or 'none')} | "
            f"{_md_cell(row['people_methods'] or 'none')} | "
            f"{_md_cell(row['people_schedules'] or 'none')} | "
            f"{_md_cell(row['activity_schedules'] or 'none')} | "
            f"{_md_cell(row['oa_definitions'] or 'none')} |"
        )
    lines.extend(["", "## Metadata conflicts", ""])
    if conflicts:
        lines.extend(
            [
                "| Source Space | Name category | Explicit SpaceType | Status | Conflict |",
                "|---|---|---|---|---|",
            ]
        )
        for row in conflicts:
            lines.append(
                f"| {row.get('source_space_name')} | {row.get('room_category')} | "
                f"{row.get('explicit_space_type')} | {row.get('metadata_status')} | "
                f"{_md_cell(_unique(row.get('metadata_conflicts', [])))} |"
            )
    else:
        lines.append("No explicit name/SpaceType conflict was found.")
    lines.extend(
        [
            "",
            "## People → Zone → HVAC boundary",
            "",
            f"Every classified Space retains its explicit source ThermalZone identity. "
            f"The source contains **{len(equipment)}** zone-equipment assignments in the "
            "audited model. Absence of source AirLoop/PlantLoop topology is not repaired ",
            "by inference; later thermal-demand experiments use a separately labelled ",
            "IdealLoads derivative only.",
            "",
            "## Interpretation guard",
            "",
            "These values describe source metadata, not measured airport operations.",
            "The reference derivative may replace only People fields supported by the",
            "evidence registry. Lighting, equipment, infiltration, constructions,",
            "geometry, SpaceTypes, and source OA remain unchanged in the main People-only",
            "comparison.",
            "",
        ]
    )
    return "\n".join(lines)


def render_source_audit(
    audit: Mapping[str, Any],
    *,
    csv_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    """校验 JSON 后写出逐 Space CSV 与证据边界清晰的 Markdown。"""

    validate_source_audit(audit)
    rows = _rows(audit)
    building_default = audit.get("building_default_space_type")
    summary: dict[str, Any] = {
        "space_count": len(rows),
        "categories": _category_summary(rows),
        "default_archetype_mixed_space_count": sum(
            bool(row.get("space_type_defaulted"))
            and row.get("effective_space_type") == building_default
            for row in rows
        ),
    }
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(_csv_row(row) for row in rows)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(audit, summary), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
    summary = render_source_audit(
        audit,
        csv_path=args.csv,
        markdown_path=args.markdown,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["AUDIT_SCHEMA", "render_source_audit", "validate_source_audit"]
