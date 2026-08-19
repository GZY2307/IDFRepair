"""Stream independently generated daily ABM profiles into annual schedules."""

from __future__ import annotations

from contextlib import ExitStack
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

from .experiment import (
    ExperimentContext,
    ExperimentError,
    ScenarioDefinition,
)
from .flight_bank import build_daily_plans, retime_plans
from .model import AgentClass, PASSENGER_CLASSES
from .normalization import CohortWeights, weights_by_agent
from .schedule_compiler import compile_traces
from .simulation import SimulationResult, simulate_agents
from .source import SourceSpace
from .validation import validate_simulation
from .v31 import (
    AIRPORT_WIDE_STRESS_CONTEXT,
    annual_cohort_weights,
)


class AnnualScheduleError(ValueError):
    """Raised when a full-year schedule cannot be emitted exactly."""


@dataclass(frozen=True, slots=True)
class AnnualScheduleArtifact:
    scenario_id: str
    schedule_path: Path
    manifest_path: Path
    row_count: int
    public_person_hours: float
    staff_person_hours: float
    whole_building_peak_occupancy: float
    cohort: CohortWeights


def annual_day_seed(master_seed: int, day_index: int) -> int:
    if master_seed <= 0:
        raise AnnualScheduleError("master seed must be positive")
    if not 0 <= day_index < 365:
        raise AnnualScheduleError("day index must lie in 0..364")
    return master_seed * 1000 + day_index + 1


