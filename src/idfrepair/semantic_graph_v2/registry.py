"""声明 V2 whole-model constraints、证据类别与 admission state。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class RelationClass(_StringEnum):
    BRANCH_PATH = "BRANCH_PATH"
    LOOP_CONNECTOR = "LOOP_CONNECTOR"
    AIR_PATH = "AIR_PATH"
    OUTDOOR_AIR_PATH = "OUTDOOR_AIR_PATH"
    ZONE_EQUIPMENT = "ZONE_EQUIPMENT"
    CONTROL_TOPOLOGY = "CONTROL_TOPOLOGY"
    ZONE_PRIORITY = "ZONE_PRIORITY"


class EvidenceClass(_StringEnum):
    INTERNAL_HARD = "INTERNAL_HARD"
    INTERNAL_REDUNDANT = "INTERNAL_REDUNDANT"
    INTERNAL_HARD_REDUNDANT = "INTERNAL_HARD_REDUNDANT"
    INTERNAL_UNDERDETERMINED = "INTERNAL_UNDERDETERMINED"
    EXTERNAL_INTENT = "EXTERNAL_INTENT"
    NOT_SEMANTIC = "NOT_SEMANTIC"


class AdmissionStatus(_StringEnum):
    ADMIT_SAFE_AUTO = "ADMIT_SAFE_AUTO"
    ADMIT_DETECT_ONLY = "ADMIT_DETECT_ONLY"
    ADMIT_NEEDS_INPUT = "ADMIT_NEEDS_INPUT"
    REJECT_EXTERNAL_INTENT = "REJECT_EXTERNAL_INTENT"
    REJECT_NOT_ENOUGH_SUPPORT = "REJECT_NOT_ENOUGH_SUPPORT"
    REJECT_NOT_SEMANTIC = "REJECT_NOT_SEMANTIC"


@dataclass(frozen=True, slots=True)
class ConstraintSpec:
    """一个不含 benchmark selector 的 immutable constraint declaration。"""

    constraint_id: str
    relation_class: RelationClass
    evidence_class: EvidenceClass
    admission_status: AdmissionStatus
    scope_type: str
    evaluator_key: str
    candidate_generator_key: str
    semantic_equivalence_key: str
    latent_factor_kind: str
    evidence_note: str

    @property
    def hard(self) -> bool:
        return self.admission_status is AdmissionStatus.ADMIT_SAFE_AUTO


@dataclass(frozen=True, slots=True)
class ConstraintRegistry:
    specs: tuple[ConstraintSpec, ...]

    def __post_init__(self) -> None:
        identifiers = tuple(spec.constraint_id for spec in self.specs)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate_constraint_id")

    def get(self, constraint_id: str) -> ConstraintSpec | None:
        return next(
            (spec for spec in self.specs if spec.constraint_id == constraint_id),
            None,
        )


def _spec(
    constraint_id: str,
    relation_class: RelationClass,
    evidence_class: EvidenceClass,
    admission_status: AdmissionStatus,
    scope_type: str,
    evaluator_key: str,
    candidate_generator_key: str,
    semantic_equivalence_key: str,
    latent_factor_kind: str,
    evidence_note: str,
) -> ConstraintSpec:
    return ConstraintSpec(
        constraint_id=constraint_id,
        relation_class=relation_class,
        evidence_class=evidence_class,
        admission_status=admission_status,
        scope_type=scope_type,
        evaluator_key=evaluator_key,
        candidate_generator_key=candidate_generator_key,
        semantic_equivalence_key=semantic_equivalence_key,
        latent_factor_kind=latent_factor_kind,
        evidence_note=evidence_note,
    )


_DOCUMENTED_SPECS = (
    _spec(
        "V2-BRANCH-TYPED-IDENTITY-001", RelationClass.BRANCH_PATH,
        EvidenceClass.INTERNAL_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "branch_member", "branch_typed_identity", "branch_typed_identity",
        "typed_reference", "branch-member",
        "Exact endpoint pair and explicit component ports provide the independent copy.",
    ),
    _spec(
        "V2-BRANCH-ENDPOINT-002", RelationClass.BRANCH_PATH,
        EvidenceClass.INTERNAL_HARD_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "branch_member", "branch_endpoint", "branch_endpoint",
        "field_value", "branch-member",
        "Declared typed component ports and adjacent path continuity constrain both endpoints.",
    ),
    _spec(
        "V2-BRANCH-CONTINUITY-003", RelationClass.BRANCH_PATH,
        EvidenceClass.INTERNAL_HARD, AdmissionStatus.ADMIT_SAFE_AUTO,
        "branch_path", "branch_continuity", "branch_reorder",
        "ordered_path", "branch-path",
        "Only a unique directed ordering of existing member tuples is auto-repairable.",
    ),
    _spec(
        "V2-LOOP-PARALLEL-SET-004", RelationClass.LOOP_CONNECTOR,
        EvidenceClass.INTERNAL_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "connector_pair", "loop_parallel_set", "loop_parallel_set",
        "unordered_set", "connector-pair",
        "Splitter and Mixer parallel branch membership are reciprocal unordered sets.",
    ),
    _spec(
        "V2-LOOP-BRANCHLIST-SET-005", RelationClass.LOOP_CONNECTOR,
        EvidenceClass.INTERNAL_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "loop_side", "loop_branchlist_set", "loop_branchlist_set",
        "unordered_set", "loop-topology",
        "BranchList membership closes against the side's ConnectorList pair.",
    ),
    _spec(
        "V2-LOOP-BRANCHLIST-BOUNDARY-006", RelationClass.LOOP_CONNECTOR,
        EvidenceClass.INTERNAL_HARD_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "loop_side", "loop_branchlist_boundary", "loop_branchlist_boundary",
        "ordered_boundary", "loop-topology",
        "Splitter inlet and Mixer outlet identify BranchList boundary positions.",
    ),
    _spec(
        "V2-LOOP-SIDE-OWNERSHIP-007", RelationClass.LOOP_CONNECTOR,
        EvidenceClass.INTERNAL_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "loop_side", "loop_side_ownership", "loop_side_ownership",
        "structural_ownership", "loop-side",
        "Loop boundary and branch/connector closure select structural ownership.",
    ),
    _spec(
        "V2-CONNECTOR-TYPED-MEMBER-008", RelationClass.LOOP_CONNECTOR,
        EvidenceClass.INTERNAL_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "connector_pair", "connector_typed_member", "connector_typed_member",
        "typed_reference", "connector-pair",
        "The reciprocal connector and branch closure constrain a typed member.",
    ),
    _spec(
        "V2-AIRPATH-TYPED-MEMBER-009", RelationClass.AIR_PATH,
        EvidenceClass.INTERNAL_HARD_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "air_path", "airpath_typed_member", "airpath_typed_member",
        "directed_path", "air-path",
        "Complete version-bound split/merge topology selects typed AirPath members.",
    ),
    _spec(
        "V2-OA-EQUIPMENT-PATH-010", RelationClass.OUTDOOR_AIR_PATH,
        EvidenceClass.INTERNAL_HARD_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "equipment_path", "oa_equipment_path", "oa_equipment_path",
        "directed_path", "oa-equipment-path",
        "Complete controller-anchored primary and relief topology selects typed/order edits.",
    ),
    _spec(
        "V2-ZONE-LIST-OWNERSHIP-011", RelationClass.ZONE_EQUIPMENT,
        EvidenceClass.INTERNAL_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "zone_equipment", "zone_list_ownership", "zone_list_ownership",
        "zone_ownership", "zone-equipment-factor",
        "Only explicit zone-side ports contribute boundary evidence.",
    ),
    _spec(
        "V2-ZONE-TYPED-MEMBER-012", RelationClass.ZONE_EQUIPMENT,
        EvidenceClass.INTERNAL_REDUNDANT, AdmissionStatus.ADMIT_SAFE_AUTO,
        "zone_equipment_member", "zone_typed_member", "zone_typed_member",
        "typed_reference", "zone-equipment-factor",
        "Member identity is constrained by explicit zone-side ports and slot occupancy.",
    ),
    _spec(
        "V2-BRANCH-MISSING-MEMBER-101", RelationClass.BRANCH_PATH,
        EvidenceClass.INTERNAL_UNDERDETERMINED, AdmissionStatus.ADMIT_NEEDS_INPUT,
        "branch_path", "branch_missing_member", "", "none", "branch-path",
        "A path gap does not generally identify an object to insert.",
    ),
    _spec(
        "V2-BRANCH-DUPLICATE-MEMBER-102", RelationClass.BRANCH_PATH,
        EvidenceClass.INTERNAL_UNDERDETERMINED, AdmissionStatus.ADMIT_DETECT_ONLY,
        "branch_path", "branch_duplicate_member", "", "none", "branch-path",
        "Deletion can alter design intent, so duplicate membership is detect-only.",
    ),
    _spec(
        "V2-CONTROLLER-OWNERSHIP-103", RelationClass.CONTROL_TOPOLOGY,
        EvidenceClass.INTERNAL_REDUNDANT, AdmissionStatus.ADMIT_DETECT_ONLY,
        "controller_ownership", "controller_ownership", "", "none",
        "controller-ownership", "Control ownership remains diagnostic in V2.1.",
    ),
    _spec(
        "V2-CONTROLLER-ACTUATOR-104", RelationClass.CONTROL_TOPOLOGY,
        EvidenceClass.INTERNAL_UNDERDETERMINED,
        AdmissionStatus.REJECT_NOT_ENOUGH_SUPPORT, "controller_actuator", "", "",
        "none", "controller-actuator",
        "The corrupted actuator removes the evidence that identified the intended coil.",
    ),
    _spec(
        "V2-ZONE-PRIORITY-EQUALITY-901", RelationClass.ZONE_PRIORITY,
        EvidenceClass.EXTERNAL_INTENT, AdmissionStatus.REJECT_EXTERNAL_INTENT,
        "zone_equipment_list", "", "", "none", "zone-priority",
        "Cooling and heating/no-load sequences are independent official semantics.",
    ),
    _spec(
        "V2-CONTROLLER-SENSOR-EQUALITY-902", RelationClass.CONTROL_TOPOLOGY,
        EvidenceClass.NOT_SEMANTIC, AdmissionStatus.REJECT_NOT_SEMANTIC,
        "controller_sensor", "", "", "none", "controller-sensor",
        "A control sensor may legally be downstream of the controlled component.",
    ),
    _spec(
        "V2-PARALLEL-MIDDLE-ORDER-903", RelationClass.LOOP_CONNECTOR,
        EvidenceClass.EXTERNAL_INTENT, AdmissionStatus.REJECT_EXTERNAL_INTENT,
        "branch_list", "", "", "none", "loop-topology",
        "Connector enumeration is not a universal oracle for BranchList middle order.",
    ),
)


_DOCUMENTED_REGISTRY = ConstraintRegistry(_DOCUMENTED_SPECS)
_PRODUCTION_REGISTRY = ConstraintRegistry(tuple(
    spec for spec in _DOCUMENTED_SPECS
    if spec.admission_status in {
        AdmissionStatus.ADMIT_SAFE_AUTO,
        AdmissionStatus.ADMIT_DETECT_ONLY,
    }
))


def production_registry() -> ConstraintRegistry:
    """返回不含 rejected/needs-input probe 的 active scanner registry。"""

    return _PRODUCTION_REGISTRY


def documented_registry() -> ConstraintRegistry:
    """返回包含 rejected rationale 的完整 engineering registry。"""

    return _DOCUMENTED_REGISTRY


__all__ = [
    "AdmissionStatus",
    "ConstraintRegistry",
    "ConstraintSpec",
    "EvidenceClass",
    "RelationClass",
    "documented_registry",
    "production_registry",
]
