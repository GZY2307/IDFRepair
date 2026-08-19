"""Claim-boundary provenance records for Airport Occupancy V3."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvidenceLevel(str, Enum):
    MODEL_FACT = "MODEL_FACT"
    OFFICIAL_PROCESS = "OFFICIAL_PROCESS"
    USER_SOURCE_ANNOTATION = "USER_SOURCE_ANNOTATION"
    DRAWING_EVIDENCE = "DRAWING_EVIDENCE"
    CONTROLLED_NOT_MEASURED = "CONTROLLED_NOT_MEASURED"
    MODEL_BOUNDARY_EXIT = "MODEL_BOUNDARY_EXIT"


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    level: EvidenceLevel
    reference: str
    supports: str
    does_not_support: str

    def __post_init__(self) -> None:
        for field in ("evidence_id", "reference", "supports", "does_not_support"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must not be blank")

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_id": self.evidence_id,
            "level": self.level.value,
            "reference": self.reference,
            "supports": self.supports,
            "does_not_support": self.does_not_support,
        }
