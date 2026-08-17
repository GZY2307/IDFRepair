'''
将启用的 Repair Memory 规则匹配到当前错误根并编译为有限候选。

match_rules(): 返回通过版本、作用域和错误语义门禁的规则。
MemoryProvider.generate(): 把规则模板绑定到当前对象和字段。
'''

from __future__ import annotations

from typing import Any, Mapping

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.domain.enums import OperationKind, Provenance, RiskLevel
from idfrepair.domain.models import CandidateEvidence, RepairCandidate, RepairOperation
from idfrepair.io.idf import apply_operations, canonical, changed_fields
from idfrepair.memory.models import RepairRule, RuleMatchContext, RuleSource
from idfrepair.memory.policy import rule_confirmation, scope_matches
from idfrepair.memory.repository import RuleRepository


def _match_context(root: Any, context: CandidateContext) -> RuleMatchContext:
    '''从错误根和候选上下文构造规则作用域身份。'''
    return RuleMatchContext(
        input_sha256=context.input_sha256,
        template_fingerprint=(str(context.metadata["template_fingerprint"]) if context.metadata.get("template_fingerprint") else None),
        project_id=(str(context.metadata["project_id"]) if context.metadata.get("project_id") else None),
        batch_id=(str(context.metadata["batch_id"]) if context.metadata.get("batch_id") else None),
        family=root.family,
        error_signature=" ".join((root.message, *root.signatures)),
        energyplus_version=context.version,
        object_type=root.object_type,
        field_name=root.field_name,
        field_index=(int(root.metadata["field_index"]) if root.metadata.get("field_index") else None),
        field_role=(str(root.metadata["field_role"]) if root.metadata.get("field_role") else None),
        graph_fingerprint=(str(context.metadata["graph_fingerprint"]) if context.metadata.get("graph_fingerprint") else None),
    )


def match_rules(
    repository: RuleRepository, root: Any, context: CandidateContext,
) -> tuple[RepairRule, ...]:
    '''按优先级返回与当前版本、错误语义和作用域相符的启用规则。'''
    match_context = _match_context(root, context)
    selected_rule_set = str(context.metadata.get("selected_rule_set_id") or "default")
    rows = [
        rule for rule in repository.list_rules(
            enabled=True, rule_set_id=selected_rule_set,
        )
        if scope_matches(rule, match_context)
    ]
    rows.sort(key=lambda rule: (-rule.priority, -rule.confidence, rule.rule_id))
    return tuple(rows)


def _resolve_object(row: Mapping[str, Any], root: Any, context: CandidateContext) -> Any | None:
    '''把规则中的当前根占位符和对象身份解析为唯一 IDF 对象。'''
    object_index = row.get("object_index")
    if object_index is not None:
        index = int(object_index)
        return context.document.objects[index] if 0 <= index < len(context.document.objects) else None
    object_type = str(row.get("object_type", root.object_type or ""))
    object_name = row.get("object_name")
    if object_name == "$ROOT_OBJECT_NAME":
        object_name = root.object_name
    matches = context.document.find_objects(object_type, str(object_name) if object_name else None)
    return matches[0] if len(matches) == 1 else None


def _compile_operation(
    row: Mapping[str, Any], root: Any, context: CandidateContext,
) -> RepairOperation | None:
    '''把一条规则操作绑定到当前对象、字段旧值和有限新值。'''
    obj = _resolve_object(row, root, context)
    if obj is None:
        return None
    try:
        kind = OperationKind(str(row.get("kind", row.get("operation", ""))))
    except ValueError:
        return None
    field_index = int(row["field_index"]) if row.get("field_index") is not None else None
    old_value = row.get("old_value")
    if old_value == "$CURRENT":
        if field_index is None or not 1 <= field_index <= len(obj.fields):
            return None
        old_value = obj.fields[field_index - 1].value
    new_value = row.get("new_value")
    if new_value == "$ROOT_OBJECT_NAME":
        new_value = root.object_name
    vertices = tuple(tuple(float(value) for value in vertex) for vertex in row.get("vertices", ()))
    return RepairOperation(
        kind=kind,
        object_type=obj.object_type,
        object_name=obj.name or None,
        object_index=obj.index,
        field_index=field_index,
        field_name=(str(row["field_name"]) if row.get("field_name") else None),
        old_value=(str(old_value) if old_value is not None else None),
        new_value=(str(new_value) if new_value is not None else None),
        vertices=vertices,
        metadata={"memory_compiled": True},
    )


