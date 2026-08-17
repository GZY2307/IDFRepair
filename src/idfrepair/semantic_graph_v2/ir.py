"""定义 V2 canonical HVAC semantic IR 与精确 source provenance。

object_ref_from_idf(): 将一个 parsed IDF 对象转换为不可变 source record。
ModelIR: 保存同一 IDF snapshot 中的对象、端口和复合 HVAC 关系。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from idfrepair.io.idf import IDFObject, canonical
from idfrepair.knowledge.idd import IDDObject, IDDSchema


class _StringEnum(str, Enum):
    """为 Python 3.10 提供稳定的字符串枚举表示。"""

    def __str__(self) -> str:
        return self.value


class IdentityStatus(_StringEnum):
    """表示一个 typed object identity 在当前 snapshot 中的解析状态。"""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"


class PortRole(_StringEnum):
    """表示 registry 明确声明的组件端口方向。"""

    INLET = "INLET"
    OUTLET = "OUTLET"
    NODE_REFERENCE = "NODE_REFERENCE"


class FluidMedium(_StringEnum):
    """表示一个端口所属的 HVAC network domain。"""

    AIR = "AIR"
    WATER = "WATER"
    STEAM = "STEAM"
    REFRIGERANT = "REFRIGERANT"
    GENERIC = "GENERIC"


class PortApplicability(_StringEnum):
    """表示 explicit port rule 对一个对象字段的支持程度。"""

    SUPPORTED_EXACT = "SUPPORTED_EXACT"
    SUPPORTED_MULTI_PORT = "SUPPORTED_MULTI_PORT"
    UNSUPPORTED_AMBIGUOUS_ROLE = "UNSUPPORTED_AMBIGUOUS_ROLE"
    UNSUPPORTED_NO_ROLE = "UNSUPPORTED_NO_ROLE"


class FlowTopologyForm(_StringEnum):
    """表示 atomic ports 之上的 directed flow topology。"""

    DIRECT = "DIRECT"
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    MULTI_CIRCUIT = "MULTI_CIRCUIT"
    COUPLED_MULTI_STREAM = "COUPLED_MULTI_STREAM"


class FlowTraversalRole(_StringEnum):
    """区分 relation traversal 使用的主流路与保留的辅助流路。"""

    PRIMARY = "PRIMARY"
    AUXILIARY = "AUXILIARY"


class FlowStreamRole(_StringEnum):
    """为 projection registry 提供封闭、可审计的 stream/circuit roles。"""

    DIRECT = "direct"
    DISTRIBUTION = "distribution"
    RETURN = "return"
    SUPPLY = "supply"
    EXHAUST = "exhaust"
    SECONDARY = "secondary"
    OUTDOOR_TO_MIXED = "outdoor_to_mixed"
    RETURN_TO_RELIEF = "return_to_relief"


class ProjectionApplicability(_StringEnum):
    """表示 compound projection 是否拥有完整的 source-backed ports。"""

    SUPPORTED_COMPLETE = "SUPPORTED_COMPLETE"
    INCOMPLETE_MISSING_PORT = "INCOMPLETE_MISSING_PORT"
    UNSUPPORTED_RULE_IDENTITY = "UNSUPPORTED_RULE_IDENTITY"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"


class ZoneSideRole(_StringEnum):
    """表示端口相对于 Zone EquipmentConnections boundary 的角色。"""

    NONE = "NONE"
    ZONE_INLET = "ZONE_INLET"
    ZONE_EXHAUST = "ZONE_EXHAUST"
    ZONE_RETURN = "ZONE_RETURN"
    ZONE_AIR = "ZONE_AIR"


class ConnectorKind(_StringEnum):
    """表示 hydronic connector 的类型。"""

    SPLITTER = "SPLITTER"
    MIXER = "MIXER"


class LoopSideKind(_StringEnum):
    """表示 Plant/Condenser loop 的供给侧或需求侧。"""

    SUPPLY = "SUPPLY"
    DEMAND = "DEMAND"


class OutdoorAirSystemContext(_StringEnum):
    """表示 OA system 是否由 DedicatedOutdoorAirSystem 拥有。"""

    NORMAL = "NORMAL"
    DEDICATED = "DEDICATED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class FieldRef:
    """保存一个 IDF 字段的值、IDD 身份与精确 source span。"""

    object_index: int
    object_type: str
    object_name: str
    field_index: int
    field_token: str
    field_name: str
    raw_value: str
    normalized_value: str
    start: int
    end: int
    extensible_ordinal: int | None = None

    @property
    def field_id(self) -> str:
        """返回 snapshot-local 的稳定字段身份。"""

        return f"object:{self.object_index}:field:{self.field_index}"


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """保存一个 IDF object occurrence 及其有序字段。"""

    object_id: str
    object_index: int
    raw_object_type: str
    normalized_object_type: str
    raw_name: str
    normalized_name: str
    start: int
    end: int
    fields: tuple[FieldRef, ...]

    def field(self, index: int) -> FieldRef | None:
        """按 1-based index 返回字段，不对缺失 extensible 字段猜值。"""

        if 1 <= index <= len(self.fields):
            return self.fields[index - 1]
        return None


@dataclass(frozen=True, slots=True)
class TypedIdentity:
    """记录一个 typed name lookup 的全部 candidate occurrences。"""

    object_type: str
    object_name: str
    normalized_object_type: str
    normalized_object_name: str
    status: IdentityStatus
    object_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PortRef:
    """记录由 explicit registry rule 证明的 typed HVAC port fact。"""

    port_id: str
    object_id: str
    field_ref: FieldRef
    node_name: str
    normalized_node_name: str
    role: PortRole
    medium: FluidMedium
    applicability: PortApplicability
    port_group: str
    zone_side_role: ZoneSideRole
    rule_id: str
    rule_version: str


@dataclass(frozen=True, slots=True)
class FlowTransition:
    """记录一个 source-backed directed transition 或一对多/多对一 fact。"""

    transition_id: str
    object_ref: ObjectRef
    inlet_ports: tuple[PortRef, ...]
    outlet_ports: tuple[PortRef, ...]
    medium: FluidMedium
    stream: FlowStreamRole
    circuit_id: str
    traversal_role: FlowTraversalRole
    rule_id: str
    rule_version: str
    applicability: ProjectionApplicability

    def __post_init__(self) -> None:
        ports = (*self.inlet_ports, *self.outlet_ports)
        if not self.rule_id or not self.rule_version or not self.circuit_id:
            raise ValueError("flow_transition_identity")
        if not isinstance(self.stream, FlowStreamRole):
            raise ValueError("flow_transition_stream_role")
        if any(port.object_id != self.object_ref.object_id for port in ports):
            raise ValueError("flow_transition_cross_object_port")
        if any(port.medium is not self.medium for port in ports):
            raise ValueError("flow_transition_mixed_medium")
        if any(port.role is not PortRole.INLET for port in self.inlet_ports):
            raise ValueError("flow_transition_inlet_role")
        if any(port.role is not PortRole.OUTLET for port in self.outlet_ports):
            raise ValueError("flow_transition_outlet_role")
        if any(port.rule_version != self.rule_version for port in ports):
            raise ValueError("flow_transition_port_version_mismatch")
        port_ids = tuple(port.port_id for port in ports)
        if len(port_ids) != len(set(port_ids)):
            raise ValueError("flow_transition_duplicate_port")
        if (
            self.applicability is ProjectionApplicability.SUPPORTED_COMPLETE
            and (not self.inlet_ports or not self.outlet_ports)
        ):
            raise ValueError("complete_flow_transition_cardinality")

    @property
    def complete(self) -> bool:
        """Derive transition completeness from status and exact evidence."""

        nodes = tuple(
            port.normalized_node_name
            for port in (*self.inlet_ports, *self.outlet_ports)
        )
        return (
            self.applicability is ProjectionApplicability.SUPPORTED_COMPLETE
            and bool(self.inlet_ports)
            and bool(self.outlet_ports)
            and all(nodes)
            and len(nodes) == len(set(nodes))
        )

    @property
    def field_refs(self) -> tuple[FieldRef, ...]:
        """返回参与该 transition 的 exact source fields。"""

        return tuple(
            port.field_ref for port in (*self.inlet_ports, *self.outlet_ports)
        )


@dataclass(frozen=True, slots=True)
class CompoundFlowProjection:
    """把同一 object 的 atomic ports 投影为显式 directed topology。"""

    projection_id: str
    object_ref: ObjectRef
    topology_form: FlowTopologyForm
    transitions: tuple[FlowTransition, ...]
    rule_id: str
    rule_version: str
    applicability: ProjectionApplicability
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id or not self.rule_version:
            raise ValueError("flow_projection_identity")
        transition_ids = tuple(row.transition_id for row in self.transitions)
        if len(transition_ids) != len(set(transition_ids)):
            raise ValueError("flow_projection_duplicate_transition")
        if any(row.object_ref != self.object_ref for row in self.transitions):
            raise ValueError("flow_projection_cross_object_transition")
        if any(row.rule_version != self.rule_version for row in self.transitions):
            raise ValueError("flow_projection_rule_version_mismatch")
        if any(not row.rule_id.startswith(f"{self.rule_id}:") for row in self.transitions):
            raise ValueError("flow_projection_rule_identity_mismatch")
        port_ids = tuple(
            port.port_id
            for row in self.transitions
            for port in (*row.inlet_ports, *row.outlet_ports)
        )
        if len(port_ids) != len(set(port_ids)):
            raise ValueError("flow_projection_duplicate_port")
        if self.applicability is ProjectionApplicability.SUPPORTED_COMPLETE:
            nodes = tuple(
                port.normalized_node_name
                for row in self.transitions
                for port in (*row.inlet_ports, *row.outlet_ports)
            )
            if not all(nodes) or len(nodes) != len(set(nodes)):
                raise ValueError("complete_flow_projection_duplicate_node")
            if any(not row.complete for row in self.transitions):
                raise ValueError("complete_flow_projection_transition")
            if not self._topology_complete():
                raise ValueError("complete_flow_projection_topology")

    def _topology_complete(self) -> bool:
        if not self.transitions:
            return False
        cardinalities = tuple(
            (len(row.inlet_ports), len(row.outlet_ports))
            for row in self.transitions
        )
        primary_count = sum(
            row.traversal_role is FlowTraversalRole.PRIMARY
            for row in self.transitions
        )
        stream_count = len({row.stream for row in self.transitions})
        if self.topology_form is FlowTopologyForm.DIRECT:
            return (
                len(cardinalities) == 1
                and cardinalities[0] == (1, 1)
                and primary_count == 1
            )
        if self.topology_form is FlowTopologyForm.SPLIT:
            return (
                len(cardinalities) == 1
                and cardinalities[0][0] == 1
                and cardinalities[0][1] >= 1
                and primary_count == 1
            )
        if self.topology_form is FlowTopologyForm.MERGE:
            return (
                len(cardinalities) == 1
                and cardinalities[0][0] >= 1
                and cardinalities[0][1] == 1
                and primary_count == 1
            )
        return (
            len(cardinalities) >= 2
            and all(cardinality == (1, 1) for cardinality in cardinalities)
            and primary_count == 1
            and stream_count == len(cardinalities)
        )

    @property
    def complete(self) -> bool:
        """只有所有 required transition 均完整时才可用于 SAFE_AUTO。"""

        return (
            self.applicability is ProjectionApplicability.SUPPORTED_COMPLETE
            and all(row.complete for row in self.transitions)
            and self._topology_complete()
            and not self.issues
        )

    @property
    def primary_transitions(self) -> tuple[FlowTransition, ...]:
        """返回 relation topology traversal 可使用的主流路。"""

        return tuple(
            row for row in self.transitions
            if row.traversal_role is FlowTraversalRole.PRIMARY
        )


@dataclass(frozen=True, slots=True)
class OrderedTypedReference:
    """记录 container 中一个有序 type/name reference slot。"""

    ordinal: int
    type_field: FieldRef
    name_field: FieldRef

    @property
    def object_type(self) -> str:
        return self.type_field.raw_value

    @property
    def object_name(self) -> str:
        return self.name_field.raw_value


@dataclass(frozen=True, slots=True)
class BranchMember:
    """表示 Branch 中一个有序 component tuple。"""

    ordinal: int
    type_field: FieldRef
    name_field: FieldRef
    inlet_field: FieldRef
    outlet_field: FieldRef

    @property
    def object_type(self) -> str:
        return self.type_field.raw_value

    @property
    def object_name(self) -> str:
        return self.name_field.raw_value

    @property
    def inlet_node(self) -> str:
        return self.inlet_field.raw_value

    @property
    def outlet_node(self) -> str:
        return self.outlet_field.raw_value


@dataclass(frozen=True, slots=True)
class BranchPath:
    """表示一个保留完整 member order 的 Branch relation。"""

    relation_id: str
    object_ref: ObjectRef
    members: tuple[BranchMember, ...]


@dataclass(frozen=True, slots=True)
class BranchListRelation:
    """表示 BranchList 的有序 branch-name fields。"""

    relation_id: str
    object_ref: ObjectRef
    member_fields: tuple[FieldRef, ...]

    @property
    def normalized_members(self) -> tuple[str, ...]:
        return tuple(field.normalized_value for field in self.member_fields)


@dataclass(frozen=True, slots=True)
class ConnectorRelation:
    """表示 Splitter 或 Mixer 的 boundary 与 ordered parallel branches。"""

    relation_id: str
    kind: ConnectorKind
    object_ref: ObjectRef
    boundary_field: FieldRef
    parallel_fields: tuple[FieldRef, ...]

    @property
    def parallel_branch_names(self) -> tuple[str, ...]:
        return tuple(field.normalized_value for field in self.parallel_fields)

    @property
    def parallel_branch_set(self) -> frozenset[str]:
        return frozenset(self.parallel_branch_names)


@dataclass(frozen=True, slots=True)
class ConnectorPair:
    """表示 ConnectorList 声明及其 resolved Splitter/Mixer relation。"""

    relation_id: str
    object_ref: ObjectRef
    declared_members: tuple[OrderedTypedReference, ...]
    splitter: ConnectorRelation | None
    mixer: ConnectorRelation | None


@dataclass(frozen=True, slots=True)
class LoopSideRelation:
    """表示 loop side 对 BranchList/ConnectorList 的 declared ownership。"""

    relation_id: str
    object_ref: ObjectRef
    side: LoopSideKind
    inlet_field: FieldRef
    outlet_field: FieldRef
    branch_list_field: FieldRef
    connector_list_field: FieldRef


@dataclass(frozen=True, slots=True)
class AirPathRelation:
    """表示 SupplyPath 或 ReturnPath boundary 与 ordered members。"""

    relation_id: str
    object_ref: ObjectRef
    boundary_field: FieldRef
    members: tuple[OrderedTypedReference, ...]
    reference_shape_complete: bool = True


@dataclass(frozen=True, slots=True)
class EquipmentPathRelation:
    """表示 OutdoorAirSystem ownership 与 ordered EquipmentList members。"""

    relation_id: str
    system_ref: ObjectRef
    equipment_list_ref: ObjectRef | None
    equipment_list_field: FieldRef
    members: tuple[OrderedTypedReference, ...]
    reference_shape_complete: bool = True
    context: OutdoorAirSystemContext = OutdoorAirSystemContext.NORMAL
    context_owner_refs: tuple[ObjectRef, ...] = ()
    controller_list_ref: ObjectRef | None = None
    outdoor_air_controller_ref: ObjectRef | None = None
    controller_node_fields: tuple[FieldRef, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceScore:
    """记录一个 inferred relation candidate 的非替代性证据。"""

    candidate_id: str
    score: int
    evidence_field_ids: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class ZoneEquipmentMember:
    """表示 Zone EquipmentList 中一个保留 ordinal 的 typed member。"""

    ordinal: int
    type_field: FieldRef
    name_field: FieldRef
    cooling_sequence_field: FieldRef | None
    heating_sequence_field: FieldRef | None

    @property
    def object_type(self) -> str:
        return self.type_field.raw_value

    @property
    def object_name(self) -> str:
        return self.name_field.raw_value


@dataclass(frozen=True, slots=True)
class ZoneEquipmentListRelation:
    """表示一个独立于当前 ownership 的 ordered EquipmentList relation。"""

    relation_id: str
    object_ref: ObjectRef
    members: tuple[ZoneEquipmentMember, ...]


@dataclass(frozen=True, slots=True)
class ZoneEquipmentRelation:
    """表示 zone boundary、declared list 与独立 ranked evidence。"""

    relation_id: str
    connection_ref: ObjectRef
    declared_list_field: FieldRef
    boundary_fields: tuple[FieldRef, ...]
    boundary_node_fields: tuple[FieldRef, ...]
    declared_list_ref: ObjectRef | None
    ranked_list_evidence: tuple[EvidenceScore, ...]
    evidence_complete: bool


@dataclass(frozen=True, slots=True)
class ControllerRelation:
    """表示 AirLoop ControllerList ownership 的 detect-only relation facts。"""

    relation_id: str
    owner_ref: ObjectRef
    controller_list_field: FieldRef
    controller_list_ref: ObjectRef | None
    members: tuple[OrderedTypedReference, ...]


RelationRecord: TypeAlias = (
    BranchPath
    | BranchListRelation
    | ConnectorRelation
    | ConnectorPair
    | LoopSideRelation
    | AirPathRelation
    | EquipmentPathRelation
    | ZoneEquipmentListRelation
    | ZoneEquipmentRelation
    | ControllerRelation
)


@dataclass(frozen=True, slots=True)
class ModelIR:
    """保存一个 IDF/IDD snapshot 的 canonical relation facts。"""

    schema_version: str
    document_sha256: str
    declared_version: str
    idd_version: str
    idd_sha256: str
    objects: tuple[ObjectRef, ...] = ()
    identities: tuple[TypedIdentity, ...] = ()
    ports: tuple[PortRef, ...] = ()
    unsupported_port_fields: tuple[FieldRef, ...] = ()
    branches: tuple[BranchPath, ...] = ()
    branch_lists: tuple[BranchListRelation, ...] = ()
    connectors: tuple[ConnectorRelation, ...] = ()
    connector_pairs: tuple[ConnectorPair, ...] = ()
    loop_sides: tuple[LoopSideRelation, ...] = ()
    air_paths: tuple[AirPathRelation, ...] = ()
    equipment_paths: tuple[EquipmentPathRelation, ...] = ()
    zone_equipment_lists: tuple[ZoneEquipmentListRelation, ...] = ()
    zone_relations: tuple[ZoneEquipmentRelation, ...] = ()
    controller_relations: tuple[ControllerRelation, ...] = ()
    parse_issues: tuple[str, ...] = ()
    extraction_issues: tuple[str, ...] = ()
    flow_projections: tuple[CompoundFlowProjection, ...] = ()

    def objects_of_type(self, object_type: str) -> tuple[ObjectRef, ...]:
        """返回一个 canonical object type 的全部 occurrences。"""

        key = canonical(object_type)
        return tuple(obj for obj in self.objects if obj.normalized_object_type == key)

    def resolve_identity(
        self, object_type: str, object_name: str,
    ) -> tuple[ObjectRef, ...]:
        """按 type/name 返回全部 occurrences，保留 multiplicity。"""

        type_key = canonical(object_type)
        name_key = canonical(object_name)
        return tuple(
            obj for obj in self.objects
            if obj.normalized_object_type == type_key
            and obj.normalized_name == name_key
        )

    def ports_for(self, object_id: str) -> tuple[PortRef, ...]:
        """返回一个 object occurrence 的 registry-supported ports。"""

        return tuple(port for port in self.ports if port.object_id == object_id)

    def projections_for(self, object_id: str) -> tuple[CompoundFlowProjection, ...]:
        """返回一个 object occurrence 的全部 source-backed flow projections。"""

        return tuple(
            row for row in self.flow_projections
            if row.object_ref.object_id == object_id
        )

    def relation(self, relation_id: str) -> RelationRecord | None:
        """按 stable relation ID 返回一个复合 relation。"""

        groups = (
            self.branches, self.branch_lists, self.connectors,
            self.connector_pairs, self.loop_sides, self.air_paths,
            self.equipment_paths, self.zone_equipment_lists, self.zone_relations,
            self.controller_relations,
        )
        return next((row for group in groups for row in group if row.relation_id == relation_id), None)


def _extensible_ordinal(
    definition: IDDObject | None,
    field_index: int,
) -> int | None:
    """依据 begin-extensible field 与 group width 计算 1-based ordinal。"""

    if definition is None or not definition.extensible:
        return None
    start = definition.extensible_start
    if start is None or field_index < start:
        return None
    return ((field_index - start) // definition.extensible) + 1


def object_ref_from_idf(obj: IDFObject, idd: IDDSchema) -> ObjectRef:
    """将一个 parsed IDF object 转换为带 IDD/provenance 的 source record。"""

    definition = idd.get(obj.object_type)
    fields = []
    for field in obj.fields:
        field_def = (
            definition.semantic_field_at(field.index)
            if definition is not None else None
        )
        fields.append(FieldRef(
            object_index=obj.index,
            object_type=obj.object_type,
            object_name=obj.name,
            field_index=field.index,
            field_token=field_def.field_id if field_def is not None else f"A{field.index}",
            field_name=field_def.name if field_def is not None else f"A{field.index}",
            raw_value=field.value,
            normalized_value=canonical(field.value),
            start=field.start,
            end=field.end,
            extensible_ordinal=_extensible_ordinal(definition, field.index),
        ))
    return ObjectRef(
        object_id=f"object:{obj.index}",
        object_index=obj.index,
        raw_object_type=obj.object_type,
        normalized_object_type=canonical(obj.object_type),
        raw_name=obj.name,
        normalized_name=canonical(obj.name),
        start=obj.start,
        end=obj.end,
        fields=tuple(fields),
    )


__all__ = [
    "AirPathRelation",
    "BranchListRelation",
    "BranchMember",
    "BranchPath",
    "ConnectorKind",
    "ConnectorPair",
    "ConnectorRelation",
    "CompoundFlowProjection",
    "ControllerRelation",
    "EquipmentPathRelation",
    "EvidenceScore",
    "FieldRef",
    "FlowTopologyForm",
    "FlowStreamRole",
    "FlowTransition",
    "FlowTraversalRole",
    "FluidMedium",
    "IdentityStatus",
    "LoopSideKind",
    "LoopSideRelation",
    "ModelIR",
    "ObjectRef",
    "OutdoorAirSystemContext",
    "OrderedTypedReference",
    "PortApplicability",
    "PortRef",
    "PortRole",
    "ProjectionApplicability",
    "TypedIdentity",
    "ZoneEquipmentMember",
    "ZoneEquipmentListRelation",
    "ZoneEquipmentRelation",
    "ZoneSideRole",
    "object_ref_from_idf",
]
