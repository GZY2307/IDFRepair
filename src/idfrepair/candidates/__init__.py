"""Unified deterministic, retrieval, and model candidate providers."""

from idfrepair.candidates.base import CandidateContext, CandidateProvider, CandidateRegistry
from idfrepair.candidates.geometry import GeometryProvider
from idfrepair.candidates.geometry_reconstruct import GeometryReconstructProvider
from idfrepair.candidates.finite_keys import FiniteKeyProvider
from idfrepair.candidates.historical import (
    ProvenanceObjectProvider,
    TypedDesignProvider,
)
from idfrepair.candidates.ems import EmsProvider
from idfrepair.candidates.hvac import HvacProvider
from idfrepair.candidates.migration import MigrationProvider
from idfrepair.candidates.outputs import OutputProvider
from idfrepair.candidates.references import ReferenceProvider
from idfrepair.candidates.schedules import ScheduleProvider
from idfrepair.candidates.schema import SchemaProvider
from idfrepair.candidates.syntax import SyntaxProvider
from idfrepair.candidates.transition_lineage import TransitionLineageProvider
from idfrepair.candidates.user import UserCandidateProvider
from idfrepair.memory.matcher import MemoryProvider


def default_registry() -> CandidateRegistry:
    return CandidateRegistry((
        SyntaxProvider(),
        SchemaProvider(),
        FiniteKeyProvider(),
        ScheduleProvider(),
        ReferenceProvider(),
        TypedDesignProvider(),
        ProvenanceObjectProvider(),
        OutputProvider(),
        TransitionLineageProvider(),
        GeometryReconstructProvider(),
        GeometryProvider(),
        MigrationProvider(),
        HvacProvider(),
        EmsProvider(),
        MemoryProvider(),
        UserCandidateProvider(),
    ))


__all__ = [
    "CandidateContext",
    "CandidateProvider",
    "CandidateRegistry",
    "default_registry",
]
