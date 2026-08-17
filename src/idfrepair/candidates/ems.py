'''
根据 EMS 符号表、调用图、RDD 和对象身份生成有限候选。

EmsProvider.generate(): 生成角色一致且覆盖全部故障位置的候选。
EmsProvider.validate_semantics(): 验证 EMS 补丁范围和图关系。
'''

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Iterable, Mapping, Sequence

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.candidates.schema import _unique_typo
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import CandidateEvidence, RepairCandidate, RepairOperation
from idfrepair.io.idf import IDFObject, canonical
from idfrepair.knowledge.ems import build_ems_calls, build_ems_symbols, normalize_ems_name, parse_ems
from idfrepair.validation.ems import validate_ems_candidate


_EMS_PREFIX = "energymanagementsystem:"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _diagnostic_mentions(root: Any, context: CandidateContext, value: str) -> bool:
    '''确认故障诊断明确包含待修改值，避免扫描式修复无关对象。'''
    key = canonical(value)
    messages = " ".join((str(root.message), context.diagnostics_text))
    return bool(key and key in canonical(messages))


def _replace_identifier(text: str, source: str, target: str) -> str:
    '''在单个 Erl 字段中替换大小写无关的完整标识符。'''
    source_key = normalize_ems_name(source)
    return _IDENTIFIER.sub(
        lambda match: target if normalize_ems_name(match.group(0)) == source_key else match.group(0),
        text,
    )


def _field_operation(
    context: CandidateContext,
    *,
    object_index: int,
    field_index: int,
    source: str,
    target: str,
    statement: bool,
) -> RepairOperation | None:
    '''把 EMS 图位置编译为绑定对象、字段和旧值的有限替换操作。'''
    if not 0 <= object_index < len(context.document.objects):
        return None
    obj = context.document.objects[object_index]
    if not 1 <= field_index <= len(obj.fields):
        return None
    field = obj.fields[field_index - 1]
    proposed = _replace_identifier(field.value, source, target) if statement else target
    if proposed == field.value:
        return None
    return RepairOperation(
        kind=OperationKind.RENAME_REFERENCE,
        object_type=obj.object_type,
        object_name=obj.name or None,
        object_index=obj.index,
        field_index=field.index,
        old_value=field.value,
        new_value=proposed,
        metadata={"ems_source": source, "ems_target": target},
    )


def _supported_symbol(
    source: str,
    metadata: Mapping[str, Any],
) -> tuple[str | None, tuple[CandidateEvidence, ...]]:
    '''从权威映射或至少两个独立正常 peer 中取得唯一 EMS 目标。'''
    targets: dict[str, tuple[str, list[CandidateEvidence]]] = {}
    mapping = metadata.get("ems_symbol_mapping", {})
    if isinstance(mapping, Mapping):
        for before, after in mapping.items():
            if normalize_ems_name(str(before)) != normalize_ems_name(source) or not after:
                continue
            target = str(after)
            targets.setdefault(normalize_ems_name(target), (target, []))[1].append(CandidateEvidence(
                kind="authoritative_symbol_mapping",
                source="version_bound_ems_mapping",
                strength=1.0,
                details={"source_symbol": str(before), "target_symbol": target},
            ))
    peer_rows = metadata.get("ems_peer_evidence", ())
    by_target: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    if isinstance(peer_rows, Sequence) and not isinstance(peer_rows, (str, bytes)):
        for row in peer_rows:
            if not isinstance(row, Mapping):
                continue
            before = str(row.get("source_symbol", ""))
            target = str(row.get("target_symbol", row.get("candidate_symbol", "")))
            identity = str(row.get("source_id", row.get("peer_id", row.get("source_sha256", ""))))
            if normalize_ems_name(before) == normalize_ems_name(source) and target and identity:
                by_target[normalize_ems_name(target)].append(row)
    for key, rows in by_target.items():
        identities = {
            str(row.get("source_id", row.get("peer_id", row.get("source_sha256", ""))))
            for row in rows
        }
        if len(identities) < 2:
            continue
        target = str(rows[0].get("target_symbol", rows[0].get("candidate_symbol")))
        targets.setdefault(key, (target, []))[1].append(CandidateEvidence(
            kind="independent_peer_consensus",
            source="normal_peer_corpus",
            strength=0.95,
            details={"independent_source_count": len(identities), "target_symbol": target},
        ))
    if len(targets) != 1:
        return None, ()
    target, evidence = next(iter(targets.values()))
    return target, tuple(evidence)


