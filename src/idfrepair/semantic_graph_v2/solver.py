"""构造依赖冲突分量并执行 bounded exact semantic-edit search。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from math import comb

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.semantic_graph_v2.candidates import (
    CandidateDomainStatus,
    CandidateGeneration,
    CandidateSet,
)
from idfrepair.semantic_graph_v2.edits import (
    SemanticEdit,
    SemanticEditConflict,
    apply_semantic_edits,
)
from idfrepair.semantic_graph_v2.registry import ConstraintRegistry
from idfrepair.semantic_graph_v2.scan import ScanResult, Violation, scan_model


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class ComponentDecisionStatus(_StringEnum):
    UNIQUE_REPAIR = "UNIQUE_REPAIR"
    AMBIGUOUS = "AMBIGUOUS"
    NEEDS_INPUT = "NEEDS_INPUT"
    UNSUPPORTED = "UNSUPPORTED"
    SEARCH_EXHAUSTED = "SEARCH_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class SolverLimits:
    max_component_violations: int = 8
    max_candidate_edits: int = 24
    max_semantic_edits: int = 4
    max_evaluated_sets: int = 256

    def __post_init__(self) -> None:
        if min(
            self.max_component_violations,
            self.max_candidate_edits,
            self.max_semantic_edits,
            self.max_evaluated_sets,
        ) < 1:
            raise ValueError("solver_limit_must_be_positive")


@dataclass(frozen=True, slots=True)
class ConflictComponent:
    component_id: str
    violations: tuple[Violation, ...]
    candidate_sets: tuple[CandidateSet, ...]

    @property
    def candidate_edits(self) -> tuple[SemanticEdit, ...]:
        unique: dict[
            tuple[tuple[int, int, str, str], ...], SemanticEdit
        ] = {}
        for domain in self.candidate_sets:
            for edit in domain.candidates:
                effect = tuple(
                    (
                        field.object_index,
                        field.field_index,
                        field.old_value,
                        field.new_value,
                    )
                    for field in edit.field_edits
                )
                unique.setdefault(effect, edit)
        return tuple(
            sorted(unique.values(), key=lambda edit: edit.semantic_signature)
        )


@dataclass(frozen=True, slots=True)
class ComponentDecision:
    component_id: str
    status: ComponentDecisionStatus
    selected_edits: tuple[SemanticEdit, ...]
    alternative_count: int
    objective: tuple[int, int] | None
    evaluated_sets: int
    candidate_domain_complete: bool
    search_exhausted: bool
    reasons: tuple[str, ...]
    alternative_signatures: tuple[tuple[str, ...], ...] = ()


def _domain_for(
    candidates: CandidateGeneration,
    violation: Violation,
) -> CandidateSet:
    domain = candidates.for_violation(violation.violation_id)
    if domain is not None:
        return domain
    return CandidateSet(
        violation_id=violation.violation_id,
        constraint_id=violation.constraint_id,
        status=CandidateDomainStatus.INCOMPLETE_UNSUPPORTED,
        candidates=(),
        reason="candidate_domain_missing",
    )


def _violation_reads(violation: Violation) -> set[str]:
    return {
        *violation.read_variables,
        *violation.latent_factors,
        *(f"field:{field.field_id}" for field in violation.field_refs),
    }


def _domain_writes(domain: CandidateSet) -> set[str]:
    return {
        variable
        for edit in domain.candidates
        for variable in (
            *edit.write_variables,
            *(f"field:{field.field_id}" for field in edit.field_edits),
        )
    }


def _domain_preconditions(domain: CandidateSet) -> set[str]:
    return {
        variable
        for edit in domain.candidates
        for variable in edit.precondition_reads
    }


def _share_dependency(
    left: Violation,
    left_domain: CandidateSet,
    right: Violation,
    right_domain: CandidateSet,
) -> bool:
    if set(left.latent_factors) & set(right.latent_factors):
        return True
    left_reads, right_reads = _violation_reads(left), _violation_reads(right)
    left_writes, right_writes = _domain_writes(left_domain), _domain_writes(right_domain)
    left_pre, right_pre = (
        _domain_preconditions(left_domain), _domain_preconditions(right_domain)
    )
    if left_writes & (right_writes | right_reads | right_pre):
        return True
    if right_writes & (left_reads | left_pre):
        return True
    left_fields = {field.field_id for field in left.field_refs}
    right_fields = {field.field_id for field in right.field_refs}
    if left_fields & right_fields:
        return True
    if left.constraint_id != right.constraint_id:
        for edit in (*left_domain.candidates, *right_domain.candidates):
            if {left.constraint_id, right.constraint_id}.issubset(
                set(edit.resolves_constraint_ids)
            ):
                return True
    return False


def build_conflict_components(
    violations: tuple[Violation, ...],
    candidates: CandidateGeneration,
) -> tuple[ConflictComponent, ...]:
    """按 factor/read/write incidence 构造保守 connected components。"""

    ordered = tuple(sorted(
        (row for row in violations if row.hard),
        key=lambda row: row.violation_id,
    ))
    if not ordered:
        return ()
    domains = tuple(_domain_for(candidates, row) for row in ordered)
    adjacency: list[set[int]] = [set() for _ in ordered]
    for left_index, right_index in combinations(range(len(ordered)), 2):
        if _share_dependency(
            ordered[left_index], domains[left_index],
            ordered[right_index], domains[right_index],
        ):
            adjacency[left_index].add(right_index)
            adjacency[right_index].add(left_index)

    unseen = set(range(len(ordered)))
    components: list[ConflictComponent] = []
    while unseen:
        seed = min(unseen)
        stack = [seed]
        indexes: set[int] = set()
        while stack:
            current = stack.pop()
            if current in indexes:
                continue
            indexes.add(current)
            unseen.discard(current)
            stack.extend(sorted(adjacency[current] - indexes, reverse=True))
        component_violations = tuple(ordered[index] for index in sorted(indexes))
        component_domains = tuple(domains[index] for index in sorted(indexes))
        anchor = min(row.violation_id for row in component_violations)
        components.append(ConflictComponent(
            component_id=f"component:{anchor}",
            violations=component_violations,
            candidate_sets=component_domains,
        ))
    return tuple(sorted(components, key=lambda row: row.component_id))


def _decision(
    component: ConflictComponent,
    status: ComponentDecisionStatus,
    *,
    selected_edits: tuple[SemanticEdit, ...] = (),
    alternative_count: int = 0,
    objective: tuple[int, int] | None = None,
    evaluated_sets: int = 0,
    candidate_domain_complete: bool = False,
    search_exhausted: bool = False,
    reasons: tuple[str, ...] = (),
    alternative_signatures: tuple[tuple[str, ...], ...] = (),
) -> ComponentDecision:
    return ComponentDecision(
        component_id=component.component_id,
        status=status,
        selected_edits=selected_edits,
        alternative_count=alternative_count,
        objective=objective,
        evaluated_sets=evaluated_sets,
        candidate_domain_complete=candidate_domain_complete,
        search_exhausted=search_exhausted,
        reasons=reasons,
        alternative_signatures=alternative_signatures,
    )


def _field_cost(edits: tuple[SemanticEdit, ...]) -> int:
    return len({
        field.field_id for edit in edits for field in edit.field_edits
    })


def _semantic_signature(edits: tuple[SemanticEdit, ...]) -> tuple[str, ...]:
    return tuple(sorted(edit.semantic_signature for edit in edits))


def _solve_component(
    text: str,
    idd: IDDSchema,
    initial_scan: ScanResult,
    component: ConflictComponent,
    *,
    registry: ConstraintRegistry | None,
    limits: SolverLimits,
) -> ComponentDecision:
    if len(component.violations) > limits.max_component_violations:
        return _decision(
            component,
            ComponentDecisionStatus.SEARCH_EXHAUSTED,
            search_exhausted=True,
            reasons=("max_component_violations_exceeded",),
        )
    if any(
        domain.status is CandidateDomainStatus.TRUNCATED
        for domain in component.candidate_sets
    ):
        return _decision(
            component,
            ComponentDecisionStatus.SEARCH_EXHAUSTED,
            search_exhausted=True,
            reasons=("candidate_domain_truncated",),
        )
    if any(
        domain.status is CandidateDomainStatus.INCOMPLETE_UNSUPPORTED
        for domain in component.candidate_sets
    ):
        return _decision(
            component,
            ComponentDecisionStatus.UNSUPPORTED,
            candidate_domain_complete=False,
            reasons=tuple(sorted({
                domain.reason for domain in component.candidate_sets
                if domain.status is CandidateDomainStatus.INCOMPLETE_UNSUPPORTED
            })),
        )

    edits = component.candidate_edits
    if len(edits) > limits.max_candidate_edits:
        return _decision(
            component,
            ComponentDecisionStatus.SEARCH_EXHAUSTED,
            search_exhausted=True,
            reasons=("max_candidate_edits_exceeded",),
        )
    if not edits:
        return _decision(
            component,
            ComponentDecisionStatus.NEEDS_INPUT,
            candidate_domain_complete=True,
            reasons=("complete_domain_has_no_candidate",),
        )

    initial_ids = {row.violation_id for row in initial_scan.hard_violations}
    component_ids = {row.violation_id for row in component.violations}
    outside_ids = initial_ids - component_ids
    evaluated = 0
    valid: list[tuple[tuple[SemanticEdit, ...], int]] = []
    exhausted = False
    upper = min(len(edits), limits.max_semantic_edits)
    for semantic_count in range(1, upper + 1):
        # Uniqueness requires the whole objective level.  If the remaining
        # budget cannot enumerate that level, fail before sampling a prefix;
        # a prefix could find S1 while silently missing an equal optimum S2.
        if evaluated + comb(len(edits), semantic_count) > limits.max_evaluated_sets:
            exhausted = True
            break
        level_valid: list[tuple[tuple[SemanticEdit, ...], int]] = []
        for indexes in combinations(range(len(edits)), semantic_count):
            if evaluated >= limits.max_evaluated_sets:
                exhausted = True
                break
            evaluated += 1
            selected = tuple(edits[index] for index in indexes)
            try:
                repaired = apply_semantic_edits(text, selected)
            except SemanticEditConflict:
                continue
            post = scan_model(parse_idf(repaired), idd, registry=registry)
            post_ids = {row.violation_id for row in post.hard_violations}
            if post_ids != outside_ids:
                continue
            level_valid.append((selected, _field_cost(selected)))
        if exhausted:
            break
        if level_valid:
            minimum_fields = min(cost for _, cost in level_valid)
            valid = [row for row in level_valid if row[1] == minimum_fields]
            break

    if exhausted:
        return _decision(
            component,
            ComponentDecisionStatus.SEARCH_EXHAUSTED,
            evaluated_sets=evaluated,
            candidate_domain_complete=True,
            search_exhausted=True,
            reasons=("max_evaluated_sets_exceeded",),
        )
    if not valid:
        reason = (
            "max_semantic_edits_insufficient"
            if len(edits) > limits.max_semantic_edits
            else "no_globally_closing_edit_set"
        )
        return _decision(
            component,
            ComponentDecisionStatus.NEEDS_INPUT,
            evaluated_sets=evaluated,
            candidate_domain_complete=True,
            reasons=(reason,),
        )

    equivalent: dict[tuple[str, ...], tuple[SemanticEdit, ...]] = {}
    for selected, _ in valid:
        equivalent.setdefault(_semantic_signature(selected), selected)
    signatures = tuple(sorted(equivalent))
    objective = (len(valid[0][0]), valid[0][1])
    if len(signatures) != 1:
        return _decision(
            component,
            ComponentDecisionStatus.AMBIGUOUS,
            alternative_count=len(signatures),
            objective=objective,
            evaluated_sets=evaluated,
            candidate_domain_complete=True,
            reasons=("multiple_equal_optimum_semantic_edit_sets",),
            alternative_signatures=signatures,
        )
    selected = equivalent[signatures[0]]
    return _decision(
        component,
        ComponentDecisionStatus.UNIQUE_REPAIR,
        selected_edits=selected,
        alternative_count=1,
        objective=objective,
        evaluated_sets=evaluated,
        candidate_domain_complete=True,
        reasons=("unique_complete_minimum",),
        alternative_signatures=signatures,
    )


def solve_components(
    text: str,
    idd: IDDSchema,
    initial_scan: ScanResult,
    components: tuple[ConflictComponent, ...],
    *,
    registry: ConstraintRegistry | None = None,
    limits: SolverLimits = SolverLimits(),
) -> tuple[ComponentDecision, ...]:
    """在同一 original faulty snapshot 上独立证明每个保守分量。"""

    return tuple(
        _solve_component(
            text,
            idd,
            initial_scan,
            component,
            registry=registry,
            limits=limits,
        )
        for component in components
    )


__all__ = [
    "ComponentDecision",
    "ComponentDecisionStatus",
    "ConflictComponent",
    "SolverLimits",
    "build_conflict_components",
    "solve_components",
]
