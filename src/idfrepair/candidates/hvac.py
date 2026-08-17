'''
根据版本绑定 IDD、HVAC 类型图和结构同类项生成有限候选。

HvacProvider.generate(): 生成引用、Branch、设备清单和节点候选。
HvacProvider.validate_semantics(): 验证补丁后的类型、方向和 multiplicity。
'''

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.candidates.schema import _unique_typo
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import CandidateEvidence, RepairCandidate, RepairOperation
from idfrepair.io.idf import canonical
from idfrepair.knowledge.hvac_graph import build_hvac_graph, structural_twins
from idfrepair.validation.hvac import validate_hvac_candidate


def _mentioned(root: Any, context: CandidateContext, value: str) -> bool:
    '''确认 EnergyPlus 诊断明确包含待修改的 HVAC 值。'''
    key = canonical(value)
    return bool(key and key in canonical(f"{root.message} {context.diagnostics_text}"))


def _operation(
    context: CandidateContext, object_index: int, field_index: int, target: str,
) -> RepairOperation | None:
    '''将图中的对象和字段身份编译为带旧值校验的有限操作。'''
    if not 0 <= object_index < len(context.document.objects):
        return None
    obj = context.document.objects[object_index]
    if not 1 <= field_index <= len(obj.fields):
        return None
    field = obj.fields[field_index - 1]
    if field.value == target:
        return None
    definition = context.idd.get(obj.object_type)
    field_def = definition.field_at(field.index) if definition is not None else None
    return RepairOperation(
        kind=OperationKind.RENAME_REFERENCE,
        object_type=obj.object_type,
        object_name=obj.name or None,
        object_index=obj.index,
        field_index=field.index,
        field_name=field_def.name if field_def is not None else None,
        old_value=field.value,
        new_value=target,
    )


def _candidate(
    provider: str,
    root: Any,
    context: CandidateContext,
    operation: RepairOperation,
    evidence: Sequence[CandidateEvidence],
    metadata: Mapping[str, Any],
) -> RepairCandidate:
    '''构造默认需要用户确认的 HVAC 有限候选。'''
    identity = candidate_identity(
        provider=provider,
        root_id=root.root_id,
        input_sha256=context.input_sha256,
        operations=(operation,),
    )
    return RepairCandidate(
        candidate_id=identity,
        provider=provider,
        root_id=root.root_id,
        family="hvac_reference",
        operations=(operation,),
        evidence=tuple(evidence),
        risk=RiskLevel.MEDIUM,
        confidence=0.9,
        input_sha256=context.input_sha256,
        idd_sha256=context.idd_sha256,
        version=context.version,
        requires_user_confirmation=True,
        metadata={**metadata, "idd_sha256": context.idd_sha256},
    )


def _typed_references(
    provider: str, root: Any, context: CandidateContext, graph: Mapping[str, Any],
) -> tuple[RepairCandidate, ...]:
    '''为缺失的 IDD object-list 引用生成 class 唯一候选。'''
    rows = []
    for issue in graph["unresolved_references"]:
        source = str(issue["value"])
        if issue["reason"] != "missing_typed_reference_provider" or not _mentioned(root, context, source):
            continue
        targets = tuple(issue["candidate_targets"])
        names = tuple(str(target["object_name"]) for target in targets)
        proposed = _unique_typo(source, names)
        matches = [target for target in targets if canonical(str(target["object_name"])) == canonical(proposed or "")]
        if proposed is None or len(matches) != 1:
            continue
        operation = _operation(context, int(issue["object_index"]), int(issue["field_index"]), proposed)
        if operation is None:
            continue
        rows.append(_candidate(
            provider, root, context, operation,
            (CandidateEvidence(
                kind="idd_typed_reference",
                source="hvac_graph",
                strength=1.0,
                details={
                    "object_list": issue["object_list"],
                    "typed_target_count": len(targets),
                    "target_object_type": matches[0]["object_type"],
                },
            ),),
            {
                "validation_kind": "hvac_typed_reference",
                "object_list": issue["object_list"],
                "source_id": issue["source_id"],
            },
        ))
    return tuple(rows)


