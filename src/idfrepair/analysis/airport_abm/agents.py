"""Agent plans and simulation trace records."""

from __future__ import annotations

from dataclasses import dataclass

from .dwell import DwellSpec
from .model import AgentClass


@dataclass(frozen=True, slots=True)
class RouteStop:
    location: str
    stage: str
    dwell: DwellSpec
    detour_anchor: str | None = None

    def __post_init__(self) -> None:
        if not self.location.strip() or not self.stage.strip():
            raise ValueError("route stop fields must not be blank")


@dataclass(frozen=True, slots=True)
class AgentPlan:
    agent_id: str
    agent_class: AgentClass
    spawn_minute: float
    stops: tuple[RouteStop, ...]
    terminal_state: str
    deadline_minute: float | None = None

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise ValueError("agent id must not be blank")
        if self.spawn_minute < 0:
            raise ValueError("spawn minute must not be negative")
        if not self.stops:
            raise ValueError("agent plan must contain at least one stop")
        if not self.terminal_state.strip():
            raise ValueError("terminal state must not be blank")
        if self.deadline_minute is not None and self.deadline_minute < self.spawn_minute:
            raise ValueError("deadline precedes spawn")


@dataclass(frozen=True, slots=True)
class Visit:
    agent_id: str
    agent_class: AgentClass
    location: str
    stage: str
    start_minute: float
    end_minute: float
    detour_anchor: str | None = None


@dataclass(frozen=True, slots=True)
class FlowEvent:
    agent_id: str
    agent_class: AgentClass
    source: str
    target: str
    minute: float


@dataclass(frozen=True, slots=True)
class AgentTrace:
    agent_id: str
    agent_class: AgentClass
    visits: tuple[Visit, ...]
    flows: tuple[FlowEvent, ...]
    terminal_state: str
    terminal_minute: float