def _unique_definition(
    table: Mapping[str, Any], proposed: str,
) -> tuple[str | None, Mapping[str, Any] | None]:
    '''验证证据目标在当前文件中只有一个显式全局定义。'''
    rows = tuple(table.get("global_symbols", {}).get(normalize_ems_name(proposed), ()))
    if len(rows) != 1:
        return None, None
    return str(rows[0]["symbol"]), rows[0]


def _candidate(
    provider: str,
    root: Any,
    context: CandidateContext,
    operations: Sequence[RepairOperation],
    evidence: Sequence[CandidateEvidence],
    *,
    confidence: float,
    risk: RiskLevel,
    confirmation: bool,
    metadata: Mapping[str, Any],
) -> RepairCandidate:
    '''构造与输入、IDD、版本和根身份绑定的 EMS 候选。'''
    operation_tuple = tuple(operations)
    identity = candidate_identity(
        provider=provider,
        root_id=root.root_id,
        input_sha256=context.input_sha256,
        operations=operation_tuple,
    )
    return RepairCandidate(
        candidate_id=identity,
        provider=provider,
        root_id=root.root_id,
        family="ems",
        operations=operation_tuple,
        evidence=tuple(evidence),
        risk=risk,
        confidence=confidence,
        input_sha256=context.input_sha256,
        idd_sha256=context.idd_sha256,
        version=context.version,
        requires_user_confirmation=confirmation,
        metadata=dict(metadata),
    )


def _symbol_candidates(
    provider: str, root: Any, context: CandidateContext,
) -> tuple[RepairCandidate, ...]:
    '''为有独立证据的未定义数据符号生成覆盖全部引用位置的候选。'''
    table = build_ems_symbols(context.document.text)
    rows: list[RepairCandidate] = []
    for unresolved in table["undefined_symbols"]:
        source = str(unresolved["spellings"][0])
        if not _diagnostic_mentions(root, context, source):
            continue
        proposed, evidence = _supported_symbol(source, context.metadata)
        if proposed is None:
            continue
        actual, definition = _unique_definition(table, proposed)
        if actual is None or definition is None:
            continue
        operations = []
        locations: set[tuple[int, int]] = set()
        for occurrence in unresolved["occurrences"]:
            location = (int(occurrence["object_index"]), int(occurrence["field_index"]))
            if location in locations:
                continue
            operation = _field_operation(
                context,
                object_index=location[0],
                field_index=location[1],
                source=source,
                target=actual,
                statement=occurrence["role"] != "output_reference",
            )
            if operation is None:
                operations = []
                break
            locations.add(location)
            operations.append(operation)
        if operations and len(locations) == len({
            (int(row["object_index"]), int(row["field_index"]))
            for row in unresolved["occurrences"]
        }):
            rows.append(_candidate(
                provider, root, context, operations,
                (*evidence, CandidateEvidence(
                    kind="unique_visible_ems_definition",
                    source="ems_symbol_graph",
                    strength=1.0,
                    details={"definition_role": definition["role"], "call_site_count": len(locations)},
                )),
                confidence=0.96,
                risk=RiskLevel.LOW,
                confirmation=False,
                metadata={
                    "validation_kind": "ems_symbol",
                    "source_symbol": source,
                    "target_symbol": actual,
                    "source_occurrence_count": len(locations),
                    "complete_call_site_coverage": True,
                },
            ))
    return tuple(rows)


def _call_candidates(
    provider: str, root: Any, context: CandidateContext,
) -> tuple[RepairCandidate, ...]:
    '''为缺失 callable 生成角色唯一且覆盖全部调用点的候选。'''
    graph = build_ems_calls(context.document.text)
    nodes_by_kind: dict[str, list[str]] = defaultdict(list)
    for node in graph["nodes"]:
        if node["kind"] in {"program", "subroutine"}:
            nodes_by_kind[str(node["kind"])].append(str(node["name"]))
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for issue in graph["unresolved_calls"]:
        grouped[(str(issue["normalized_target"]), str(issue["expected_kind"]))].append(issue)
    rows = []
    for (_, expected_kind), issues in grouped.items():
        source = str(issues[0]["target_name"])
        if not _diagnostic_mentions(root, context, source):
            continue
        proposed = _unique_typo(source, nodes_by_kind.get(expected_kind, ()))
        if proposed is None:
            continue
        operations = []
        locations: set[tuple[int, int]] = set()
        for issue in issues:
            location = issue["location"]
            key = (int(location["object_index"]), int(location["field_index"]))
            if key in locations:
                continue
            operation = _field_operation(
                context,
                object_index=key[0],
                field_index=key[1],
                source=source,
                target=proposed,
                statement=issue["relation"] == "run_invokes_subroutine",
            )
            if operation is None:
                operations = []
                break
            locations.add(key)
            operations.append(operation)
        if operations:
            rows.append(_candidate(
                provider, root, context, operations,
                (CandidateEvidence(
                    kind="typed_callable_graph",
                    source="ems_call_graph",
                    strength=0.98,
                    details={
                        "expected_kind": expected_kind,
                        "call_site_count": len(locations),
                        "candidate_count": len(nodes_by_kind[expected_kind]),
                    },
                ),),
                confidence=0.95,
                risk=RiskLevel.LOW,
                confirmation=False,
                metadata={
                    "validation_kind": "ems_call",
                    "source_symbol": source,
                    "target_symbol": proposed,
                    "expected_kind": expected_kind,
                    "source_occurrence_count": len(locations),
                    "complete_call_site_coverage": True,
                },
            ))
    return tuple(rows)


