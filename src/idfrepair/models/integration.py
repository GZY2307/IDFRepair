'''把关闭世界模型决定接入有限候选、工具和统一验证之前的边界。

integrate_model_candidates(): 执行 T1–T6 关闭世界决策并编译有限候选。
'''

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import re
from typing import Any, Callable, Iterable, Mapping, Protocol

from idfrepair.candidates.base import CandidateContext
from idfrepair.domain.enums import Provenance
from idfrepair.domain.models import (
    CandidateEvidence, DiagnosticRoot, RepairCandidate, to_primitive,
)
from idfrepair.knowledge.case_retrieval import CaseIndex
from idfrepair.models.contracts import ALLOWED_TOOLS, ToolRequest, parse_repair_plan
from idfrepair.models.qwen import QwenSelection
from idfrepair.models.tool_runtime import ToolRuntime, build_standard_tool_runtime
from idfrepair.validation.static import validate_candidate_static


FAMILY_TO_MODEL_ROOTS = {
    "ems": ("ems_symbol_resolution",),
    "external_dependency": ("nonlocal_target_localization",),
    "extra_field": ("extensible_group_alignment",),
    "geometry": ("geometric_structure_validation",),
    "hvac_reference": ("typed_hvac_graph_planning",),
    "output_variable": ("output_dictionary_resolution",),
    "reference": ("nonlocal_target_localization",),
    "reference_schedule": ("missing_schedule_reference",),
    "schema": ("construction_peer_reconstruction", "field_schema_alignment"),
    "syntax": ("field_schema_alignment",),
    "version_migration": ("versioned_schema_migration",),
}


class SelectorBackend(Protocol):
    '''描述 Qwen 与测试后端共享的有限选择接口。'''

    def select(
        self,
        *,
        task: str,
        visible: Mapping[str, Any],
        expected_output_type: str,
        allowed_values: tuple[str, ...],
        max_tokens: int = 96,
    ) -> QwenSelection: ...


