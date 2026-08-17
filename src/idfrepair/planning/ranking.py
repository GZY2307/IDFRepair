"""Reproducible evidence-first candidate ranking."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from idfrepair.domain.enums import Provenance, RiskLevel
from idfrepair.domain.models import CandidateScore, RepairCandidate


def score_candidate(candidate: RepairCandidate) -> CandidateScore:
    kinds = {evidence.kind for evidence in candidate.evidence}
    components = {
        "evidence_strength": sum(
            max(0.0, min(1.0, evidence.strength))
            for evidence in candidate.evidence
            if evidence.kind not in {"public_case_similarity", "repair_memory_rule"}
        ),
        "same_role_evidence": 0.8 if "idd_field_role" in kinds else 0.0,
        "peer_consensus": 0.8 if "same_type_peer_consensus" in kinds else 0.0,
        "idd_alignment": 0.9 if any(kind.startswith("idd_") for kind in kinds) else 0.0,
        "rdd_alignment": 0.9 if "version_bound_rdd" in kinds else 0.0,
        "object_graph_support": 0.7 if any("graph" in evidence.source for evidence in candidate.evidence) else 0.0,
        "retrieval_similarity": max(
            (evidence.strength for evidence in candidate.evidence if evidence.kind == "public_case_similarity"),
            default=0.0,
        ) * 0.4,
        "memory_rule_support": max(
            (evidence.strength for evidence in candidate.evidence if evidence.kind == "repair_memory_rule"),
            default=0.0,
        ) * 0.6,
        "model_confidence": candidate.confidence * 0.25 if candidate.provenance is Provenance.MODEL_PROPOSED else 0.0,
        "patch_size_penalty": -0.12 * max(0, len(candidate.operations) - 1),
        "risk_penalty": {RiskLevel.LOW: 0.0, RiskLevel.MEDIUM: -0.8, RiskLevel.HIGH: -2.0}[candidate.risk],
        "historical_failure_penalty": -float(candidate.metadata.get("historical_failure_count", 0)) * 0.25,
        "confidence": candidate.confidence,
    }
    return CandidateScore(total=round(sum(components.values()), 12), components=components)


def rank_candidates(candidates: Iterable[RepairCandidate]) -> tuple[RepairCandidate, ...]:
    scored = [replace(candidate, score=score_candidate(candidate)) for candidate in candidates]
    scored.sort(key=lambda candidate: (
        -(candidate.score.total if candidate.score else 0.0),
        -candidate.confidence,
        candidate.risk.order,
        candidate.provider,
        candidate.candidate_id,
    ))
    return tuple(scored)
