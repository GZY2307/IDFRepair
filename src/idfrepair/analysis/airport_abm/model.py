"""Core immutable domain types for the Airport Occupancy V3 ABM."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class AgentClass(str, Enum):
    DOMESTIC_DEPARTURE = "DOMESTIC_DEPARTURE"
    DOMESTIC_ARRIVAL = "DOMESTIC_ARRIVAL"
    DOMESTIC_TRANSFER = "DOMESTIC_TRANSFER"
    INTERNATIONAL_ARRIVAL = "INTERNATIONAL_ARRIVAL"
    STAFF = "STAFF"


PASSENGER_CLASSES = frozenset(
    {
        AgentClass.DOMESTIC_DEPARTURE,
        AgentClass.DOMESTIC_ARRIVAL,
        AgentClass.DOMESTIC_TRANSFER,
        AgentClass.INTERNATIONAL_ARRIVAL,
    }
)


class EvidenceLayer(str, Enum):
    A = "A_EXPLICIT_DOOR"
    B = "B_FUNCTIONAL_PROCESS"
    C = "C_PAIRED_THERMAL_SURFACE"


@dataclass(frozen=True, slots=True)
class SpaceNode:
    name: str
    function: str
    region: str
    is_virtual: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.function.strip() or not self.region.strip():
            raise ValueError("SpaceNode fields must not be blank")


@dataclass(frozen=True, slots=True)
class AccessEdge:
    source: str
    target: str
    role_set: frozenset[AgentClass]
    direction: str
    evidence_layer: EvidenceLayer
    evidence_ref: str
    abstraction_flag: bool
    scenario_condition: str | None
    blocked_reason: str | None
    door_instances: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.target.strip():
            raise ValueError("edge endpoints must not be blank")
        if not self.role_set:
            raise ValueError("role_set must not be empty")
        if self.direction != "DIRECTED":
            raise ValueError("V3 routing edges must be explicitly DIRECTED")
        if not self.evidence_ref.strip():
            raise ValueError("evidence_ref must not be blank")
        if self.evidence_layer is EvidenceLayer.B and not self.abstraction_flag:
            raise ValueError("Layer B edges must be labelled as abstractions")
        if self.evidence_layer is EvidenceLayer.C and self.blocked_reason is None:
            raise ValueError("Layer C candidates must carry a blocked reason")

    @property
    def routable(self) -> bool:
        return self.evidence_layer is not EvidenceLayer.C and self.blocked_reason is None

    @property
    def evidence_label(self) -> str:
        if self.evidence_layer is EvidenceLayer.A:
            return "STRONG_ACCESS_EDGE"
        if self.evidence_layer is EvidenceLayer.B:
            return "functional route abstraction"
        return "CANDIDATE_NOT_WALKABLE_BY_DEFAULT"

    @classmethod
    def functional(
        cls,
        source: str,
        target: str,
        roles: Iterable[AgentClass],
        evidence_ref: str,
        *,
        scenario_condition: str | None = None,
        blocked_reason: str | None = None,
    ) -> "AccessEdge":
        return cls(
            source=source,
            target=target,
            role_set=frozenset(roles),
            direction="DIRECTED",
            evidence_layer=EvidenceLayer.B,
            evidence_ref=evidence_ref,
            abstraction_flag=True,
            scenario_condition=scenario_condition,
            blocked_reason=blocked_reason,
        )

    @classmethod
    def strong_door(
        cls,
        source: str,
        target: str,
        roles: Iterable[AgentClass],
        evidence_ref: str,
        *,
        door_instances: tuple[str, ...] = (),
        scenario_condition: str | None = None,
        blocked_reason: str | None = None,
    ) -> "AccessEdge":
        return cls(
            source=source,
            target=target,
            role_set=frozenset(roles),
            direction="DIRECTED",
            evidence_layer=EvidenceLayer.A,
            evidence_ref=evidence_ref,
            abstraction_flag=False,
            scenario_condition=scenario_condition,
            blocked_reason=blocked_reason,
            door_instances=door_instances,
        )


@dataclass(frozen=True, slots=True)
class RoutePath:
    nodes: tuple[str, ...]
    edges: tuple[AccessEdge, ...]
