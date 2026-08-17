"""记录 Formal Final 冻结 mutation operator registry。

registry_payload(): 序列化方法冻结前已经存在的 operator frontier。

每个条目均引用 Formal Final 任务前已经开发的 mutation semantics；本模块只
选择并记录既有 support frontier，不增加错误类型。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json


@dataclass(frozen=True, slots=True)
class OperatorSpec:
    operator_id: str
    relation_class: str
    fault_stratum: str
    expected_contract: str
    source_module: str
    precondition: str
    mutation_semantics: str
    oracle_semantics: str
    repair_target: bool
    safe_abstention_target: bool


def _spec(
    operator_id: str,
    relation_class: str,
    fault_stratum: str,
    expected_contract: str,
    source_module: str,
    precondition: str,
    mutation_semantics: str,
    oracle_semantics: str,
    *,
    repair_target: bool = True,
    safe_abstention_target: bool = False,
) -> OperatorSpec:
    return OperatorSpec(
        operator_id=operator_id,
        relation_class=relation_class,
        fault_stratum=fault_stratum,
        expected_contract=expected_contract,
        source_module=source_module,
        precondition=precondition,
        mutation_semantics=mutation_semantics,
        oracle_semantics=oracle_semantics,
        repair_target=repair_target,
        safe_abstention_target=safe_abstention_target,
    )


V21 = "idfrepair.semantic_graph_v2_benchmark.operators"
V22 = "idfrepair.semantic_graph_v22_benchmark.operators"


OPERATOR_SPECS = (
    _spec("branch_wrong_typed_reference", "branch_path", "single", "AUTO_REPAIR", V21,
          "typed Branch member has a direct supported endpoint witness and a foreign donor exists",
          "replace member type and name with the frozen donor pair",
          "restore the clean typed member pair"),
    _spec("branch_wrong_inlet", "branch_path", "single", "AUTO_REPAIR", V21,
          "typed Branch member has a direct supported inlet/outlet witness",
          "replace its inlet with a foreign clean Branch node",
          "restore the clean inlet"),
    _spec("branch_wrong_outlet", "branch_path", "single", "AUTO_REPAIR", V21,
          "typed Branch member has a direct supported inlet/outlet witness",
          "replace its outlet with a foreign clean Branch node",
          "restore the clean outlet"),
    _spec("branch_member_order", "branch_path", "single", "AUTO_REPAIR", V21,
          "a Branch has adjacent members",
          "swap the adjacent four-field member groups",
          "restore clean semantic member order"),
    _spec("splitter_wrong_parallel_member", "loop_connector", "single", "AUTO_REPAIR", V21,
          "Connector:Splitter has a replaceable parallel Branch member",
          "replace one parallel member with a foreign Branch",
          "restore clean parallel membership"),
    _spec("mixer_wrong_parallel_member", "loop_connector", "single", "AUTO_REPAIR", V21,
          "Connector:Mixer has a replaceable parallel Branch member",
          "replace one parallel member with a foreign Branch",
          "restore clean parallel membership"),
    _spec("branchlist_wrong_member", "loop_connector", "single", "AUTO_REPAIR", V21,
          "BranchList has a foreign Branch donor",
          "replace one declared BranchList member",
          "restore clean BranchList set/boundary semantics"),
    _spec("branchlist_boundary_swap", "loop_connector", "single", "AUTO_REPAIR", V21,
          "BranchList has at least inlet, middle, and outlet members",
          "swap inlet boundary and first middle member",
          "restore clean boundary/order semantics"),
    _spec("connectorlist_typed_member_mismatch", "loop_connector", "single", "AUTO_REPAIR", V21,
          "same-type Connector donor exists",
          "replace ConnectorList member name",
          "restore clean typed Connector identity"),
    _spec("loop_side_connectorlist_mismatch", "loop_connector", "single", "AUTO_REPAIR", V21,
          "Plant/Condenser loop side and foreign ConnectorList exist",
          "replace loop-side ConnectorList ownership",
          "restore clean loop-side ownership"),
    _spec("zone_list_ownership_mismatch", "zone_equipment", "single", "AUTO_REPAIR", V21,
          "multiple ZoneHVAC:EquipmentList identities exist",
          "replace a ZoneHVAC:EquipmentConnections list reference",
          "restore clean one-to-one list ownership"),
    _spec("zone_typed_member_mismatch", "zone_equipment", "single", "AUTO_REPAIR", V21,
          "same-type zone equipment donor exists",
          "replace EquipmentList member name",
          "restore clean typed zone member identity"),
    _spec("v22_supplypath_member_name_mismatch", "air_path", "single", "AUTO_REPAIR", V22,
          "same-type SupplyPath compound member donor exists",
          "replace the declared member name",
          "restore clean SupplyPath typed member"),
    _spec("v22_supplypath_type_name_mismatch", "air_path", "single", "AUTO_REPAIR", V22,
          "alternate admitted SupplyPath compound type/name exists",
          "replace declared type and name together",
          "restore clean SupplyPath typed member"),
    _spec("v22_returnpath_member_name_mismatch", "air_path", "single", "AUTO_REPAIR", V22,
          "same-type ReturnPath compound member donor exists",
          "replace the declared member name",
          "restore clean ReturnPath typed member"),
    _spec("v22_returnpath_type_name_mismatch", "air_path", "single", "AUTO_REPAIR", V22,
          "alternate admitted ReturnPath compound type/name exists",
          "replace declared type and name together",
          "restore clean ReturnPath typed member"),
    _spec("v22_oa_member_name_mismatch", "outdoor_air_path", "single", "AUTO_REPAIR", V22,
          "normal-context admitted OA member has same-type donor",
          "replace the declared member name",
          "restore clean OA member identity"),
    _spec("v22_oa_type_name_mismatch", "outdoor_air_path", "single", "AUTO_REPAIR", V22,
          "normal-context admitted OA member has alternate admitted pair",
          "replace declared type and name together",
          "restore clean OA typed member"),
    _spec("v22_oa_member_order_mismatch", "outdoor_air_path", "single", "AUTO_REPAIR", V22,
          "normal-context OA list has at least two admitted members",
          "swap the first two typed member groups",
          "restore clean compound-flow order"),
    _spec("connected_branch_double", "branch_path", "connected_double", "AUTO_REPAIR", V21,
          "single-member Branch exposes two direct ports",
          "mutate inlet and outlet of the same Branch member",
          "restore two edits in one branch-member factor"),
    _spec("connected_loop_double", "loop_connector", "connected_double", "AUTO_REPAIR", V21,
          "parallel connector and BranchList atomics share one loop factor",
          "compose the two frozen atomics",
          "restore two edits in one loop conflict component"),
    _spec("connected_zone_list_member", "zone_equipment", "connected_double", "AUTO_REPAIR", V21,
          "list ownership and typed member share an explicit zone-port factor",
          "compose the two frozen zone atomics",
          "restore two edits in one zone ownership component"),
    _spec("independent_double", "cross_relation", "independent_double", "AUTO_REPAIR", V21,
          "two parallel-member atomics belong to distinct complete parent loops",
          "compose the two frozen atomics",
          "restore two edits in two independent conflict components"),
    _spec("ambiguous_branch_twin", "branch_path", "ambiguity", "ABSTAIN", V21,
          "a cloneable typed Branch member has a direct endpoint witness",
          "inject an equal endpoint twin and replace reference with unknown identity",
          "preserve the faulty artifact because two equal complete optima exist",
          safe_abstention_target=True),
    _spec("insufficient_evidence", "branch_path", "insufficient", "ABSTAIN", V21,
          "a multi-member Branch admits a duplicate design-intent mutation",
          "replace one member name with a sibling identity",
          "preserve input under insufficient/duplicate design evidence",
          safe_abstention_target=True),
    _spec("clean_control", "whole_model", "control", "VALID", V21,
          "qualified clean source",
          "no mutation",
          "byte-preserve clean artifact with no hard violation",
          repair_target=False),
)

BY_OPERATOR = {spec.operator_id: spec for spec in OPERATOR_SPECS}


def registry_payload() -> dict[str, object]:
    operators = [asdict(spec) for spec in OPERATOR_SPECS]
    encoded = json.dumps(
        operators, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema_version": "idfrepair.semantic-graph-formal-operator-registry.v1",
        "frozen_before_sealed_enumeration": True,
        "operator_count": len(operators),
        "identity_sha256": sha256(encoded).hexdigest(),
        "operators": operators,
    }


__all__ = ["BY_OPERATOR", "OPERATOR_SPECS", "OperatorSpec", "registry_payload"]
