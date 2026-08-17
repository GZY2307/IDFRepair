"""从一个 IDF/IDD snapshot 构建 canonical HVAC semantic IR。

build_model_ir() 只读取当前模型及精确 IDD。它不会接收 benchmark family、
locator、clean twin、oracle edit 或文件名，因此同一模型在 CLI、benchmark 与
直接 API 中会得到相同的关系事实。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from idfrepair.io.idf import IDFDocument, canonical
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.semantic_graph_v2.flow import build_flow_projections
from idfrepair.semantic_graph_v2.ir import (
    AirPathRelation,
    BranchListRelation,
    BranchMember,
    BranchPath,
    ConnectorKind,
    ConnectorPair,
    ConnectorRelation,
    ControllerRelation,
    EquipmentPathRelation,
    EvidenceScore,
    FieldRef,
    IdentityStatus,
    LoopSideKind,
    LoopSideRelation,
    ModelIR,
    ObjectRef,
    OutdoorAirSystemContext,
    OrderedTypedReference,
    TypedIdentity,
    ZoneEquipmentListRelation,
    ZoneEquipmentMember,
    ZoneEquipmentRelation,
    ZoneSideRole,
    object_ref_from_idf,
)
from idfrepair.semantic_graph_v2.ports import (
    PRODUCTION_PORT_REGISTRY,
    PortRegistry,
    extract_ports,
)


IR_SCHEMA_VERSION = "idfrepair.semantic-graph-v2.ir.v2"


def _normalize_version(value: str) -> str:
    parts = value.strip().split(".")
    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def _field_group(
    source: ObjectRef,
    start: int,
    width: int,
) -> Iterable[tuple[FieldRef, ...]]:
    """按 1-based field index 遍历完整 extensible groups。"""

    index = start
    while index <= len(source.fields):
        group = tuple(source.field(index + offset) for offset in range(width))
        if any(field is None for field in group):
            return
        yield tuple(field for field in group if field is not None)
        index += width


def _typed_references(
    source: ObjectRef,
    *,
    start: int,
    width: int = 2,
) -> tuple[OrderedTypedReference, ...]:
    """提取有序 type/name slots，同时保留 partial faulty reference。"""

    rows: list[OrderedTypedReference] = []
    for ordinal, group in enumerate(_field_group(source, start, width), start=1):
        type_field, name_field = group[0], group[1]
        if not (type_field.raw_value.strip() or name_field.raw_value.strip()):
            continue
        rows.append(OrderedTypedReference(
            ordinal=ordinal,
            type_field=type_field,
            name_field=name_field,
        ))
    return tuple(rows)


def _typed_reference_shape_complete(
    source: ObjectRef,
    *,
    start: int,
    width: int = 2,
) -> bool:
    """Report whether the current source contains only complete typed slots."""

    present = max(0, len(source.fields) - start + 1)
    return present % width == 0


class _ObjectIndex:
    """提供保留 multiplicity 的 snapshot-local typed lookup。"""

    def __init__(self, objects: tuple[ObjectRef, ...]) -> None:
        grouped: dict[tuple[str, str], list[ObjectRef]] = defaultdict(list)
        for obj in objects:
            grouped[(obj.normalized_object_type, obj.normalized_name)].append(obj)
        self._grouped = {
            key: tuple(values) for key, values in grouped.items()
        }

    def resolve(self, object_type: str, object_name: str) -> tuple[ObjectRef, ...]:
        return self._grouped.get(
            (canonical(object_type), canonical(object_name)), (),
        )

    def unique(self, object_type: str, object_name: str) -> ObjectRef | None:
        matches = self.resolve(object_type, object_name)
        return matches[0] if len(matches) == 1 else None


def _extract_branches(objects: tuple[ObjectRef, ...]) -> tuple[BranchPath, ...]:
    rows: list[BranchPath] = []
    for source in objects:
        if source.normalized_object_type != "branch":
            continue
        members: list[BranchMember] = []
        for ordinal, group in enumerate(_field_group(source, 3, 4), start=1):
            type_field, name_field, inlet_field, outlet_field = group
            if not any(field.raw_value.strip() for field in group):
                continue
            members.append(BranchMember(
                ordinal=ordinal,
                type_field=type_field,
                name_field=name_field,
                inlet_field=inlet_field,
                outlet_field=outlet_field,
            ))
        rows.append(BranchPath(
            relation_id=f"branch-path:{source.object_id}",
            object_ref=source,
            members=tuple(members),
        ))
    return tuple(rows)


def _extract_branch_lists(
    objects: tuple[ObjectRef, ...],
) -> tuple[BranchListRelation, ...]:
    return tuple(
        BranchListRelation(
            relation_id=f"branch-list:{source.object_id}",
            object_ref=source,
            member_fields=tuple(
                field for field in source.fields[1:] if field.raw_value.strip()
            ),
        )
        for source in objects
        if source.normalized_object_type == "branchlist"
    )


def _extract_connectors(
    objects: tuple[ObjectRef, ...],
) -> tuple[ConnectorRelation, ...]:
    kinds = {
        "connector:splitter": ConnectorKind.SPLITTER,
        "connector:mixer": ConnectorKind.MIXER,
    }
    rows: list[ConnectorRelation] = []
    for source in objects:
        kind = kinds.get(source.normalized_object_type)
        boundary = source.field(2)
        if kind is None or boundary is None:
            continue
        rows.append(ConnectorRelation(
            relation_id=f"connector:{kind.value.casefold()}:{source.object_id}",
            kind=kind,
            object_ref=source,
            boundary_field=boundary,
            parallel_fields=tuple(
                field for field in source.fields[2:] if field.raw_value.strip()
            ),
        ))
    return tuple(rows)


def _extract_connector_pairs(
    objects: tuple[ObjectRef, ...],
    index: _ObjectIndex,
    connectors: tuple[ConnectorRelation, ...],
) -> tuple[ConnectorPair, ...]:
    connector_by_object_id = {
        connector.object_ref.object_id: connector for connector in connectors
    }
    rows: list[ConnectorPair] = []
    for source in objects:
        if source.normalized_object_type != "connectorlist":
            continue
        declared = _typed_references(source, start=2)
        splitter: ConnectorRelation | None = None
        mixer: ConnectorRelation | None = None
        for member in declared:
            resolved = index.unique(member.object_type, member.object_name)
            connector = (
                connector_by_object_id.get(resolved.object_id)
                if resolved is not None else None
            )
            if connector is None:
                continue
            if connector.kind is ConnectorKind.SPLITTER and splitter is None:
                splitter = connector
            elif connector.kind is ConnectorKind.MIXER and mixer is None:
                mixer = connector
        rows.append(ConnectorPair(
            relation_id=f"connector-pair:{source.object_id}",
            object_ref=source,
            declared_members=declared,
            splitter=splitter,
            mixer=mixer,
        ))
    return tuple(rows)


def _extract_loop_sides(
    objects: tuple[ObjectRef, ...],
) -> tuple[LoopSideRelation, ...]:
    rows: list[LoopSideRelation] = []
    layouts = (
        (LoopSideKind.SUPPLY, 11, 12, 13, 14),
        (LoopSideKind.DEMAND, 15, 16, 17, 18),
    )
    for source in objects:
        if source.normalized_object_type not in {"plantloop", "condenserloop"}:
            continue
        for side, inlet_index, outlet_index, branch_index, connector_index in layouts:
            fields = tuple(source.field(position) for position in (
                inlet_index, outlet_index, branch_index, connector_index,
            ))
            if any(field is None for field in fields):
                continue
            inlet, outlet, branch_list, connector_list = (
                field for field in fields if field is not None
            )
            if not (
                inlet.raw_value.strip()
                or outlet.raw_value.strip()
                or branch_list.raw_value.strip()
                or connector_list.raw_value.strip()
            ):
                continue
            rows.append(LoopSideRelation(
                relation_id=f"loop-side:{source.object_id}:{side.value.casefold()}",
                object_ref=source,
                side=side,
                inlet_field=inlet,
                outlet_field=outlet,
                branch_list_field=branch_list,
                connector_list_field=connector_list,
            ))
    return tuple(rows)


def _extract_air_paths(objects: tuple[ObjectRef, ...]) -> tuple[AirPathRelation, ...]:
    supported = {"airloophvac:supplypath", "airloophvac:returnpath"}
    rows: list[AirPathRelation] = []
    for source in objects:
        boundary = source.field(2)
        if source.normalized_object_type not in supported or boundary is None:
            continue
        rows.append(AirPathRelation(
            relation_id=f"air-path:{source.object_id}",
            object_ref=source,
            boundary_field=boundary,
            members=_typed_references(source, start=3),
            reference_shape_complete=_typed_reference_shape_complete(
                source, start=3,
            ),
        ))
    return tuple(rows)


def _extract_equipment_paths(
    objects: tuple[ObjectRef, ...],
    index: _ObjectIndex,
) -> tuple[EquipmentPathRelation, ...]:
    rows: list[EquipmentPathRelation] = []
    doas_objects = tuple(
        source for source in objects
        if source.normalized_object_type == "airloophvac:dedicatedoutdoorairsystem"
    )
    for source in objects:
        equipment_list_field = source.field(3)
        if (
            source.normalized_object_type != "airloophvac:outdoorairsystem"
            or equipment_list_field is None
        ):
            continue
        equipment_list = index.unique(
            "AirLoopHVAC:OutdoorAirSystem:EquipmentList",
            equipment_list_field.raw_value,
        )
        members = (
            _typed_references(equipment_list, start=2)
            if equipment_list is not None else ()
        )
        owners = tuple(
            owner for owner in doas_objects
            if owner.field(2) is not None
            and owner.field(2).normalized_value == source.normalized_name
        )
        source_identity = index.resolve(
            "AirLoopHVAC:OutdoorAirSystem", source.raw_name,
        )
        context = (
            OutdoorAirSystemContext.AMBIGUOUS
            if owners and len(source_identity) != 1
            else OutdoorAirSystemContext.DEDICATED
            if owners
            else OutdoorAirSystemContext.NORMAL
        )
        controller_list_field = source.field(2)
        controller_list = (
            index.unique(
                "AirLoopHVAC:ControllerList", controller_list_field.raw_value,
            )
            if controller_list_field is not None else None
        )
        outdoor_air_controllers = tuple(
            resolved[0]
            for member in (
                _typed_references(controller_list, start=2)
                if controller_list is not None else ()
            )
            if canonical(member.object_type) == "controller:outdoorair"
            for resolved in (
                index.resolve(member.object_type, member.object_name),
            )
            if len(resolved) == 1
        )
        outdoor_air_controller = (
            outdoor_air_controllers[0]
            if len(outdoor_air_controllers) == 1 else None
        )
        controller_node_fields = (
            tuple(
                field for position in (2, 3, 4, 5)
                for field in (outdoor_air_controller.field(position),)
                if field is not None and field.raw_value.strip()
            )
            if outdoor_air_controller is not None else ()
        )
        rows.append(EquipmentPathRelation(
            relation_id=f"equipment-path:{source.object_id}",
            system_ref=source,
            equipment_list_ref=equipment_list,
            equipment_list_field=equipment_list_field,
            members=members,
            reference_shape_complete=(
                equipment_list is not None
                and _typed_reference_shape_complete(equipment_list, start=2)
            ),
            context=context,
            context_owner_refs=owners,
            controller_list_ref=controller_list,
            outdoor_air_controller_ref=outdoor_air_controller,
            controller_node_fields=controller_node_fields,
        ))
    return tuple(rows)


def _extract_zone_lists(
    objects: tuple[ObjectRef, ...],
) -> tuple[ZoneEquipmentListRelation, ...]:
    rows: list[ZoneEquipmentListRelation] = []
    for source in objects:
        if source.normalized_object_type != "zonehvac:equipmentlist":
            continue
        members: list[ZoneEquipmentMember] = []
        index = 3
        ordinal = 1
        while index <= len(source.fields):
            # The final two fields in each six-wide EquipmentList group are
            # optional schedules.  EnergyPlus permits the final group to end
            # after its four required type/name/sequence fields, so requiring
            # all six silently drops a legal final member.
            required = tuple(source.field(index + offset) for offset in range(4))
            if any(field is None for field in required):
                break
            type_field, name_field, cooling_field, heating_field = (
                field for field in required if field is not None
            )
            if not (type_field.raw_value.strip() or name_field.raw_value.strip()):
                index += 6
                ordinal += 1
                continue
            members.append(
                ZoneEquipmentMember(
                    ordinal=ordinal,
                    type_field=type_field,
                    name_field=name_field,
                    cooling_sequence_field=cooling_field,
                    heating_sequence_field=heating_field,
                )
            )
            index += 6
            ordinal += 1
        rows.append(ZoneEquipmentListRelation(
            relation_id=f"zone-equipment-list:{source.object_id}",
            object_ref=source,
            members=tuple(members),
        ))
    return tuple(rows)


def _expand_node_field(
    field: FieldRef,
    index: _ObjectIndex,
) -> tuple[tuple[FieldRef, ...], tuple[FieldRef, ...]]:
    """返回 provenance fields 与实际 boundary node fields。

    第一个 tuple 始终保留原 EquipmentConnections 字段；若它唯一指向
    NodeList，则追加有序成员字段。第二个 tuple 仅含实际 node values，避免
    把 NodeList 名称误当作 node evidence。
    """

    node_list = index.unique("NodeList", field.raw_value)
    if node_list is None:
        return (field,), (field,)
    members = tuple(
        member for member in node_list.fields[1:] if member.raw_value.strip()
    )
    return (field, *members), members


def _zone_candidate_evidence(
    zone_list: ZoneEquipmentListRelation,
    boundary_node_fields: tuple[FieldRef, ...],
    index: _ObjectIndex,
    ports_by_object_id: dict[str, tuple],
) -> EvidenceScore:
    candidate_fields: list[FieldRef] = []
    complete = bool(zone_list.members)
    for member in zone_list.members:
        resolved = index.resolve(member.type_field.raw_value, member.name_field.raw_value)
        if len(resolved) != 1:
            complete = False
            continue
        zone_ports = tuple(
            port for port in ports_by_object_id.get(resolved[0].object_id, ())
            if port.zone_side_role is not ZoneSideRole.NONE
        )
        if not zone_ports:
            # Resolved equipment with no explicit zone-side port rule is
            # neutral: radiant and compound zone equipment is legal in the
            # same list as directly witnessed equipment.  It cannot create a
            # positive match or become an autonomous replacement target.
            continue
        candidate_fields.extend(port.field_ref for port in zone_ports)
    complete = complete and bool(candidate_fields)

    boundary_by_node: dict[str, list[FieldRef]] = defaultdict(list)
    for field in boundary_node_fields:
        if field.normalized_value:
            boundary_by_node[field.normalized_value].append(field)
    candidate_by_node: dict[str, list[FieldRef]] = defaultdict(list)
    for field in candidate_fields:
        if field.normalized_value:
            candidate_by_node[field.normalized_value].append(field)
    matched_nodes = sorted(set(boundary_by_node) & set(candidate_by_node))
    evidence_ids = sorted({
        field.field_id
        for node in matched_nodes
        for field in (*boundary_by_node[node], *candidate_by_node[node])
    })
    return EvidenceScore(
        candidate_id=zone_list.relation_id,
        score=len(matched_nodes),
        evidence_field_ids=tuple(evidence_ids),
        complete=complete,
    )


def _extract_zone_relations(
    objects: tuple[ObjectRef, ...],
    index: _ObjectIndex,
    zone_lists: tuple[ZoneEquipmentListRelation, ...],
    ports_by_object_id: dict[str, tuple],
) -> tuple[ZoneEquipmentRelation, ...]:
    rows: list[ZoneEquipmentRelation] = []
    for source in objects:
        declared_field = source.field(2)
        if (
            source.normalized_object_type != "zonehvac:equipmentconnections"
            or declared_field is None
        ):
            continue
        provenance_fields: list[FieldRef] = []
        boundary_node_fields: list[FieldRef] = []
        for position in (3, 4, 5, 6):
            field = source.field(position)
            if field is None or not field.raw_value.strip():
                continue
            provenance, nodes = _expand_node_field(field, index)
            provenance_fields.extend(provenance)
            boundary_node_fields.extend(nodes)
        evidence = tuple(sorted(
            (
                _zone_candidate_evidence(
                    zone_list,
                    tuple(boundary_node_fields),
                    index,
                    ports_by_object_id,
                )
                for zone_list in zone_lists
            ),
            key=lambda item: (
                -item.score,
                not item.complete,
                item.candidate_id,
            ),
        ))
        rows.append(ZoneEquipmentRelation(
            relation_id=f"zone-equipment:{source.object_id}",
            connection_ref=source,
            declared_list_field=declared_field,
            boundary_fields=tuple(provenance_fields),
            boundary_node_fields=tuple(boundary_node_fields),
            declared_list_ref=index.unique(
                "ZoneHVAC:EquipmentList", declared_field.raw_value,
            ),
            ranked_list_evidence=evidence,
            evidence_complete=all(
                item.complete for item in evidence if item.score > 0
            ),
        ))
    return tuple(rows)


def _extract_controller_relations(
    objects: tuple[ObjectRef, ...],
    index: _ObjectIndex,
) -> tuple[ControllerRelation, ...]:
    rows: list[ControllerRelation] = []
    for source in objects:
        list_field = source.field(2)
        if source.normalized_object_type != "airloophvac" or list_field is None:
            continue
        controller_list = index.unique(
            "AirLoopHVAC:ControllerList", list_field.raw_value,
        )
        rows.append(ControllerRelation(
            relation_id=f"controller-ownership:{source.object_id}",
            owner_ref=source,
            controller_list_field=list_field,
            controller_list_ref=controller_list,
            members=(
                _typed_references(controller_list, start=2)
                if controller_list is not None else ()
            ),
        ))
    return tuple(rows)


def _all_typed_references(
    branches: tuple[BranchPath, ...],
    connector_pairs: tuple[ConnectorPair, ...],
    air_paths: tuple[AirPathRelation, ...],
    equipment_paths: tuple[EquipmentPathRelation, ...],
    zone_lists: tuple[ZoneEquipmentListRelation, ...],
    controllers: tuple[ControllerRelation, ...],
) -> Iterable[tuple[str, str]]:
    for branch in branches:
        for member in branch.members:
            yield member.object_type, member.object_name
    for pair in connector_pairs:
        for member in pair.declared_members:
            yield member.object_type, member.object_name
    for path in air_paths:
        for member in path.members:
            yield member.object_type, member.object_name
    for path in equipment_paths:
        for member in path.members:
            yield member.object_type, member.object_name
    for zone_list in zone_lists:
        for member in zone_list.members:
            yield member.type_field.raw_value, member.name_field.raw_value
    for controller in controllers:
        for member in controller.members:
            yield member.object_type, member.object_name


def _build_identities(
    objects: tuple[ObjectRef, ...],
    index: _ObjectIndex,
    references: Iterable[tuple[str, str]],
) -> tuple[TypedIdentity, ...]:
    raw_by_key: dict[tuple[str, str], tuple[str, str]] = {}
    for obj in objects:
        raw_by_key.setdefault(
            (obj.normalized_object_type, obj.normalized_name),
            (obj.raw_object_type, obj.raw_name),
        )
    for object_type, object_name in references:
        raw_by_key.setdefault(
            (canonical(object_type), canonical(object_name)),
            (object_type, object_name),
        )

    rows: list[TypedIdentity] = []
    for type_key, name_key in sorted(raw_by_key):
        raw_type, raw_name = raw_by_key[(type_key, name_key)]
        matches = index.resolve(raw_type, raw_name)
        status = (
            IdentityStatus.RESOLVED if len(matches) == 1
            else IdentityStatus.AMBIGUOUS if len(matches) > 1
            else IdentityStatus.UNRESOLVED
        )
        rows.append(TypedIdentity(
            object_type=raw_type,
            object_name=raw_name,
            normalized_object_type=type_key,
            normalized_object_name=name_key,
            status=status,
            object_ids=tuple(obj.object_id for obj in matches),
        ))
    return tuple(rows)


def build_model_ir(
    document: IDFDocument,
    idd: IDDSchema,
    *,
    port_registry: PortRegistry = PRODUCTION_PORT_REGISTRY,
) -> ModelIR:
    """构建完整、target-free、不可变的 canonical relation snapshot。"""

    objects = tuple(object_ref_from_idf(obj, idd) for obj in document.objects)
    index = _ObjectIndex(objects)

    ports = []
    unsupported_port_fields = []
    extraction_issues: list[str] = []
    extraction_issues_by_object_id: dict[str, tuple[str, ...]] = {}
    for parsed, source in zip(document.objects, objects):
        if idd.get(parsed.object_type) is None:
            continue
        extraction = extract_ports(parsed, idd, registry=port_registry)
        ports.extend(extraction.ports)
        unsupported_port_fields.extend(extraction.unregistered_node_fields)
        extraction_issues_by_object_id[source.object_id] = extraction.issues
        extraction_issues.extend(
            f"{source.object_id}:{issue}" for issue in extraction.issues
        )
    ports_by_object_id: dict[str, tuple] = defaultdict(tuple)
    mutable_ports: dict[str, list] = defaultdict(list)
    for port in ports:
        mutable_ports[port.object_id].append(port)
    ports_by_object_id = {
        object_id: tuple(values) for object_id, values in mutable_ports.items()
    }
    declared_version = _normalize_version(document.version)
    idd_version = _normalize_version(idd.version)
    version_compatible = not declared_version or declared_version == idd_version
    if version_compatible:
        flow_projections = build_flow_projections(
            objects,
            tuple(ports),
            idd_version=idd.version,
            extraction_issues_by_object_id=extraction_issues_by_object_id,
        )
    else:
        flow_projections = ()
        extraction_issues.append(
            f"document_idd_version_mismatch:{declared_version}:{idd_version}"
        )

    branches = _extract_branches(objects)
    branch_lists = _extract_branch_lists(objects)
    connectors = _extract_connectors(objects)
    connector_pairs = _extract_connector_pairs(objects, index, connectors)
    loop_sides = _extract_loop_sides(objects)
    air_paths = _extract_air_paths(objects)
    equipment_paths = _extract_equipment_paths(objects, index)
    zone_lists = _extract_zone_lists(objects)
    zone_relations = _extract_zone_relations(
        objects, index, zone_lists, ports_by_object_id,
    )
    controller_relations = _extract_controller_relations(objects, index)
    identities = _build_identities(
        objects,
        index,
        _all_typed_references(
            branches,
            connector_pairs,
            air_paths,
            equipment_paths,
            zone_lists,
            controller_relations,
        ),
    )

    return ModelIR(
        schema_version=IR_SCHEMA_VERSION,
        document_sha256=document.sha256,
        declared_version=document.version,
        idd_version=idd.version,
        idd_sha256=idd.sha256,
        objects=objects,
        identities=identities,
        ports=tuple(ports),
        flow_projections=flow_projections,
        unsupported_port_fields=tuple(unsupported_port_fields),
        branches=branches,
        branch_lists=branch_lists,
        connectors=connectors,
        connector_pairs=connector_pairs,
        loop_sides=loop_sides,
        air_paths=air_paths,
        equipment_paths=equipment_paths,
        zone_equipment_lists=zone_lists,
        zone_relations=zone_relations,
        controller_relations=controller_relations,
        parse_issues=document.issues,
        extraction_issues=tuple(extraction_issues),
    )


__all__ = ["IR_SCHEMA_VERSION", "build_model_ir"]
