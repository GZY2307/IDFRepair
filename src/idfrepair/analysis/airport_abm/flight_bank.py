"""Controlled route-plan generation and passenger timing-bank scenarios."""

from __future__ import annotations

from dataclasses import dataclass, replace
import random
from typing import Iterable, Mapping, Sequence

from .agents import AgentPlan, RouteStop
from .dwell import DwellSpec
from .model import AgentClass, PASSENGER_CLASSES
from .source import SourceSpace


_TIMING_WINDOWS = {
    "MORNING_BANK": ((360.0, 600.0),),
    "MIDDAY_BANK": ((660.0, 900.0),),
    "EVENING_BANK": ((960.0, 1200.0),),
    "DOUBLE_BANK": ((360.0, 600.0), (960.0, 1200.0)),
}

_BASELINE_WINDOWS = {
    AgentClass.DOMESTIC_DEPARTURE: (
        (0.0, 300.0, 0.03), (300.0, 480.0, 0.17), (480.0, 720.0, 0.26),
        (720.0, 1020.0, 0.28), (1020.0, 1260.0, 0.21), (1260.0, 1440.0, 0.05),
    ),
    AgentClass.DOMESTIC_ARRIVAL: (
        (0.0, 300.0, 0.08), (300.0, 480.0, 0.10), (480.0, 720.0, 0.20),
        (720.0, 1020.0, 0.25), (1020.0, 1260.0, 0.25), (1260.0, 1440.0, 0.12),
    ),
    AgentClass.DOMESTIC_TRANSFER: (
        (0.0, 300.0, 0.05), (300.0, 480.0, 0.12), (480.0, 720.0, 0.22),
        (720.0, 1020.0, 0.28), (1020.0, 1260.0, 0.24), (1260.0, 1440.0, 0.09),
    ),
    AgentClass.INTERNATIONAL_ARRIVAL: (
        (0.0, 300.0, 0.15), (300.0, 480.0, 0.08), (480.0, 720.0, 0.17),
        (720.0, 1020.0, 0.20), (1020.0, 1260.0, 0.23), (1260.0, 1440.0, 0.17),
    ),
}

_BANK_MIX_FRACTION = 0.82


