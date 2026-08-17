'''
依据版本匹配 IDD 建立 HVAC 类型化引用、端口和容器关系图。

build_hvac_graph(): 建立对象、流体端口、引用边、Branch 和设备清单关系。
structural_twins(): 查找对象类型、端口和引用签名一致的结构同类项。
trace_hvac_object(): 返回单个对象的端口、引用和容器关系。
'''

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from idfrepair.io.idf import IDFDocument, IDFObject, canonical
from idfrepair.knowledge.idd import IDDField, IDDSchema


def _object_id(obj: IDFObject) -> str:
    '''生成稳定的 HVAC 对象身份。'''
    return f"hvac-object:{canonical(obj.object_type)}#{obj.index}:{canonical(obj.name)}"


def _category(object_type: str) -> str:
    '''将关键 HVAC 对象归入环路、支路、连接器、控制器或组件类别。'''
    value = canonical(object_type)
    if value in {"airloophvac", "plantloop", "condenserloop"}:
        return "loop"
    if value in {"branch", "branchlist"}:
        return "branch"
    if value.startswith("connector:") or value == "connectorlist":
        return "connector"
    if value.startswith("controller:") or value == "controllerlist":
        return "controller"
    if value.startswith("availabilitymanager"):
        return "availability_manager"
    if value.startswith("zonehvac") or "zoneequipment" in value:
        return "zone_equipment"
    if value in {"airloophvac:supplypath", "airloophvac:returnpath"}:
        return "air_path"
    return "component"


def _medium(object_type: str, field_name: str) -> str:
    '''根据对象域和字段物理名称保守识别 air、water 或 refrigerant。'''
    combined = canonical(f"{object_type} {field_name}")
    if any(token in combined for token in (
        "airloop", "air terminal", "airconditioner", "fan", "coil:cooling:dx",
        "outdoor air", "zonehvac", "air inlet", "air outlet",
    )):
        return "air"
    if any(token in combined for token in (
        "plantloop", "condenserloop", "boiler", "chiller", "pump",
        "water inlet", "water outlet", "fluidcooler", "coolingtower",
    )):
        return "water"
    if "refrigerant" in combined:
        return "refrigerant"
    return "generic"


def _port_role(field: IDDField) -> str:
    '''从 IDD 字段身份识别入口、出口或未定向 node 引用。'''
    name = canonical(field.name)
    lists = {canonical(value) for value in field.object_lists}
    node_field = (
        "node name" in name or "node names" in name
        or any("node" in value for value in lists)
    )
    if not node_field or name.startswith("number of"):
        return ""
    if any(token in name for token in ("inlet", "entering")):
        return "inlet"
    if any(token in name for token in ("outlet", "leaving", "exhaust", "relief")):
        return "outlet"
    return "node_reference"


def _providers(
    document: IDFDocument, idd: IDDSchema,
) -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    '''按 Name 字段 reference class 和实例名称建立类型化提供方索引。'''
    by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        name_field = definition.field_at(1) if definition is not None else None
        if name_field is None or not obj.name.strip():
            continue
        row = {
            "object_id": _object_id(obj),
            "object_index": obj.index,
            "object_type": obj.object_type,
            "object_name": obj.name,
        }
        for reference in name_field.references:
            key = canonical(reference)
            by_identity[(key, canonical(obj.name))].append(row)
            by_class[key].append(row)
    return by_identity, by_class


def _branch_relations(
    document: IDFDocument, idd: IDDSchema,
) -> tuple[dict[str, Any], ...]:
    '''解析 Branch extensible 组件类型、名称和两端节点关系。'''
    relations: list[dict[str, Any]] = []
    by_type_name: dict[tuple[str, str], list[IDFObject]] = defaultdict(list)
    for obj in document.objects:
        if obj.name:
            by_type_name[(canonical(obj.object_type), canonical(obj.name))].append(obj)
    for branch in document.objects:
        if canonical(branch.object_type) != "branch":
            continue
        definition = idd.get(branch.object_type)
        if definition is None:
            continue
        for field in branch.fields:
            field_def = definition.field_at(field.index)
            field_name = canonical(field_def.name) if field_def is not None else ""
            if field_def is None or not (
                "component" in field_name and "object type" in field_name
            ):
                continue
            name_index = field.index + 1
            inlet_index = field.index + 2
            outlet_index = field.index + 3
            if outlet_index > len(branch.fields):
                continue
            component_type = field.value.strip()
            component_name = branch.fields[name_index - 1].value.strip()
            inlet = branch.fields[inlet_index - 1].value.strip()
            outlet = branch.fields[outlet_index - 1].value.strip()
            matches = by_type_name.get((canonical(component_type), canonical(component_name)), [])
            endpoints = []
            for target in matches:
                values = {canonical(item.value) for item in target.fields[1:] if item.value.strip()}
                if canonical(inlet) in values and canonical(outlet) in values:
                    endpoints.append(target)
            relations.append({
                "container_id": _object_id(branch),
                "container_index": branch.index,
                "component_type_index": field.index,
                "component_name_index": name_index,
                "inlet_index": inlet_index,
                "outlet_index": outlet_index,
                "component_type": component_type,
                "component_name": component_name,
                "inlet_node": inlet,
                "outlet_node": outlet,
                "matching_object_ids": tuple(_object_id(obj) for obj in matches),
                "endpoint_matching_object_ids": tuple(_object_id(obj) for obj in endpoints),
                "status": (
                    "OK" if len(matches) == 1 and len(endpoints) == 1
                    else "MISSING" if not matches
                    else "ENDPOINT_MISMATCH" if not endpoints
                    else "AMBIGUOUS"
                ),
            })
    return tuple(relations)