def write_people_manifest(
    path: str | Path,
    *,
    schedule_path: str | Path,
    spaces: Iterable[SourceSpace],
    days: int,
    interval_minutes: int,
) -> Path:
    supported = tuple(
        sorted(
            (space for space in spaces if space.bem_people_supported),
            key=lambda space: space.name,
        )
    )
    if not supported:
        raise AnnualScheduleError("manifest has no source-supported People Spaces")
    rows = [
        {
            "source_space_name": space.name,
            "schedule_column": index,
            "source_design_people": space.source_design_people,
            # The source mapping stores area to 0.001 m2. Carry only the
            # resulting half-unit rounding envelope into the derivative gate.
            "source_design_people_tolerance": (
                0.0005 / float(space.people_m2_per_person) + 1.0e-9
            ),
        }
        for index, space in enumerate(supported, start=1)
    ]
    payload = {
        "schema_version": "idfrepair.airport-abm-people-manifest.v3",
        "calendar_days": days,
        "interval_minutes": interval_minutes,
        "schedule_file": str(Path(schedule_path).resolve()),
        "spaces": rows,
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def _validate_result(context: ExperimentContext, result: SimulationResult) -> None:
    report = validate_simulation(
        result,
        context.location_functions,
        context.allowed_edges,
    )
    if report.status != "PASS":
        raise AnnualScheduleError("ABM_INVALID:" + "|".join(report.violations[:20]))


def _physical_hours(
    result: SimulationResult,
    supported: frozenset[str],
) -> tuple[float, float]:
    public = 0.0
    staff = 0.0
    for trace in result.traces.values():
        hours = sum(
            max(0.0, visit.end_minute - visit.start_minute) / 60.0
            for visit in trace.visits
            if visit.location in supported
        )
        if trace.agent_class in PASSENGER_CLASSES:
            public += hours
        elif trace.agent_class is AgentClass.STAFF:
            staff += hours
    return public, staff


def _base_day(context: ExperimentContext, seed: int):
    plans = build_daily_plans(
        spaces=context.spaces,
        groups=context.groups,
        door_detours=context.door_detours,
        counts=context.registry.base_counts,
        parameters=context.registry.base_parameters,
        seed=seed,
    )
    result = simulate_agents(plans, seed=seed)
    _validate_result(context, result)
    return plans, result


def generate_annual_timing_schedules(
    context: ExperimentContext,
    scenarios: Sequence[ScenarioDefinition],
    *,
    output_dir: str | Path,
    master_seed: int,
    scale_mode: str = AIRPORT_WIDE_STRESS_CONTEXT,
) -> tuple[AnnualScheduleArtifact, ...]:
    """Generate 365 distinct daily realizations and stream 35040 rows per case."""

    selected = tuple(scenarios)
    if not selected or any(scenario.family != "timing" for scenario in selected):
        raise AnnualScheduleError("annual core accepts timing scenarios only")
    if master_seed != context.registry.annual_seed:
        raise AnnualScheduleError("annual master seed differs from pre-registration")
    supported_spaces = tuple(
        sorted(
            (space for space in context.spaces if space.bem_people_supported),
            key=lambda space: space.name,
        )
    )
    supported_names = frozenset(space.name for space in supported_spaces)
    capacities = {
        space.name: float(space.source_design_people) for space in supported_spaces
    }

    raw_public = 0.0
    raw_staff = 0.0
    for day_index in range(365):
        _, result = _base_day(context, annual_day_seed(master_seed, day_index))
        public, staff = _physical_hours(result, supported_names)
        raw_public += public
        raw_staff += staff
    if raw_public <= 0 or raw_staff <= 0:
        raise AnnualScheduleError("annual raw person-hours must be positive")
    public_agents_per_day = sum(context.registry.base_counts[name] for name in PASSENGER_CLASSES)
    cohort = annual_cohort_weights(
        raw_public_person_hours=raw_public,
        raw_staff_person_hours=raw_staff,
        calendar_days=365,
        public_agents_per_day=public_agents_per_day,
        targets=context.targets,
        airport_wide_public_arrivals=context.registry.public_arrivals_per_day,
        scale_mode=scale_mode,
    )

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    writers: dict[str, csv.writer] = {}
    schedules: dict[str, Path] = {}
    row_counts = {scenario.scenario_id: 0 for scenario in selected}
    public_hours = {scenario.scenario_id: 0.0 for scenario in selected}
    staff_hours = {scenario.scenario_id: 0.0 for scenario in selected}
    peaks = {scenario.scenario_id: 0.0 for scenario in selected}
    virtual = set(context.location_functions).difference(
        space.name for space in context.spaces
    )
    with ExitStack() as stack:
        for scenario in selected:
            scenario_dir = root / scenario.scenario_id
            scenario_dir.mkdir(parents=True, exist_ok=True)
            schedule_path = scenario_dir / "occupancy.csv"
            handle = stack.enter_context(
                schedule_path.open("w", encoding="utf-8", newline="")
            )
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(space.name for space in supported_spaces)
            writers[scenario.scenario_id] = writer
            schedules[scenario.scenario_id] = schedule_path

        for day_index in range(365):
            day_seed = annual_day_seed(master_seed, day_index)
            base_plans, base_result = _base_day(context, day_seed)
            for scenario in selected:
                if scenario.timing_mode is None:
                    result = base_result
                else:
                    plans = retime_plans(
                        base_plans,
                        scenario.timing_mode,
                        seed=day_seed,
                    )
                    result = simulate_agents(plans, seed=day_seed)
                    _validate_result(context, result)
                weights = weights_by_agent(result, cohort)
                compiled = compile_traces(
                    result.traces,
                    space_areas_m2={space.name: space.area_m2 for space in context.spaces},
                    interval_minutes=15,
                    horizon_minutes=1440,
                    agent_weights=weights,
                    virtual_locations=virtual,
                    periodic=True,
                )
                scenario_id = scenario.scenario_id
                for interval_index in range(96):
                    writers[scenario_id].writerow(
                        format(
                            compiled.space_counts[space.name][interval_index]
                            / capacities[space.name],
                            ".8g",
                        )
                        for space in supported_spaces
                    )
                    row_counts[scenario_id] += 1
                day_public = 0.0
                day_staff = 0.0
                total_profile = [0.0] * 96
                for space in supported_spaces:
                    classes = compiled.class_counts[space.name]
                    day_public += sum(
                        sum(classes[agent_class.value]) * 0.25
                        for agent_class in PASSENGER_CLASSES
                    )
                    day_staff += sum(classes[AgentClass.STAFF.value]) * 0.25
                    for index, value in enumerate(compiled.space_counts[space.name]):
                        total_profile[index] += value
                public_hours[scenario_id] += day_public
                staff_hours[scenario_id] += day_staff
                peaks[scenario_id] = max(peaks[scenario_id], *total_profile)

    expected_rows = 365 * 96
    for scenario in selected:
        scenario_id = scenario.scenario_id
        if row_counts[scenario_id] != expected_rows:
            raise AnnualScheduleError(
                f"annual row count mismatch: {scenario_id}:{row_counts[scenario_id]}"
            )
    reference = selected[0].scenario_id
    for scenario in selected[1:]:
        scenario_id = scenario.scenario_id
        if not math.isclose(
            public_hours[scenario_id], public_hours[reference], rel_tol=0, abs_tol=1e-5
        ) or not math.isclose(
            staff_hours[scenario_id], staff_hours[reference], rel_tol=0, abs_tol=1e-5
        ):
            raise AnnualScheduleError(
                f"annual timing person-hours differ: {reference}:{scenario_id}"
            )

    artifacts: list[AnnualScheduleArtifact] = []
    for scenario in selected:
        scenario_id = scenario.scenario_id
        scenario_dir = root / scenario_id
        manifest = write_people_manifest(
            scenario_dir / "people_manifest.json",
            schedule_path=schedules[scenario_id],
            spaces=supported_spaces,
            days=365,
            interval_minutes=15,
        )
        summary = {
            "schema_version": "idfrepair.airport-abm-annual-schedule.v3",
            "scenario_id": scenario_id,
            "master_seed": master_seed,
            "daily_stream_count": 365,
            "row_count": row_counts[scenario_id],
            "interval_minutes": 15,
            "source_supported_space_count": len(supported_spaces),
            "public_person_hours": public_hours[scenario_id],
            "staff_person_hours": staff_hours[scenario_id],
            "whole_building_peak_occupancy": peaks[scenario_id],
            "public_cohort_weight": cohort.public_weight,
            "staff_cohort_weight": cohort.staff_weight,
            "evidence_status": "CONTROLLED_NOT_MEASURED",
            "occupancy_scale": scale_mode,
        }
        (scenario_dir / "annual_schedule_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        artifacts.append(
            AnnualScheduleArtifact(
                scenario_id=scenario_id,
                schedule_path=schedules[scenario_id],
                manifest_path=manifest,
                row_count=row_counts[scenario_id],
                public_person_hours=public_hours[scenario_id],
                staff_person_hours=staff_hours[scenario_id],
                whole_building_peak_occupancy=peaks[scenario_id],
                cohort=cohort,
            )
        )
    return tuple(artifacts)