class MemoryProvider(CandidateProvider):
    '''从启用规则生成有限候选，所有候选继续经过统一静态、语义和 EnergyPlus 门禁。'''

    name = "repair_memory"
    families = frozenset()

    def supports(self, root, context):  # type: ignore[no-untyped-def]
        '''只在上下文显式注入 RuleRepository 时参与任意错误族。'''
        return isinstance(context.metadata.get("rule_repository"), RuleRepository)

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        '''匹配规则并将每条完整模板编译为一个状态绑定候选。'''
        repository = context.metadata.get("rule_repository")
        if not isinstance(repository, RuleRepository):
            return ()
        rows = []
        for rule in match_rules(repository, root, context):
            operations = tuple(
                operation for item in rule.finite_operations
                if (operation := _compile_operation(item, root, context)) is not None
            )
            if len(operations) != len(rule.finite_operations) or not operations:
                continue
            try:
                apply_operations(context.document.text, operations)
            except Exception:
                continue
            identity = candidate_identity(
                provider=self.name,
                root_id=root.root_id,
                input_sha256=context.input_sha256,
                operations=operations,
            )
            confirmation = rule_confirmation(rule)
            rows.append(RepairCandidate(
                candidate_id=identity,
                provider=self.name,
                root_id=root.root_id,
                family=root.family,
                operations=operations,
                evidence=(CandidateEvidence(
                    kind="repair_memory_rule",
                    source="repair_memory",
                    strength=rule.confidence,
                    details={
                        "rule_id": rule.rule_id,
                        "rule_set_id": rule.rule_set_id,
                        "scope": rule.scope.value,
                        "source": rule.source.value,
                        "priority": rule.priority,
                    },
                ),),
                risk=RiskLevel.MEDIUM if confirmation else RiskLevel.LOW,
                confidence=rule.confidence,
                input_sha256=context.input_sha256,
                idd_sha256=context.idd_sha256,
                version=context.version,
                requires_user_confirmation=confirmation,
                provenance=(
                    Provenance.DETERMINISTIC
                    if rule.source in {RuleSource.BUILTIN, RuleSource.USER_CONFIRMED}
                    else Provenance.RETRIEVAL
                ),
                metadata={
                    "memory_rule_id": rule.rule_id,
                    "memory_rule_set_id": rule.rule_set_id,
                    "memory_scope": rule.scope.value,
                    "historical_failure_count": rule.failure_count,
                },
            ))
        return tuple(rows[:3])

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        '''验证规则候选只产生其声明的有限变化，不把规则当成语义门禁豁免。'''
        expected = tuple(sorted((
            operation.object_index,
            operation.field_index,
            operation.old_value,
            operation.new_value,
        ) for operation in candidate.operations if (
            operation.field_index is not None
            and operation.kind in {
                OperationKind.REPLACE_FIELD, OperationKind.RENAME_REFERENCE,
                OperationKind.UPDATE_VERSION,
            }
        )))
        actual = tuple(sorted(changed_fields(before, after)))
        if expected and actual != expected:
            return False, ("memory_rule_patch_scope_changed",), {"changes": actual}
        if apply_operations(before, candidate.operations) != after:
            return False, ("memory_rule_output_not_reproducible",), {"changes": actual}
        return True, (), {"changes": actual, "rule_id": candidate.metadata.get("memory_rule_id")}


__all__ = ["MemoryProvider", "match_rules"]