def _equipment_relations(
    document: IDFDocument, idd: IDDSchema,
) -> tuple[dict[str, Any], ...]:
    '''解析设备清单中的类型/名称对，并验证实际设备 multiplicity。'''
    relations: list[dict[str, Any]] = []
    by_type_name: dict[tuple[str, str], list[IDFObject]] = defaultdict(list)
    for obj in document.objects:
        if obj.name:
            by_type_name[(canonical(obj.object_type), canonical(obj.name))].append(obj)
    for container in document.objects:
        if "equipmentlist" not in canonical(container.object_type):
            continue
        definition = idd.get(container.object_type)
        if definition is None:
            continue
        for field in container.fields:
            field_def = definition.field_at(field.index)
            field_name = canonical(field_def.name) if field_def is not None else ""
            if field_def is None or not (
                "equipment" in field_name and "object type" in field_name
            ):
                continue
            name_index = field.index + 1
            if name_index > len(container.fields):
                continue
            equipment_type = field.value.strip()
            equipment_name = container.fields[name_index - 1].value.strip()
            matches = by_type_name.get((canonical(equipment_type), canonical(equipment_name)), [])
            relations.append({
                "container_id": _object_id(container),
                "container_index": container.index,
                "equipment_type_index": field.index,
                "equipment_name_index": name_index,
                "equipment_type": equipment_type,
                "equipment_name": equipment_name,
                "matching_object_ids": tuple(_object_id(obj) for obj in matches),
                "multiplicity": len(matches),
                "status": "OK" if len(matches) == 1 else "MISSING" if not matches else "AMBIGUOUS",
            })
    return tuple(relations)