def _branch_candidates(
    provider: str, root: Any, context: CandidateContext, graph: Mapping[str, Any],
) -> tuple[RepairCandidate, ...]:
    '''用组件类型和两端节点共同证明 Branch 组件名称。'''
    rows = []
    for relation in graph["branch_relations"]:
        source = str(relation["component_name"])
        if relation["status"] == "OK" or not _mentioned(root, context, source):
            continue
        targets = []
        for obj in context.document.objects:
            if canonical(obj.object_type) != canonical(str(relation["component_type"])) or not obj.name:
                continue
            values = {canonical(field.value) for field in obj.fields[1:] if field.value.strip()}
            if (
                canonical(str(relation["inlet_node"])) in values
                and canonical(str(relation["outlet_node"])) in values
            ):
                targets.append(obj)
        if len(targets) != 1:
            continue
        operation = _operation(
            context,
            int(relation["container_index"]),
            int(relation["component_name_index"]),
            targets[0].name,
        )
        if operation is None:
            continue
        rows.append(_candidate(
            provider, root, context, operation,
            (CandidateEvidence(
                kind="branch_endpoint_closure",
                source="hvac_graph",
                strength=1.0,
                details={
                    "component_type": targets[0].object_type,
                    "inlet_node": relation["inlet_node"],
                    "outlet_node": relation["outlet_node"],
                },
            ),),
            {
                "validation_kind": "hvac_branch_component",
                "container_id": relation["container_id"],
            },
        ))
    return tuple(rows)


def _equipment_candidates(
    provider: str, root: Any, context: CandidateContext, graph: Mapping[str, Any],
) -> tuple[RepairCandidate, ...]:
    '''为设备清单中的缺失设备名称生成对象类型唯一候选。'''
    rows = []
    for relation in graph["equipment_relations"]:
        source = str(relation["equipment_name"])
        if relation["status"] == "OK" or not _mentioned(root, context, source):
            continue
        targets = [
            obj for obj in context.document.objects
            if canonical(obj.object_type) == canonical(str(relation["equipment_type"])) and obj.name
        ]
        proposed = _unique_typo(source, tuple(obj.name for obj in targets))
        matches = [obj for obj in targets if canonical(obj.name) == canonical(proposed or "")]
        if proposed is None or len(matches) != 1:
            continue
        operation = _operation(
            context,
            int(relation["container_index"]),
            int(relation["equipment_name_index"]),
            proposed,
        )
        if operation is None:
            continue
        rows.append(_candidate(
            provider, root, context, operation,
            (CandidateEvidence(
                kind="equipment_type_multiplicity",
                source="hvac_graph",
                strength=0.95,
                details={"equipment_type": relation["equipment_type"], "matching_target_count": 1},
            ),),
            {
                "validation_kind": "hvac_equipment_reference",
                "container_id": relation["container_id"],
            },
        ))
    return tuple(rows)


def _node_candidates(
    provider: str, root: Any, context: CandidateContext, graph: Mapping[str, Any],
) -> tuple[RepairCandidate, ...]:
    '''要求至少两个结构同类对象在同一端口字段上达成一致后提出节点候选。'''
    rows = []
    for port in graph["ports"]:
        source = str(port["node_name"])
        if not _mentioned(root, context, source):
            continue
        twins = structural_twins(graph, str(port["object_id"]))
        values = []
        for twin in twins:
            obj = context.document.objects[int(twin["object_index"])]
            index = int(port["field_index"])
            if index <= len(obj.fields) and obj.fields[index - 1].value.strip():
                values.append(obj.fields[index - 1].value.strip())
        counts = Counter(canonical(value) for value in values)
        approved = [key for key, count in counts.items() if count >= 2]
        if len(approved) != 1:
            continue
        proposed_values = sorted({value for value in values if canonical(value) == approved[0]})
        if len(proposed_values) != 1 or canonical(source) == approved[0]:
            continue
        operation = _operation(
            context, int(port["object_index"]), int(port["field_index"]), proposed_values[0],
        )
        if operation is None:
            continue
        rows.append(_candidate(
            provider, root, context, operation,
            (CandidateEvidence(
                kind="structural_twin_consensus",
                source="hvac_graph",
                strength=0.92,
                details={
                    "peer_count": counts[approved[0]],
                    "role": port["role"],
                    "medium": port["medium"],
                },
            ),),
            {
                "validation_kind": "hvac_node_reference",
                "source_id": port["object_id"],
                "role": port["role"],
                "medium": port["medium"],
            },
        ))
    return tuple(rows)


class HvacProvider(CandidateProvider):
    '''基于内置类型图生成 HVAC 候选，未经用户确认不进入自动提交。'''

    name = "hvac_typed_graph"
    families = frozenset({"hvac_reference"})

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        '''合并类型引用、Branch、设备清单和结构同类节点候选。'''
        graph = build_hvac_graph(context.document, context.idd)
        candidates = (
            *_branch_candidates(self.name, root, context, graph),
            *_typed_references(self.name, root, context, graph),
            *_equipment_candidates(self.name, root, context, graph),
            *_node_candidates(self.name, root, context, graph),
        )
        unique = {candidate.candidate_id: candidate for candidate in candidates}
        return tuple(unique[key] for key in sorted(unique))[:3]

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        '''调用 HVAC 专用验证器检查引用 class、方向、端点和 multiplicity。'''
        return validate_hvac_candidate(before, after, candidate, context)


__all__ = ["HvacProvider"]
