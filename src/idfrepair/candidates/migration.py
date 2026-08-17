'''
根据源、目标 IDD 的精确身份生成多对象版本迁移候选。

MigrationProvider.generate(): 编译字段插入、删除、重排和 Version 更新。
MigrationProvider.validate_semantics(): 验证迁移输出与冻结计划完全一致。
'''

from __future__ import annotations

from typing import Any, Mapping

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import CandidateEvidence, RepairCandidate, RepairOperation
from idfrepair.io.idf import apply_operations, text_sha256
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.knowledge.idd_registry import resolve_registry
from idfrepair.knowledge.migration import plan_migration
from idfrepair.runtime.discovery import normalize_version
from idfrepair.validation.migration import validate_migration_candidate


def _version_schema(registry: Mapping[str, IDDSchema], version: str) -> IDDSchema | None:
    '''按去除尾零后的版本身份选择唯一 IDD schema。'''
    target = normalize_version(version)
    matches = [schema for key, schema in registry.items() if normalize_version(key) == target]
    identities = {schema.sha256: schema for schema in matches}
    return next(iter(identities.values())) if len(identities) == 1 else None


class MigrationProvider(CandidateProvider):
    '''只在源、目标 IDD 均可复核且完整计划无阻塞时生成迁移候选。'''

    name = "version_migration"
    families = frozenset({"version_migration"})

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        '''生成一个包含全部受影响对象和 Version 字段的原子迁移候选。'''
        document = context.document
        target_version = str(context.metadata.get("target_version", context.version))
        if not document.version or not target_version or normalize_version(document.version) == normalize_version(target_version):
            return ()
        registry = resolve_registry(context.metadata.get("idd_registry"))
        source_schema = _version_schema(registry, document.version)
        target_schema = _version_schema(registry, target_version)
        if source_schema is None or target_schema is None or target_schema.sha256 != context.idd_sha256:
            return ()
        renames = context.metadata.get("migration_field_renames")
        plan = plan_migration(
            document,
            source_schema,
            target_schema,
            target_version,
            field_renames=renames if isinstance(renames, Mapping) else None,
        )
        if plan["status"] != "OK":
            return ()
        operations: list[RepairOperation] = []
        for row in plan["replacements"]:
            operations.append(RepairOperation(
                kind=OperationKind.REPLACE_OBJECT,
                object_type=str(row["object_type"]),
                object_name=str(row["object_name"]) or None,
                object_index=int(row["object_index"]),
                old_value=str(row["old_text"]),
                object_text=str(row["object_text"]),
                metadata={
                    "source_field_count": row["source_field_count"],
                    "target_field_count": row["target_field_count"],
                },
            ))
        if plan["update_version"]:
            version_obj = document.find_objects("Version")[0]
            operations.append(RepairOperation(
                kind=OperationKind.UPDATE_VERSION,
                object_type=version_obj.object_type,
                object_index=version_obj.index,
                field_index=1,
                old_value=version_obj.fields[0].value,
                new_value=target_version,
            ))
        if not operations:
            return ()
        operation_tuple = tuple(operations)
        expected = apply_operations(document.text, operation_tuple)
        identity = candidate_identity(
            provider=self.name,
            root_id=root.root_id,
            input_sha256=context.input_sha256,
            operations=operation_tuple,
        )
        object_diff_count = len(plan["diff"]["object_diffs"])
        return (RepairCandidate(
            candidate_id=identity,
            provider=self.name,
            root_id=root.root_id,
            family="version_migration",
            operations=operation_tuple,
            evidence=(
                CandidateEvidence(
                    kind="source_idd_identity",
                    source="idd_registry",
                    strength=1.0,
                    details={"version": document.version, "sha256": source_schema.sha256},
                ),
                CandidateEvidence(
                    kind="target_idd_identity",
                    source="idd_registry",
                    strength=1.0,
                    details={"version": target_version, "sha256": target_schema.sha256},
                ),
                CandidateEvidence(
                    kind="complete_migration_plan",
                    source="idd_diff_graph",
                    strength=0.98,
                    details={
                        "object_replacement_count": len(plan["replacements"]),
                        "changed_schema_object_count": object_diff_count,
                    },
                ),
            ),
            risk=RiskLevel.MEDIUM,
            confidence=0.94,
            input_sha256=context.input_sha256,
            idd_sha256=context.idd_sha256,
            version=context.version,
            requires_user_confirmation=True,
            metadata={
                "source_version": document.version,
                "target_version": target_version,
                "source_idd_sha256": source_schema.sha256,
                "target_idd_sha256": target_schema.sha256,
                "plan_sha256": plan["plan_sha256"],
                "expected_output_sha256": text_sha256(expected),
                "object_replacement_count": len(plan["replacements"]),
                "multi_object": len(plan["replacements"]) > 1,
                "transition_program": context.metadata.get("transition_program"),
            },
        ),)

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        '''调用版本迁移专用验证器复核计划身份和目标 schema。'''
        return validate_migration_candidate(before, after, candidate, context)


__all__ = ["MigrationProvider"]