def build_hvac_graph(document: IDFDocument, idd: IDDSchema) -> dict[str, Any]:
    '''
    建立版本绑定的 HVAC 对象、端口、引用、Branch 和设备清单关系图。

    只有 reference class 一致的对象形成引用边；只有介质相同且方向相反的同名端口形成流边。

    :param document: 保留对象和字段位置的当前 IDF 文档。
    :param idd: 与 EnergyPlus 运行版本一致的 IDD schema。
    :return: 图节点、批准边、未解析关系和 multiplicity 问题。
    '''
    provider_index, provider_classes = _providers(document, idd)
    object_nodes: list[dict[str, Any]] = []
    ports: list[dict[str, Any]] = []
    reference_edges: list[dict[str, Any]] = []
    unresolved_references: list[dict[str, Any]] = []
    node_ports: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        object_id = _object_id(obj)
        object_nodes.append({
            "node_id": object_id,
            "object_index": obj.index,
            "object_type": obj.object_type,
            "object_name": obj.name,
            "category": _category(obj.object_type),
        })
        for field in obj.fields:
            field_def = definition.field_at(field.index)
            if field_def is None or not field.value.strip():
                continue
            role = _port_role(field_def)
            if role:
                port = {
                    "port_id": f"{object_id}:port:{field.index}",
                    "object_id": object_id,
                    "object_index": obj.index,
                    "object_type": obj.object_type,
                    "object_name": obj.name,
                    "field_index": field.index,
                    "field_name": field_def.name,
                    "node_name": field.value,
                    "normalized_node_name": canonical(field.value),
                    "role": role,
                    "medium": _medium(obj.object_type, field_def.name),
                    "idd_object_lists": tuple(field_def.object_lists),
                }
                ports.append(port)
                node_ports[canonical(field.value)].append(port)
            for object_list in field_def.object_lists:
                list_key = canonical(object_list)
                if "node" in list_key:
                    continue
                matches = provider_index.get((list_key, canonical(field.value)), [])
                issue = {
                    "source_id": object_id,
                    "object_index": obj.index,
                    "object_type": obj.object_type,
                    "object_name": obj.name,
                    "field_index": field.index,
                    "field_name": field_def.name,
                    "value": field.value,
                    "object_list": object_list,
                    "candidate_targets": tuple(provider_classes.get(list_key, ())),
                }
                if len(matches) == 1:
                    reference_edges.append({
                        **issue,
                        "target_id": matches[0]["object_id"],
                        "relation": "idd_typed_reference",
                    })
                else:
                    unresolved_references.append({
                        **issue,
                        "reason": (
                            "missing_typed_reference_provider" if not matches
                            else "ambiguous_typed_reference_provider"
                        ),
                        "matching_target_ids": tuple(row["object_id"] for row in matches),
                    })
    fluid_nodes: list[dict[str, Any]] = []
    flow_edges: list[dict[str, Any]] = []
    role_conflicts: list[dict[str, Any]] = []
    multiplicity_issues: list[dict[str, Any]] = []
    for node_key, attached in sorted(node_ports.items()):
        media = {str(port["medium"]) for port in attached if port["medium"] != "generic"}
        node_id = f"hvac-node:{node_key}"
        fluid_nodes.append({
            "node_id": node_id,
            "node_name": attached[0]["node_name"],
            "media": tuple(sorted(media)) or ("generic",),
            "port_ids": tuple(port["port_id"] for port in attached),
        })
        if len(media) > 1:
            role_conflicts.append({"node_id": node_id, "reason": "incompatible_port_media"})
        outlets = [port for port in attached if port["role"] == "outlet"]
        inlets = [port for port in attached if port["role"] == "inlet"]
        if len(outlets) > 1 and not any(port["object_type"].startswith("Connector:") for port in attached):
            multiplicity_issues.append({
                "node_id": node_id,
                "reason": "multiple_outlet_providers_without_connector",
                "count": len(outlets),
            })
        for outlet in outlets:
            for inlet in inlets:
                if outlet["object_id"] == inlet["object_id"]:
                    role_conflicts.append({
                        "node_id": node_id,
                        "reason": "same_object_inlet_outlet_self_connection",
                    })
                elif outlet["medium"] == inlet["medium"] and outlet["medium"] != "generic":
                    flow_edges.append({
                        "source_port_id": outlet["port_id"],
                        "target_port_id": inlet["port_id"],
                        "node_id": node_id,
                        "relation": "typed_flow",
                        "medium": outlet["medium"],
                    })
    branch_relations = _branch_relations(document, idd)
    equipment_relations = _equipment_relations(document, idd)
    relationship_issues = tuple(
        row for row in (*branch_relations, *equipment_relations) if row["status"] != "OK"
    )
    return {
        "schema_version": "idfrepair.hvac.graph.v1",
        "idd_sha256": idd.sha256,
        "idd_version": idd.version,
        "status": "OK" if not (
            unresolved_references or role_conflicts or multiplicity_issues or relationship_issues
        ) else "GRAPH_ISSUES_FOUND",
        "object_nodes": tuple(object_nodes),
        "ports": tuple(ports),
        "fluid_nodes": tuple(fluid_nodes),
        "reference_edges": tuple(reference_edges),
        "flow_edges": tuple(flow_edges),
        "unresolved_references": tuple(unresolved_references),
        "role_conflicts": tuple(role_conflicts),
        "multiplicity_issues": tuple(multiplicity_issues),
        "branch_relations": branch_relations,
        "equipment_relations": equipment_relations,
        "relationship_issues": relationship_issues,
        "stats": {
            "object_count": len(object_nodes),
            "port_count": len(ports),
            "typed_flow_count": len(flow_edges),
            "typed_reference_count": len(reference_edges),
        },
    }


def _signature(graph: Mapping[str, Any], object_id: str) -> tuple[Any, ...]:
    '''提取对象的端口角色、介质和引用 class 签名，不比较实例值。'''
    ports = tuple(sorted(
        (port["field_index"], port["role"], port["medium"])
        for port in graph.get("ports", ()) if port["object_id"] == object_id
    ))
    references = tuple(sorted(
        (edge["field_index"], canonical(str(edge["object_list"])))
        for edge in (*graph.get("reference_edges", ()), *graph.get("unresolved_references", ()))
        if edge["source_id"] == object_id
    ))
    return ports, references


def structural_twins(graph: Mapping[str, Any], object_id: str) -> tuple[Mapping[str, Any], ...]:
    '''查找相同对象类型且端口、引用签名完整一致的结构同类项。'''
    source = next((row for row in graph.get("object_nodes", ()) if row["node_id"] == object_id), None)
    if source is None:
        return ()
    signature = _signature(graph, object_id)
    return tuple(row for row in graph.get("object_nodes", ()) if (
        row["node_id"] != object_id
        and canonical(str(row["object_type"])) == canonical(str(source["object_type"]))
        and _signature(graph, str(row["node_id"])) == signature
    ))


def trace_hvac_object(graph: Mapping[str, Any], object_id: str) -> dict[str, Any]:
    '''返回一个对象的端口、引用、容器关系和结构同类项。'''
    return {
        "schema_version": "idfrepair.hvac.trace.v1",
        "object_id": object_id,
        "ports": tuple(row for row in graph.get("ports", ()) if row["object_id"] == object_id),
        "references": tuple(row for row in (
            *graph.get("reference_edges", ()), *graph.get("unresolved_references", ())
        ) if row["source_id"] == object_id),
        "container_relations": tuple(row for row in (
            *graph.get("branch_relations", ()), *graph.get("equipment_relations", ())
        ) if row["container_id"] == object_id),
        "structural_twins": structural_twins(graph, object_id),
    }


__all__ = ["build_hvac_graph", "structural_twins", "trace_hvac_object"]
