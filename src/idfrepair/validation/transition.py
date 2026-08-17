"""Selected-root transition validation across EnergyPlus rounds."""

from __future__ import annotations

from idfrepair.domain.enums import OperationKind, ValidationStage
from idfrepair.domain.models import (
    DiagnosticRoot,
    EnergyPlusResult,
    RepairCandidate,
    ValidationResult,
)


def _root_key(root: DiagnosticRoot) -> tuple[str, str, str]:
    line_identity = root.metadata.get("line_number")
    return (
        root.family,
        (root.object_type or "").casefold(),
        (root.object_name or (f"line:{line_identity}" if line_identity is not None else "")).casefold(),
    )


def validate_transition(
    *,
    selected_root: DiagnosticRoot,
    candidate: RepairCandidate,
    before_roots: tuple[DiagnosticRoot, ...],
    after_roots: tuple[DiagnosticRoot, ...],
    energyplus_result: EnergyPlusResult,
    family_semantic_passed: bool,
) -> ValidationResult:
    reasons: list[str] = []
    selected_key = _root_key(selected_root)
    selected_resolved = not any(
        root.root_id == selected_root.root_id or _root_key(root) == selected_key
        for root in after_roots
    )
    if not selected_resolved:
        reasons.append("selected_root_not_resolved")
    if not family_semantic_passed:
        reasons.append("family_semantic_validation_failed")
    if energyplus_result.process_failure or energyplus_result.timed_out:
        reasons.append("energyplus_process_failure")
    before_keys = {_root_key(root) for root in before_roots}
    unrelated = [
        root for root in after_roots
        if _root_key(root) not in before_keys and root.family == "unknown"
    ]
    before_signatures = {
        signature for root in before_roots for signature in root.signatures
    }
    lineage_unknown = [
        root for root in unrelated
        if before_signatures.intersection(root.signatures)
    ]
    revealed_unknown = [root for root in unrelated if root not in lineage_unknown]
    operations = candidate.operations
    normalization_certificate = bool(
        family_semantic_passed
        and len(operations) == 1
        and (
            (
                candidate.family == "syntax"
                and candidate.provider == "syntax_delimiter"
                and operations[0].kind is OperationKind.INSERT_DELIMITER
                and candidate.metadata.get("single_exact_delimiter_insertion") is True
            )
            or (
                candidate.family == "extra_field"
                and candidate.provider == "idd_schema"
                and operations[0].kind is OperationKind.DELETE_FIELD
            )
        )
    )
    # Correct parser-boundary and current-IDD tail normalization can reveal a
    # second, previously unreachable diagnostic.  Their provider semantics
    # prove exact, one-operation normalization.  Other operation classes may
    # carry forward only a signature-linked unknown root; genuinely new
    # unknowns remain fail-closed.  No intermediate transition authorizes an
    # output: the search still commits only after EnergyPlus passes with no
    # remaining roots, and otherwise backtracks to the original bytes.
    revealed_roots_allowed = bool(revealed_unknown and normalization_certificate)
    if revealed_unknown and not revealed_roots_allowed:
        reasons.append("patch_induced_unknown_root")
    return ValidationResult(
        stage=ValidationStage.TRANSITION,
        passed=not reasons,
        reasons=tuple(reasons),
        details={
            "after_root_count": len(after_roots),
            "before_root_count": len(before_roots),
            "selected_root_resolved": selected_resolved,
            "normalization_certificate": normalization_certificate,
            "lineage_unknown_root_ids": [root.root_id for root in lineage_unknown],
            "revealed_unknown_root_ids": [root.root_id for root in revealed_unknown],
            "revealed_unknown_roots_allowed": revealed_roots_allowed,
            "unrelated_unknown_root_ids": [root.root_id for root in unrelated],
        },
    )
