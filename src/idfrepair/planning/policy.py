"""Mode-specific policy that never bypasses validation."""

from __future__ import annotations

from idfrepair.config import EngineConfig
from idfrepair.domain.enums import Provenance, RepairMode
from idfrepair.domain.models import RepairCandidate


def candidate_is_eligible(candidate: RepairCandidate, config: EngineConfig) -> bool:
    if config.mode is RepairMode.ANALYZE_ONLY:
        return False
    if config.mode is RepairMode.ASSISTED:
        return False
    return bool(
        candidate.risk.order <= config.maximum_automatic_risk.order
        and candidate.confidence >= config.minimum_automatic_confidence
        and not candidate.requires_user_confirmation
        and candidate.provenance in {Provenance.DETERMINISTIC, Provenance.RETRIEVAL}
    )
