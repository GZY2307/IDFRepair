'''
把用户确认且通过完整验证的有限候选保存为受限 Repair Memory 规则。

save_validated_rule(): 在全部门禁通过后创建 EXACT_TEMPLATE 或 PROJECT 规则。
'''

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from idfrepair.domain.enums import OperationKind
from idfrepair.domain.models import RepairCandidate, to_primitive, utc_now
from idfrepair.io.idf import canonical, parse_idf
from idfrepair.memory.models import RepairRule, RuleScope, RuleSource
from idfrepair.memory.policy import portable_error_signature
from idfrepair.memory.repository import RuleRepository


def template_fingerprint(text: str) -> str:
    '''按对象类型、顺序和字段数量计算忽略文件特有取值的模板指纹。'''
    document = parse_idf(text)
    shape = tuple(
        (canonical(obj.object_type), len(obj.fields))
        for obj in document.objects
    )
    payload = json.dumps(shape, ensure_ascii=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def save_validated_rule(
    repository: RuleRepository,
    candidate: RepairCandidate,
    *,
    name_zh: str,
    name_en: str,
    scope: RuleScope,
    template_fingerprint: str | None = None,
    project_id: str | None = None,
    batch_id: str | None = None,
    input_sha256: str,
    family: str,
    error_signature: str,
    energyplus_version: str,
    static_passed: bool,
    semantic_passed: bool,
    energyplus_passed: bool,
    final_passed: bool,
    rule_set_id: str = "default",
    allow_global: bool = False,
    root_object_type: str | None = None,
    root_object_name: str | None = None,
) -> RepairRule:
    '''
    仅在静态、语义、EnergyPlus 和最终门禁全部通过后保存用户确认规则。

    GLOBAL 必须由调用方提供独立治理授权；普通确认默认使用模板或项目范围。
    '''
    if not all((static_passed, semantic_passed, energyplus_passed, final_passed)):
        raise ValueError("rule_learning_requires_complete_validation")
    if scope is RuleScope.GLOBAL and not allow_global:
        raise ValueError("global_rule_requires_explicit_authorization")
    conditions: dict[str, Any] = {}
    if scope is RuleScope.EXACT_FILE:
        conditions["input_sha256"] = input_sha256
    elif scope is RuleScope.EXACT_TEMPLATE:
        if not template_fingerprint:
            raise ValueError("template_fingerprint_required")
        conditions["template_fingerprint"] = template_fingerprint
    elif scope is RuleScope.PROJECT:
        if not project_id:
            raise ValueError("project_id_required")
        conditions["project_id"] = project_id
    elif scope is RuleScope.BATCH:
        if not batch_id:
            raise ValueError("batch_id_required")
        conditions["batch_id"] = batch_id
    operations = []
    operation_identities = {
        (canonical(operation.object_type or ""), canonical(operation.object_name or ""))
        for operation in candidate.operations
    }
    one_target = len(operation_identities) == 1
    for operation in candidate.operations:
        if operation.kind in {OperationKind.INSERT_OBJECT, OperationKind.DELETE_OBJECT, OperationKind.REPLACE_OBJECT}:
            raise ValueError("rule_learning_operation_not_allowed")
        root_bound = (
            scope is not RuleScope.EXACT_FILE
            and operation.object_name is not None
            and (
                (
                    root_object_name is not None
                    and canonical(operation.object_name) == canonical(root_object_name)
                    and (
                        root_object_type is None
                        or canonical(operation.object_type or "") == canonical(root_object_type)
                    )
                )
                or (root_object_name is None and one_target)
            )
        )
        row = {
            "kind": operation.kind.value,
            "object_type": operation.object_type,
            "object_name": "$ROOT_OBJECT_NAME" if root_bound else operation.object_name,
            "field_index": operation.field_index,
            "field_name": operation.field_name,
            "old_value": "$CURRENT" if operation.old_value is not None else None,
            "new_value": operation.new_value,
            "vertices": to_primitive(operation.vertices),
        }
        operations.append({key: value for key, value in row.items() if value not in (None, [], ())})
    now = utc_now()
    rule = RepairRule(
        rule_id=uuid4().hex,
        rule_set_id=rule_set_id,
        name_zh=name_zh,
        name_en=name_en,
        description_zh="由用户确认候选经过完整验证后保存。",
        description_en="Saved after a user-confirmed candidate passed every validation gate.",
        enabled=True,
        priority=50,
        scope=scope,
        source=RuleSource.USER_CONFIRMED,
        created_at=now,
        updated_at=now,
        energyplus_version_min=energyplus_version,
        energyplus_version_max=energyplus_version,
        error_signature=canonical(family),
        family=family,
        object_type=candidate.operations[0].object_type,
        field_name=candidate.operations[0].field_name,
        field_index=candidate.operations[0].field_index,
        conditions=conditions,
        candidate_template={
            "provider": candidate.provider,
            "root_id": candidate.root_id,
            "observed_error_signature": portable_error_signature(error_signature),
        },
        finite_operations=tuple(operations),
        requires_confirmation=False,
        confidence=max(0.85, candidate.confidence),
        tags=("user-confirmed", "fully-validated"),
    )
    return repository.create_rule(rule)


__all__ = ["save_validated_rule", "template_fingerprint"]
