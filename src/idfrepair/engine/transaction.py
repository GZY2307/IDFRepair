"""Candidate application and conflict identities."""

from __future__ import annotations

from dataclasses import dataclass

from idfrepair.domain.models import RepairCandidate
from idfrepair.io.idf import apply_operations, text_sha256


def patch_locations(candidate: RepairCandidate) -> frozenset[tuple[object, ...]]:
    return frozenset(
        (
            operation.object_index,
            operation.object_type,
            operation.object_name,
            operation.field_index,
            operation.kind.value,
        )
        for operation in candidate.operations
    )


@dataclass(frozen=True, slots=True)
class CandidateTransaction:
    before: str
    candidate: RepairCandidate
    after: str

    @classmethod
    def apply(cls, before: str, candidate: RepairCandidate) -> "CandidateTransaction":
        return cls(before=before, candidate=candidate, after=apply_operations(before, candidate.operations))

    @property
    def before_sha256(self) -> str:
        return text_sha256(self.before)

    @property
    def after_sha256(self) -> str:
        return text_sha256(self.after)

    def rollback(self) -> str:
        return self.before
