'''
验证版本迁移候选的冻结输出、目标 IDD 结构和必需字段。

validate_migration_candidate(): 执行多对象迁移专用语义门禁。
'''

from __future__ import annotations

from typing import Any

from idfrepair.io.idf import canonical, parse_idf, text_sha256
from idfrepair.runtime.discovery import normalize_version


def validate_migration_candidate(
    before: str, after: str, candidate: Any, context: Any,
) -> tuple[bool, tuple[str, ...], dict[str, Any]]:
    '''
    验证迁移结果与候选冻结输出逐字节一致，并符合目标版本 IDD 结构。

    :param before: 源版本 IDF 正文。
    :param after: 候选应用后的目标版本临时正文。
    :param candidate: 绑定两侧 IDD 摘要和计划摘要的迁移候选。
    :param context: 当前目标运行时及其 IDD 上下文。
    :return: 是否通过、拒绝原因和结构检查统计。
    '''
    reasons: list[str] = []
    document = parse_idf(after)
    expected_sha = str(candidate.metadata.get("expected_output_sha256", ""))
    if text_sha256(after) != expected_sha:
        reasons.append("migration_output_not_equal_to_frozen_plan")
    if candidate.metadata.get("target_idd_sha256") != context.idd_sha256:
        reasons.append("migration_target_idd_identity_mismatch")
    target_version = str(candidate.metadata.get("target_version", ""))
    if normalize_version(document.version) != normalize_version(target_version):
        reasons.append("migration_version_not_updated")
    unknown = []
    required_missing = []
    arity_errors = []
    for obj in document.objects:
        definition = context.idd.get(obj.object_type)
        if definition is None:
            unknown.append(obj.object_type)
            continue
        if definition.maximum_fields is not None and len(obj.fields) > definition.maximum_fields:
            arity_errors.append(obj.index)
        for field in definition.fields:
            if field.required and (
                field.index > len(obj.fields) or not obj.fields[field.index - 1].value.strip()
            ):
                required_missing.append((obj.index, field.index, field.name))
    if unknown:
        reasons.append("migration_object_not_in_target_idd")
    if required_missing:
        reasons.append("migration_required_target_field_missing")
    if arity_errors:
        reasons.append("migration_target_arity_exceeded")
    before_document = parse_idf(before)
    changed_objects = sum(
        1 for old, new in zip(before_document.objects, document.objects)
        if (
            canonical(old.object_type) != canonical(new.object_type)
            or tuple(field.value for field in old.fields) != tuple(field.value for field in new.fields)
        )
    )
    return not reasons, tuple(reasons), {
        "target_version": document.version,
        "object_count": len(document.objects),
        "changed_object_count": changed_objects,
        "unknown_object_types": tuple(unknown),
        "required_missing": tuple(required_missing),
        "arity_errors": tuple(arity_errors),
    }


__all__ = ["validate_migration_candidate"]
