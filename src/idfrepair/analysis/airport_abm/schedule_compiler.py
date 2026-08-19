"""Compile agent visits into auditable 15-minute Space People schedules."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .agents import AgentTrace
from .model import AgentClass


class ScheduleCompilationError(ValueError):
    """Raised when an ABM trace cannot be compiled without hidden assumptions."""


@dataclass(frozen=True, slots=True)
class CompiledSchedule:
    interval_minutes: int
    horizon_minutes: int
    interval_labels: tuple[str, ...]
    space_counts: dict[str, tuple[float, ...]]
    space_density: dict[str, tuple[float, ...]]
    class_counts: dict[str, dict[str, tuple[float, ...]]]
    flow_counts: dict[tuple[str, str], tuple[float, ...]]
    class_flow_counts: dict[tuple[str, str], dict[str, tuple[float, ...]]]
    person_hours: float
    class_person_hours: dict[str, float]


def _interval_label(start: int, end: int) -> str:
    def label(value: int) -> str:
        hours, minutes = divmod(value, 60)
        return f"{hours:02d}:{minutes:02d}"

    return f"{label(start)}-{label(end)}"


def _validate_grid(interval_minutes: int, horizon_minutes: int) -> int:
    if interval_minutes <= 0 or horizon_minutes <= 0:
        raise ScheduleCompilationError("interval and horizon must be positive")
    if horizon_minutes % interval_minutes:
        raise ScheduleCompilationError("horizon must be divisible by interval")
    return horizon_minutes // interval_minutes


def compile_traces(
    traces: Mapping[str, AgentTrace] | Iterable[AgentTrace],
    *,
    space_areas_m2: Mapping[str, float],
    interval_minutes: int = 15,
    horizon_minutes: int = 1440,
    agent_weights: Mapping[str, float] | None = None,
    virtual_locations: Iterable[str] = (),
    periodic: bool = False,
) -> CompiledSchedule:
    """Integrate visits over fixed intervals.

    Counts are interval-average persons, not an instantaneous endpoint sample.
    Agent weights allow a simulated cohort to represent multiple people while
    preserving the same route and dwell semantics.
    """

    interval_count = _validate_grid(interval_minutes, horizon_minutes)
    if isinstance(traces, Mapping):
        trace_items = tuple(traces.values())
    else:
        trace_items = tuple(traces)
    if len({trace.agent_id for trace in trace_items}) != len(trace_items):
        raise ScheduleCompilationError("duplicate trace agent id")

    area = dict(space_areas_m2)
    if not area:
        raise ScheduleCompilationError("at least one Space area is required")
    for name, value in area.items():
        if not name.strip() or not math.isfinite(value) or value <= 0:
            raise ScheduleCompilationError(f"invalid Space area: {name}")
    virtual = frozenset(virtual_locations)

    weights = dict(agent_weights or {})
    known_ids = {trace.agent_id for trace in trace_items}
    unexpected_weights = set(weights).difference(known_ids)
    if unexpected_weights:
        raise ScheduleCompilationError(
            "weights reference unknown agents: " + ", ".join(sorted(unexpected_weights))
        )

    class_names = tuple(agent_class.value for agent_class in AgentClass)
    count_work = {name: [0.0] * interval_count for name in sorted(area)}
    class_work = {
        name: {agent_class: [0.0] * interval_count for agent_class in class_names}
        for name in sorted(area)
    }
    flow_work: dict[tuple[str, str], list[float]] = {}
    class_flow_work: dict[tuple[str, str], dict[str, list[float]]] = {}
    class_person_hours = {agent_class: 0.0 for agent_class in class_names}
    person_hours = 0.0

    for trace in sorted(trace_items, key=lambda item: item.agent_id):
        weight = weights.get(trace.agent_id, 1.0)
        if not math.isfinite(weight) or weight <= 0:
            raise ScheduleCompilationError(
                f"agent weight must be finite and positive: {trace.agent_id}"
            )
        _validate_visits(trace)
        class_name = trace.agent_class.value
        for visit in trace.visits:
            if visit.location not in area:
                if visit.location in virtual:
                    continue
                raise ScheduleCompilationError(
                    f"trace location has no Space area: {visit.location}"
                )
            if periodic:
                duration = visit.end_minute - visit.start_minute
                if duration > horizon_minutes:
                    raise ScheduleCompilationError(
                        f"periodic visit exceeds horizon: {trace.agent_id}"
                    )
                start = visit.start_minute % horizon_minutes
                end = start + duration
                segments = (
                    ((start, float(horizon_minutes)), (0.0, end - horizon_minutes))
                    if end > horizon_minutes
                    else ((start, end),)
                )
            else:
                start = max(0.0, visit.start_minute)
                end = min(float(horizon_minutes), visit.end_minute)
                segments = ((start, end),)
            duration = sum(max(0.0, end - start) for start, end in segments)
            if duration <= 0:
                continue
            person_hours += weight * duration / 60.0
            class_person_hours[class_name] += weight * duration / 60.0
            for start, end in segments:
                if end <= start:
                    continue
                first = int(start // interval_minutes)
                last = min(
                    interval_count - 1,
                    int(math.ceil(end / interval_minutes) - 1),
                )
                for index in range(first, last + 1):
                    bin_start = index * interval_minutes
                    bin_end = bin_start + interval_minutes
                    overlap = max(0.0, min(end, bin_end) - max(start, bin_start))
                    if overlap <= 0:
                        continue
                    contribution = weight * overlap / interval_minutes
                    count_work[visit.location][index] += contribution
                    class_work[visit.location][class_name][index] += contribution

        for flow in trace.flows:
            if periodic:
                index = int((flow.minute % horizon_minutes) // interval_minutes)
            else:
                if flow.minute < 0 or flow.minute >= horizon_minutes:
                    continue
                index = int(flow.minute // interval_minutes)
            edge = (flow.source, flow.target)
            flow_work.setdefault(edge, [0.0] * interval_count)[index] += weight
            class_edge = class_flow_work.setdefault(
                edge,
                {agent_class: [0.0] * interval_count for agent_class in class_names},
            )
            class_edge[class_name][index] += weight

    counts = {name: tuple(values) for name, values in count_work.items()}
    density = {
        name: tuple(value / area[name] for value in values)
        for name, values in count_work.items()
    }
    class_counts = {
        name: {
            agent_class: tuple(values)
            for agent_class, values in classes.items()
        }
        for name, classes in class_work.items()
    }
    flow_counts = {
        edge: tuple(values) for edge, values in sorted(flow_work.items())
    }
    class_flow_counts = {
        edge: {
            agent_class: tuple(values)
            for agent_class, values in classes.items()
        }
        for edge, classes in sorted(class_flow_work.items())
    }
    labels = tuple(
        _interval_label(index * interval_minutes, (index + 1) * interval_minutes)
        for index in range(interval_count)
    )
    return CompiledSchedule(
        interval_minutes=interval_minutes,
        horizon_minutes=horizon_minutes,
        interval_labels=labels,
        space_counts=counts,
        space_density=density,
        class_counts=class_counts,
        flow_counts=flow_counts,
        class_flow_counts=class_flow_counts,
        person_hours=person_hours,
        class_person_hours=class_person_hours,
    )


def _validate_visits(trace: AgentTrace) -> None:
    previous_end: float | None = None
    for visit in trace.visits:
        if visit.agent_id != trace.agent_id or visit.agent_class is not trace.agent_class:
            raise ScheduleCompilationError(f"trace identity mismatch: {trace.agent_id}")
        if not math.isfinite(visit.start_minute) or not math.isfinite(visit.end_minute):
            raise ScheduleCompilationError(f"non-finite visit time: {trace.agent_id}")
        if visit.end_minute < visit.start_minute:
            raise ScheduleCompilationError(f"negative visit duration: {trace.agent_id}")
        if previous_end is not None and visit.start_minute < previous_end - 1e-9:
            raise ScheduleCompilationError(f"overlapping visits: {trace.agent_id}")
        previous_end = visit.end_minute


def counts_to_fractions(
    counts: Mapping[str, Sequence[float]],
    *,
    source_design_capacity: Mapping[str, float | None],
) -> dict[str, tuple[float, ...]]:
    """Convert count profiles without clipping overload above fraction 1.0."""

    fractions: dict[str, tuple[float, ...]] = {}
    for name in sorted(counts):
        if name not in source_design_capacity:
            raise ScheduleCompilationError(f"missing source People capacity: {name}")
        capacity = source_design_capacity[name]
        if capacity is None:
            if any(abs(float(value)) > 1e-12 for value in counts[name]):
                raise ScheduleCompilationError(
                    f"Space has no source People capacity: {name}"
                )
            continue
        if not math.isfinite(capacity) or capacity <= 0:
            raise ScheduleCompilationError(f"invalid source People capacity: {name}")
        output: list[float] = []
        for value in counts[name]:
            numeric = float(value)
            if not math.isfinite(numeric) or numeric < 0:
                raise ScheduleCompilationError(f"invalid occupant count: {name}")
            output.append(numeric / capacity)
        fractions[name] = tuple(output)
    return fractions


def write_schedule_file(
    path: str | Path,
    schedules: Mapping[str, Sequence[float]],
    *,
    days: int,
    interval_minutes: int = 15,
) -> Path:
    """Write a headered Schedule:File CSV after strict calendar validation."""

    if days <= 0:
        raise ScheduleCompilationError("days must be positive")
    intervals_per_day = _validate_grid(interval_minutes, 1440)
    expected = days * intervals_per_day
    if not schedules:
        raise ScheduleCompilationError("at least one schedule is required")
    lengths = {len(values) for values in schedules.values()}
    if len(lengths) != 1:
        raise ScheduleCompilationError("all schedules must have the same row count")
    actual = next(iter(lengths))
    if actual != expected:
        raise ScheduleCompilationError(
            f"schedule requires {expected} rows for {days} days, received {actual}"
        )

    names = tuple(sorted(schedules))
    columns: dict[str, tuple[float, ...]] = {}
    for name in names:
        values: list[float] = []
        for raw in schedules[name]:
            value = float(raw)
            if not math.isfinite(value):
                raise ScheduleCompilationError(f"schedule values must be finite: {name}")
            if value < 0:
                raise ScheduleCompilationError(
                    f"schedule values must not be negative: {name}"
                )
            values.append(value)
        columns[name] = tuple(values)

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(names)
        for row_index in range(expected):
            writer.writerow(format(columns[name][row_index], ".12g") for name in names)
    return destination
