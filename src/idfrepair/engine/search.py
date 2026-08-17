"""Candidate retry, multi-error closure, and limited backtracking."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import time
from typing import Any, Callable, Iterable, Mapping

from idfrepair.candidates import CandidateRegistry, default_registry
from idfrepair.candidates.base import CandidateContext
from idfrepair.candidates.retrieval import attach_retrieval_evidence
from idfrepair.candidates.transition_lineage import (
    _VerifiedTransitionLineage,
    transition_lineage_root,
)
from idfrepair.config import EngineConfig
from idfrepair.diagnostics.roots import (
    bind_output_roots_to_document,
    bind_roots_to_document,
    build_roots,
)
from idfrepair.diagnostics.clusters import cluster_roots, has_renderable_questions
from idfrepair.diagnostics.err_parser import parse_err
from idfrepair.diagnostics.ledger import LatentFaultLedger, completion_certificate
from idfrepair.diagnostics.semantic_preflight import (
    SemanticPreflight,
    scan_semantic_issues,
    semantic_roots,
)
from idfrepair.domain.enums import Provenance, RepairMode, RepairStatus, ValidationStage
from idfrepair.domain.models import (
    CommittedRound,
    DiagnosticRoot,
    EnergyPlusResult,
    PendingDecisionFrame,
    PendingFaultLedgerState,
    PendingRepairState,
    RepairAttempt,
    RepairCandidate,
    RepairOutcome,
    ValidationResult,
    pending_repair_checkpoint_id,
    pending_repair_state_is_valid,
    to_primitive,
)
from idfrepair.engine.transaction import patch_locations
from idfrepair.interaction.questions import question_for_context
from idfrepair.io.idf import canonical, parse_idf, text_sha256
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.knowledge.case_retrieval import CaseIndex, query_tokens
from idfrepair.knowledge.object_graph import build_object_graph
from idfrepair.knowledge.provenance import (
    resolve_single_object_superset,
    unique_missing_reference,
)
from idfrepair.knowledge.rdd import parse_rdd
from idfrepair.models.integration import integrate_model_candidates, select_after_failure
from idfrepair.models.qwen import QwenPlannerBackend
from idfrepair.planning.policy import candidate_is_eligible
from idfrepair.planning.ranking import rank_candidates
from idfrepair.validation.final import validate_final
from idfrepair.validation.semantic import validate_candidate_semantics
from idfrepair.validation.static import validate_candidate_static
from idfrepair.validation.terminal_safety import (
    TerminalSafetyEvidence,
    enforce_terminal_safety,
)
from idfrepair.validation.transition import validate_transition


RunEnergyPlus = Callable[[str, int], EnergyPlusResult]


def _failure_validation(stage: ValidationStage, reason: str) -> ValidationResult:
    return ValidationResult(stage=stage, passed=False, reasons=(reason,))


class SearchEngine:
    """Depth-first bounded search with state-bound candidate regeneration."""

    def __init__(
        self,
        runner: RunEnergyPlus,
        idd: IDDSchema,
        *,
        config: EngineConfig | None = None,
        registry: CandidateRegistry | None = None,
        context_metadata: Mapping[str, Any] | None = None,
        _verified_transition_lineage: _VerifiedTransitionLineage | None = None,
    ) -> None:
        self.runner = runner
        self.idd = idd
        self.config = config or EngineConfig()
        self.registry = registry or default_registry()
        self.context_metadata = dict(context_metadata or {})
        if "transition_lineage" in self.context_metadata:
            raise ValueError(
                "transition_lineage_requires_internal_verified_channel"
            )
        if _verified_transition_lineage is not None:
            if not isinstance(
                _verified_transition_lineage,
                _VerifiedTransitionLineage,
            ):
                raise TypeError("transition_lineage_internal_type_invalid")
            self.context_metadata["transition_lineage"] = (
                _verified_transition_lineage
            )
        self._evaluation_skip_semantic_gate = bool(
            self.context_metadata.get("evaluation_skip_semantic_gate", False)
        )
        self._evaluation_skip_whole_file_preflight = bool(
            self.context_metadata.get(
                "evaluation_skip_whole_file_semantic_preflight",
                False,
            )
        )
        self._evaluation_skip_terminal_safety = bool(
            self.context_metadata.get(
                "evaluation_skip_terminal_safety_guard",
                False,
            )
        )
        if (
            self._evaluation_skip_semantic_gate
            or self._evaluation_skip_whole_file_preflight
            or self._evaluation_skip_terminal_safety
        ) and not (
            self.context_metadata.get("evaluation_isolated") is True
            and self.context_metadata.get("evaluation_persist_output") is False
        ):
            raise ValueError(
                "evaluation_ablation_requires_isolated_nonpersisting_context"
            )
        case_index = self.context_metadata.get("case_index")
        self.case_index = case_index if isinstance(case_index, CaseIndex) else None
        injected_backend = self.context_metadata.get("model_backend")
        self._owns_model_backend = False
        self.model_backend: Any | None = None
        self._model_calls: list[Mapping[str, Any]] = []
        self._tool_calls: list[Mapping[str, Any]] = []
        self._model_limitations: list[str] = []
        self._static_reference_root_cache: dict[
            str, tuple[DiagnosticRoot, ...]
        ] = {}
        self._fault_ledger = LatentFaultLedger()
        self._last_preflight_report = SemanticPreflight(issues=(), audit={})
        self.last_semantic_preflight: dict[str, Any] = {}
        self.last_fault_ledger: dict[str, Any] = {}
        self.last_completion_certificate: dict[str, Any] = {}
        self.last_terminal_safety: dict[str, Any] = {}
        self._preferred_injected_root_ids: frozenset[str] = frozenset()
        if self.config.model != "none":
            if injected_backend is not None:
                self.model_backend = injected_backend
            else:
                self.model_backend = QwenPlannerBackend(
                    self.config.model,
                    base_path=self.config.model_base_path,
                    adapter_path=self.config.model_adapter_path,
                    runtime_python=self.config.model_runtime_python,
                    timeout_seconds=self.config.timeout_seconds,
                )
                self._owns_model_backend = True

    def _finish(self, outcome: RepairOutcome) -> RepairOutcome:
        '''附加模型审计记录并释放当前引擎拥有的本地模型进程。'''
        outcome.model_calls = list(self._model_calls)
        outcome.tool_calls = list(self._tool_calls)
        outcome.limitations.extend(
            row for row in self._model_limitations if row not in outcome.limitations
        )
        if self._owns_model_backend and hasattr(self.model_backend, "close"):
            self.model_backend.close()
        return outcome

    def _model_candidates(
        self,
        root: DiagnosticRoot,
        context: CandidateContext,
        candidates: tuple[RepairCandidate, ...],
        *,
        run_candidate: Callable[[RepairCandidate], Any] | None = None,
    ) -> tuple[RepairCandidate, ...]:
        '''调用真实关闭世界模型；任何异常只记录限制，不改变确定性安全路径。'''
        backend = self.model_backend
        if backend is None:
            return ()
        if hasattr(backend, "available") and not backend.available:
            status = getattr(backend, "status", None)
            reasons = getattr(status, "reasons", ())
            self._model_calls.append({
                "error": ";".join(reasons) or "model_runtime_unavailable",
                "model": self.config.model,
                "status": "RUNTIME_UNAVAILABLE",
            })
            self._model_limitations.append("MODEL_RUNTIME_UNAVAILABLE")
            return ()
        try:
            result = integrate_model_candidates(
                backend,
                root=root,
                context=context,
                candidates=candidates,
                case_index=self.case_index,
                maximum_tool_calls=self.config.max_model_tool_calls,
                run_candidate=run_candidate,
                allowed_tools=self.context_metadata.get("model_allowed_tools"),
            )
        except Exception as exc:
            self._model_calls.append({
                "error": f"{type(exc).__name__}:{exc}",
                "model": self.config.model,
                "status": "FAILED_CLOSED",
            })
            self._model_limitations.append("MODEL_INTEGRATION_FAILED_CLOSED")
            return ()
        self._model_calls.extend(result.model_calls)
        self._tool_calls.extend(result.tool_calls)
        self._model_limitations.extend(result.limitations)
        return result.candidates

    def _feedback_candidates(
        self,
        *,
        root: DiagnosticRoot,
        context: CandidateContext,
        failed_candidate: RepairCandidate,
        remaining: list[RepairCandidate],
        failure_stage: str,
        failure_reasons: tuple[str, ...],
    ) -> list[RepairCandidate]:
        '''允许模型读取结构化失败并重排剩余 ID，但不能新增或修改操作。'''
        if (
            self.model_backend is None
            or not remaining
            or not bool(self.context_metadata.get("model_energyplus_feedback", False))
        ):
            return remaining
        result = select_after_failure(
            self.model_backend,
            root=root,
            context=context,
            failed_candidate=failed_candidate,
            remaining_candidates=tuple(remaining),
            failure_stage=failure_stage,
            failure_reasons=failure_reasons,
        )
        if result.model_call is not None:
            self._model_calls.append(result.model_call)
        if result.limitation is not None:
            self._model_limitations.append(result.limitation)
        return list(result.candidates)

    @staticmethod
    def _record_memory_application(context: CandidateContext, attempt: RepairAttempt) -> None:
        '''把 Memory 候选的门禁结果写入仓储；记录失败不得改变规则内容。'''
        rule_id = attempt.candidate.metadata.get("memory_rule_id")
        repository = context.metadata.get("rule_repository")
        if not rule_id or not hasattr(repository, "record_application"):
            return
        validation = {
            "static": attempt.static_result,
            "semantic": attempt.semantic_result,
            "transition": attempt.transition_result,
        }
        repository.record_application(
            rule_id=str(rule_id),
            input_fingerprint=attempt.state_sha256,
            candidate_id=attempt.candidate_id,
            validation_result=validation,
            energyplus_result=attempt.energyplus_result,
            accepted=attempt.accepted,
            rejected_reason=attempt.rejection_reason,
        )

    def _context(
        self,
        text: str,
        result: EnergyPlusResult,
        roots: tuple[DiagnosticRoot, ...],
    ) -> CandidateContext:
        document = parse_idf(text)
        return CandidateContext(
            document=document,
            idd=self.idd,
            roots=roots,
            diagnostics_text=result.diagnostics,
            rdd=parse_rdd(result.rdd_text),
            version=result.runtime_identity.get("energyplus_version", document.version) or document.version,
            runtime_identity=result.runtime_identity,
            object_graph=build_object_graph(document, self.idd),
            metadata=self.context_metadata,
        )

    def _roots(self, text: str, result: EnergyPlusResult) -> tuple[DiagnosticRoot, ...]:
        document = parse_idf(text)
        rdd = parse_rdd(result.rdd_text)
        roots = bind_roots_to_document(
            build_roots(result.diagnostics),
            document=document,
            idd=self.idd,
            diagnostics_text=result.diagnostics,
        )
        roots = bind_output_roots_to_document(
            roots,
            document=document,
            idd=self.idd,
            diagnostics_text=result.diagnostics,
            rdd=rdd,
        )
        target_version = str(
            result.runtime_identity.get("energyplus_version")
            or self.context_metadata.get("target_version")
            or document.version
        )
        if self._evaluation_skip_whole_file_preflight:
            preflight = SemanticPreflight(
                issues=(),
                audit={
                    "evaluation_ablation": "whole_file_semantic_preflight_disabled",
                    "geometry_audit_passed": True,
                    "idd_audit_passed": True,
                    "rdd_audit_passed": True,
                    "reference_audit_passed": True,
                    "warning_audit_passed": True,
                },
            )
        else:
            preflight = scan_semantic_issues(
                text,
                self.idd,
                rdd,
                result.runtime_identity,
                target_version=target_version,
                diagnostics_text=result.diagnostics,
            )
        self._last_preflight_report = preflight
        self.last_semantic_preflight = preflight.to_dict()
        semantic = semantic_roots(preflight)
        replaced_families = {root.family for root in semantic}
        # Keep the original diagnostic roots as a parallel evidence channel.
        # Semantic roots remain first, but an explicitly approved, state-bound
        # user candidate may still target the diagnostic root from which its
        # interactive question was created.
        roots = (*semantic, *roots)
        lineage_root = transition_lineage_root(
            text,
            target_idd=self.idd,
            metadata=self.context_metadata,
        )
        if lineage_root is not None and all(
            root.root_id != lineage_root.root_id for root in roots
        ):
            roots = (*roots, lineage_root)
        if result.passed:
            return self._ordered_roots(roots)
        cached_static = self._static_reference_root_cache.get(document.sha256)
        if cached_static is not None:
            return self._ordered_roots((*roots, *cached_static))
        if replaced_families.intersection({"object_reference", "reference_schedule"}):
            self._static_reference_root_cache[document.sha256] = ()
            return self._ordered_roots(roots)
        missing = unique_missing_reference(document, self.idd)
        if missing is None:
            self._static_reference_root_cache[document.sha256] = ()
            return self._ordered_roots(roots)
        raw_roots = self.context_metadata.get("provenance_roots", ())
        provenance_roots = tuple(
            Path(value)
            for value in raw_roots
            if isinstance(value, (str, Path))
        ) if isinstance(raw_roots, (tuple, list)) else ()
        resolved = (
            resolve_single_object_superset(
                text,
                missing=missing,
                idd=self.idd,
                version=(
                    result.runtime_identity.get("energyplus_version")
                    or document.version
                ),
                roots=provenance_roots,
            )
            if provenance_roots else None
        )
        payload = "|".join((
            "reference",
            canonical(missing.name),
            *missing.reference_lists,
            document.sha256,
        ))
        metadata: dict[str, Any] = {
            "missing_reference_name": missing.name,
            "missing_reference_lists": missing.reference_lists,
            "owner_bindings": missing.owner_bindings,
            "fault_side_evidence": "unique_unresolved_explicit_idd_object_list",
        }
        if resolved is not None:
            metadata.update({
                "preflight_recovery_certificate": "single_object_superset_v1",
                "provenance_resolution": resolved.to_metadata(),
            })
        static_roots = (DiagnosticRoot(
            root_id=sha256(payload.encode("utf-8")).hexdigest()[:20],
            family="reference",
            message=(
                f"One explicit IDD object-list identity is unresolved: "
                f"{missing.name}."
            ),
            severity="Fatal",
            object_name=missing.name,
            signatures=tuple(
                value for value in (result.err_sha256,) if value
            ),
            metadata=metadata,
        ),)
        self._static_reference_root_cache[document.sha256] = static_roots
        return self._ordered_roots((*roots, *static_roots))

    @classmethod
    def _candidate_roots(
        cls,
        roots: Iterable[DiagnosticRoot],
        diagnostics_text: str,
    ) -> tuple[DiagnosticRoot, ...]:
        ordered = cls._ordered_roots(roots)
        actionable_ids = {
            str(cluster["root"].get("root_id") or "")
            for cluster in cluster_roots(ordered, parse_err(diagnostics_text))
        }
        return tuple(root for root in ordered if root.root_id in actionable_ids)

    @staticmethod
    def _ordered_roots(roots: Iterable[DiagnosticRoot]) -> tuple[DiagnosticRoot, ...]:
        '''按修复依赖顺序排列并去除相同 issue/root 身份。'''
        priority = {
            "syntax": 0,
            "extra_field": 1,
            "finite_key": 2,
            "reference_schedule": 3,
            "object_reference": 4,
            "output_variable": 5,
            "geometry": 6,
            "schema": 7,
            "reference": 8,
        }
        unique: dict[str, DiagnosticRoot] = {}
        for root in roots:
            identity = str(root.metadata.get("semantic_issue_id") or root.root_id)
            unique.setdefault(identity, root)
        def order(root: DiagnosticRoot) -> tuple[int, int, str]:
            base = priority.get(root.family, 99)
            # An ambiguous finite-key issue has no autonomous repair.  Keep it
            # in the ledger, but let an explicit diagnostic/user channel run
            # first; the completion certificate still prevents a partial fix
            # This prevents reporting a partial repair as REPAIRED.
            if (
                root.family == "finite_key"
                and root.metadata.get("semantic_issue") is True
                and root.metadata.get("recoverability") == "AMBIGUOUS"
            ):
                base = 90
            semantic_rank = 0 if root.metadata.get("semantic_issue") is True else 1
            return base, semantic_rank, root.root_id

        return tuple(sorted(unique.values(), key=order))

    def _update_completion_evidence(
        self,
        roots: tuple[DiagnosticRoot, ...],
        *,
        energyplus_passed: bool,
    ) -> dict[str, Any]:
        '''只根据当前已提交状态刷新 ledger 与 all-fault certificate。'''
        certificate = completion_certificate(
            self._fault_ledger,
            roots,
            self._last_preflight_report.audit,
            energyplus_passed=energyplus_passed,
        )
        self.last_fault_ledger = self._fault_ledger.to_dict()
        self.last_completion_certificate = certificate
        return certificate

    @staticmethod
    def _fault_rows(
        rows: Mapping[str, Mapping[str, Any]],
    ) -> tuple[Mapping[str, Any], ...]:
        return tuple(dict(rows[key]) for key in sorted(rows))

    def _fault_ledger_checkpoint(self) -> PendingFaultLedgerState:
        resolved = {
            issue_id: row
            for issue_id, row in self._fault_ledger.seen.items()
            if issue_id not in self._fault_ledger.current
        }
        return PendingFaultLedgerState(
            initial=self._fault_rows(self._fault_ledger.initial),
            seen=self._fault_rows(self._fault_ledger.seen),
            current=self._fault_rows(self._fault_ledger.current),
            newly_revealed=self._fault_rows(self._fault_ledger.newly_revealed),
            resolved=self._fault_rows(resolved),
        )

    def _restore_fault_ledger(self, state: PendingFaultLedgerState) -> None:
        def indexed(
            rows: tuple[Mapping[str, Any], ...],
        ) -> dict[str, dict[str, Any]]:
            return {str(row["issue_id"]): dict(row) for row in rows}

        self._fault_ledger.initial = indexed(state.initial)
        self._fault_ledger.seen = indexed(state.seen)
        self._fault_ledger.current = indexed(state.current)
        self._fault_ledger.newly_revealed = indexed(state.newly_revealed)
        self._fault_ledger.initialized = True
        self.last_fault_ledger = self._fault_ledger.to_dict()

    @staticmethod
    def _observable_ambiguity_count(
        roots: Iterable[DiagnosticRoot],
    ) -> int:
        '''Count only ambiguity already surfaced by diagnostics or preflight.'''
        observable = {"ambiguous", "needs_input", "design_intent_required"}
        syntax_object_indices = {
            root.metadata.get("object_index")
            for root in roots
            if root.family == "syntax"
            and isinstance(root.metadata.get("object_index"), int)
            and root.metadata.get("structural_kind") in {
                "missing_blank_comma",
                "missing_comma",
                "numeric_concatenation_comma",
                "schedule_compact_until_comma",
            }
        }
        count = 0
        for root in roots:
            tokens = {
                canonical(str(root.metadata.get(field, "")))
                for field in ("recoverability", "resolution", "status")
            }
            parser_cascade = bool(
                root.metadata.get("semantic_issue") is True
                and root.metadata.get("object_index") in syntax_object_indices
            )
            if parser_cascade:
                continue
            if tokens & observable:
                count += 1
        return count

    def _enforce_terminal(
        self,
        outcome: RepairOutcome,
        *,
        original: str,
        tentative_text: str,
        result: EnergyPlusResult,
        initial_ambiguity_count: int,
        user_answer_present: bool,
        already_valid: bool = False,
    ) -> RepairOutcome:
        '''Independently rescan the tentative state immediately before return.'''
        if self._evaluation_skip_terminal_safety:
            outcome.terminal_safety_admitted = False
            outcome.terminal_safety_disposition = (
                "EVALUATION_TERMINAL_SAFETY_GUARD_DISABLED"
            )
            self.last_terminal_safety = {
                "disposition": outcome.terminal_safety_disposition,
                "evaluation_ablation": True,
                "final_recheck_performed": False,
                "final_status": outcome.status.value,
                "schema_version": "idfrepair.terminal_safety_evidence.v1",
            }
            return outcome
        repository = self.context_metadata.get("rule_repository")
        for committed in outcome.committed_rounds:
            rule_id = committed.candidate.metadata.get("memory_rule_id")
            if not rule_id or not hasattr(repository, "get_rule"):
                continue
            try:
                source = repository.get_rule(str(rule_id)).source
            except (KeyError, RuntimeError, ValueError):
                continue
            source_value = getattr(source, "value", str(source))
            if source_value in {"USER_CONFIRMED", "USER_CREATED"}:
                user_answer_present = True
                break
        rechecked_roots = self._roots(tentative_text, result)
        certificate = self._update_completion_evidence(
            rechecked_roots,
            energyplus_passed=result.passed,
        )
        outcome.final_diagnostics = list(rechecked_roots)
        evidence = TerminalSafetyEvidence(
            original_text=original,
            energyplus_passed=(
                result.passed
                and not result.process_failure
                and not result.timed_out
            ),
            final_issue_count=len(rechecked_roots),
            final_audit=dict(self._last_preflight_report.audit),
            completion_certificate=certificate,
            initial_observable_ambiguity_count=initial_ambiguity_count,
            final_observable_ambiguity_count=(
                self._observable_ambiguity_count(rechecked_roots)
            ),
            user_answer_present=user_answer_present,
            already_valid=already_valid,
            final_recheck_performed=True,
        )
        enforced = enforce_terminal_safety(outcome, evidence)
        self.last_terminal_safety = {
            **evidence.to_dict(),
            "disposition": enforced.terminal_safety_disposition,
            "final_status": enforced.status.value,
            "rollback_reason": enforced.rollback_reason,
        }
        return enforced

    def repair(
        self,
        original: str,
        *,
        approved_candidate_ids: Iterable[str] = (),
        extra_candidates: Iterable[RepairCandidate] = (),
        pending_state: PendingRepairState | None = None,
    ) -> RepairOutcome:
        started = time.monotonic()
        input_sha = text_sha256(original)
        approved = frozenset(approved_candidate_ids)
        injected = tuple(extra_candidates)
        self._preferred_injected_root_ids = frozenset(
            candidate.root_id
            for candidate in injected
            if candidate.candidate_id in approved
        )
        self._model_calls = []
        self._tool_calls = []
        self._model_limitations = []
        self._fault_ledger = LatentFaultLedger()
        self.last_semantic_preflight = {}
        self.last_fault_ledger = {}
        self.last_completion_certificate = {}
        self.last_terminal_safety = {}
        if pending_state is not None and not pending_repair_state_is_valid(
            pending_state,
            original_input_sha256=input_sha,
        ):
            raise ValueError("pending_repair_state_invalid")
        attempts = list(pending_state.attempts) if pending_state else []
        committed = list(pending_state.committed_rounds) if pending_state else []
        rejected = list(pending_state.rejected_candidates) if pending_state else []
        failed_keys: set[tuple[str, str, str]] = (
            set(pending_state.failed_candidate_keys)
            if pending_state is not None
            else {
                (attempt.state_sha256, attempt.root_id, attempt.candidate_id)
                for attempt in attempts
                if not attempt.accepted
            }
        )
        seen_states = (
            set(pending_state.seen_state_sha256s)
            if pending_state is not None
            else {input_sha}
        )
        model_preview_results: dict[str, EnergyPlusResult] = {}
        decision_stack = (
            list(pending_state.decision_stack) if pending_state is not None else []
        )
        current_text = (
            pending_state.working_text if pending_state is not None else original
        )
        if pending_state is not None:
            assert pending_state.working_result is not None
            current_result = pending_state.working_result
            run_count = pending_state.energyplus_runs
            initial_roots = tuple(pending_state.initial_diagnostics)
            initial_diagnostics_text = (
                pending_state.initial_energyplus_diagnostics
            )
        else:
            current_result = self.runner(current_text, len(committed))
            run_count = (pending_state.energyplus_runs if pending_state else 0) + 1
            initial_roots = (
                tuple(pending_state.initial_diagnostics)
                if pending_state is not None
                else self._roots(original, current_result)
            )
            initial_diagnostics_text = (
                pending_state.initial_energyplus_diagnostics
                if pending_state is not None
                else current_result.diagnostics
            )
        initial_ambiguity_count = self._observable_ambiguity_count(initial_roots)
        user_answer_present = bool(
            approved
            or any(
                self.context_metadata.get(key)
                for key in (
                    "user_field_values",
                    "user_selected_families",
                    "user_selected_objects",
                )
            )
        )
        if pending_state is not None:
            self._restore_fault_ledger(pending_state.fault_ledger)
        else:
            self._fault_ledger.initialize(initial_roots)
            self.last_fault_ledger = self._fault_ledger.to_dict()
        backtracks = pending_state.backtracks if pending_state else 0
        terminal_reason: str | None = None
        terminal_status: RepairStatus | None = None

        preflight_recoverable = any(
            root.metadata.get("preflight_recovery_certificate")
            == "single_object_superset_v1"
            for root in initial_roots
        )
        if (
            pending_state is None
            and (current_result.process_failure or current_result.timed_out)
            and not preflight_recoverable
        ):
            terminal_status = RepairStatus.PROCESS_FAILED
            terminal_reason = "initial_energyplus_process_failure"
        elif pending_state is None and current_result.passed and not initial_roots:
            self._update_completion_evidence(
                initial_roots,
                energyplus_passed=True,
            )
            return self._finish(self._enforce_terminal(RepairOutcome(
                status=RepairStatus.VALID,
                input_sha256=input_sha,
                output_sha256=input_sha,
                output_text=original,
                initial_diagnostics=[],
                final_diagnostics=[],
                energyplus_runs=1,
                initial_energyplus_diagnostics=initial_diagnostics_text,
            ),
                original=original,
                tentative_text=original,
                result=current_result,
                initial_ambiguity_count=initial_ambiguity_count,
                user_answer_present=user_answer_present,
                already_valid=True,
            ))

        while terminal_status is None:
            elapsed = time.monotonic() - started
            if elapsed > self.config.max_wall_time:
                terminal_status = RepairStatus.LIMIT_REACHED
                terminal_reason = "max_wall_time_exceeded"
                break
            roots = self._roots(current_text, current_result)
            candidate_roots = self._candidate_roots(roots, current_result.diagnostics)
            certificate = self._update_completion_evidence(
                roots,
                energyplus_passed=current_result.passed,
            )
            if current_result.passed and not roots:
                final_result = validate_final(current_result, roots)
                if final_result.passed and certificate["passed"] is True:
                    output_sha = text_sha256(current_text)
                    return self._finish(self._enforce_terminal(RepairOutcome(
                        status=RepairStatus.REPAIRED,
                        input_sha256=input_sha,
                        output_sha256=output_sha,
                        output_text=current_text,
                        initial_diagnostics=list(initial_roots),
                        final_diagnostics=[],
                        attempts=attempts,
                        committed_rounds=committed,
                        rejected_candidates=rejected,
                        backtracks=backtracks,
                        energyplus_runs=run_count,
                        initial_energyplus_diagnostics=initial_diagnostics_text,
                    ),
                        original=original,
                        tentative_text=current_text,
                        result=current_result,
                        initial_ambiguity_count=initial_ambiguity_count,
                        user_answer_present=user_answer_present,
                    ))
            if len(committed) >= self.config.max_rounds:
                terminal_status = RepairStatus.LIMIT_REACHED
                terminal_reason = "max_rounds_exceeded"
                break
            if run_count >= self.config.max_total_energyplus_runs:
                terminal_status = RepairStatus.LIMIT_REACHED
                terminal_reason = "max_total_energyplus_runs_exceeded"
                break
            if not candidate_roots:
                terminal_status = RepairStatus.UNSUPPORTED
                terminal_reason = "energyplus_failed_without_actionable_root"
                break
            preferred = next((
                root for root in candidate_roots
                if root.root_id in self._preferred_injected_root_ids
                and any(
                    candidate.root_id == root.root_id
                    and candidate.input_sha256 == text_sha256(current_text)
                    and candidate.idd_sha256 == self.idd.sha256
                    for candidate in injected
                )
            ), None)
            if preferred is not None:
                candidate_roots = (preferred, *(
                    root for root in candidate_roots if root.root_id != preferred.root_id
                ))
            root = candidate_roots[0]
            selected_families = self.context_metadata.get("user_selected_families", {})
            selected_objects = self.context_metadata.get("user_selected_objects", {})
            if isinstance(selected_families, Mapping):
                selected_family = selected_families.get(root.root_id)
                if isinstance(selected_family, str):
                    root = replace(root, family=selected_family)
            if isinstance(selected_objects, Mapping):
                selected_object = selected_objects.get(root.root_id)
                if isinstance(selected_object, Mapping):
                    root = replace(
                        root,
                        object_type=(
                            str(selected_object["object_type"])
                            if selected_object.get("object_type") else root.object_type
                        ),
                        object_name=(
                            str(selected_object["object_name"])
                            if selected_object.get("object_name") else root.object_name
                        ),
                        metadata={
                            **root.metadata,
                            "object_index": selected_object.get("object_index"),
                            "user_selected_object": True,
                        },
                    )
            context_roots = (root, *(
                row for row in roots if row.root_id != root.root_id
            ))
            context = self._context(current_text, current_result, context_roots)
            retrieved = ()
            if self.case_index is not None:
                allowed_usage = context.metadata.get("retrieval_allowed_usage", (
                    "development-exposed", "demo-only",
                ))
                retrieved = self.case_index.retrieve(
                    error_tokens=query_tokens((root.family, root.message, *root.signatures)),
                    object_types=(root.object_type,) if root.object_type else (),
                    field_roles=(root.field_name,) if root.field_name else (),
                    limit=int(context.metadata.get("retrieval_limit", 5)),
                    allowed_usage=allowed_usage,
                )
                context = replace(context, metadata={
                    **context.metadata,
                    "retrieved_cases": tuple({
                        "case_id": row.case_id,
                        "similarity": row.score,
                        "matching_features": row.matching_features,
                        "usage_status": row.usage_status,
                    } for row in retrieved),
                })
            generated = tuple(
                attach_retrieval_evidence(candidate, retrieved)
                for candidate in self.registry.generate(root, context)
            )
            additions = tuple(
                candidate for candidate in injected
                if candidate.input_sha256 == context.input_sha256
                and candidate.idd_sha256 == context.idd_sha256
                and candidate.version == context.version
                and candidate.root_id == root.root_id
            )
            pooled = {candidate.candidate_id: candidate for candidate in (*generated, *additions)}
            preliminary = rank_candidates(tuple(pooled[key] for key in sorted(pooled)))

            def run_model_candidate(candidate: RepairCandidate) -> Any:
                '''在同一预算内执行模型请求的候选预览，并缓存供统一门禁复用。'''
                nonlocal run_count
                static_result, proposed = validate_candidate_static(candidate, context)
                if not static_result.passed or proposed is None:
                    return {"reasons": list(static_result.reasons), "status": "STATIC_REJECTED"}
                provider = self.registry.provider(candidate.provider)
                semantic_result = self._semantic_validation(
                    provider=provider, before=current_text, after=proposed,
                    candidate=candidate, context=context,
                )
                if not semantic_result.passed:
                    return {"reasons": list(semantic_result.reasons), "status": "SEMANTIC_REJECTED"}
                proposed_sha = text_sha256(proposed)
                cached = model_preview_results.get(proposed_sha)
                if cached is None:
                    if run_count >= self.config.max_total_energyplus_runs:
                        return {"status": "ENERGYPLUS_BUDGET_EXHAUSTED"}
                    cached = self.runner(proposed, len(committed) + 1)
                    run_count += 1
                    model_preview_results[proposed_sha] = cached
                return {
                    "candidate_id": candidate.candidate_id,
                    "fatal_count": cached.fatal_count,
                    "passed": cached.passed,
                    "process_failure": cached.process_failure,
                    "severe_count": cached.severe_count,
                    "status": "ENERGYPLUS_EXECUTED",
                    "timed_out": cached.timed_out,
                }

            model_candidates = self._model_candidates(
                root,
                context,
                preliminary[:self.config.max_candidates_per_root],
                run_candidate=run_model_candidate,
            )
            pooled.update({candidate.candidate_id: candidate for candidate in model_candidates})
            ranked_all = rank_candidates(tuple(pooled[key] for key in sorted(pooled)))
            if self.config.mode in {RepairMode.SAFE_AUTO, RepairMode.ANALYZE_ONLY}:
                ranked_all = tuple(
                    candidate for candidate in ranked_all
                    if candidate.provenance is not Provenance.MODEL_PROPOSED
                )
            ranked = tuple(
                candidate for candidate in ranked_all
                if (context.input_sha256, root.root_id, candidate.candidate_id) not in failed_keys
            )[:self.config.max_candidates_per_root]
            if self.config.mode is RepairMode.ANALYZE_ONLY:
                terminal_status = RepairStatus.UNSUPPORTED
                terminal_reason = "analyze_only"
                break
            if self.config.mode is RepairMode.ASSISTED and ranked and not any(
                candidate.candidate_id in approved for candidate in ranked
            ):
                return self._finish(self._enforce_terminal(self._needs_input(
                    original=original,
                    input_sha=input_sha,
                    initial_roots=initial_roots,
                    current_roots=roots,
                    attempts=attempts,
                    committed=committed,
                    rejected=rejected,
                    backtracks=backtracks,
                    run_count=run_count,
                    root=root,
                    candidates=ranked,
                    reason="assisted_confirmation_required",
                    initial_diagnostics_text=initial_diagnostics_text,
                    current_text=current_text,
                    current_result=current_result,
                    decision_stack=decision_stack,
                    failed_keys=failed_keys,
                    seen_states=seen_states,
                    context=context,
                ),
                    original=original,
                    tentative_text=current_text,
                    result=current_result,
                    initial_ambiguity_count=initial_ambiguity_count,
                    user_answer_present=user_answer_present,
                ))
            eligible = tuple(
                replace(
                    candidate,
                    provenance=(
                        candidate.provenance
                        if candidate.provenance is Provenance.USER_SUPPLIED
                        else Provenance.USER_SELECTED
                    ),
                    requires_user_confirmation=False,
                )
                if candidate.candidate_id in approved else candidate
                for candidate in ranked
                if candidate.candidate_id in approved or candidate_is_eligible(candidate, self.config)
            )
            if not eligible:
                if (
                    self.config.mode in {RepairMode.INTERACTIVE, RepairMode.ASSISTED}
                    or ranked
                ):
                    return self._finish(self._enforce_terminal(self._needs_input(
                        original=original,
                        input_sha=input_sha,
                        initial_roots=initial_roots,
                        current_roots=roots,
                        attempts=attempts,
                        committed=committed,
                        rejected=rejected,
                        backtracks=backtracks,
                        run_count=run_count,
                        root=root,
                        candidates=ranked,
                        reason="no_automatic_candidate",
                        initial_diagnostics_text=initial_diagnostics_text,
                        current_text=current_text,
                        current_result=current_result,
                        decision_stack=decision_stack,
                        failed_keys=failed_keys,
                        seen_states=seen_states,
                        context=context,
                    ),
                        original=original,
                        tentative_text=current_text,
                        result=current_result,
                        initial_ambiguity_count=initial_ambiguity_count,
                        user_answer_present=user_answer_present,
                    ))
                restored = self._backtrack(
                    decision_stack,
                    failed_keys,
                    committed,
                    backtracks,
                )
                if restored is not None and backtracks < self.config.max_backtracks:
                    current_text, current_result, backtracks = restored
                    continue
                terminal_status = RepairStatus.UNSUPPORTED
                terminal_reason = "provider_unavailable"
                break

            accepted = False
            touched = set().union(*(patch_locations(round_.candidate) for round_ in committed)) if committed else set()
            eligible_queue = list(eligible)
            rank = 0
            while eligible_queue:
                candidate = eligible_queue.pop(0)
                rank += 1
                key = (context.input_sha256, root.root_id, candidate.candidate_id)
                locations = patch_locations(candidate)
                if locations & touched:
                    static_result = _failure_validation(ValidationStage.STATIC, "patch_conflict")
                    semantic_result = _failure_validation(ValidationStage.SEMANTIC, "not_run")
                    attempts.append(RepairAttempt(
                        state_sha256=context.input_sha256,
                        root_id=root.root_id,
                        candidate_id=candidate.candidate_id,
                        rank=rank,
                        candidate=candidate,
                        static_result=static_result,
                        semantic_result=semantic_result,
                        energyplus_result=None,
                        transition_result=None,
                        accepted=False,
                        rejection_reason="patch_conflict",
                    ))
                    self._record_memory_application(context, attempts[-1])
                    failed_keys.add(key)
                    rejected.append(candidate.candidate_id)
                    eligible_queue = self._feedback_candidates(
                        root=root,
                        context=context,
                        failed_candidate=candidate,
                        remaining=eligible_queue,
                        failure_stage="static validation failed",
                        failure_reasons=("patch_conflict",),
                    )
                    continue
                static_result, proposed = validate_candidate_static(candidate, context)
                if not static_result.passed or proposed is None:
                    semantic_result = _failure_validation(ValidationStage.SEMANTIC, "not_run")
                    attempts.append(RepairAttempt(
                        state_sha256=context.input_sha256,
                        root_id=root.root_id,
                        candidate_id=candidate.candidate_id,
                        rank=rank,
                        candidate=candidate,
                        static_result=static_result,
                        semantic_result=semantic_result,
                        energyplus_result=None,
                        transition_result=None,
                        accepted=False,
                        rejection_reason=";".join(static_result.reasons),
                    ))
                    self._record_memory_application(context, attempts[-1])
                    failed_keys.add(key)
                    rejected.append(candidate.candidate_id)
                    eligible_queue = self._feedback_candidates(
                        root=root,
                        context=context,
                        failed_candidate=candidate,
                        remaining=eligible_queue,
                        failure_stage="static validation failed",
                        failure_reasons=static_result.reasons,
                    )
                    continue
                proposed_sha = text_sha256(proposed)
                if proposed_sha in seen_states:
                    semantic_result = _failure_validation(ValidationStage.SEMANTIC, "repair_loop_detected")
                    attempts.append(RepairAttempt(
                        state_sha256=context.input_sha256,
                        root_id=root.root_id,
                        candidate_id=candidate.candidate_id,
                        rank=rank,
                        candidate=candidate,
                        static_result=static_result,
                        semantic_result=semantic_result,
                        energyplus_result=None,
                        transition_result=None,
                        accepted=False,
                        rejection_reason="repair_loop_detected",
                    ))
                    self._record_memory_application(context, attempts[-1])
                    failed_keys.add(key)
                    rejected.append(candidate.candidate_id)
                    eligible_queue = self._feedback_candidates(
                        root=root,
                        context=context,
                        failed_candidate=candidate,
                        remaining=eligible_queue,
                        failure_stage="semantic validation failed",
                        failure_reasons=("repair_loop_detected",),
                    )
                    continue
                provider = self.registry.provider(candidate.provider)
                semantic_result = self._semantic_validation(
                    provider=provider, before=current_text, after=proposed,
                    candidate=candidate, context=context,
                )
                if not semantic_result.passed:
                    attempts.append(RepairAttempt(
                        state_sha256=context.input_sha256,
                        root_id=root.root_id,
                        candidate_id=candidate.candidate_id,
                        rank=rank,
                        candidate=candidate,
                        static_result=static_result,
                        semantic_result=semantic_result,
                        energyplus_result=None,
                        transition_result=None,
                        accepted=False,
                        rejection_reason=";".join(semantic_result.reasons),
                    ))
                    self._record_memory_application(context, attempts[-1])
                    failed_keys.add(key)
                    rejected.append(candidate.candidate_id)
                    eligible_queue = self._feedback_candidates(
                        root=root,
                        context=context,
                        failed_candidate=candidate,
                        remaining=eligible_queue,
                        failure_stage="semantic validation failed",
                        failure_reasons=semantic_result.reasons,
                    )
                    continue
                if run_count >= self.config.max_total_energyplus_runs:
                    terminal_status = RepairStatus.LIMIT_REACHED
                    terminal_reason = "max_total_energyplus_runs_exceeded"
                    break
                candidate_result = model_preview_results.pop(proposed_sha, None)
                if candidate_result is None:
                    candidate_result = self.runner(proposed, len(committed) + 1)
                    run_count += 1
                if candidate_result.process_failure or candidate_result.timed_out:
                    transition_result = _failure_validation(ValidationStage.TRANSITION, "runtime_process_failure")
                    attempts.append(RepairAttempt(
                        state_sha256=context.input_sha256,
                        root_id=root.root_id,
                        candidate_id=candidate.candidate_id,
                        rank=rank,
                        candidate=candidate,
                        static_result=static_result,
                        semantic_result=semantic_result,
                        energyplus_result=candidate_result,
                        transition_result=transition_result,
                        accepted=False,
                        rejection_reason="runtime_process_failure",
                    ))
                    self._record_memory_application(context, attempts[-1])
                    terminal_status = RepairStatus.PROCESS_FAILED
                    terminal_reason = "candidate_energyplus_process_failure"
                    break
                after_roots = self._roots(proposed, candidate_result)
                transition_result = validate_transition(
                    selected_root=root,
                    candidate=candidate,
                    before_roots=roots,
                    after_roots=after_roots,
                    energyplus_result=candidate_result,
                    family_semantic_passed=True,
                )
                attempts.append(RepairAttempt(
                    state_sha256=context.input_sha256,
                    root_id=root.root_id,
                    candidate_id=candidate.candidate_id,
                    rank=rank,
                    candidate=candidate,
                    static_result=static_result,
                    semantic_result=semantic_result,
                    energyplus_result=candidate_result,
                    transition_result=transition_result,
                    accepted=transition_result.passed,
                    rejection_reason=None if transition_result.passed else ";".join(transition_result.reasons),
                ))
                self._record_memory_application(context, attempts[-1])
                if not transition_result.passed:
                    failed_keys.add(key)
                    rejected.append(candidate.candidate_id)
                    feedback_stage = (
                        "new root introduced"
                        if any("new" in reason.casefold() for reason in transition_result.reasons)
                        else "target root not resolved"
                    )
                    if candidate_result.severe_count or candidate_result.fatal_count:
                        feedback_stage = "EnergyPlus severe error"
                    eligible_queue = self._feedback_candidates(
                        root=root,
                        context=context,
                        failed_candidate=candidate,
                        remaining=eligible_queue,
                        failure_stage=feedback_stage,
                        failure_reasons=transition_result.reasons,
                    )
                    continue
                decision_stack.append(PendingDecisionFrame(
                    parent_text=current_text,
                    parent_sha256=context.input_sha256,
                    parent_result=current_result,
                    parent_round_count=len(committed),
                    candidate_id=candidate.candidate_id,
                    root_id=root.root_id,
                ))
                committed.append(CommittedRound(
                    round_index=len(committed) + 1,
                    before_sha256=context.input_sha256,
                    after_sha256=proposed_sha,
                    root=root,
                    candidate=candidate,
                    energyplus_result=candidate_result,
                ))
                current_text = proposed
                current_result = candidate_result
                seen_states.add(proposed_sha)
                accepted = True
                break
            if terminal_status is not None:
                break
            if accepted:
                continue
            restored = self._backtrack(
                decision_stack,
                failed_keys,
                committed,
                backtracks,
            )
            if restored is not None and backtracks < self.config.max_backtracks:
                current_text, current_result, backtracks = restored
                continue
            terminal_status = RepairStatus.SEARCH_EXHAUSTED
            terminal_reason = "all_candidates_rejected"

        final_roots = self._roots(current_text, current_result)
        self._update_completion_evidence(
            final_roots,
            energyplus_passed=current_result.passed,
        )
        return self._finish(self._enforce_terminal(RepairOutcome(
            status=terminal_status or RepairStatus.ROLLED_BACK,
            input_sha256=input_sha,
            output_sha256=input_sha,
            output_text=original,
            initial_diagnostics=list(initial_roots),
            final_diagnostics=list(final_roots),
            attempts=attempts,
            committed_rounds=committed,
            rejected_candidates=rejected,
            backtracks=backtracks,
            energyplus_runs=run_count,
            rollback_reason=terminal_reason,
            initial_energyplus_diagnostics=initial_diagnostics_text,
        ),
            original=original,
            tentative_text=current_text,
            result=current_result,
            initial_ambiguity_count=initial_ambiguity_count,
            user_answer_present=user_answer_present,
        ))

    def _semantic_validation(
        self, *, provider: Any, before: str, after: str,
        candidate: RepairCandidate, context: CandidateContext,
    ) -> ValidationResult:
        '''仅为隔离且不落盘的 A9 实验关闭 provider 语义门禁。'''
        if self._evaluation_skip_semantic_gate:
            return ValidationResult(
                stage=ValidationStage.SEMANTIC,
                passed=True,
                details={
                    "evaluation_ablation": "semantic_gate_disabled",
                    "isolated": True,
                    "persist_output": False,
                },
            )
        return validate_candidate_semantics(
            provider=provider,
            before=before,
            after=after,
            candidate=candidate,
            context=context,
        )

    def _backtrack(
        self,
        stack: list[PendingDecisionFrame],
        failed_keys: set[tuple[str, str, str]],
        committed: list[CommittedRound],
        current_backtracks: int,
    ) -> tuple[str, EnergyPlusResult, int] | None:
        if not stack or current_backtracks >= self.config.max_backtracks:
            return None
        frame = stack.pop()
        parent_sha = text_sha256(frame.parent_text)
        failed_keys.add((parent_sha, frame.root_id, frame.candidate_id))
        del committed[frame.parent_round_count:]
        return frame.parent_text, frame.parent_result, current_backtracks + 1

    def _needs_input(
        self,
        *,
        original: str,
        input_sha: str,
        initial_roots: tuple[DiagnosticRoot, ...],
        current_roots: tuple[DiagnosticRoot, ...],
        attempts: list[RepairAttempt],
        committed: list[CommittedRound],
        rejected: list[str],
        backtracks: int,
        run_count: int,
        root: DiagnosticRoot,
        candidates: tuple[RepairCandidate, ...],
        reason: str,
        initial_diagnostics_text: str,
        context: CandidateContext,
        current_text: str,
        current_result: EnergyPlusResult,
        decision_stack: list[PendingDecisionFrame],
        failed_keys: set[tuple[str, str, str]],
        seen_states: set[str],
    ) -> RepairOutcome:
        question = question_for_context(root, candidates, context)
        renderable = question is not None and has_renderable_questions({
            "questions": [to_primitive(question)],
        })
        pending_state = PendingRepairState(
            working_text=current_text,
            working_sha256=text_sha256(current_text),
            committed_rounds=tuple(committed),
            remaining_root_ids=tuple(root.root_id for root in current_roots),
            question=question,
            attempts=tuple(attempts),
            rejected_candidates=tuple(rejected),
            backtracks=backtracks,
            energyplus_runs=run_count,
            initial_diagnostics=tuple(initial_roots),
            initial_energyplus_diagnostics=initial_diagnostics_text,
            original_input_sha256=input_sha,
            working_result=current_result,
            decision_stack=tuple(decision_stack),
            failed_candidate_keys=tuple(sorted(failed_keys)),
            seen_state_sha256s=tuple(sorted(seen_states)),
            fault_ledger=self._fault_ledger_checkpoint(),
        ) if renderable and question is not None else None
        if pending_state is not None:
            pending_state = replace(
                pending_state,
                checkpoint_id=pending_repair_checkpoint_id(pending_state),
            )
        return RepairOutcome(
            status=(
                RepairStatus.NEEDS_INPUT if renderable else RepairStatus.UNSUPPORTED
            ),
            input_sha256=input_sha,
            output_sha256=input_sha,
            output_text=original,
            initial_diagnostics=list(initial_roots),
            final_diagnostics=list(current_roots),
            attempts=attempts,
            committed_rounds=committed,
            rejected_candidates=rejected,
            backtracks=backtracks,
            energyplus_runs=run_count,
            questions=[question] if renderable else [],
            rollback_reason=reason if renderable else "provider_unavailable",
            initial_energyplus_diagnostics=initial_diagnostics_text,
            pending_state=pending_state,
        )