@dataclass(frozen=True, slots=True)
class ControlledParameters:
    transit_minutes: float = 5.0
    departure_wait_minimum: float = 60.0
    departure_wait_maximum: float = 90.0
    transfer_wait_minimum: float = 45.0
    transfer_wait_maximum: float = 75.0
    baggage_minutes: float = 20.0
    detour_probability: float = 0.35
    detour_minutes: float = 15.0
    staff_work_minutes: float = 480.0
    staff_break_probability: float = 0.15
    staff_break_minutes: float = 20.0
    evidence_status: str = "CONTROLLED_NOT_MEASURED"

    def __post_init__(self) -> None:
        if self.transit_minutes <= 0:
            raise ValueError("transit_minutes must be positive")
        if not 30 <= self.departure_wait_minimum <= self.departure_wait_maximum <= 120:
            raise ValueError("departure wait must remain within 30-120 minutes")
        if self.transfer_wait_minimum <= 0 or self.transfer_wait_maximum < self.transfer_wait_minimum:
            raise ValueError("invalid transfer wait bounds")
        for name in ("detour_probability", "staff_break_probability"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must lie in [0, 1]")
        if self.detour_minutes <= 0 or self.detour_minutes + 2 > self.departure_wait_minimum:
            raise ValueError("detour does not fit inside departure waiting budget")
        if self.evidence_status != "CONTROLLED_NOT_MEASURED":
            raise ValueError("unsupported parameters must remain controlled")


def _fixed(minutes: float) -> DwellSpec:
    return DwellSpec(
        kind="deterministic",
        minimum=float(minutes),
        maximum=float(minutes),
        value=float(minutes),
    )


def _choice(rng: random.Random, values: Sequence[str], label: str) -> str:
    if not values:
        raise ValueError(f"source group is empty: {label}")
    return rng.choice(tuple(values))


def _sample_baseline_spawn(rng: random.Random, agent_class: AgentClass) -> float:
    windows = _BASELINE_WINDOWS[agent_class]
    selected = rng.choices(windows, weights=[row[2] for row in windows], k=1)[0]
    return rng.uniform(selected[0], selected[1])


def _weighted_detour(
    rng: random.Random,
    names: Sequence[str],
    spaces: Mapping[str, SourceSpace],
) -> str:
    weights = []
    for name in names:
        capacity = spaces[name].source_design_people
        weights.append(float(capacity) if capacity is not None and capacity > 0 else 1.0)
    return rng.choices(tuple(names), weights=weights, k=1)[0]


def _weighted_space(
    rng: random.Random,
    names: Sequence[str],
    spaces: Mapping[str, SourceSpace],
    label: str,
) -> str:
    if not names:
        raise ValueError(f"source group is empty: {label}")
    weights = []
    for name in names:
        capacity = spaces[name].source_design_people
        if capacity is None or capacity <= 0:
            raise ValueError(f"weighted group lacks source People capacity: {name}")
        weights.append(capacity)
    return rng.choices(tuple(names), weights=weights, k=1)[0]


def _pier_concourse(
    gate: str,
    groups: Mapping[str, Sequence[str]],
    rng: random.Random,
) -> str | None:
    if gate in groups.get("ne_gates", ()):
        return _choice(rng, groups.get("ne_concourse", ()), "ne_concourse")
    if gate in groups.get("nw_gates", ()):
        return _choice(rng, groups.get("nw_concourse", ()), "nw_concourse")
    return None


def build_daily_plans(
    *,
    spaces: Iterable[SourceSpace],
    groups: Mapping[str, Sequence[str]],
    door_detours: Mapping[str, Sequence[str]],
    counts: Mapping[AgentClass, int],
    parameters: ControlledParameters,
    seed: int,
) -> tuple[AgentPlan, ...]:
    source = {space.name: space for space in spaces}
    plans: list[AgentPlan] = []
    for class_index, agent_class in enumerate(AgentClass, start=1):
        # Independent deterministic streams keep staff and each passenger class
        # unchanged when another class's controlled arrival volume changes.
        rng = random.Random(seed + class_index * 1_000_003)
        count = counts.get(agent_class, 0)
        if count < 0:
            raise ValueError("agent count must not be negative")
        for index in range(count):
            agent_id = f"{agent_class.value.lower()}-{index + 1:06d}"
            spawn = (
                420.0
                if agent_class is AgentClass.STAFF
                else _sample_baseline_spawn(rng, agent_class)
            )
            plans.append(
                _build_one(
                    agent_id,
                    agent_class,
                    spawn,
                    source,
                    groups,
                    door_detours,
                    parameters,
                    rng,
                )
            )
    return tuple(plans)


def _build_one(
    agent_id: str,
    agent_class: AgentClass,
    spawn: float,
    spaces: Mapping[str, SourceSpace],
    groups: Mapping[str, Sequence[str]],
    door_detours: Mapping[str, Sequence[str]],
    p: ControlledParameters,
    rng: random.Random,
) -> AgentPlan:
    transit = _fixed(p.transit_minutes)
    central = _choice(rng, groups.get("central_public", ()), "central_public")

    if agent_class is AgentClass.DOMESTIC_DEPARTURE:
        gate = _weighted_space(
            rng, groups.get("domestic_gates", ()), spaces, "domestic_gates"
        )
        stops = [
            RouteStop(
                _choice(rng, groups.get("departure_entries", ()), "departure_entries"),
                "departure_entry",
                transit,
            ),
            RouteStop(central, "mixed_flow", transit),
        ]
        concourse = _pier_concourse(gate, groups, rng)
        if concourse:
            stops.append(RouteStop(concourse, "concourse", transit))
        wait = rng.uniform(p.departure_wait_minimum, p.departure_wait_maximum)
        choices = tuple(door_detours.get(gate, ()))
        if choices and rng.random() < p.detour_probability:
            destination = _weighted_detour(rng, choices, spaces)
            stops.extend(
                (
                    RouteStop(gate, "gate_anchor", _fixed(2.0)),
                    RouteStop(
                        destination,
                        "discretionary_detour",
                        _fixed(p.detour_minutes),
                        gate,
                    ),
                    RouteStop(
                        gate,
                        "gate_wait",
                        _fixed(wait - p.detour_minutes - 2.0),
                        gate,
                    ),
                )
            )
        else:
            stops.append(RouteStop(gate, "gate_wait", _fixed(wait)))
        duration = sum(stop.dwell.value for stop in stops)
        return AgentPlan(
            agent_id,
            agent_class,
            spawn,
            tuple(stops),
            "BOARDING",
            spawn + duration + 1.0,
        )

    if agent_class is AgentClass.DOMESTIC_ARRIVAL:
        gate = _weighted_space(
            rng, groups.get("domestic_gates", ()), spaces, "domestic_gates"
        )
        stops = [RouteStop(gate, "deplane", transit)]
        concourse = _pier_concourse(gate, groups, rng)
        if concourse:
            stops.append(RouteStop(concourse, "concourse", transit))
        stops.extend(
            (
                RouteStop(central, "mixed_flow", transit),
                RouteStop(
                    _weighted_space(
                        rng,
                        groups.get("baggage_claim", ()),
                        spaces,
                        "baggage_claim",
                    ),
                    "baggage",
                    _fixed(p.baggage_minutes),
                ),
                RouteStop(
                    _weighted_space(
                        rng,
                        groups.get("arrival_exits", ()),
                        spaces,
                        "arrival_exits",
                    ),
                    "arrival_exit",
                    _fixed(1.0),
                ),
            )
        )
        return AgentPlan(agent_id, agent_class, spawn, tuple(stops), "OUT")

    if agent_class is AgentClass.DOMESTIC_TRANSFER:
        gates = groups.get("domestic_gates", ())
        origin = _weighted_space(rng, gates, spaces, "domestic_gates")
        destination_pool = tuple(name for name in gates if name != origin) or tuple(gates)
        destination = _weighted_space(
            rng, destination_pool, spaces, "domestic_gates"
        )
        stops = [RouteStop(origin, "deplane", transit)]
        origin_concourse = _pier_concourse(origin, groups, rng)
        if origin_concourse:
            stops.append(RouteStop(origin_concourse, "concourse", transit))
        stops.append(RouteStop(central, "mixed_flow", transit))
        destination_concourse = _pier_concourse(destination, groups, rng)
        if destination_concourse:
            stops.append(RouteStop(destination_concourse, "concourse", transit))
        wait = rng.uniform(p.transfer_wait_minimum, p.transfer_wait_maximum)
        stops.append(RouteStop(destination, "gate_wait", _fixed(wait)))
        duration = sum(stop.dwell.value for stop in stops)
        return AgentPlan(
            agent_id,
            agent_class,
            spawn,
            tuple(stops),
            "BOARDING",
            spawn + duration + 1.0,
        )

    if agent_class is AgentClass.INTERNATIONAL_ARRIVAL:
        stops = (
            RouteStop(
                _weighted_space(
                    rng,
                    groups.get("international_arrival", ()),
                    spaces,
                    "international_arrival",
                ),
                "deplane",
                transit,
            ),
            RouteStop(
                _weighted_space(
                    rng,
                    groups.get("international_hall", ()),
                    spaces,
                    "international_hall",
                ),
                "international_hall",
                transit,
            ),
            RouteStop(
                _weighted_space(
                    rng,
                    groups.get("international_transfer", ()),
                    spaces,
                    "international_transfer",
                ),
                "vertical_transfer",
                transit,
            ),
        )
        return AgentPlan(
            agent_id,
            agent_class,
            spawn,
            stops,
            "OFF_MODEL_LEVEL1_IMMIGRATION",
        )

    office = _weighted_space(rng, groups.get("offices", ()), spaces, "offices")
    entry = _choice(
        rng,
        groups.get("staff_entry", ("STAFF_ENTRY_BOUNDARY",)),
        "staff_entry",
    )
    stops = [RouteStop(entry, "staff_entry", _fixed(1.0))]
    breakrooms = tuple(groups.get("staff_breakrooms", ()))
    if breakrooms and rng.random() < p.staff_break_probability:
        work_before = (p.staff_work_minutes - p.staff_break_minutes) / 2.0
        stops.extend(
            (
                RouteStop(office, "work", _fixed(work_before)),
                RouteStop(
                    _weighted_space(rng, breakrooms, spaces, "staff_breakrooms"),
                    "staff_break",
                    _fixed(p.staff_break_minutes),
                ),
                RouteStop(office, "work", _fixed(work_before)),
            )
        )
    else:
        stops.append(RouteStop(office, "work", _fixed(p.staff_work_minutes)))
    return AgentPlan(
        agent_id,
        agent_class,
        spawn,
        tuple(stops),
        "STAFF_EXIT_BOUNDARY",
    )


def retime_plans(
    plans: Iterable[AgentPlan], scenario_id: str, *, seed: int
) -> tuple[AgentPlan, ...]:
    if scenario_id not in _TIMING_WINDOWS:
        raise ValueError(f"unknown timing scenario: {scenario_id}")
    rng = random.Random(seed)
    windows = _TIMING_WINDOWS[scenario_id]
    retimed: list[AgentPlan] = []
    for plan in plans:
        if plan.agent_class not in PASSENGER_CLASSES:
            retimed.append(plan)
            continue
        if rng.random() < _BANK_MIX_FRACTION:
            window = rng.choice(windows)
            new_spawn = rng.uniform(*window)
        else:
            new_spawn = _sample_baseline_spawn(rng, plan.agent_class)
        shift = new_spawn - plan.spawn_minute
        new_deadline = (
            plan.deadline_minute + shift
            if plan.deadline_minute is not None
            else None
        )
        retimed.append(
            replace(
                plan,
                spawn_minute=new_spawn,
                deadline_minute=new_deadline,
            )
        )
    return tuple(retimed)
