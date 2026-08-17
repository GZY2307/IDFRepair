"""Final all-roots-closed validation."""

from __future__ import annotations

from idfrepair.domain.enums import ValidationStage
from idfrepair.domain.models import DiagnosticRoot, EnergyPlusResult, ValidationResult


def validate_final(
    result: EnergyPlusResult,
    roots: tuple[DiagnosticRoot, ...],
) -> ValidationResult:
    reasons = []
    if result.process_failure or result.timed_out:
        reasons.append("energyplus_process_failure")
    if not result.passed:
        reasons.append("energyplus_not_passed")
    if roots:
        reasons.append("diagnostic_roots_remain")
    return ValidationResult(
        stage=ValidationStage.FINAL,
        passed=not reasons,
        reasons=tuple(reasons),
        details={"root_count": len(roots)},
    )
