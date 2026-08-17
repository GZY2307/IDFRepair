"""验证 partial repair、全局 closure 与 public runtime boundary。"""

from __future__ import annotations

import inspect
from dataclasses import replace

from idfrepair.semantic_graph_v2.registry import ConstraintRegistry, production_registry
from idfrepair.semantic_graph_v2.runtime import RepairStatus, repair_model

from .conftest import IR_IDD
from .test_candidates import CLEAN
from .test_joint_solver import _ambiguous_branch


def test_independent_unique_and_ambiguous_components_commit_only_unique() -> None:
    text = _ambiguous_branch(CLEAN).replace(
        "BranchList,BL1,SI,P2,P1,SO;",
        "BranchList,BL1,SI,P2,Air Branch,SO;",
    )
    outcome = repair_model(text, IR_IDD)

    assert outcome.status is RepairStatus.PARTIAL_NEEDS_INPUT
    assert len(outcome.components) == 2
    assert len(outcome.selected_edits) == 1
    assert "BranchList,BL1,SI,P2,P1,SO;" in outcome.output_text
    assert "Fan:ConstantVolume,Unknown,A0,A1" in outcome.output_text
    assert {
        row.violation_id for row in outcome.final_scan.hard_violations
    } == set(outcome.unresolved_violation_ids)


def test_valid_model_is_a_noop_with_explicit_valid_status() -> None:
    outcome = repair_model(CLEAN, IR_IDD)

    assert outcome.status is RepairStatus.VALID
    assert outcome.output_text == CLEAN
    assert outcome.initial_scan.hard_violations == ()
    assert outcome.selected_edits == ()


def test_runtime_reports_all_core_phase_timings() -> None:
    fault = CLEAN.replace(
        "BranchList,BL1,SI,P2,P1,SO;",
        "BranchList,BL1,SI,P2,Air Branch,SO;",
    )
    outcome = repair_model(fault, IR_IDD)

    assert tuple(row.phase for row in outcome.phase_timings) == (
        "parse",
        "ir_build",
        "constraint_scan",
        "candidate_generation",
        "conflict_graph",
        "solver",
        "global_closure",
    )
    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert all(row.seconds > 0.0 for row in outcome.phase_timings)


def test_runtime_public_boundary_has_no_family_locator_or_oracle() -> None:
    parameters = inspect.signature(repair_model).parameters

    assert not {"family", "locator", "clean", "oracle", "record"} & set(parameters)


def test_unterminated_input_fails_without_editing() -> None:
    text = "Branch,unterminated"
    outcome = repair_model(text, IR_IDD)

    assert outcome.status is RepairStatus.PROCESS_FAILURE
    assert outcome.output_text == text
    assert outcome.selected_edits == ()


def test_independent_unique_and_unsupported_components_return_partial_unsupported() -> None:
    text = _ambiguous_branch(CLEAN).replace(
        "BranchList,BL1,SI,P2,P1,SO;",
        "BranchList,BL1,SI,P2,Air Branch,SO;",
    )
    production = production_registry()
    branch = next(
        row for row in production.specs
        if row.constraint_id == "V2-BRANCH-TYPED-IDENTITY-001"
    )
    loop = next(
        row for row in production.specs
        if row.constraint_id == "V2-LOOP-BRANCHLIST-SET-005"
    )
    # The evaluator is valid, while the intentionally new constraint identity has
    # no autonomous generator. This exercises the runtime's generic unsupported
    # component contract without weakening the production registry.
    registry = ConstraintRegistry((
        replace(branch, constraint_id="TEST-UNSUPPORTED-BRANCH-001"),
        loop,
    ))

    outcome = repair_model(text, IR_IDD, registry=registry)

    assert outcome.status is RepairStatus.PARTIAL_UNSUPPORTED
    assert len(outcome.selected_edits) == 1
    assert "BranchList,BL1,SI,P2,P1,SO;" in outcome.output_text
    assert "Fan:ConstantVolume,Unknown,A0,A1" in outcome.output_text