@dataclass(frozen=True, slots=True)
class ModelIntegrationResult:
    '''封装模型候选、调用证据和失败关闭限制。'''

    candidates: tuple[RepairCandidate, ...]
    model_calls: tuple[Mapping[str, Any], ...]
    tool_calls: tuple[Mapping[str, Any], ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelFeedbackResult:
    '''封装候选失败后模型对剩余有限候选的重新排序。'''

    candidates: tuple[RepairCandidate, ...]
    model_call: Mapping[str, Any] | None
    limitation: str | None


def _evidence_codes(root: DiagnosticRoot) -> list[str]:
    '''从错误根提取不含 gold 的稳定大写证据码。'''
    rows = [f"FAMILY_{root.family}"]
    if root.object_type:
        rows.append("OBJECT_TYPE_PRESENT")
    if root.field_name:
        rows.append("FIELD_ROLE_PRESENT")
    rows.extend("SIGNATURE_" + item for item in root.signatures[:3])
    cleaned = []
    for row in rows:
        token = re.sub(r"[^A-Z0-9_]+", "_", row.upper()).strip("_")
        if token and token not in cleaned:
            cleaned.append(token)
    return cleaned[:8] or ["DIAGNOSTIC_PRESENT"]


def _root_index(root: DiagnosticRoot, context: CandidateContext) -> int:
    '''优先使用已定位索引，否则按对象类型和名称寻找可审计目标。'''
    raw = root.metadata.get("object_index")
    try:
        index = int(raw)
    except (TypeError, ValueError):
        index = -1
    if 0 <= index < len(context.document.objects):
        return index
    for row in context.document.objects:
        if root.object_type and row.object_type.casefold() != root.object_type.casefold():
            continue
        if root.object_name and row.name.casefold() != root.object_name.casefold():
            continue
        return row.index
    return 0


def _field_index(root: DiagnosticRoot) -> int:
    '''提取诊断中的字段索引；缺失时采用第一个数据字段。'''
    for key in ("field_index", "field_number"):
        try:
            value = int(root.metadata.get(key))
        except (TypeError, ValueError):
            continue
        return max(0, value)
    return 1


def _tool_arguments(
    tool: str,
    root: DiagnosticRoot,
    context: CandidateContext,
    candidates: tuple[RepairCandidate, ...],
) -> dict[str, Any]:
    '''由程序而非模型构造工具参数，确保不能注入自由补丁或路径。'''
    index = _root_index(root, context)
    object_type = root.object_type or context.document.objects[index].object_type
    field_index = _field_index(root)
    node_id = context.object_graph.nodes[index].node_id
    first_candidate = candidates[0].candidate_id
    table: dict[str, dict[str, Any]] = {
        "find_reference_targets": {"object_index": index, "field_index": field_index},
        "find_same_type_peers": {"object_index": index},
        "inspect_graph_neighbors": {"node_id": node_id},
        "inspect_object": {"object_index": index},
        "query_idd_field": {"object_type": object_type, "field_index": field_index},
        "query_idd_object": {"object_type": object_type},
        "query_rdd": {"query": root.field_name or root.message, "limit": 20},
        "request_user_input": {
            "choices": [candidate.candidate_id for candidate in candidates[:3]],
            "prompt": "Select a bounded candidate or provide the missing intent.",
            "question_type": "choose_candidate",
            "root_id": root.root_id,
        },
        "retrieve_memory_rules": {
            "error_signature": " ".join(root.signatures) or root.message,
            "family": root.family,
            "limit": 5,
            "object_type": root.object_type,
        },
        "retrieve_public_cases": {
            "error_tokens": [root.family, *root.signatures],
            "field_roles": [root.field_name] if root.field_name else [],
            "limit": 5,
            "object_types": [root.object_type] if root.object_type else [],
        },
        "run_energyplus_candidate": {"candidate_id": first_candidate},
        "simulate_candidate": {"candidate_id": first_candidate},
    }
    return table[tool]


def _tool_catalog(
    root: DiagnosticRoot,
    context: CandidateContext,
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    '''提供全部十二个已注册工具及不泄露评分器的粗粒度适用性线索。'''
    preferred = {
        "geometry": {"inspect_object", "inspect_graph_neighbors", "find_same_type_peers"},
        "output_variable": {"query_rdd", "query_idd_field"},
        "reference": {"find_reference_targets", "inspect_graph_neighbors", "query_idd_field"},
        "reference_schedule": {"find_reference_targets", "retrieve_memory_rules", "query_idd_field"},
        "schema": {"query_idd_object", "query_idd_field", "find_same_type_peers"},
        "syntax": {"inspect_object", "query_idd_object"},
    }.get(root.family, {"query_idd_object", "inspect_object", "retrieve_memory_rules"})
    return [
        {
            "applicable": True,
            "evidence_overlap": 1 if name in preferred else 0,
            "name": name,
            "score": 900 if name in preferred else 500,
        }
        for name in sorted(set(allowed_tools))
    ]


def _target_catalog(
    root: DiagnosticRoot, context: CandidateContext,
) -> list[dict[str, Any]]:
    '''以当前根优先的稳定顺序提供可定位错误根目录。'''
    roots = {row.root_id: row for row in (*context.roots, root)}
    ordered = [root, *(
        roots[key] for key in sorted(roots)
        if key != root.root_id
    )]
    return [{
        "family": row.family,
        "id": f"TARGET_{index:02d}",
        "root_id": row.root_id,
        "object_name": row.object_name,
        "object_type": row.object_type,
        "severity": row.severity,
        "signature_codes": list(row.signatures[:3]),
    } for index, row in enumerate(ordered, start=1)]


def _candidate_catalog(candidates: tuple[RepairCandidate, ...]) -> list[dict[str, Any]]:
    '''把有限候选投影为训练期兼容的选择目录，不暴露 gold 或完整 scorer。'''
    rows = []
    for candidate in candidates:
        kinds = {evidence.kind for evidence in candidate.evidence}
        rows.append({
            "id": candidate.candidate_id,
            "patches": len(candidate.operations),
            "peer": 900 if "same_type_peer_consensus" in kinds else 0,
            "score": round(candidate.confidence * 1000),
            "static": True,
        })
    return rows


def _bounded_result(value: Any) -> Any:
    '''限制工具审计结果大小，同时保留摘要和内容摘要。'''
    primitive = to_primitive(value)
    encoded = json.dumps(primitive, ensure_ascii=False, sort_keys=True, default=str)
    if len(encoded) <= 16000:
        return primitive
    return {
        "json_characters": len(encoded),
        "result_sha256": sha256(encoded.encode("utf-8")).hexdigest(),
        "truncated": True,
    }


def _tool_observation(tool: str, value: Any, *, succeeded: bool) -> dict[str, Any]:
    '''把工具结果编译为后续决策可见的有界观测。'''
    result = _bounded_result(value)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "result": result,
        "result_sha256": sha256(encoded.encode("utf-8")).hexdigest(),
        "succeeded": succeeded,
        "tool": tool,
    }


def _visible_observation(value: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    '''从完整工具记录提取适合模型提示的短观测。'''
    if value is None:
        return None
    result = value.get("result")
    summary: dict[str, Any] = {}
    if isinstance(result, Mapping):
        summary["keys"] = sorted(str(key) for key in result)[:12]
        for key in ("name", "passed", "status", "required", "truncated"):
            item = result.get(key)
            if isinstance(item, (str, int, float, bool)) or item is None:
                summary[key] = item
        fields = result.get("fields")
        if isinstance(fields, list):
            summary["field_count"] = len(fields)
            summary["field_names"] = [
                str(row.get("name")) for row in fields[:6]
                if isinstance(row, Mapping) and row.get("name")
            ]
    elif isinstance(result, list):
        summary["item_count"] = len(result)
        summary["items"] = [str(item)[:120] for item in result[:4]]
    elif result is not None:
        summary["value"] = str(result)[:240]
    return {
        "result_sha256": value.get("result_sha256"),
        "succeeded": bool(value.get("succeeded")),
        "summary": summary,
        "tool": value.get("tool"),
    }


def _finite_plan(
    candidate: RepairCandidate,
    *,
    root: DiagnosticRoot,
    family: str,
    evidence_codes: list[str],
    selected_tool: str | None,
    tool_arguments: Mapping[str, Any] | None,
) -> tuple[str, Mapping[str, Any]]:
    '''由程序从有限候选编译 RepairPlan，模型只能选择 plan ID。'''
    primitives = [{
        "operation": operation.kind.value,
        "target": operation.field_name or operation.field_index or operation.object_type or "object",
    } for operation in candidate.operations]
    requested_tools = (
        [{"tool": selected_tool, "arguments": dict(tool_arguments or {})}]
        if selected_tool else []
    )
    payload = {
        "ambiguities": [],
        "candidate_primitives": primitives,
        "confidence": candidate.confidence,
        "evidence_summary": evidence_codes,
        "hypothesized_family": family,
        "needs_user_input": candidate.requires_user_confirmation,
        "requested_tools": requested_tools,
        "root_id": root.root_id,
        "target_field": root.field_name,
        "target_object": root.object_type,
    }
    plan = parse_repair_plan(payload)
    plan_payload = to_primitive(plan)
    encoded = json.dumps(plan_payload, ensure_ascii=False, sort_keys=True)
    return "plan-" + sha256(encoded.encode("utf-8")).hexdigest()[:20], plan_payload


def _selection(
    backend: SelectorBackend,
    calls: list[Mapping[str, Any]],
    *,
    task: str,
    visible: Mapping[str, Any],
    output_type: str,
    allowed: tuple[str, ...],
) -> str | None:
    '''执行一次模型选择并把成功或失败都写入审计调用。'''
    try:
        result = backend.select(
            task=task,
            visible=visible,
            expected_output_type=output_type,
            allowed_values=allowed,
        )
    except Exception as exc:
        calls.append({
            "error": f"{type(exc).__name__}:{exc}",
            "status": "FAILED_CLOSED",
            "task": task,
        })
        return None
    calls.append({**dict(result.record), "status": "ACCEPTED_SCHEMA"})
    return result.decision.value


def integrate_model_candidates(
    backend: SelectorBackend,
    *,
    root: DiagnosticRoot,
    context: CandidateContext,
    candidates: tuple[RepairCandidate, ...],
    case_index: CaseIndex | None,
    maximum_tool_calls: int,
    run_candidate: Callable[[RepairCandidate], Any] | None = None,
    allowed_tools: Iterable[str] | None = None,
) -> ModelIntegrationResult:
    '''让模型完整执行 T1–T6，但只编译程序已有的有限操作。'''
    if not candidates:
        return ModelIntegrationResult((), (), (), ("MODEL_CANDIDATE_CATALOG_EMPTY",))
    model_calls: list[Mapping[str, Any]] = []
    limitations: list[str] = []
    enabled_tools = frozenset(ALLOWED_TOOLS if allowed_tools is None else allowed_tools)
    if not enabled_tools <= ALLOWED_TOOLS:
        raise ValueError("model_tool_allowlist_invalid")
    evidence_codes = _evidence_codes(root)
    common_context = {
        "evidence": evidence_codes,
        "field_index": _field_index(root),
        "field_role": root.field_name,
        "object_type": root.object_type,
        "version_pair": [context.version, context.version],
    }
    available_families = {root.family, *(candidate.family for candidate in candidates)}
    model_families = tuple(sorted({
        model_root
        for unified_family in available_families
        for model_root in FAMILY_TO_MODEL_ROOTS.get(unified_family, ())
    }))
    if not model_families:
        return ModelIntegrationResult((), (), (), ("MODEL_ROOT_CATALOG_EMPTY",))
    model_family = _selection(
        backend,
        model_calls,
        task="T1_ROOT_CLASSIFICATION",
        visible={"allowed_roots": list(model_families), "context": common_context},
        output_type="ROOT_FAMILY",
        allowed=model_families,
    )
    if model_family is None:
        family = root.family
        limitations.append("MODEL_REPAIR_INTENT_INVALID")
    else:
        matches = sorted(
            unified_family
            for unified_family in available_families
            if model_family in FAMILY_TO_MODEL_ROOTS.get(unified_family, ())
        )
        family = root.family if root.family in matches else matches[0]
        if not any(candidate.family == family for candidate in candidates):
            limitations.append("MODEL_REPAIR_INTENT_NO_CANDIDATE_MATCH")
    filtered = tuple(candidate for candidate in candidates if candidate.family == family) or candidates

    targets = _target_catalog(root, context)
    selected_target_token = _selection(
        backend,
        model_calls,
        task="T2_TARGET_LOCALIZATION",
        visible={"context": common_context, "targets": targets},
        output_type="TARGET_ID",
        allowed=tuple(row["id"] for row in targets),
    )
    selected_target = next((
        str(row["root_id"]) for row in targets
        if row["id"] == selected_target_token
    ), None)
    target_localized = selected_target == root.root_id
    if selected_target_token is None:
        limitations.append("MODEL_TARGET_LOCALIZATION_INVALID")
    elif not target_localized:
        limitations.append("MODEL_TARGET_LOCALIZATION_MISMATCH")

    def simulate(candidate: RepairCandidate) -> Any:
        static, proposed = validate_candidate_static(candidate, context)
        return {
            "passed": static.passed,
            "proposed_sha256": sha256(proposed.encode("utf-8")).hexdigest() if proposed else None,
            "reasons": list(static.reasons),
        }

    runtime = build_standard_tool_runtime(
        context,
        candidates={candidate.candidate_id: candidate for candidate in filtered},
        case_index=case_index,
        simulate=simulate,
        run_candidate=run_candidate,
        maximum_calls=maximum_tool_calls,
        allowed_tools=enabled_tools,
    )
    catalog = _tool_catalog(root, context, enabled_tools)
    allowed_tools = tuple(row["name"] for row in catalog)
    selected_tool: str | None = None
    selected_tool_arguments: Mapping[str, Any] | None = None
    observation: Mapping[str, Any] | None = None
    if not allowed_tools:
        limitations.append("MODEL_TOOLS_DISABLED")
    else:
        selected_tool = _selection(
            backend,
            model_calls,
            task="T3_TOOL_SELECTION",
            visible={"context": common_context, "tools": catalog},
            output_type="TOOL_NAME",
            allowed=allowed_tools,
        )
        if selected_tool is None:
            limitations.append("MODEL_TOOL_SELECTION_INVALID")
        elif maximum_tool_calls <= 0:
            limitations.append("MODEL_TOOL_CALL_LIMIT_ZERO")
        else:
            selected_tool_arguments = _tool_arguments(
                selected_tool, root, context, filtered,
            )
            try:
                result = runtime.call(ToolRequest(selected_tool, selected_tool_arguments))
                observation = _tool_observation(selected_tool, result, succeeded=True)
            except Exception as exc:
                observation = _tool_observation(
                    selected_tool, {"error_type": type(exc).__name__}, succeeded=False,
                )
                limitations.append(f"MODEL_TOOL_FAILED:{type(exc).__name__}")

    candidate_rows = _candidate_catalog(filtered)
    candidate_tokens = {
        f"CANDIDATE_{index:02d}": candidate.candidate_id
        for index, candidate in enumerate(filtered, start=1)
    }
    for row, token in zip(candidate_rows, candidate_tokens, strict=True):
        row["candidate_id"] = row.pop("id")
        row["id"] = token
    selected_candidate_token = _selection(
        backend,
        model_calls,
        task="T4_CANDIDATE_SELECTION",
        visible={
            "candidates": candidate_rows,
            "context": {
                **common_context,
                "tool_observation": _visible_observation(observation),
            },
        },
        output_type="MODEL_DECISION",
        allowed=tuple(candidate_tokens) + ("ABSTAIN",),
    )
    selected_candidate = (
        candidate_tokens.get(selected_candidate_token)
        if selected_candidate_token != "ABSTAIN" else "ABSTAIN"
    )
    compiled: tuple[RepairCandidate, ...] = ()
    selected_source: RepairCandidate | None = None
    if selected_candidate is None:
        limitations.append("MODEL_CANDIDATE_SELECTION_INVALID")
    elif selected_candidate == "ABSTAIN":
        limitations.append("MODEL_SAFE_ABSTENTION")
    else:
        selected_source = next(
            candidate for candidate in filtered
            if candidate.candidate_id == selected_candidate
        )

    plan_id: str | None = None
    plan_payload: Mapping[str, Any] | None = None
    plan_catalog = []
    if selected_source is not None:
        plan_id, plan_payload = _finite_plan(
            selected_source,
            root=root,
            family=family,
            evidence_codes=evidence_codes,
            selected_tool=selected_tool,
            tool_arguments=selected_tool_arguments,
        )
        plan_catalog.append({
            "candidate_id": selected_source.candidate_id,
            "complete": True,
            "conflict_free": True,
            "conflict_count": 0,
            "coverage_count": 1,
            "id": "PLAN_01",
            "patches": len(selected_source.operations),
            "score": min(1000, 1000 - len(selected_source.operations)),
            "schema": "RepairPlan",
        })
    selected_plan_token = _selection(
        backend,
        model_calls,
        task="T5_PLAN_SELECTION",
        visible={
            "context": common_context,
            "plans": plan_catalog,
            "recommended_candidate_id": selected_candidate_token,
            "tool_observation": _visible_observation(observation),
        },
        output_type="MODEL_DECISION",
        allowed=tuple(row["id"] for row in plan_catalog) + ("ABSTAIN",),
    )
    selected_plan = plan_id if selected_plan_token == "PLAN_01" else selected_plan_token
    if selected_plan_token is None:
        limitations.append("MODEL_REPAIR_PLAN_INVALID")
    elif selected_plan == "ABSTAIN":
        limitations.append("MODEL_REPAIR_PLAN_ABSTAINED")
    elif selected_plan != plan_id or plan_payload is None:
        limitations.append("MODEL_REPAIR_PLAN_OUTSIDE_CATALOG")
    else:
        model_calls[-1] = {
            **dict(model_calls[-1]),
            "plan_id": selected_plan_token,
            "plan_schema_sha256": sha256(json.dumps(
                plan_payload, ensure_ascii=False, sort_keys=True,
            ).encode("utf-8")).hexdigest(),
            "plan_schema_valid": True,
        }

    scores = sorted(
        (round(candidate.confidence * 1000) for candidate in filtered), reverse=True,
    )
    release_decision = _selection(
        backend,
        model_calls,
        task="T6_SAFE_ABSTENTION",
        visible={
            "abstention": {
                "ambiguity_margin_milli": 25,
                "evidence_count": max(3, len(selected_source.evidence)) if selected_source else 0,
                "minimum_evidence_count": 2,
                "minimum_score_milli": 700,
                "runner_up_score_milli": scores[1] if len(scores) > 1 else 0,
                "top_score_milli": scores[0] if selected_source else 0,
            },
            "allowed_decisions": ["ABSTAIN", "CONTINUE"],
            "candidate_count": 1 if selected_source else 0,
            "context": common_context,
        },
        output_type="MODEL_DECISION",
        allowed=("CONTINUE", "ABSTAIN"),
    )
    if release_decision is None:
        limitations.append("MODEL_SAFE_ABSTENTION_INVALID")
    elif release_decision == "ABSTAIN":
        limitations.append("MODEL_EXPLICIT_SAFE_ABSTENTION")
    elif (
        target_localized
        and selected_source is not None
        and selected_plan == plan_id
        and plan_payload is not None
    ):
        source = selected_source
        identity = sha256(
            f"{backend.__class__.__name__}:{source.input_sha256}:{source.root_id}:{source.candidate_id}".encode()
        ).hexdigest()[:24]
        compiled = (replace(
            source,
            candidate_id=identity,
            evidence=source.evidence + (CandidateEvidence(
                kind="model_closed_set_selection",
                source="local_qwen_selector",
                strength=0.6,
                details={
                    "base_candidate_id": source.candidate_id,
                    "selected_family": family,
                    "selected_model_root": model_family,
                    "selected_tool": selected_tool,
                    "selected_target_id": selected_target,
                    "selected_plan_id": selected_plan,
                    "tool_observation_sha256": (
                        observation.get("result_sha256") if observation else None
                    ),
                },
            ),),
            metadata={
                **source.metadata,
                "base_candidate_id": source.candidate_id,
                "model_selected_family": family,
                "model_selected_root": model_family,
                "model_selected_tool": selected_tool,
                "model_selected_target_id": selected_target,
                "model_selected_plan_id": selected_plan,
                "model_safe_abstention": release_decision,
            },
            provenance=Provenance.MODEL_PROPOSED,
            score=None,
            requires_user_confirmation=True,
        ),)
    tool_calls = tuple({
        "arguments": dict(row.arguments),
        "result": _bounded_result(row.result),
        "succeeded": row.succeeded,
        "tool": row.tool,
    } for row in runtime.records)
    return ModelIntegrationResult(
        compiled,
        tuple(model_calls),
        tool_calls,
        tuple(limitations),
    )


def select_after_failure(
    backend: SelectorBackend,
    *,
    root: DiagnosticRoot,
    context: CandidateContext,
    failed_candidate: RepairCandidate,
    remaining_candidates: tuple[RepairCandidate, ...],
    failure_stage: str,
    failure_reasons: tuple[str, ...],
) -> ModelFeedbackResult:
    '''把结构化门禁失败反馈给模型，仅允许重排剩余候选 ID。'''
    if not remaining_candidates:
        return ModelFeedbackResult((), None, None)
    visible = {
        "candidates": _candidate_catalog(remaining_candidates),
        "context": {
            "evidence": _evidence_codes(root),
            "field_index": _field_index(root),
            "field_role": root.field_name,
            "object_type": root.object_type,
            "version_pair": [context.version, context.version],
        },
        "previous_failure": {
            "candidate_id": failed_candidate.candidate_id,
            "reasons": list(failure_reasons)[:8],
            "stage": failure_stage,
        },
    }
    allowed = tuple(candidate.candidate_id for candidate in remaining_candidates) + ("ABSTAIN",)
    try:
        result = backend.select(
            task="T4_CANDIDATE_SELECTION",
            visible=visible,
            expected_output_type="MODEL_DECISION",
            allowed_values=allowed,
        )
    except Exception as exc:
        return ModelFeedbackResult(
            remaining_candidates,
            {
                "error": f"{type(exc).__name__}:{exc}",
                "failure_stage": failure_stage,
                "status": "FEEDBACK_FAILED_CLOSED",
                "task": "T4_CANDIDATE_SELECTION",
            },
            "MODEL_FEEDBACK_INVALID",
        )
    record = {
        **dict(result.record),
        "failed_candidate_id": failed_candidate.candidate_id,
        "failure_stage": failure_stage,
        "status": "FEEDBACK_ACCEPTED_SCHEMA",
    }
    selected = result.decision.value
    if selected == "ABSTAIN":
        return ModelFeedbackResult(
            remaining_candidates, record, "MODEL_FEEDBACK_SAFE_ABSTENTION",
        )
    ordered = tuple(sorted(
        remaining_candidates,
        key=lambda candidate: candidate.candidate_id != selected,
    ))
    return ModelFeedbackResult(ordered, record, None)


__all__ = [
    "ModelFeedbackResult",
    "ModelIntegrationResult",
    "SelectorBackend",
    "integrate_model_candidates",
    "select_after_failure",
]
