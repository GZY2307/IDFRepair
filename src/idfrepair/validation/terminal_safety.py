'''Independent final transaction gate for repaired artifact admission.'''

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from idfrepair.domain.enums import RepairStatus
from idfrepair.domain.models import RepairOutcome
from idfrepair.io.idf import text_sha256


_REQUIRED_AUDITS = (
    "geometry_audit_passed",
    "idd_audit_passed",
    "rdd_audit_passed",
    "reference_audit_passed",
    "warning_audit_passed",
)


@dataclass(frozen=True, slots=True)
class TerminalSafetyEvidence:
    '''Evidence captured by an independent recheck of the tentative terminal state.'''

    original_text: str
    energyplus_passed: bool
    final_issue_count: int
    final_audit: Mapping[str, Any]
    completion_certificate: Mapping[str, Any]
    initial_observable_ambiguity_count: int = 0
    final_observable_ambiguity_count: int = 0
    user_answer_present: bool = False
    already_valid: bool = False
    final_recheck_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "already_valid": self.already_valid,
            "completion_certificate_passed": (
                self.completion_certificate.get("passed") is True
            ),
            "energyplus_passed": self.energyplus_passed,
            "final_audit": dict(self.final_audit),
            "final_issue_count": self.final_issue_count,
            "final_observable_ambiguity_count": (
                self.final_observable_ambiguity_count
            ),
            "final_recheck_performed": self.final_recheck_performed,
            "initial_observable_ambiguity_count": (
                self.initial_observable_ambiguity_count
            ),
            "schema_version": "idfrepair.terminal_safety_evidence.v1",
            "user_answer_present": self.user_answer_present,
        }


def _ambiguity_locked(evidence: TerminalSafetyEvidence) -> bool:
    return bool(
        (
            evidence.initial_observable_ambiguity_count
            or evidence.final_observable_ambiguity_count
        )
        and not evidence.user_answer_present
    )


def _rejection_reasons(
    outcome: RepairOutcome,
    evidence: TerminalSafetyEvidence,
) -> tuple[str, ...]:
    reasons = []
    original_sha = text_sha256(evidence.original_text)
    if outcome.input_sha256 != original_sha:
        reasons.append("original_input_sha256_mismatch")
    if not evidence.final_recheck_performed:
        reasons.append("final_semantic_recheck_missing")
    if not evidence.energyplus_passed:
        reasons.append("final_energyplus_not_passed")
    if evidence.final_issue_count:
        reasons.append("final_semantic_issue_remains")
    for field in _REQUIRED_AUDITS:
        if evidence.final_audit.get(field) is not True:
            reasons.append(field.removesuffix("_passed") + "_failed")
    if _ambiguity_locked(evidence):
        reasons.append("observable_ambiguity_without_user_answer")
    if evidence.completion_certificate.get("passed") is not True:
        reasons.append("completion_certificate_failed")
    if outcome.output_sha256 != text_sha256(outcome.output_text):
        reasons.append("tentative_output_sha256_mismatch")
    if outcome.output_sha256 == outcome.input_sha256:
        reasons.append("repaired_output_is_byte_identical")
    return tuple(reasons)


def _rollback(outcome: RepairOutcome, evidence: TerminalSafetyEvidence) -> None:
    outcome.output_text = evidence.original_text
    outcome.output_sha256 = outcome.input_sha256
    outcome.terminal_safety_admitted = False


def enforce_terminal_safety(
    tentative: RepairOutcome,
    evidence: TerminalSafetyEvidence,
) -> RepairOutcome:
    '''Admit only fully rechecked repairs; roll every other output back to input.'''
    if tentative.status is RepairStatus.VALID:
        valid_reasons = _rejection_reasons(tentative, evidence)
        valid_reasons = tuple(
            reason for reason in valid_reasons
            if reason != "repaired_output_is_byte_identical"
        )
        _rollback(tentative, evidence)
        if evidence.already_valid and not valid_reasons:
            tentative.terminal_safety_disposition = "ALREADY_VALID"
            return tentative
        tentative.status = RepairStatus.ROLLED_BACK
        tentative.rollback_reason = "terminal_safety_invalid_valid_contract:" + ";".join(
            valid_reasons or ("already_valid_evidence_missing",)
        )
        tentative.terminal_safety_disposition = "VALID_REJECTED"
        return tentative

    if tentative.status is RepairStatus.REPAIRED:
        reasons = _rejection_reasons(tentative, evidence)
        if not reasons:
            tentative.terminal_safety_admitted = True
            tentative.terminal_safety_disposition = "REPAIRED_ADMITTED"
            tentative.rollback_reason = None
            return tentative
        _rollback(tentative, evidence)
        if _ambiguity_locked(evidence):
            tentative.status = RepairStatus.NEEDS_INPUT
            tentative.terminal_safety_disposition = "NEEDS_INPUT_ROLLBACK"
        else:
            tentative.status = RepairStatus.ROLLED_BACK
            tentative.terminal_safety_disposition = "REPAIRED_REJECTED"
        tentative.rollback_reason = "terminal_safety_rejected:" + ";".join(reasons)
        return tentative

    _rollback(tentative, evidence)
    tentative.terminal_safety_disposition = "NON_REPAIRED_ROLLBACK"
    return tentative


def repaired_artifact_allowed(outcome: RepairOutcome) -> bool:
    '''Return true only for an outcome admitted by the terminal transaction gate.'''
    return bool(
        outcome.status is RepairStatus.REPAIRED
        and outcome.terminal_safety_admitted
        and outcome.terminal_safety_disposition == "REPAIRED_ADMITTED"
        and outcome.output_sha256 == text_sha256(outcome.output_text)
        and outcome.output_sha256 != outcome.input_sha256
        and not outcome.final_diagnostics
        and outcome.rollback_reason is None
    )


__all__ = [
    "TerminalSafetyEvidence",
    "enforce_terminal_safety",
    "repaired_artifact_allowed",
]
