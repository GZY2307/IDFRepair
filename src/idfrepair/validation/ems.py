'''
验证 EMS 候选的有限补丁范围、符号闭包和调用角色。

validate_ems_candidate(): 执行 EMS 专用语义门禁。
'''

from __future__ import annotations

from typing import Any

from idfrepair.io.idf import canonical, changed_fields, parse_idf
from idfrepair.knowledge.ems import build_ems_calls, build_ems_symbols, normalize_ems_name, parse_ems


def _expected_changes(candidate: Any) -> tuple[tuple[int, int, str, str], ...]:
    '''按 IDF 文档顺序生成候选声明的精确字段变化。'''
    rows = (
        (
            int(operation.object_index),
            int(operation.field_index),
            str(operation.old_value),
            str(operation.new_value),
        )
        for operation in candidate.operations
        if operation.object_index is not None and operation.field_index is not None
        and operation.old_value is not None and operation.new_value is not None
    )
    return tuple(sorted(rows, key=lambda row: (row[0], row[1])))


def validate_ems_candidate(
    before: str, after: str, candidate: Any, context: Any,
) -> tuple[bool, tuple[str, ...], dict[str, Any]]:
    '''
    验证 EMS 补丁只修改声明字段，并在修复后满足对应符号或调用角色。

    :param before: 应用候选前的 IDF 正文。
    :param after: 应用候选后的临时 IDF 正文。
    :param candidate: 已绑定输入身份的有限 EMS 候选。
    :param context: 包含版本 RDD 和当前对象图的候选上下文。
    :return: 是否通过、拒绝原因和可审计验证明细。
    '''
    reasons: list[str] = []
    actual = tuple(sorted(changed_fields(before, after), key=lambda row: (row[0], row[1])))
    expected = _expected_changes(candidate)
    if actual != expected:
        reasons.append("ems_patch_scope_changed")
    before_parse = parse_ems(before)
    after_parse = parse_ems(after)
    if len(after_parse["issues"]) > len(before_parse["issues"]):
        reasons.append("ems_parser_issue_introduced")
    kind = str(candidate.metadata.get("validation_kind", ""))
    source = normalize_ems_name(str(candidate.metadata.get("source_symbol", "")))
    target = normalize_ems_name(str(candidate.metadata.get("target_symbol", "")))
    details: dict[str, Any] = {
        "changes": actual,
        "validation_kind": kind,
        "source_symbol": source,
        "target_symbol": target,
    }
    if kind == "ems_symbol":
        symbols = build_ems_symbols(after)
        unresolved = {
            row["normalized_symbol"]: row for row in symbols["undefined_symbols"]
        }
        definitions = tuple(symbols["global_symbols"].get(target, ()))
        if source in unresolved:
            reasons.append("ems_source_symbol_still_unresolved")
        if target in unresolved or len(definitions) != 1:
            reasons.append("ems_target_definition_missing_or_ambiguous")
        details["target_definition_count"] = len(definitions)
    elif kind == "ems_call":
        graph = build_ems_calls(after)
        matching_issues = [
            row for row in (*graph["unresolved_calls"], *graph["ambiguous_calls"], *graph["call_role_conflicts"])
            if row.get("normalized_target") in {source, target}
        ]
        expected_kind = str(candidate.metadata.get("expected_kind", ""))
        resolved = [
            edge for edge in graph["edges"]
            if normalize_ems_name(str(edge["resolved_target_name"])) == target
            and edge["expected_kind"] == expected_kind
        ]
        if matching_issues:
            reasons.append("ems_callable_not_uniquely_resolved")
        if len(resolved) < int(candidate.metadata.get("source_occurrence_count", 1)):
            reasons.append("ems_call_site_coverage_incomplete")
        details.update({"resolved_call_count": len(resolved), "remaining_call_issues": len(matching_issues)})
    elif kind == "ems_sensor_output":
        proposed = str(candidate.metadata.get("target_symbol", ""))
        if not context.rdd.contains(proposed):
            reasons.append("ems_sensor_output_not_in_version_rdd")
    elif kind == "ems_actuator_component":
        names = {
            canonical(obj.name) for obj in parse_idf(after).objects
            if obj.name and not canonical(obj.object_type).startswith("energymanagementsystem:")
        }
        if canonical(str(candidate.metadata.get("target_symbol", ""))) not in names:
            reasons.append("ems_actuator_component_not_in_object_graph")
    else:
        reasons.append("ems_validation_kind_unknown")
    return not reasons, tuple(reasons), details


__all__ = ["validate_ems_candidate"]
