"""Strict model planner interface; no direct file mutation is accepted."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from idfrepair.models.tool_runtime import ToolRuntime
from idfrepair.models.contracts import RepairPlan, parse_repair_plan
from idfrepair.domain.models import DiagnosticRoot, RepairCandidate, to_primitive
from idfrepair.candidates.base import CandidateContext


class PlannerBackend(Protocol):
    def generate(self, request: Mapping[str, Any]) -> str | Mapping[str, Any]: ...


class LLMPlanner:
    def __init__(self, backend: PlannerBackend) -> None:
        self.backend = backend

    def plan(self, request: Mapping[str, Any]) -> RepairPlan:
        return parse_repair_plan(self.backend.generate(request))

    def plan_with_tools(
        self,
        request: Mapping[str, Any],
        runtime: ToolRuntime,
    ) -> tuple[RepairPlan, tuple[Any, ...]]:
        plan = self.plan(request)
        results = tuple(runtime.call(tool) for tool in plan.requested_tools)
        return plan, results


def build_planner_request(
    root: DiagnosticRoot,
    context: CandidateContext,
    candidates: tuple[RepairCandidate, ...],
) -> dict[str, Any]:
    '''构造不含 gold 的模型上下文，并显式携带案例检索审计记录。'''
    return {
        "schema_version": "idfrepair.model.request.v1",
        "root": to_primitive(root),
        "input_sha256": context.input_sha256,
        "idd_sha256": context.idd_sha256,
        "version": context.version,
        "candidate_catalog": tuple({
            "candidate_id": candidate.candidate_id,
            "family": candidate.family,
            "provider": candidate.provider,
            "confidence": candidate.confidence,
            "risk": candidate.risk.value,
            "evidence": to_primitive(candidate.evidence),
        } for candidate in candidates),
        "retrieved_cases": to_primitive(context.metadata.get("retrieved_cases", ())),
    }


@dataclass(frozen=True, slots=True)
class PlanDisposition:
    requires_user_input: bool
    reason: str | None


def plan_disposition(plan: RepairPlan, *, minimum_confidence: float = 0.65) -> PlanDisposition:
    if plan.needs_user_input:
        return PlanDisposition(True, "model_requested_user_input")
    if plan.confidence < minimum_confidence:
        return PlanDisposition(True, "model_confidence_below_threshold")
    if plan.ambiguities:
        return PlanDisposition(True, "model_reported_ambiguity")
    return PlanDisposition(False, None)
