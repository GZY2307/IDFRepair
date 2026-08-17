"""One provider contract for every candidate source."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping, Sequence

from idfrepair.domain.models import DiagnosticRoot, RepairCandidate, RepairOperation, to_primitive
from idfrepair.io.idf import IDFDocument
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.knowledge.object_graph import ObjectGraph
from idfrepair.knowledge.rdd import RDDCatalog


@dataclass(frozen=True, slots=True)
class CandidateContext:
    document: IDFDocument
    idd: IDDSchema
    roots: tuple[DiagnosticRoot, ...]
    diagnostics_text: str
    rdd: RDDCatalog
    version: str
    runtime_identity: Mapping[str, Any]
    object_graph: ObjectGraph
    metadata: Mapping[str, Any]
    _input_sha256: str = field(init=False, repr=False, compare=False)
    _idd_sha256: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        '''缓存不可变文档和 IDD 的摘要，避免按候选重复编码大文件。'''
        object.__setattr__(self, "_input_sha256", self.document.sha256)
        object.__setattr__(self, "_idd_sha256", self.idd.sha256)

    @property
    def input_sha256(self) -> str:
        return self._input_sha256

    @property
    def idd_sha256(self) -> str:
        return self._idd_sha256


class CandidateProvider(ABC):
    name: str
    families: frozenset[str]

    def supports(self, root: DiagnosticRoot, context: CandidateContext) -> bool:
        return root.family in self.families

    @abstractmethod
    def generate(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> Sequence[RepairCandidate]:
        """Return state-bound candidates without mutating the state."""

    def validate_semantics(
        self,
        before: str,
        after: str,
        candidate: RepairCandidate,
        context: CandidateContext,
    ) -> tuple[bool, tuple[str, ...], Mapping[str, Any]]:
        return True, (), {}


def candidate_identity(
    *,
    provider: str,
    root_id: str,
    input_sha256: str,
    operations: Sequence[RepairOperation],
) -> str:
    payload = json.dumps(
        {
            "input_sha256": input_sha256,
            "operations": to_primitive(operations),
            "provider": provider,
            "root_id": root_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:24]


class CandidateRegistry:
    """Stable provider order and one shared pool for all candidate sources."""

    def __init__(self, providers: Iterable[CandidateProvider]) -> None:
        rows = tuple(providers)
        names = [provider.name for provider in rows]
        if len(names) != len(set(names)):
            raise ValueError("candidate_provider_names_must_be_unique")
        self.providers = tuple(sorted(rows, key=lambda provider: provider.name))

    def provider(self, name: str) -> CandidateProvider:
        matches = [provider for provider in self.providers if provider.name == name]
        if len(matches) != 1:
            raise KeyError(name)
        return matches[0]

    def generate(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> tuple[RepairCandidate, ...]:
        candidates: list[RepairCandidate] = []
        for provider in self.providers:
            if not provider.supports(root, context):
                continue
            for candidate in provider.generate(root, context):
                if candidate.provider != provider.name:
                    raise ValueError("candidate_provider_identity_mismatch")
                if candidate.root_id != root.root_id:
                    raise ValueError("candidate_root_identity_mismatch")
                candidates.append(candidate)
        unique = {candidate.candidate_id: candidate for candidate in candidates}
        return tuple(unique[key] for key in sorted(unique))
