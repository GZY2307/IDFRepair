"""实现有限 HVAC 关系故障注入、约束定位与最小安全修复。

apply_field_edits(): 按原始字段跨度执行无损确定性回写。
discover_fault_mutations(): 发现具备 clean oracle 的结构故障机会。
detect_constraint_violations(): 仅依据当前 IDF 与版本匹配 IDD 定位约束冲突。
solve_at_locator(): 枚举定位点的最小候选并执行唯一性判定。

本模块与冻结的 Final400 工作流隔离。clean 模型只在构造 mutation 时提供
离线评价 oracle；推理阶段仅使用 faulty 模型中剩余的跨对象关系证据。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Any, Iterable, Mapping, Sequence

from idfrepair.io.idf import IDFDocument, IDFObject, canonical
from idfrepair.knowledge.idd import IDDSchema


AUTO_REPAIR_FAMILIES = (
    "branch_component_reassignment",
    "branch_endpoint_mismatch",
    "branch_member_order",
    "zone_equipment_list_mismatch",
    "zone_equipment_member_mismatch",
    "zone_equipment_priority_mismatch",
    "connector_parallel_membership",
    "loop_side_branchlist_mismatch",
    "air_path_component_mismatch",
)
ABSTENTION_FAMILY = "zone_equipment_member_ambiguous"
ALL_FEASIBILITY_FAMILIES = (*AUTO_REPAIR_FAMILIES, ABSTENTION_FAMILY)


@dataclass(frozen=True, slots=True)
class FieldEdit:
    """表示一个带旧值校验的确定性 IDF 字段替换。"""

    object_index: int
    field_index: int
    old_value: str
    new_value: str


@dataclass(frozen=True, slots=True)
class FaultMutation:
    """表示 schema-valid 关系 mutation 及仅用于评价的逆向 oracle。"""

    family: str
    mutation_edits: tuple[FieldEdit, ...]
    oracle_edits: tuple[FieldEdit, ...]
    locator: Mapping[str, Any]
    oracle_relation: str
    mutated_relation: str
    semantic_edit_cost: int = 1


@dataclass(frozen=True, slots=True)
class RepairDecision:
    """表示依据 faulty 模型证据得到的最小修复与可恢复性结果。"""

    status: str
    edits: tuple[FieldEdit, ...]
    candidate_count: int
    minimum_candidate_count: int
    minimum_cost: int | None
    evidence: tuple[str, ...]
    alternatives: tuple[tuple[FieldEdit, ...], ...] = ()
    used_clean_oracle: bool = False


@dataclass(frozen=True, slots=True)
class _BranchComponent:
    branch: IDFObject
    ordinal: int
    type_index: int
    name_index: int
    inlet_index: int
    outlet_index: int
    component_type: str
    component_name: str
    inlet_node: str
    outlet_node: str


@dataclass(frozen=True, slots=True)
class _EquipmentMember:
    equipment_list: IDFObject
    ordinal: int
    type_index: int
    name_index: int
    equipment_type: str
    equipment_name: str


def apply_field_edits(
    document: IDFDocument,
    edits: Sequence[FieldEdit],
) -> str:
    """校验旧值后按源位置逆序替换字段，不重新格式化其他文本。"""

    if not edits:
        return document.text
    seen: set[tuple[int, int]] = set()
    replacements: list[tuple[int, int, str]] = []
    for edit in edits:
        key = (edit.object_index, edit.field_index)
        if key in seen:
            raise ValueError("duplicate_field_edit")
        seen.add(key)
        if not 0 <= edit.object_index < len(document.objects):
            raise ValueError("object_index_out_of_range")
        obj = document.objects[edit.object_index]
        if not 1 <= edit.field_index <= len(obj.fields):
            raise ValueError("field_index_out_of_range")
        field = obj.fields[edit.field_index - 1]
        if field.value != edit.old_value:
            raise ValueError("field_old_value_mismatch")
        if edit.new_value == field.value:
            raise ValueError("field_edit_is_noop")
        replacements.append((field.start, field.end, edit.new_value))
    text = document.text
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def _reverse(edits: Iterable[FieldEdit]) -> tuple[FieldEdit, ...]:
    return tuple(
        FieldEdit(
            object_index=edit.object_index,
            field_index=edit.field_index,
            old_value=edit.new_value,
            new_value=edit.old_value,
        )
        for edit in edits
    )


def _identity_index(
    document: IDFDocument,
) -> dict[tuple[str, str], tuple[IDFObject, ...]]:
    pending: dict[tuple[str, str], list[IDFObject]] = {}
    for obj in document.objects:
        if not obj.name.strip():
            continue
        pending.setdefault(
            (canonical(obj.object_type), canonical(obj.name)), []
        ).append(obj)
    return {key: tuple(values) for key, values in pending.items()}


def _objects_by_type(document: IDFDocument) -> dict[str, tuple[IDFObject, ...]]:
    pending: dict[str, list[IDFObject]] = {}
    for obj in document.objects:
        pending.setdefault(canonical(obj.object_type), []).append(obj)
    return {key: tuple(values) for key, values in pending.items()}


def _branch_components(branch: IDFObject) -> tuple[_BranchComponent, ...]:
    rows: list[_BranchComponent] = []
    ordinal = 0
    for type_index in range(3, len(branch.fields) + 1, 4):
        outlet_index = type_index + 3
        if outlet_index > len(branch.fields):
            continue
        values = tuple(
            branch.fields[index - 1].value
            for index in range(type_index, outlet_index + 1)
        )
        if not values[0].strip():
            continue
        ordinal += 1
        rows.append(_BranchComponent(
            branch=branch,
            ordinal=ordinal,
            type_index=type_index,
            name_index=type_index + 1,
            inlet_index=type_index + 2,
            outlet_index=type_index + 3,
            component_type=values[0],
            component_name=values[1],
            inlet_node=values[2],
            outlet_node=values[3],
        ))
    return tuple(rows)


def _all_branch_components(document: IDFDocument) -> tuple[_BranchComponent, ...]:
    return tuple(
        row
        for branch in document.find_objects("Branch")
        for row in _branch_components(branch)
    )


def _equipment_members(equipment_list: IDFObject) -> tuple[_EquipmentMember, ...]:
    rows: list[_EquipmentMember] = []
    ordinal = 0
    for type_index in range(3, len(equipment_list.fields) + 1, 6):
        name_index = type_index + 1
        if name_index > len(equipment_list.fields):
            continue
        equipment_type = equipment_list.fields[type_index - 1].value
        if not equipment_type.strip():
            continue
        ordinal += 1
        rows.append(_EquipmentMember(
            equipment_list=equipment_list,
            ordinal=ordinal,
            type_index=type_index,
            name_index=name_index,
            equipment_type=equipment_type,
            equipment_name=equipment_list.fields[name_index - 1].value,
        ))
    return tuple(rows)


def _node_lists(document: IDFDocument) -> dict[str, frozenset[str]]:
    return {
        canonical(obj.name): frozenset(
            canonical(field.value)
            for field in obj.fields[1:]
            if field.value.strip()
        )
        for obj in document.find_objects("NodeList")
    }


def _expand_node(value: str, node_lists: Mapping[str, frozenset[str]]) -> set[str]:
    key = canonical(value)
    if not key:
        return set()
    return set(node_lists.get(key, frozenset((key,))))


def _object_node_roles(
    obj: IDFObject,
    idd: IDDSchema,
    node_lists: Mapping[str, frozenset[str]],
) -> dict[str, set[str]]:
    roles = {"inlet": set(), "outlet": set(), "all": set()}
    definition = idd.get(obj.object_type)
    if definition is None:
        return roles
    for field in obj.fields:
        if not field.value.strip():
            continue
        field_def = definition.field_at(field.index)
        if field_def is None:
            continue
        name = canonical(field_def.name)
        if "node" not in name or name.startswith("number of"):
            continue
        values = _expand_node(field.value, node_lists)
        roles["all"].update(values)
        if any(token in name for token in ("inlet", "entering")):
            roles["inlet"].update(values)
        if any(token in name for token in (
            "outlet", "leaving", "exhaust", "relief",
        )):
            roles["outlet"].update(values)
    return roles


def _object_all_values(obj: IDFObject) -> set[str]:
    return {
        canonical(field.value) for field in obj.fields[1:] if field.value.strip()
    }


def _zone_nodes(
    connection: IDFObject,
    node_lists: Mapping[str, frozenset[str]],
) -> set[str]:
    values: set[str] = set()
    for index in (3, 4, 6):
        if index <= len(connection.fields):
            values.update(_expand_node(connection.fields[index - 1].value, node_lists))
    return values


def _equipment_list_nodes(
    equipment_list: IDFObject,
    *,
    identities: Mapping[tuple[str, str], tuple[IDFObject, ...]],
    idd: IDDSchema,
    node_lists: Mapping[str, frozenset[str]],
) -> set[str]:
    values: set[str] = set()
    for member in _equipment_members(equipment_list):
        matches = identities.get((
            canonical(member.equipment_type), canonical(member.equipment_name),
        ), ())
        if len(matches) == 1:
            values.update(_object_node_roles(matches[0], idd, node_lists)["all"])
    return values


def _relation_text(row: _BranchComponent, component_name: str | None = None) -> str:
    name = row.component_name if component_name is None else component_name
    return (
        f"Branch:{row.branch.name}/member:{row.ordinal}="
        f"{row.component_type}:{name}[{row.inlet_node}->{row.outlet_node}]"
    )


def _mutation(
    *,
    family: str,
    edits: Sequence[FieldEdit],
    locator: Mapping[str, Any],
    oracle_relation: str,
    mutated_relation: str,
) -> FaultMutation:
    mutation_edits = tuple(edits)
    return FaultMutation(
        family=family,
        mutation_edits=mutation_edits,
        oracle_edits=_reverse(mutation_edits),
        locator=dict(locator),
        oracle_relation=oracle_relation,
        mutated_relation=mutated_relation,
    )


def _discover_branch_component_reassignment(
    document: IDFDocument,
) -> tuple[FaultMutation, ...]:
    identities = _identity_index(document)
    by_type = _objects_by_type(document)
    rows: list[FaultMutation] = []
    for relation in _all_branch_components(document):
        matches = identities.get((
            canonical(relation.component_type), canonical(relation.component_name),
        ), ())
        if len(matches) != 1:
            continue
        endpoints = {canonical(relation.inlet_node), canonical(relation.outlet_node)}
        if not endpoints.issubset(_object_all_values(matches[0])):
            continue
        compatible = tuple(
            obj for obj in by_type.get(canonical(relation.component_type), ())
            if obj.name.strip() and endpoints.issubset(_object_all_values(obj))
        )
        if len(compatible) != 1 or compatible[0] is not matches[0]:
            continue
        donors = tuple(
            obj for obj in by_type.get(canonical(relation.component_type), ())
            if obj.name.strip() and canonical(obj.name) != canonical(relation.component_name)
        )
        if not donors:
            continue
        donor = donors[0]
        edit = FieldEdit(
            relation.branch.index, relation.name_index,
            relation.component_name, donor.name,
        )
        rows.append(_mutation(
            family="branch_component_reassignment",
            edits=(edit,),
            locator={
                "object_index": relation.branch.index,
                "name_index": relation.name_index,
            },
            oracle_relation=_relation_text(relation),
            mutated_relation=_relation_text(relation, donor.name),
        ))
    return tuple(rows)


def _discover_branch_endpoint_mismatch(
    document: IDFDocument,
    idd: IDDSchema,
) -> tuple[FaultMutation, ...]:
    identities = _identity_index(document)
    node_lists = _node_lists(document)
    all_nodes = sorted({
        canonical(value)
        for relation in _all_branch_components(document)
        for value in (relation.inlet_node, relation.outlet_node)
        if value.strip()
    })
    display = {
        canonical(value): value
        for relation in _all_branch_components(document)
        for value in (relation.inlet_node, relation.outlet_node)
        if value.strip()
    }
    rows: list[FaultMutation] = []
    for relation in _all_branch_components(document):
        matches = identities.get((
            canonical(relation.component_type), canonical(relation.component_name),
        ), ())
        if len(matches) != 1:
            continue
        roles = _object_node_roles(matches[0], idd, node_lists)
        if (
            canonical(relation.inlet_node) not in roles["all"]
            or canonical(relation.outlet_node) not in roles["all"]
        ):
            continue
        foreign = next((
            node for node in all_nodes
            if node not in roles["all"]
            and node != canonical(relation.outlet_node)
        ), None)
        if foreign is None:
            continue
        new_value = display[foreign]
        edit = FieldEdit(
            relation.branch.index, relation.outlet_index,
            relation.outlet_node, new_value,
        )
        rows.append(_mutation(
            family="branch_endpoint_mismatch",
            edits=(edit,),
            locator={
                "object_index": relation.branch.index,
                "outlet_index": relation.outlet_index,
            },
            oracle_relation=_relation_text(relation),
            mutated_relation=(
                f"Branch:{relation.branch.name}/member:{relation.ordinal}="
                f"{relation.component_type}:{relation.component_name}"
                f"[{relation.inlet_node}->{new_value}]"
            ),
        ))
    return tuple(rows)


def _continuous(components: Sequence[_BranchComponent]) -> bool:
    return all(
        canonical(left.outlet_node) == canonical(right.inlet_node)
        for left, right in zip(components, components[1:])
    )


def _discover_branch_member_order(document: IDFDocument) -> tuple[FaultMutation, ...]:
    rows: list[FaultMutation] = []
    for branch in document.find_objects("Branch"):
        components = _branch_components(branch)
        if not 2 <= len(components) <= 7 or not _continuous(components):
            continue
        reordered = (components[1], components[0], *components[2:])
        if _continuous(reordered):
            continue
        edits: list[FieldEdit] = []
        for destination, source in zip(components, reordered):
            old_values = (
                destination.component_type, destination.component_name,
                destination.inlet_node, destination.outlet_node,
            )
            new_values = (
                source.component_type, source.component_name,
                source.inlet_node, source.outlet_node,
            )
            for offset, (old, new) in enumerate(zip(old_values, new_values)):
                if old != new:
                    edits.append(FieldEdit(
                        branch.index, destination.type_index + offset, old, new,
                    ))
        rows.append(_mutation(
            family="branch_member_order",
            edits=edits,
            locator={"object_index": branch.index},
            oracle_relation=(
                f"Branch:{branch.name}/order="
                + ">".join(item.component_name for item in components)
            ),
            mutated_relation=(
                f"Branch:{branch.name}/order="
                + ">".join(item.component_name for item in reordered)
            ),
        ))
    return tuple(rows)


def _zone_list_scores(
    connection: IDFObject,
    equipment_lists: Sequence[IDFObject],
    *,
    identities: Mapping[tuple[str, str], tuple[IDFObject, ...]],
    idd: IDDSchema,
    node_lists: Mapping[str, frozenset[str]],
) -> tuple[tuple[int, IDFObject], ...]:
    zone_nodes = _zone_nodes(connection, node_lists)
    return tuple(sorted(
        [(
            len(zone_nodes & _equipment_list_nodes(
                item, identities=identities, idd=idd, node_lists=node_lists,
            )),
            item,
        )
        for item in equipment_lists
        ],
        key=lambda row: (-row[0], canonical(row[1].name)),
    ))


def _discover_zone_equipment_list(
    document: IDFDocument,
    idd: IDDSchema,
) -> tuple[FaultMutation, ...]:
    identities = _identity_index(document)
    node_lists = _node_lists(document)
    equipment_lists = document.find_objects("ZoneHVAC:EquipmentList")
    rows: list[FaultMutation] = []
    for connection in document.find_objects("ZoneHVAC:EquipmentConnections"):
        if len(connection.fields) < 2:
            continue
        scores = _zone_list_scores(
            connection, equipment_lists,
            identities=identities, idd=idd, node_lists=node_lists,
        )
        if not scores or scores[0][0] <= 0:
            continue
        winners = tuple(item for score, item in scores if score == scores[0][0])
        current = connection.fields[1].value
        if len(winners) != 1 or canonical(winners[0].name) != canonical(current):
            continue
        donor = next((
            item for item in equipment_lists if canonical(item.name) != canonical(current)
        ), None)
        if donor is None:
            continue
        edit = FieldEdit(connection.index, 2, current, donor.name)
        rows.append(_mutation(
            family="zone_equipment_list_mismatch",
            edits=(edit,),
            locator={"object_index": connection.index, "field_index": 2},
            oracle_relation=f"Zone:{connection.name}->EquipmentList:{current}",
            mutated_relation=f"Zone:{connection.name}->EquipmentList:{donor.name}",
        ))
    return tuple(rows)


def _owning_connection(
    document: IDFDocument,
    equipment_list: IDFObject,
) -> IDFObject | None:
    matches = tuple(
        item for item in document.find_objects("ZoneHVAC:EquipmentConnections")
        if len(item.fields) >= 2
        and canonical(item.fields[1].value) == canonical(equipment_list.name)
    )
    return matches[0] if len(matches) == 1 else None


def _member_scores(
    document: IDFDocument,
    idd: IDDSchema,
    member: _EquipmentMember,
) -> tuple[tuple[int, IDFObject], ...]:
    connection = _owning_connection(document, member.equipment_list)
    if connection is None:
        return ()
    node_lists = _node_lists(document)
    zone_nodes = _zone_nodes(connection, node_lists)
    candidates = _objects_by_type(document).get(canonical(member.equipment_type), ())
    return tuple(sorted(
        [(
            len(zone_nodes & _object_node_roles(item, idd, node_lists)["all"]),
            item,
        )
        for item in candidates if item.name.strip()
        ],
        key=lambda row: (-row[0], canonical(row[1].name)),
    ))


def _discover_zone_equipment_member(
    document: IDFDocument,
    idd: IDDSchema,
    *,
    ambiguous: bool,
) -> tuple[FaultMutation, ...]:
    rows: list[FaultMutation] = []
    family = ABSTENTION_FAMILY if ambiguous else "zone_equipment_member_mismatch"
    for equipment_list in document.find_objects("ZoneHVAC:EquipmentList"):
        for member in _equipment_members(equipment_list):
            scores = _member_scores(document, idd, member)
            if len(scores) < 2:
                continue
            top = scores[0][0]
            winners = tuple(item for score, item in scores if score == top)
            current = next((
                item for _, item in scores
                if canonical(item.name) == canonical(member.equipment_name)
            ), None)
            if current is None:
                continue
            is_ambiguous = top == 0 and len(winners) >= 2 and current in winners
            is_unique = top > 0 and len(winners) == 1 and winners[0] is current
            if (ambiguous and not is_ambiguous) or (not ambiguous and not is_unique):
                continue
            donor = next(item for _, item in scores if item is not current)
            edit = FieldEdit(
                equipment_list.index, member.name_index,
                member.equipment_name, donor.name,
            )
            rows.append(_mutation(
                family=family,
                edits=(edit,),
                locator={
                    "object_index": equipment_list.index,
                    "name_index": member.name_index,
                },
                oracle_relation=(
                    f"EquipmentList:{equipment_list.name}/member:{member.ordinal}="
                    f"{member.equipment_type}:{member.equipment_name}"
                ),
                mutated_relation=(
                    f"EquipmentList:{equipment_list.name}/member:{member.ordinal}="
                    f"{member.equipment_type}:{donor.name}"
                ),
            ))
    return tuple(rows)


def _discover_zone_equipment_priority(
    document: IDFDocument,
) -> tuple[FaultMutation, ...]:
    rows: list[FaultMutation] = []
    for equipment_list in document.find_objects("ZoneHVAC:EquipmentList"):
        members = _equipment_members(equipment_list)
        if len(members) < 2:
            continue
        cooling: list[tuple[int, str]] = []
        heating: list[tuple[int, str]] = []
        for member in members:
            cooling_index = member.type_index + 2
            heating_index = member.type_index + 3
            if heating_index > len(equipment_list.fields):
                break
            cooling.append((
                cooling_index, equipment_list.fields[cooling_index - 1].value,
            ))
            heating.append((
                heating_index, equipment_list.fields[heating_index - 1].value,
            ))
        if len(cooling) != len(members):
            continue
        cooling_values = tuple(value.strip() for _, value in cooling)
        heating_values = tuple(value.strip() for _, value in heating)
        if (
            not all(cooling_values)
            or cooling_values != heating_values
            or len(set(cooling_values)) != len(cooling_values)
        ):
            continue
        swapped = (cooling_values[1], cooling_values[0], *cooling_values[2:])
        edits = tuple(
            FieldEdit(
                equipment_list.index, index, old_value, new_value,
            )
            for (index, old_value), new_value in zip(cooling, swapped)
            if old_value != new_value
        )
        if not edits:
            continue
        rows.append(_mutation(
            family="zone_equipment_priority_mismatch",
            edits=edits,
            locator={"object_index": equipment_list.index},
            oracle_relation=(
                f"EquipmentList:{equipment_list.name}/cooling-priority="
                + ">".join(cooling_values)
            ),
            mutated_relation=(
                f"EquipmentList:{equipment_list.name}/cooling-priority="
                + ">".join(swapped)
            ),
        ))
    return tuple(rows)


def _connector_pair(
    document: IDFDocument,
    connector_list: IDFObject,
) -> tuple[IDFObject | None, IDFObject | None]:
    identities = _identity_index(document)
    found: list[IDFObject] = []
    for type_index in (2, 4):
        name_index = type_index + 1
        if name_index > len(connector_list.fields):
            continue
        matches = identities.get((
            canonical(connector_list.fields[type_index - 1].value),
            canonical(connector_list.fields[name_index - 1].value),
        ), ())
        if len(matches) == 1:
            found.append(matches[0])
    splitter = next((
        item for item in found if canonical(item.object_type) == "connector:splitter"
    ), None)
    mixer = next((
        item for item in found if canonical(item.object_type) == "connector:mixer"
    ), None)
    return splitter, mixer


def _connector_branches(connector: IDFObject) -> set[str]:
    return {
        canonical(field.value)
        for field in connector.fields[1:]
        if field.value.strip()
    }


def _discover_connector_membership(document: IDFDocument) -> tuple[FaultMutation, ...]:
    all_branches = tuple(document.find_objects("Branch"))
    rows: list[FaultMutation] = []
    for connector_list in document.find_objects("ConnectorList"):
        splitter, mixer = _connector_pair(document, connector_list)
        if splitter is None or mixer is None or len(splitter.fields) < 3:
            continue
        splitter_parallel = {
            canonical(field.value) for field in splitter.fields[2:] if field.value.strip()
        }
        mixer_parallel = {
            canonical(field.value) for field in mixer.fields[2:] if field.value.strip()
        }
        if splitter_parallel != mixer_parallel or not splitter_parallel:
            continue
        donor = next((
            item for item in all_branches
            if canonical(item.name) not in _connector_branches(splitter)
            and canonical(item.name) not in _connector_branches(mixer)
        ), None)
        if donor is None:
            continue
        field = splitter.fields[2]
        edit = FieldEdit(splitter.index, 3, field.value, donor.name)
        rows.append(_mutation(
            family="connector_parallel_membership",
            edits=(edit,),
            locator={
                "object_index": splitter.index,
                "field_index": 3,
                "connector_list_index": connector_list.index,
            },
            oracle_relation=(
                f"ConnectorPair:{connector_list.name}/parallel={field.value}"
            ),
            mutated_relation=(
                f"ConnectorPair:{connector_list.name}/parallel={donor.name}"
            ),
        ))
    return tuple(rows)


def _branch_list_members(branch_list: IDFObject) -> set[str]:
    return {
        canonical(field.value)
        for field in branch_list.fields[1:]
        if field.value.strip()
    }


def _discover_loop_branchlist(document: IDFDocument) -> tuple[FaultMutation, ...]:
    identities = _identity_index(document)
    branch_lists = document.find_objects("BranchList")
    rows: list[FaultMutation] = []
    for loop_type in ("PlantLoop", "CondenserLoop"):
        for loop in document.find_objects(loop_type):
            for branch_index, connector_index, side in (
                (13, 14, "supply"), (17, 18, "demand"),
            ):
                if connector_index > len(loop.fields):
                    continue
                branch_name = loop.fields[branch_index - 1].value
                connector_name = loop.fields[connector_index - 1].value
                if not branch_name.strip() or not connector_name.strip():
                    continue
                connector_matches = identities.get((
                    "connectorlist", canonical(connector_name),
                ), ())
                branch_matches = identities.get((
                    "branchlist", canonical(branch_name),
                ), ())
                if len(connector_matches) != 1 or len(branch_matches) != 1:
                    continue
                splitter, mixer = _connector_pair(document, connector_matches[0])
                if splitter is None or mixer is None:
                    continue
                needed = _connector_branches(splitter) | _connector_branches(mixer)
                if _branch_list_members(branch_matches[0]) != needed:
                    continue
                donor = next((
                    item for item in branch_lists
                    if canonical(item.name) != canonical(branch_name)
                    and _branch_list_members(item) != needed
                ), None)
                if donor is None:
                    continue
                edit = FieldEdit(loop.index, branch_index, branch_name, donor.name)
                rows.append(_mutation(
                    family="loop_side_branchlist_mismatch",
                    edits=(edit,),
                    locator={
                        "object_index": loop.index,
                        "field_index": branch_index,
                        "connector_index": connector_index,
                    },
                    oracle_relation=f"Loop:{loop.name}/{side}->BranchList:{branch_name}",
                    mutated_relation=f"Loop:{loop.name}/{side}->BranchList:{donor.name}",
                ))
    return tuple(rows)


def _path_components(path: IDFObject) -> tuple[tuple[int, int, str, str], ...]:
    rows: list[tuple[int, int, str, str]] = []
    for type_index in range(3, len(path.fields) + 1, 2):
        name_index = type_index + 1
        if name_index > len(path.fields):
            continue
        component_type = path.fields[type_index - 1].value
        component_name = path.fields[name_index - 1].value
        if component_type.strip():
            rows.append((type_index, name_index, component_type, component_name))
    return tuple(rows)


def _path_boundary_matches(
    path: IDFObject,
    component: IDFObject,
) -> bool:
    if len(path.fields) < 2 or len(component.fields) < 2:
        return False
    boundary = canonical(path.fields[1].value)
    component_boundary = canonical(component.fields[1].value)
    return bool(boundary and boundary == component_boundary)


def _discover_air_path(document: IDFDocument) -> tuple[FaultMutation, ...]:
    identities = _identity_index(document)
    by_type = _objects_by_type(document)
    rows: list[FaultMutation] = []
    for path_type in ("AirLoopHVAC:SupplyPath", "AirLoopHVAC:ReturnPath"):
        for path in document.find_objects(path_type):
            for _, name_index, component_type, component_name in _path_components(path):
                matches = identities.get((
                    canonical(component_type), canonical(component_name),
                ), ())
                if len(matches) != 1 or not _path_boundary_matches(path, matches[0]):
                    continue
                donor = next((
                    item for item in by_type.get(canonical(component_type), ())
                    if canonical(item.name) != canonical(component_name)
                    and not _path_boundary_matches(path, item)
                ), None)
                if donor is None:
                    continue
                edit = FieldEdit(path.index, name_index, component_name, donor.name)
                rows.append(_mutation(
                    family="air_path_component_mismatch",
                    edits=(edit,),
                    locator={"object_index": path.index, "name_index": name_index},
                    oracle_relation=(
                        f"{path.object_type}:{path.name}->"
                        f"{component_type}:{component_name}"
                    ),
                    mutated_relation=(
                        f"{path.object_type}:{path.name}->{component_type}:{donor.name}"
                    ),
                ))
    return tuple(rows)


def discover_fault_mutations(
    document: IDFDocument,
    idd: IDDSchema,
    family: str,
) -> tuple[FaultMutation, ...]:
    """发现一个结构故障 family 中具备 clean oracle 的注入机会。"""

    if family == "branch_component_reassignment":
        return _discover_branch_component_reassignment(document)
    if family == "branch_endpoint_mismatch":
        return _discover_branch_endpoint_mismatch(document, idd)
    if family == "branch_member_order":
        return _discover_branch_member_order(document)
    if family == "zone_equipment_list_mismatch":
        return _discover_zone_equipment_list(document, idd)
    if family == "zone_equipment_member_mismatch":
        return _discover_zone_equipment_member(document, idd, ambiguous=False)
    if family == "zone_equipment_priority_mismatch":
        return _discover_zone_equipment_priority(document)
    if family == ABSTENTION_FAMILY:
        return _discover_zone_equipment_member(document, idd, ambiguous=True)
    if family == "connector_parallel_membership":
        return _discover_connector_membership(document)
    if family == "loop_side_branchlist_mismatch":
        return _discover_loop_branchlist(document)
    if family == "air_path_component_mismatch":
        return _discover_air_path(document)
    raise ValueError(f"unknown fault family: {family}")


def _decision(
    candidates: Sequence[tuple[FieldEdit, ...]],
    *,
    evidence: Sequence[str],
    semantic_cost: int = 1,
) -> RepairDecision:
    unique: dict[tuple[tuple[int, int, str], ...], tuple[FieldEdit, ...]] = {}
    for candidate in candidates:
        key = tuple(sorted(
            (edit.object_index, edit.field_index, canonical(edit.new_value))
            for edit in candidate
        ))
        unique[key] = candidate
    minima = tuple(unique.values())
    if len(minima) == 1:
        return RepairDecision(
            status="AUTO_REPAIR",
            edits=minima[0],
            candidate_count=len(minima),
            minimum_candidate_count=1,
            minimum_cost=semantic_cost,
            evidence=tuple(evidence),
            alternatives=minima,
        )
    if minima:
        return RepairDecision(
            status="ABSTAIN",
            edits=(),
            candidate_count=len(minima),
            minimum_candidate_count=len(minima),
            minimum_cost=semantic_cost,
            evidence=tuple(evidence),
            alternatives=minima,
        )
    return RepairDecision(
        status="UNSUPPORTED",
        edits=(),
        candidate_count=0,
        minimum_candidate_count=0,
        minimum_cost=None,
        evidence=tuple(evidence),
    )


def _locate_branch_component(
    document: IDFDocument,
    object_index: int,
    field_index: int,
) -> _BranchComponent | None:
    if not 0 <= object_index < len(document.objects):
        return None
    return next((
        row for row in _branch_components(document.objects[object_index])
        if field_index in {
            row.type_index, row.name_index, row.inlet_index, row.outlet_index,
        }
    ), None)


def _solve_branch_component(
    document: IDFDocument,
    locator: Mapping[str, Any],
) -> RepairDecision:
    relation = _locate_branch_component(
        document, int(locator["object_index"]), int(locator["name_index"]),
    )
    if relation is None:
        return _decision((), evidence=("branch_member_not_found",))
    by_type = _objects_by_type(document)
    endpoints = {canonical(relation.inlet_node), canonical(relation.outlet_node)}
    candidates = []
    for obj in by_type.get(canonical(relation.component_type), ()):
        if not obj.name.strip() or not endpoints.issubset(_object_all_values(obj)):
            continue
        if canonical(obj.name) == canonical(relation.component_name):
            continue
        candidates.append((FieldEdit(
            relation.branch.index, relation.name_index,
            relation.component_name, obj.name,
        ),))
    return _decision(candidates, evidence=(
        "typed_component_identity", "branch_endpoint_pair",
    ))


def _solve_branch_endpoint(
    document: IDFDocument,
    idd: IDDSchema,
    locator: Mapping[str, Any],
) -> RepairDecision:
    object_index = int(locator["object_index"])
    field_index = int(locator["outlet_index"])
    relation = _locate_branch_component(document, object_index, field_index)
    if relation is None:
        return _decision((), evidence=("branch_member_not_found",))
    identities = _identity_index(document)
    matches = identities.get((
        canonical(relation.component_type), canonical(relation.component_name),
    ), ())
    if len(matches) != 1:
        return _decision((), evidence=("component_identity_not_unique",))
    roles = _object_node_roles(matches[0], idd, _node_lists(document))
    role = "outlet" if field_index == relation.outlet_index else "inlet"
    values = roles[role] or roles["all"]
    branch_rows = _branch_components(relation.branch)
    position = branch_rows.index(relation)
    candidates: list[tuple[FieldEdit, ...]] = []
    for value in sorted(values):
        inlet = canonical(relation.inlet_node)
        outlet = canonical(relation.outlet_node)
        if role == "outlet":
            outlet = value
        else:
            inlet = value
        if not {inlet, outlet}.issubset(_object_all_values(matches[0])):
            continue
        if position + 1 < len(branch_rows):
            if outlet != canonical(branch_rows[position + 1].inlet_node):
                continue
        if position > 0:
            if inlet != canonical(branch_rows[position - 1].outlet_node):
                continue
        current = relation.branch.fields[field_index - 1].value
        if canonical(current) == value:
            continue
        # Preserve the spelling already present on the target component.
        display = next(
            field.value for field in matches[0].fields
            if canonical(field.value) == value
        )
        candidates.append((FieldEdit(
            relation.branch.index, field_index, current, display,
        ),))
    return _decision(candidates, evidence=(
        "component_port_role", "branch_path_continuity",
    ))


def _solve_branch_order(
    document: IDFDocument,
    locator: Mapping[str, Any],
) -> RepairDecision:
    branch = document.objects[int(locator["object_index"])]
    current = _branch_components(branch)
    if not 2 <= len(current) <= 7:
        return _decision((), evidence=("bounded_branch_order_search",))
    candidates: list[tuple[FieldEdit, ...]] = []
    for ordered in permutations(current):
        if ordered == current or not _continuous(ordered):
            continue
        edits: list[FieldEdit] = []
        for destination, source in zip(current, ordered):
            old_values = (
                destination.component_type, destination.component_name,
                destination.inlet_node, destination.outlet_node,
            )
            new_values = (
                source.component_type, source.component_name,
                source.inlet_node, source.outlet_node,
            )
            for offset, (old, new) in enumerate(zip(old_values, new_values)):
                if old != new:
                    edits.append(FieldEdit(
                        branch.index, destination.type_index + offset, old, new,
                    ))
        candidates.append(tuple(edits))
    return _decision(candidates, evidence=(
        "directed_component_path", "bounded_permutation_search",
    ))


def _solve_zone_list(
    document: IDFDocument,
    idd: IDDSchema,
    locator: Mapping[str, Any],
) -> RepairDecision:
    connection = document.objects[int(locator["object_index"])]
    identities = _identity_index(document)
    node_lists = _node_lists(document)
    scores = _zone_list_scores(
        connection, document.find_objects("ZoneHVAC:EquipmentList"),
        identities=identities, idd=idd, node_lists=node_lists,
    )
    if not scores or scores[0][0] <= 0:
        return _decision((), evidence=("no_zone_node_overlap",))
    top = scores[0][0]
    current = connection.fields[1].value
    candidates = tuple(
        (FieldEdit(connection.index, 2, current, item.name),)
        for score, item in scores
        if score == top and canonical(item.name) != canonical(current)
    )
    return _decision(candidates, evidence=(
        "zone_connection_nodes", "equipment_member_ports", f"overlap={top}",
    ))


def _solve_zone_member(
    document: IDFDocument,
    idd: IDDSchema,
    locator: Mapping[str, Any],
) -> RepairDecision:
    equipment_list = document.objects[int(locator["object_index"])]
    name_index = int(locator["name_index"])
    member = next((
        item for item in _equipment_members(equipment_list)
        if item.name_index == name_index
    ), None)
    if member is None:
        return _decision((), evidence=("equipment_member_not_found",))
    scores = _member_scores(document, idd, member)
    if not scores:
        return _decision((), evidence=("no_same_type_candidates",))
    top = scores[0][0]
    current = member.equipment_name
    winners = tuple(item for score, item in scores if score == top)
    candidates = tuple(
        (FieldEdit(equipment_list.index, name_index, current, item.name),)
        for item in winners if canonical(item.name) != canonical(current)
    )
    # If the current (faulty) value also ties, it remains one minimum semantic
    # interpretation. Include an explicit no-change interpretation so the
    # uniqueness test abstains instead of silently choosing another object.
    if any(canonical(item.name) == canonical(current) for item in winners):
        candidates = (*candidates, ())
    return _decision(candidates, evidence=(
        "zone_connection_nodes", "same_type_equipment_ports", f"overlap={top}",
    ))


def _solve_zone_priority(
    document: IDFDocument,
    locator: Mapping[str, Any],
) -> RepairDecision:
    equipment_list = document.objects[int(locator["object_index"])]
    members = _equipment_members(equipment_list)
    if len(members) < 2:
        return _decision((), evidence=("insufficient_equipment_members",))
    edits: list[FieldEdit] = []
    heating_values: list[str] = []
    for member in members:
        cooling_index = member.type_index + 2
        heating_index = member.type_index + 3
        if heating_index > len(equipment_list.fields):
            return _decision((), evidence=("priority_field_missing",))
        cooling_value = equipment_list.fields[cooling_index - 1].value
        heating_value = equipment_list.fields[heating_index - 1].value
        if not heating_value.strip():
            return _decision((), evidence=("paired_priority_missing",))
        heating_values.append(canonical(heating_value))
        if cooling_value != heating_value:
            edits.append(FieldEdit(
                equipment_list.index, cooling_index, cooling_value, heating_value,
            ))
    if len(set(heating_values)) != len(heating_values):
        return _decision((), evidence=("paired_priority_not_a_permutation",))
    candidates = (tuple(edits),) if edits else ()
    return _decision(candidates, evidence=(
        "paired_cooling_heating_priority", "one_to_one_priority_permutation",
    ))


def _solve_connector(
    document: IDFDocument,
    locator: Mapping[str, Any],
) -> RepairDecision:
    splitter = document.objects[int(locator["object_index"])]
    field_index = int(locator["field_index"])
    connector_list = document.objects[int(locator["connector_list_index"])]
    paired_splitter, mixer = _connector_pair(document, connector_list)
    if paired_splitter is not splitter or mixer is None:
        return _decision((), evidence=("connector_pair_not_found",))
    other_splitter = {
        canonical(field.value)
        for field in splitter.fields[2:]
        if field.index != field_index and field.value.strip()
    }
    mixer_parallel = {
        canonical(field.value): field.value
        for field in mixer.fields[2:] if field.value.strip()
    }
    current = splitter.fields[field_index - 1].value
    missing = tuple(
        display for key, display in mixer_parallel.items() if key not in other_splitter
    )
    candidates = tuple(
        (FieldEdit(splitter.index, field_index, current, value),)
        for value in missing if canonical(value) != canonical(current)
    )
    return _decision(candidates, evidence=(
        "connectorlist_pair", "splitter_mixer_reciprocity",
    ))


def _solve_loop_branchlist(
    document: IDFDocument,
    locator: Mapping[str, Any],
) -> RepairDecision:
    loop = document.objects[int(locator["object_index"])]
    field_index = int(locator["field_index"])
    connector_index = int(locator["connector_index"])
    identities = _identity_index(document)
    connector_matches = identities.get((
        "connectorlist", canonical(loop.fields[connector_index - 1].value),
    ), ())
    if len(connector_matches) != 1:
        return _decision((), evidence=("connectorlist_not_unique",))
    splitter, mixer = _connector_pair(document, connector_matches[0])
    if splitter is None or mixer is None:
        return _decision((), evidence=("connector_pair_not_found",))
    needed = _connector_branches(splitter) | _connector_branches(mixer)
    current = loop.fields[field_index - 1].value
    candidates = tuple(
        (FieldEdit(loop.index, field_index, current, branch_list.name),)
        for branch_list in document.find_objects("BranchList")
        if _branch_list_members(branch_list) == needed
        and canonical(branch_list.name) != canonical(current)
    )
    return _decision(candidates, evidence=(
        "loop_connectorlist", "exact_branch_membership",
    ))


def _solve_air_path(
    document: IDFDocument,
    locator: Mapping[str, Any],
) -> RepairDecision:
    path = document.objects[int(locator["object_index"])]
    name_index = int(locator["name_index"])
    component = next((
        row for row in _path_components(path) if row[1] == name_index
    ), None)
    if component is None:
        return _decision((), evidence=("path_component_not_found",))
    _, _, component_type, current = component
    candidates = tuple(
        (FieldEdit(path.index, name_index, current, item.name),)
        for item in _objects_by_type(document).get(canonical(component_type), ())
        if item.name.strip()
        and canonical(item.name) != canonical(current)
        and _path_boundary_matches(path, item)
    )
    return _decision(candidates, evidence=(
        "air_path_boundary_node", "typed_path_component",
    ))


def solve_injected_fault(
    document: IDFDocument,
    idd: IDDSchema,
    fault: FaultMutation,
) -> RepairDecision:
    """在约束定位点求解，且不读取该故障的 clean oracle。"""

    return solve_at_locator(document, idd, fault.family, fault.locator)


def solve_at_locator(
    document: IDFDocument,
    idd: IDDSchema,
    family: str,
    locator: Mapping[str, Any],
) -> RepairDecision:
    """枚举图约束冲突定位点的最小修复并返回唯一性决策。"""

    if family == "branch_component_reassignment":
        return _solve_branch_component(document, locator)
    if family == "branch_endpoint_mismatch":
        return _solve_branch_endpoint(document, idd, locator)
    if family == "branch_member_order":
        return _solve_branch_order(document, locator)
    if family == "zone_equipment_list_mismatch":
        return _solve_zone_list(document, idd, locator)
    if family in {"zone_equipment_member_mismatch", ABSTENTION_FAMILY}:
        return _solve_zone_member(document, idd, locator)
    if family == "zone_equipment_priority_mismatch":
        return _solve_zone_priority(document, locator)
    if family == "connector_parallel_membership":
        return _solve_connector(document, locator)
    if family == "loop_side_branchlist_mismatch":
        return _solve_loop_branchlist(document, locator)
    if family == "air_path_component_mismatch":
        return _solve_air_path(document, locator)
    raise ValueError(f"unknown fault family: {family}")


def detect_constraint_violations(
    document: IDFDocument,
    idd: IDDSchema,
    family: str,
) -> tuple[Mapping[str, Any], ...]:
    """仅使用当前 IDF 与 IDD 定位指定 family 的关系约束冲突。

    歧义 family 不进行全局报错，因为并列成员关系也可能是合法 clean 关系。
    只有外部诊断或用户先指向该成员后才评估可恢复性；若存在多个最小解释，
    唯一性门返回拒绝自动修改。
    """

    identities = _identity_index(document)
    by_type = _objects_by_type(document)
    locations: list[dict[str, Any]] = []
    if family == "branch_component_reassignment":
        for relation in _all_branch_components(document):
            endpoints = {
                canonical(relation.inlet_node), canonical(relation.outlet_node),
            }
            compatible = tuple(
                item for item in by_type.get(canonical(relation.component_type), ())
                if item.name.strip() and endpoints.issubset(_object_all_values(item))
            )
            current = identities.get((
                canonical(relation.component_type),
                canonical(relation.component_name),
            ), ())
            if compatible and not (
                len(current) == 1 and current[0] in compatible
            ):
                locations.append({
                    "object_index": relation.branch.index,
                    "name_index": relation.name_index,
                })
        return tuple(locations)

    if family == "branch_endpoint_mismatch":
        for relation in _all_branch_components(document):
            current = identities.get((
                canonical(relation.component_type),
                canonical(relation.component_name),
            ), ())
            if len(current) != 1:
                continue
            endpoints = {
                canonical(relation.inlet_node), canonical(relation.outlet_node),
            }
            if endpoints.issubset(_object_all_values(current[0])):
                continue
            locator = {
                "object_index": relation.branch.index,
                "outlet_index": relation.outlet_index,
            }
            if _solve_branch_endpoint(document, idd, locator).candidate_count:
                locations.append(locator)
        return tuple(locations)

    if family == "branch_member_order":
        for branch in document.find_objects("Branch"):
            components = _branch_components(branch)
            if len(components) >= 2 and not _continuous(components):
                locator = {"object_index": branch.index}
                if _solve_branch_order(document, locator).candidate_count:
                    locations.append(locator)
        return tuple(locations)

    if family == "zone_equipment_list_mismatch":
        node_lists = _node_lists(document)
        equipment_lists = document.find_objects("ZoneHVAC:EquipmentList")
        for connection in document.find_objects("ZoneHVAC:EquipmentConnections"):
            if len(connection.fields) < 2:
                continue
            scores = _zone_list_scores(
                connection, equipment_lists,
                identities=identities, idd=idd, node_lists=node_lists,
            )
            if not scores or scores[0][0] <= 0:
                continue
            winners = tuple(
                item for score, item in scores if score == scores[0][0]
            )
            if len(winners) == 1 and canonical(winners[0].name) != canonical(
                connection.fields[1].value
            ):
                locations.append({
                    "object_index": connection.index, "field_index": 2,
                })
        return tuple(locations)

    if family == "zone_equipment_member_mismatch":
        for equipment_list in document.find_objects("ZoneHVAC:EquipmentList"):
            for member in _equipment_members(equipment_list):
                scores = _member_scores(document, idd, member)
                if not scores or scores[0][0] <= 0:
                    continue
                winners = tuple(
                    item for score, item in scores if score == scores[0][0]
                )
                if len(winners) == 1 and canonical(winners[0].name) != canonical(
                    member.equipment_name
                ):
                    locations.append({
                        "object_index": equipment_list.index,
                        "name_index": member.name_index,
                    })
        return tuple(locations)

    if family == "zone_equipment_priority_mismatch":
        for equipment_list in document.find_objects("ZoneHVAC:EquipmentList"):
            members = _equipment_members(equipment_list)
            if len(members) < 2:
                continue
            cooling: list[str] = []
            heating: list[str] = []
            complete = True
            for member in members:
                cooling_index = member.type_index + 2
                heating_index = member.type_index + 3
                if heating_index > len(equipment_list.fields):
                    complete = False
                    break
                cooling.append(equipment_list.fields[cooling_index - 1].value)
                heating.append(equipment_list.fields[heating_index - 1].value)
            if (
                complete and cooling != heating and all(value.strip() for value in heating)
                and len({canonical(value) for value in heating}) == len(heating)
            ):
                locations.append({"object_index": equipment_list.index})
        return tuple(locations)

    if family == "connector_parallel_membership":
        for connector_list in document.find_objects("ConnectorList"):
            splitter, mixer = _connector_pair(document, connector_list)
            if splitter is None or mixer is None:
                continue
            splitter_parallel = {
                canonical(field.value) for field in splitter.fields[2:]
                if field.value.strip()
            }
            mixer_parallel = {
                canonical(field.value) for field in mixer.fields[2:]
                if field.value.strip()
            }
            if splitter_parallel == mixer_parallel:
                continue
            for field in splitter.fields[2:]:
                if canonical(field.value) not in mixer_parallel:
                    locations.append({
                        "object_index": splitter.index,
                        "field_index": field.index,
                        "connector_list_index": connector_list.index,
                    })
        return tuple(locations)

    if family == "loop_side_branchlist_mismatch":
        for loop_type in ("PlantLoop", "CondenserLoop"):
            for loop in document.find_objects(loop_type):
                for branch_index, connector_index in ((13, 14), (17, 18)):
                    if connector_index > len(loop.fields):
                        continue
                    connector_matches = identities.get((
                        "connectorlist",
                        canonical(loop.fields[connector_index - 1].value),
                    ), ())
                    branch_matches = identities.get((
                        "branchlist",
                        canonical(loop.fields[branch_index - 1].value),
                    ), ())
                    if len(connector_matches) != 1:
                        continue
                    splitter, mixer = _connector_pair(document, connector_matches[0])
                    if splitter is None or mixer is None:
                        continue
                    needed = _connector_branches(splitter) | _connector_branches(mixer)
                    current_members = (
                        _branch_list_members(branch_matches[0])
                        if len(branch_matches) == 1 else set()
                    )
                    if current_members != needed:
                        locations.append({
                            "object_index": loop.index,
                            "field_index": branch_index,
                            "connector_index": connector_index,
                        })
        return tuple(locations)

    if family == "air_path_component_mismatch":
        for path_type in ("AirLoopHVAC:SupplyPath", "AirLoopHVAC:ReturnPath"):
            for path in document.find_objects(path_type):
                for _, name_index, component_type, component_name in _path_components(path):
                    current = identities.get((
                        canonical(component_type), canonical(component_name),
                    ), ())
                    if len(current) == 1 and _path_boundary_matches(path, current[0]):
                        continue
                    if any(
                        _path_boundary_matches(path, item)
                        for item in by_type.get(canonical(component_type), ())
                    ):
                        locations.append({
                            "object_index": path.index, "name_index": name_index,
                        })
        return tuple(locations)

    if family == ABSTENTION_FAMILY:
        return ()
    raise ValueError(f"unknown fault family: {family}")


__all__ = [
    "ABSTENTION_FAMILY",
    "ALL_FEASIBILITY_FAMILIES",
    "AUTO_REPAIR_FAMILIES",
    "FaultMutation",
    "FieldEdit",
    "RepairDecision",
    "apply_field_edits",
    "detect_constraint_violations",
    "discover_fault_mutations",
    "solve_at_locator",
    "solve_injected_fault",
]
