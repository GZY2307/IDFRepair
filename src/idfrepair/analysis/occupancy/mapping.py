"""把 People target 解析为 Zone，并复用 frozen V2 Zone→HVAC relations。

本模块只是适配器：不会修改 ``semantic_graph_v2``，也不会在缺失 HVAC 时
合成设备关系。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from idfrepair.analysis.occupancy.extract import extract_people
from idfrepair.analysis.occupancy.models import ZoneServiceMap
from idfrepair.io.idf import IDFDocument, IDFObject, canonical
from idfrepair.knowledge.idd import IDDObject, IDDSchema
from idfrepair.semantic_graph_v2 import ModelIR, build_model_ir


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    """按源顺序返回 canonical 去重后的非空名称。"""

    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        value = raw.strip()
        key = canonical(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def _field_position(definition: IDDObject, name: str) -> int:
    """按当前 IDD 的精确字段名解析 1-based 位置。"""

    target = canonical(name)
    matches = tuple(field.index for field in definition.fields if canonical(field.name) == target)
    if len(matches) != 1:
        raise ValueError(f"idd_field_not_unique:{definition.name}:{name}")
    return matches[0]


def _value(obj: IDFObject, position: int) -> str:
    if not 1 <= position <= len(obj.fields):
        return ""
    return obj.fields[position - 1].value.strip()


def _objects_by_name(document: IDFDocument, object_type: str) -> dict[str, tuple[IDFObject, ...]]:
    grouped: dict[str, list[IDFObject]] = {}
    for obj in document.find_objects(object_type):
        grouped.setdefault(canonical(obj.name), []).append(obj)
    return {key: tuple(values) for key, values in grouped.items()}


def _list_members(obj: IDFObject, definition: IDDObject, first_field_name: str) -> tuple[str, ...]:
    start = _field_position(definition, first_field_name)
    return _unique(field.value for field in obj.fields[start - 1 :])


def map_people_to_zones(
    document: IDFDocument,
    idd: IDDSchema,
) -> tuple[Mapping[str, tuple[str, ...]], tuple[str, ...]]:
    """解析 People 的 Zone/ZoneList/Space/SpaceList 多态 target。"""

    definitions: dict[str, IDDObject] = {}
    for object_type in ("Zone", "Space", "ZoneList", "SpaceList"):
        definition = idd.get(object_type)
        if definition is None:
            raise ValueError(f"mapping_object_missing_from_idd:{object_type}")
        definitions[object_type] = definition

    zones = _objects_by_name(document, "Zone")
    spaces = _objects_by_name(document, "Space")
    zone_lists = _objects_by_name(document, "ZoneList")
    space_lists = _objects_by_name(document, "SpaceList")
    space_zone_position = _field_position(definitions["Space"], "Zone Name")

    issues: list[str] = []

    def zones_for_space(space_name: str, *, owner: str) -> tuple[str, ...]:
        matches = spaces.get(canonical(space_name), ())
        if not matches:
            issues.append(f"space_target_unresolved:{owner}:{space_name}")
            return ()
        if len(matches) > 1:
            issues.append(f"space_target_multiplicity:{owner}:{space_name}:{len(matches)}")
        resolved: list[str] = []
        for space in matches:
            zone_name = _value(space, space_zone_position)
            if not zone_name:
                issues.append(f"space_zone_missing:{owner}:{space.name}")
                continue
            zone_matches = zones.get(canonical(zone_name), ())
            if not zone_matches:
                issues.append(f"space_zone_unresolved:{owner}:{space.name}:{zone_name}")
                continue
            if len(zone_matches) > 1:
                issues.append(
                    f"zone_name_multiplicity:{owner}:{zone_name}:{len(zone_matches)}"
                )
            resolved.extend(zone.name for zone in zone_matches)
        return _unique(resolved)

    result: dict[str, tuple[str, ...]] = {}
    for record in extract_people(document, idd):
        target_key = canonical(record.target_name)
        category_matches = {
            "Zone": zones.get(target_key, ()),
            "Space": spaces.get(target_key, ()),
            "ZoneList": zone_lists.get(target_key, ()),
            "SpaceList": space_lists.get(target_key, ()),
        }
        present = tuple(name for name, rows in category_matches.items() if rows)
        if not present:
            issues.append(
                f"people_target_unresolved:{record.name}:{record.target_name}"
            )
            resolved_zones: tuple[str, ...] = ()
        else:
            if len(present) > 1:
                issues.append(
                    "people_target_ambiguous:"
                    f"{record.name}:{record.target_name}:{'|'.join(present)}"
                )
            values: list[str] = []
            for zone in category_matches["Zone"]:
                values.append(zone.name)
            for space in category_matches["Space"]:
                values.extend(zones_for_space(space.name, owner=record.name))
            for zone_list in category_matches["ZoneList"]:
                members = _list_members(
                    zone_list, definitions["ZoneList"], "Zone 1 Name"
                )
                for member in members:
                    zone_matches = zones.get(canonical(member), ())
                    if not zone_matches:
                        issues.append(
                            f"zone_list_member_unresolved:{record.name}:{zone_list.name}:{member}"
                        )
                    values.extend(zone.name for zone in zone_matches)
            for space_list in category_matches["SpaceList"]:
                members = _list_members(
                    space_list, definitions["SpaceList"], "Space 1 Name"
                )
                for member in members:
                    values.extend(zones_for_space(member, owner=record.name))
            resolved_zones = _unique(values)

        if record.name in result:
            issues.append(f"people_name_multiplicity:{record.name}")
            result[record.name] = _unique((*result[record.name], *resolved_zones))
        else:
            result[record.name] = resolved_zones
    return MappingProxyType(result), tuple(_unique(issues))


def map_zones_to_hvac(
    model: ModelIR,
    zone_names: Iterable[str],
) -> tuple[Mapping[str, tuple[str, ...]], tuple[str, ...]]:
    """用 frozen ModelIR 的 declared EquipmentList 建立 Zone→HVAC 映射。"""

    requested = _unique(zone_names)
    relations: dict[str, list] = {}
    for relation in model.zone_relations:
        zone_field = relation.connection_ref.field(1)
        if zone_field is None or not zone_field.raw_value.strip():
            continue
        relations.setdefault(canonical(zone_field.raw_value), []).append(relation)
    lists_by_id = {
        row.object_ref.object_id: row for row in model.zone_equipment_lists
    }
    result: dict[str, tuple[str, ...]] = {}
    issues: list[str] = []
    for zone_name in requested:
        matches = relations.get(canonical(zone_name), [])
        if len(matches) > 1:
            issues.append(f"zone_connection_multiplicity:{zone_name}:{len(matches)}")
        equipment: list[str] = []
        for relation in matches:
            if relation.declared_list_ref is None:
                issues.append(
                    "zone_equipment_list_unresolved:"
                    f"{zone_name}:{relation.declared_list_field.raw_value}"
                )
                continue
            zone_list = lists_by_id.get(relation.declared_list_ref.object_id)
            if zone_list is None:
                issues.append(f"zone_equipment_relation_missing:{zone_name}")
                continue
            equipment.extend(
                f"{member.object_type.strip()} / {member.object_name.strip()}"
                for member in zone_list.members
                if member.object_type.strip() and member.object_name.strip()
            )
        result[zone_name] = _unique(equipment)
        if not result[zone_name]:
            issues.append(f"zone_without_hvac:{zone_name}")
    return MappingProxyType(result), tuple(_unique(issues))


def build_semantic_mapping(
    document: IDFDocument,
    idd: IDDSchema,
) -> ZoneServiceMap:
    """一次构建完整 People→Zone→HVAC 映射与审计问题。"""

    people_to_zones, people_issues = map_people_to_zones(document, idd)
    zones = _unique(
        zone for mapped in people_to_zones.values() for zone in mapped
    )
    model = build_model_ir(document, idd)
    zone_to_hvac, hvac_issues = map_zones_to_hvac(model, zones)
    return ZoneServiceMap(
        people_to_zones=people_to_zones,
        zone_to_hvac=zone_to_hvac,
        issues=tuple(_unique((*people_issues, *hvac_issues))),
    )


__all__ = [
    "build_semantic_mapping",
    "map_people_to_zones",
    "map_zones_to_hvac",
]
