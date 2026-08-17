"""Public orchestration boundary for one unified engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from idfrepair.candidates import CandidateRegistry
from idfrepair.capabilities.registry import (
    ReleaseCandidateRegistry,
    build_release_candidate_registry,
)
from idfrepair.capabilities.reporting import empty_registry_audit
from idfrepair.candidates.base import CandidateContext
from idfrepair.config import EngineConfig
from idfrepair.domain.enums import RepairStatus
from idfrepair.domain.models import PendingRepairState, RepairCandidate, RepairOutcome
from idfrepair.engine.search import RunEnergyPlus, SearchEngine
from idfrepair.io.idf import parse_idf, text_sha256
from idfrepair.knowledge.idd import parse_idd
from idfrepair.knowledge.object_graph import build_object_graph
from idfrepair.knowledge.rdd import parse_rdd
from idfrepair.validation.terminal_safety import repaired_artifact_allowed


class UnifiedEngine:
    def __init__(
        self,
        runner: RunEnergyPlus,
        idd_text: str,
        *,
        config: EngineConfig | None = None,
        registry: CandidateRegistry | None = None,
        context_metadata: Mapping[str, object] | None = None,
    ) -> None:
        self.config = config or EngineConfig()
        self.context_metadata = dict(context_metadata or {})
        if registry is None and (
            self.config.model != "none"
            or self.config.model_base_path is not None
            or self.config.model_adapter_path is not None
            or self.config.model_runtime_python is not None
        ):
            raise ValueError("model_component_not_release_authorized")
        selected_registry: CandidateRegistry | ReleaseCandidateRegistry = (
            registry
            if registry is not None
            else build_release_candidate_registry(self.config.mode)
        )
        self.registry = selected_registry
        self.idd = parse_idd(idd_text)
        self.search = SearchEngine(
            runner,
            self.idd,
            config=self.config,
            registry=selected_registry,
            context_metadata=self.context_metadata,
        )

    def support_registry_audit(self) -> dict[str, Any]:
        '''返回本次公共运行的 Registry 调用与根支持快照。'''
        if isinstance(self.registry, ReleaseCandidateRegistry):
            return self.registry.audit_snapshot()
        return empty_registry_audit()

    def terminal_safety_evidence(self) -> dict[str, Any]:
        '''Return aggregate evidence from the last terminal transaction gate.'''
        return dict(self.search.last_terminal_safety)

    def repair_text(
        self,
        text: str,
        *,
        approved_candidate_ids: Iterable[str] = (),
        extra_candidates: Iterable[RepairCandidate] = (),
        pending_state: PendingRepairState | None = None,
    ) -> RepairOutcome:
        document = parse_idf(text)
        approved = tuple(approved_candidate_ids)
        injected = tuple(extra_candidates)
        if isinstance(self.registry, ReleaseCandidateRegistry):
            injected = self.registry.authorize_injected_candidates(injected, approved)
        outcome = self.search.repair(
            text,
            approved_candidate_ids=approved,
            extra_candidates=injected,
            pending_state=pending_state,
        )
        if isinstance(self.registry, ReleaseCandidateRegistry):
            roots = tuple(outcome.initial_diagnostics)
            context = CandidateContext(
                document=document,
                idd=self.idd,
                roots=roots,
                diagnostics_text=outcome.initial_energyplus_diagnostics,
                rdd=parse_rdd(""),
                version=str(
                    self.context_metadata.get("target_version") or document.version
                ),
                runtime_identity={},
                object_graph=build_object_graph(document, self.idd),
                metadata=self.context_metadata,
            )
            self.registry.record_unreached_decisions(roots, context)
            outcome = self.registry.apply_terminal_disposition(outcome)
        terminal_ablation = bool(
            self.context_metadata.get("evaluation_skip_terminal_safety_guard")
            and self.context_metadata.get("evaluation_isolated") is True
            and self.context_metadata.get("evaluation_persist_output") is False
        )
        if (
            outcome.status is RepairStatus.REPAIRED
            and not terminal_ablation
            and not repaired_artifact_allowed(outcome)
        ):
            outcome.status = RepairStatus.ROLLED_BACK
            outcome.rollback_reason = "orchestrator_repaired_artifact_guard_rejected"
            outcome.terminal_safety_admitted = False
            outcome.terminal_safety_disposition = "REPAIRED_REJECTED"
        if outcome.status is not RepairStatus.REPAIRED:
            outcome.output_text = text
            outcome.output_sha256 = text_sha256(text)
        return outcome

    def repair_file(
        self,
        path: Path,
        *,
        approved_candidate_ids: Iterable[str] = (),
        extra_candidates: Iterable[RepairCandidate] = (),
    ) -> RepairOutcome:
        return self.repair_text(
            path.read_text(encoding="utf-8-sig"),
            approved_candidate_ids=approved_candidate_ids,
            extra_candidates=extra_candidates,
        )
