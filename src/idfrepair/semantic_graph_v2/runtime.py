"""公开 V2 target-free scan/candidate/joint-repair orchestration。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import perf_counter

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.semantic_graph_v2.build_ir import build_model_ir
from idfrepair.semantic_graph_v2.candidates import (
    CandidateGeneration,
    generate_candidates,
)
from idfrepair.semantic_graph_v2.edits import (
    SemanticEdit,
    SemanticEditConflict,
    apply_semantic_edits,
)
from idfrepair.semantic_graph_v2.registry import ConstraintRegistry
from idfrepair.semantic_graph_v2.scan import ScanResult, scan_ir, scan_model
from idfrepair.semantic_graph_v2.solver import (
    ComponentDecision,
    ComponentDecisionStatus,
    ConflictComponent,
    SolverLimits,
    build_conflict_components,
    solve_components,
)


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class RepairStatus(_StringEnum):
    VALID = "VALID"
    REPAIRED_COMPLETE = "REPAIRED_COMPLETE"
    PARTIAL_NEEDS_INPUT = "PARTIAL_NEEDS_INPUT"
    PARTIAL_UNSUPPORTED = "PARTIAL_UNSUPPORTED"
    NEEDS_INPUT = "NEEDS_INPUT"
    UNSUPPORTED = "UNSUPPORTED"
    SEARCH_EXHAUSTED = "SEARCH_EXHAUSTED"
    DYNAMIC_REJECT = "DYNAMIC_REJECT"
    PROCESS_FAILURE = "PROCESS_FAILURE"


@dataclass(frozen=True, slots=True)
class RepairPhaseTiming:
    phase: str
    seconds: float


_TIMING_PHASES = (
    "parse",
    "ir_build",
    "constraint_scan",
    "candidate_generation",
    "conflict_graph",
    "solver",
    "global_closure",
)


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    status: RepairStatus
    input_text: str
    output_text: str
    initial_scan: ScanResult
    final_scan: ScanResult
    candidate_generation: CandidateGeneration | None
    components: tuple[ConflictComponent, ...]
    decisions: tuple[ComponentDecision, ...]
    selected_edits: tuple[SemanticEdit, ...]
    unresolved_violation_ids: tuple[str, ...]
    reason: str
    phase_timings: tuple[RepairPhaseTiming, ...]


def _phase_timings(values: dict[str, float]) -> tuple[RepairPhaseTiming, ...]:
    return tuple(
        RepairPhaseTiming(phase=phase, seconds=max(0.0, values.get(phase, 0.0)))
        for phase in _TIMING_PHASES
    )


def _unique_edits(decisions: tuple[ComponentDecision, ...]) -> tuple[SemanticEdit, ...]:
    unique: dict[str, SemanticEdit] = {}
    for decision in decisions:
        if decision.status is not ComponentDecisionStatus.UNIQUE_REPAIR:
            continue
        for edit in decision.selected_edits:
            unique.setdefault(edit.semantic_signature, edit)
    return tuple(unique[key] for key in sorted(unique))


def _unresolved_component_ids(
    components: tuple[ConflictComponent, ...],
    decisions: tuple[ComponentDecision, ...],
) -> set[str]:
    by_id = {component.component_id: component for component in components}
    return {
        violation.violation_id
        for decision in decisions
        if decision.status is not ComponentDecisionStatus.UNIQUE_REPAIR
        for violation in by_id[decision.component_id].violations
    }


def _status_without_repairs(
    decisions: tuple[ComponentDecision, ...],
) -> RepairStatus:
    statuses = {decision.status for decision in decisions}
    if ComponentDecisionStatus.SEARCH_EXHAUSTED in statuses:
        return RepairStatus.SEARCH_EXHAUSTED
    if ComponentDecisionStatus.UNSUPPORTED in statuses:
        return RepairStatus.UNSUPPORTED
    return RepairStatus.NEEDS_INPUT


def repair_model(
    text: str,
    idd: IDDSchema,
    *,
    registry: ConstraintRegistry | None = None,
    limits: SolverLimits = SolverLimits(),
) -> RepairOutcome:
    """只用 current IDF + exact IDD 执行 scan、joint solve 与 global closure。"""

    timings: dict[str, float] = {}
    started = perf_counter()
    document = parse_idf(text)
    timings["parse"] = perf_counter() - started
    started = perf_counter()
    model = build_model_ir(document, idd)
    timings["ir_build"] = perf_counter() - started
    started = perf_counter()
    initial = scan_ir(model, registry=registry)
    timings["constraint_scan"] = perf_counter() - started
    if document.issues:
        unresolved = tuple(row.violation_id for row in initial.hard_violations)
        return RepairOutcome(
            status=RepairStatus.PROCESS_FAILURE,
            input_text=text,
            output_text=text,
            initial_scan=initial,
            final_scan=initial,
            candidate_generation=None,
            components=(),
            decisions=(),
            selected_edits=(),
            unresolved_violation_ids=unresolved,
            reason="|".join(document.issues),
            phase_timings=_phase_timings(timings),
        )
    if not initial.hard_violations:
        return RepairOutcome(
            status=RepairStatus.VALID,
            input_text=text,
            output_text=text,
            initial_scan=initial,
            final_scan=initial,
            candidate_generation=None,
            components=(),
            decisions=(),
            selected_edits=(),
            unresolved_violation_ids=(),
            reason="no_active_hard_violations",
            phase_timings=_phase_timings(timings),
        )

    started = perf_counter()
    candidates = generate_candidates(initial.model, initial)
    timings["candidate_generation"] = perf_counter() - started
    started = perf_counter()
    components = build_conflict_components(initial.hard_violations, candidates)
    timings["conflict_graph"] = perf_counter() - started
    started = perf_counter()
    decisions = solve_components(
        text,
        idd,
        initial,
        components,
        registry=registry,
        limits=limits,
    )
    timings["solver"] = perf_counter() - started
    selected = _unique_edits(decisions)
    if not selected:
        status = _status_without_repairs(decisions)
        unresolved = tuple(row.violation_id for row in initial.hard_violations)
        return RepairOutcome(
            status=status,
            input_text=text,
            output_text=text,
            initial_scan=initial,
            final_scan=initial,
            candidate_generation=candidates,
            components=components,
            decisions=decisions,
            selected_edits=(),
            unresolved_violation_ids=unresolved,
            reason="no_component_has_a_unique_complete_minimum",
            phase_timings=_phase_timings(timings),
        )

    started = perf_counter()
    try:
        output = apply_semantic_edits(text, selected)
    except SemanticEditConflict as exc:
        timings["global_closure"] = perf_counter() - started
        unresolved = tuple(row.violation_id for row in initial.hard_violations)
        return RepairOutcome(
            status=RepairStatus.PROCESS_FAILURE,
            input_text=text,
            output_text=text,
            initial_scan=initial,
            final_scan=initial,
            candidate_generation=candidates,
            components=components,
            decisions=decisions,
            selected_edits=(),
            unresolved_violation_ids=unresolved,
            reason=f"combined_edit_conflict:{exc}",
            phase_timings=_phase_timings(timings),
        )

    final = scan_model(parse_idf(output), idd, registry=registry)
    timings["global_closure"] = perf_counter() - started
    final_ids = {row.violation_id for row in final.hard_violations}
    initial_ids = {row.violation_id for row in initial.hard_violations}
    expected_unresolved = _unresolved_component_ids(components, decisions)
    if final_ids != expected_unresolved or not final_ids.issubset(initial_ids):
        unresolved = tuple(row.violation_id for row in initial.hard_violations)
        return RepairOutcome(
            status=RepairStatus.NEEDS_INPUT,
            input_text=text,
            output_text=text,
            initial_scan=initial,
            final_scan=initial,
            candidate_generation=candidates,
            components=components,
            decisions=decisions,
            selected_edits=(),
            unresolved_violation_ids=unresolved,
            reason="combined_global_closure_rejected",
            phase_timings=_phase_timings(timings),
        )

    unresolved = tuple(sorted(final_ids))
    if not unresolved:
        status = RepairStatus.REPAIRED_COMPLETE
        reason = "all_active_hard_violations_closed"
    elif any(
        decision.status is ComponentDecisionStatus.UNSUPPORTED
        for decision in decisions
    ):
        status = RepairStatus.PARTIAL_UNSUPPORTED
        reason = "unique_components_committed_with_unsupported_residual"
    else:
        status = RepairStatus.PARTIAL_NEEDS_INPUT
        reason = "unique_components_committed_with_unchanged_residual"
    return RepairOutcome(
        status=status,
        input_text=text,
        output_text=output,
        initial_scan=initial,
        final_scan=final,
        candidate_generation=candidates,
        components=components,
        decisions=decisions,
        selected_edits=selected,
        unresolved_violation_ids=unresolved,
        reason=reason,
        phase_timings=_phase_timings(timings),
    )


__all__ = [
    "RepairOutcome",
    "RepairPhaseTiming",
    "RepairStatus",
    "repair_model",
]
