'''
验证 HVAC 候选的补丁范围、IDD 绑定和类型化图闭包。

validate_hvac_candidate(): 执行 HVAC 专用语义门禁。
'''

from __future__ import annotations

from typing import Any

from idfrepair.io.idf import changed_fields, parse_idf
from idfrepair.knowledge.hvac_graph import build_hvac_graph


def validate_hvac_candidate(
    before: str, after: str, candidate: Any, context: Any,
) -> tuple[bool, tuple[str, ...], dict[str, Any]]:
    '''
    验证 HVAC 候选仅修改声明字段，并使目标关系在同一版本 IDD 图中唯一闭合。

    :param before: 候选应用前的 IDF 正文。
    :param after: 候选应用后的临时 IDF 正文。
    :param candidate: 绑定输入和 IDD 身份的 HVAC 候选。
    :param context: 当前版本、IDD 和故障文档上下文。
    :return: 是否通过、拒绝原因和图验证明细。
    '''
    reasons: list[str] = []
    operation = candidate.operations[0]
    expected = ((
        operation.object_index,
        operation.field_index,
        operation.old_value,
        operation.new_value,
    ),)
    actual = changed_fields(before, after)
    if actual != expected:
        reasons.append("hvac_patch_scope_changed")
    if candidate.metadata.get("idd_sha256") != context.idd_sha256:
        reasons.append("hvac_idd_identity_mismatch")
    before_graph = build_hvac_graph(parse_idf(before), context.idd)
    after_graph = build_hvac_graph(parse_idf(after), context.idd)
    kind = str(candidate.metadata.get("validation_kind", ""))
    object_index = int(operation.object_index)
    field_index = int(operation.field_index)
    if kind == "hvac_typed_reference":
        edges = [
            edge for edge in after_graph["reference_edges"]
            if edge["object_index"] == object_index and edge["field_index"] == field_index
        ]
        if len(edges) != 1:
            reasons.append("hvac_typed_reference_not_unique")
        elif edge_list := str(candidate.metadata.get("object_list", "")):
            if edges[0]["object_list"].casefold() != edge_list.casefold():
                reasons.append("hvac_reference_class_changed")
    elif kind == "hvac_branch_component":
        relations = [
            row for row in after_graph["branch_relations"]
            if row["container_index"] == object_index
            and row["component_name_index"] == field_index
        ]
        if len(relations) != 1 or relations[0]["status"] != "OK":
            reasons.append("hvac_branch_endpoints_not_closed")
    elif kind == "hvac_equipment_reference":
        relations = [
            row for row in after_graph["equipment_relations"]
            if row["container_index"] == object_index
            and row["equipment_name_index"] == field_index
        ]
        if len(relations) != 1 or relations[0]["multiplicity"] != 1:
            reasons.append("hvac_equipment_reference_not_unique")
    elif kind == "hvac_node_reference":
        ports = [
            row for row in after_graph["ports"]
            if row["object_index"] == object_index and row["field_index"] == field_index
        ]
        if len(ports) != 1:
            reasons.append("hvac_node_port_missing")
        elif (
            ports[0]["role"] != candidate.metadata.get("role")
            or ports[0]["medium"] != candidate.metadata.get("medium")
        ):
            reasons.append("hvac_node_role_or_medium_changed")
    else:
        reasons.append("hvac_validation_kind_unknown")
    before_severe = len(before_graph["role_conflicts"]) + len(before_graph["multiplicity_issues"])
    after_severe = len(after_graph["role_conflicts"]) + len(after_graph["multiplicity_issues"])
    if after_severe > before_severe:
        reasons.append("hvac_graph_issue_introduced")
    return not reasons, tuple(reasons), {
        "changes": actual,
        "validation_kind": kind,
        "before_graph_issue_count": before_severe,
        "after_graph_issue_count": after_severe,
    }


__all__ = ["validate_hvac_candidate"]
