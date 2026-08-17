"""Candidate contract and patch-scope validation."""

from __future__ import annotations

from idfrepair.candidates.base import CandidateContext
from idfrepair.domain.enums import OperationKind, ValidationStage
from idfrepair.domain.errors import CandidateApplicationError
from idfrepair.domain.models import RepairCandidate, ValidationResult
from idfrepair.io.idf import apply_operations, parse_idf, text_sha256


def validate_candidate_static(
    candidate: RepairCandidate,
    context: CandidateContext,
) -> tuple[ValidationResult, str | None]:
    reasons: list[str] = []
    if candidate.input_sha256 != context.input_sha256:
        reasons.append("input_sha256_mismatch")
    if candidate.idd_sha256 != context.idd_sha256:
        reasons.append("idd_sha256_mismatch")
    if candidate.version != context.version:
        reasons.append("version_mismatch")
    if not candidate.rollback_supported:
        reasons.append("rollback_not_supported")
    if not candidate.operations:
        reasons.append("no_operations")
    locations = []
    for operation in candidate.operations:
        if not isinstance(operation.kind, OperationKind):
            reasons.append("unknown_operation")
        location = (operation.object_index, operation.object_type, operation.object_name, operation.field_index)
        if location in locations:
            reasons.append("overlapping_operations")
        locations.append(location)
    proposed = None
    if not reasons:
        try:
            proposed = apply_operations(context.document.text, candidate.operations)
            parsed = parse_idf(proposed)
            if proposed == context.document.text:
                reasons.append("no_op_patch")
            if text_sha256(proposed) == context.input_sha256:
                reasons.append("state_identity_unchanged")
            if len(parsed.objects) == 0:
                reasons.append("patch_destroyed_document")
        except (CandidateApplicationError, IndexError, KeyError, TypeError, ValueError) as exc:
            reasons.append(f"candidate_application_failed:{type(exc).__name__}")
    return ValidationResult(
        stage=ValidationStage.STATIC,
        passed=not reasons,
        reasons=tuple(reasons),
        details={
            "operation_count": len(candidate.operations),
            "proposed_sha256": text_sha256(proposed) if proposed is not None else None,
        },
    ), proposed