def _named_objects(context: CandidateContext) -> tuple[str, ...]:
    '''收集非 EMS 对象的稳定名称，作为显式组件身份候选。'''
    return tuple(sorted({
        obj.name for obj in context.document.objects
        if obj.name and not canonical(obj.object_type).startswith(_EMS_PREFIX)
    }, key=lambda value: (canonical(value), value)))


def _reference_candidate(
    provider: str,
    root: Any,
    context: CandidateContext,
    obj: IDFObject,
    field_index: int,
    choices: Iterable[str],
    *,
    validation_kind: str,
    evidence: CandidateEvidence,
    confirmation: bool,
) -> RepairCandidate | None:
    '''为一个诊断指向的 EMS 引用字段生成唯一近似目标。'''
    if not 1 <= field_index <= len(obj.fields):
        return None
    field = obj.fields[field_index - 1]
    if not field.value or not _diagnostic_mentions(root, context, field.value):
        return None
    proposed = _unique_typo(field.value, tuple(choices))
    if proposed is None:
        return None
    operation = _field_operation(
        context,
        object_index=obj.index,
        field_index=field.index,
        source=field.value,
        target=proposed,
        statement=False,
    )
    if operation is None:
        return None
    return _candidate(
        provider, root, context, (operation,), (evidence,),
        confidence=0.95 if not confirmation else 0.84,
        risk=RiskLevel.LOW if not confirmation else RiskLevel.MEDIUM,
        confirmation=confirmation,
        metadata={
            "validation_kind": validation_kind,
            "source_symbol": field.value,
            "target_symbol": proposed,
            "complete_call_site_coverage": True,
        },
    )


def _object_candidates(
    provider: str, root: Any, context: CandidateContext,
) -> tuple[RepairCandidate, ...]:
    '''为 Sensor 输出变量和 Actuator 组件引用生成类型化字段候选。'''
    rows: list[RepairCandidate] = []
    named_objects = _named_objects(context)
    for obj in context.document.objects:
        object_type = canonical(obj.object_type)
        candidate = None
        if object_type == _EMS_PREFIX + "sensor" and len(obj.fields) >= 3:
            candidate = _reference_candidate(
                provider, root, context, obj, 3, context.rdd.variable_names,
                validation_kind="ems_sensor_output",
                evidence=CandidateEvidence(
                    kind="version_bound_rdd",
                    source="EnergyPlus.rdd",
                    strength=1.0,
                    details={"rdd_sha256": context.rdd.sha256},
                ),
                confirmation=False,
            )
        elif object_type == _EMS_PREFIX + "actuator" and len(obj.fields) >= 2:
            candidate = _reference_candidate(
                provider, root, context, obj, 2, named_objects,
                validation_kind="ems_actuator_component",
                evidence=CandidateEvidence(
                    kind="typed_component_identity",
                    source="object_graph",
                    strength=0.86,
                    details={"target_count": len(named_objects)},
                ),
                confirmation=True,
            )
        if candidate is not None:
            rows.append(candidate)
    return tuple(rows)


class EmsProvider(CandidateProvider):
    '''基于内置 EMS 语义图生成候选，不依赖宿主注入适配器。'''

    name = "ems_symbol_graph"
    families = frozenset({"ems"})

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        '''按调用、符号和对象字段证据生成至多三个稳定候选。'''
        candidates = (
            *_call_candidates(self.name, root, context),
            *_symbol_candidates(self.name, root, context),
            *_object_candidates(self.name, root, context),
        )
        unique = {candidate.candidate_id: candidate for candidate in candidates}
        return tuple(unique[key] for key in sorted(unique))[:3]

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        '''调用 EMS 专用验证器检查补丁范围、角色和解析闭包。'''
        return validate_ems_candidate(before, after, candidate, context)


__all__ = ["EmsProvider"]
