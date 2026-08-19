"""Priority-queue discrete-event execution of pre-registered agent plans."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Iterable

from .agents import AgentPlan, AgentTrace, FlowEvent, Visit
from .dwell import sample_dwell
from .events import EventQueue


class SimulationError(ValueError):
    """Raised when an agent lifecycle violates a hard ABM invariant."""


@dataclass(frozen=True, slots=True)
class SimulationResult:
    traces: dict[str, AgentTrace]
    spawned_count: int
    terminal_count: int
    active_count: int
    missing_agent_ids: tuple[str, ...]


@dataclass(slots=True)
class _Runtime:
    plan: AgentPlan
    sampled_dwells: tuple[float, ...]
    stop_index: int = -1
    visits: list[Visit] | None = None
    flows: list[FlowEvent] | None = None
    terminal_minute: float | None = None

    def __post_init__(self) -> None:
        self.visits = []
        self.flows = []


def simulate_agents(
    plans: Iterable[AgentPlan], *, seed: int
) -> SimulationResult:
    plan_tuple = tuple(plans)
    ids = [plan.agent_id for plan in plan_tuple]
    if len(ids) != len(set(ids)):
        raise SimulationError("duplicate agent id")

    rng = random.Random(seed)
    sampled: dict[str, tuple[float, ...]] = {}
    for plan in sorted(plan_tuple, key=lambda item: item.agent_id):
        sampled[plan.agent_id] = tuple(
            sample_dwell(stop.dwell, rng) for stop in plan.stops
        )

    runtimes = {
        plan.agent_id: _Runtime(plan, sampled[plan.agent_id])
        for plan in plan_tuple
    }
    queue = EventQueue()
    for plan in plan_tuple:
        queue.push(plan.spawn_minute, "spawn", plan.agent_id, {})

    active: set[str] = set()
    spawned: set[str] = set()

    for event in queue:
        runtime = runtimes[event.agent_id]
        plan = runtime.plan
        if event.kind == "spawn":
            if event.agent_id in spawned:
                raise SimulationError(f"agent spawned twice: {event.agent_id}")
            spawned.add(event.agent_id)
            active.add(event.agent_id)
            runtime.stop_index = 0
            _enter_stop(runtime, event.time, queue)
            continue
        if event.kind != "advance":
            raise SimulationError(f"unknown event kind: {event.kind}")
        if event.agent_id not in active:
            raise SimulationError(f"inactive agent received an event: {event.agent_id}")

        current = plan.stops[runtime.stop_index]
        next_index = runtime.stop_index + 1
        if next_index < len(plan.stops):
            next_stop = plan.stops[next_index]
            runtime.flows.append(
                FlowEvent(
                    agent_id=plan.agent_id,
                    agent_class=plan.agent_class,
                    source=current.location,
                    target=next_stop.location,
                    minute=event.time,
                )
            )
            runtime.stop_index = next_index
            _enter_stop(runtime, event.time, queue)
            continue

        runtime.flows.append(
            FlowEvent(
                agent_id=plan.agent_id,
                agent_class=plan.agent_class,
                source=current.location,
                target=plan.terminal_state,
                minute=event.time,
            )
        )
        if (
            plan.deadline_minute is not None
            and event.time > plan.deadline_minute + 1e-9
        ):
            raise SimulationError(
                f"boarding deadline violated for {plan.agent_id}: "
                f"{event.time} > {plan.deadline_minute}"
            )
        runtime.terminal_minute = event.time
        active.remove(event.agent_id)

    traces: dict[str, AgentTrace] = {}
    for agent_id, runtime in runtimes.items():
        if runtime.terminal_minute is None:
            continue
        traces[agent_id] = AgentTrace(
            agent_id=agent_id,
            agent_class=runtime.plan.agent_class,
            visits=tuple(runtime.visits),
            flows=tuple(runtime.flows),
            terminal_state=runtime.plan.terminal_state,
            terminal_minute=runtime.terminal_minute,
        )
    missing = tuple(sorted(set(ids).difference(traces)))
    return SimulationResult(
        traces=traces,
        spawned_count=len(spawned),
        terminal_count=len(traces),
        active_count=len(active),
        missing_agent_ids=missing,
    )


def _enter_stop(runtime: _Runtime, start: float, queue: EventQueue) -> None:
    plan = runtime.plan
    index = runtime.stop_index
    stop = plan.stops[index]
    duration = runtime.sampled_dwells[index]
    end = start + duration
    runtime.visits.append(
        Visit(
            agent_id=plan.agent_id,
            agent_class=plan.agent_class,
            location=stop.location,
            stage=stop.stage,
            start_minute=start,
            end_minute=end,
            detour_anchor=stop.detour_anchor,
        )
    )
    queue.push(end, "advance", plan.agent_id, {})
