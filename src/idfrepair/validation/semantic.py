"""Provider-specific semantics plus common invariants."""

from __future__ import annotations

from idfrepair.candidates.base import CandidateContext, CandidateProvider
from idfrepair.domain.enums import ValidationStage
from idfrepair.domain.models import RepairCandidate, ValidationResult


def validate_candidate_semantics(
    *,
    provider: CandidateProvider,
    before: str,
    after: str,
    candidate: RepairCandidate,
    context: CandidateContext,
) -> ValidationResult:
    try:
        passed, reasons, details = provider.validate_semantics(before, after, candidate, context)
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        return ValidationResult(
            stage=ValidationStage.SEMANTIC,
            passed=False,
            reasons=(f"semantic_validator_failed:{type(exc).__name__}",),
        )
    return ValidationResult(
        stage=ValidationStage.SEMANTIC,
        passed=bool(passed),
        reasons=tuple(reasons),
        details=dict(details),
    )
