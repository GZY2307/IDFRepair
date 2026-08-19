"""Pre-registered Airport Occupancy V3 experiment orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import gzip
import json
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .flight_bank import ControlledParameters, build_daily_plans, retime_plans
from .model import AgentClass, PASSENGER_CLASSES
from .normalization import (
    CohortWeights,
    PersonHourTargets,
    derive_throughput_cohort_weights,
    source_person_hour_targets,
    weights_by_agent,
)
from .schedule_compiler import CompiledSchedule, compile_traces
from .simulation import SimulationResult, simulate_agents
from .source import SourceSpace, load_space_mapping
from .validation import SimulationValidationReport, validate_simulation


class ExperimentError(ValueError):
    """Raised when a pre-registered experiment input is incomplete."""


@dataclass(frozen=True, slots=True)
class ExperimentRegistry:
    monte_carlo_seeds: tuple[int, ...]
    seasonal_seeds: tuple[int, ...]
    annual_seed: int
    base_counts: dict[AgentClass, int]
    base_parameters: ControlledParameters
    schedule_hours_by_function: dict[str, float]
    staff_functions: frozenset[str]
    public_arrivals_per_day: float
    traffic_context_status: str
    evidence_status: str


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    scenario_id: str
    family: str
    counts: dict[AgentClass, int]
    parameters: ControlledParameters
    timing_mode: str | None = None
    volume_factor: float | None = None
    evidence_status: str = "CONTROLLED_NOT_MEASURED"


@dataclass(frozen=True, slots=True)
class ExperimentContext:
    spaces: tuple[SourceSpace, ...]
    groups: dict[str, tuple[str, ...]]
    door_detours: dict[str, tuple[str, ...]]
    location_functions: dict[str, str]
    allowed_edges: dict[AgentClass, set[tuple[str, str]]]
    targets: PersonHourTargets
    registry: ExperimentRegistry


@dataclass(frozen=True, slots=True)
class ScenarioSeedResult:
    scenario_id: str
    family: str
    seed: int
    validation: SimulationValidationReport
    cohort: CohortWeights
    compiled: CompiledSchedule
    summary: dict[str, object]
    function_counts: dict[str, tuple[float, ...]]
    region_counts: dict[str, tuple[float, ...]]
    hvac_group_counts: dict[str, tuple[float, ...]]
    function_flows: dict[tuple[str, str], tuple[float, ...]]


def _counts(payload: Mapping[str, object]) -> dict[AgentClass, int]:
    output: dict[AgentClass, int] = {}
    for agent_class in AgentClass:
        value = int(payload.get(agent_class.value, 0))
        if value < 0:
            raise ExperimentError(f"negative agent count: {agent_class.value}")
        output[agent_class] = value
    return output


def _parameters(payload: Mapping[str, object]) -> ControlledParameters:
    names = ControlledParameters.__dataclass_fields__
    values = {name: payload[name] for name in names if name in payload}
    return ControlledParameters(**values)


def load_parameter_registry(
    path: str | Path,
) -> tuple[ExperimentRegistry, tuple[ScenarioDefinition, ...]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "idfrepair.airport-abm-parameters.v3":
        raise ExperimentError("parameter registry schema is invalid")
    evidence = payload.get("evidence_status")
    if evidence != "CONTROLLED_NOT_MEASURED":
        raise ExperimentError("unsupported inputs must remain controlled")
    seed_payload = payload["seeds"]
    monte_carlo = tuple(int(value) for value in seed_payload["monte_carlo"])
    if monte_carlo != tuple(range(40001, 40031)):
        raise ExperimentError("Monte Carlo seeds differ from the pre-registration")
    seasonal = tuple(int(value) for value in seed_payload["seasonal_energyplus"])
    if seasonal != (40003, 40009, 40015, 40021, 40027):
        raise ExperimentError("seasonal seeds differ from the pre-registration")
    annual = int(seed_payload["annual_energyplus"])
    if annual != 40015:
        raise ExperimentError("annual seed differs from the pre-registration")

    base_counts = _counts(payload["base_agent_counts"])
    base_parameters = _parameters(payload["base_parameters"])
    hours_by_function: dict[str, float] = {}
    for schedule in payload["source_schedule_integrals"].values():
        hours = float(schedule["equivalent_full_load_hours"])
        for function in schedule["functions"]:
            if function in hours_by_function:
                raise ExperimentError(f"duplicate schedule function: {function}")
            hours_by_function[function] = hours
    traffic = payload.get("airport_wide_throughput_context", {})
    if not isinstance(traffic, Mapping):
        raise ExperimentError("airport-wide throughput context is invalid")
    annual_passengers = float(traffic.get("reported_annual_passengers", 0))
    days = int(traffic.get("days_per_year", 0))
    mapping_fraction = float(traffic.get("controlled_model_mapping_fraction", 0))
    traffic_status = str(traffic.get("evidence_status", ""))
    if (
        not math.isfinite(annual_passengers)
        or annual_passengers <= 0
        or days != 365
        or not 0 < mapping_fraction <= 1
        or traffic_status
        != "SOURCE_BACKED_AIRPORT_CONTEXT_CONTROLLED_MODEL_MAPPING"
    ):
        raise ExperimentError("airport-wide throughput context is incomplete")
    registry = ExperimentRegistry(
        monte_carlo_seeds=monte_carlo,
        seasonal_seeds=seasonal,
        annual_seed=annual,
        base_counts=base_counts,
        base_parameters=base_parameters,
        schedule_hours_by_function=hours_by_function,
        staff_functions=frozenset(payload["staff_functions"]),
        public_arrivals_per_day=annual_passengers / days * mapping_fraction,
        traffic_context_status=traffic_status,
        evidence_status=evidence,
    )

    scenarios: list[ScenarioDefinition] = []
    for timing in payload["timing_scenarios"]:
        scenarios.append(
            ScenarioDefinition(
                timing,
                "timing",
                dict(base_counts),
                base_parameters,
                timing_mode=None if timing == "BASELINE_SPREAD" else timing,
            )
        )
    for name, factor_raw in payload["volume_scenarios"].items():
        factor = float(factor_raw)
        counts = dict(base_counts)
        for agent_class in PASSENGER_CLASSES:
            scaled = base_counts[agent_class] * factor
            if not scaled.is_integer():
                raise ExperimentError(f"volume scale is not integral: {name}")
            counts[agent_class] = int(scaled)
        scenarios.append(
            ScenarioDefinition(
                name,
                "volume",
                counts,
                base_parameters,
                volume_factor=factor,
            )
        )
    for name, count_payload in payload["composition_scenarios"].items():
        scenarios.append(
            ScenarioDefinition(
                name,
                "composition",
                _counts(count_payload),
                base_parameters,
            )
        )
    for name, limits in payload["dwell_scenarios"].items():
        scenarios.append(
            ScenarioDefinition(
                name,
                "dwell",
                dict(base_counts),
                replace(
                    base_parameters,
                    departure_wait_minimum=float(limits[0]),
                    departure_wait_maximum=float(limits[1]),
                ),
            )
        )
    for name, probability in payload["discretionary_scenarios"].items():
        scenarios.append(
            ScenarioDefinition(
                name,
                "discretionary",
                dict(base_counts),
                replace(base_parameters, detour_probability=float(probability)),
            )
        )
    if len({scenario.scenario_id for scenario in scenarios}) != len(scenarios):
        raise ExperimentError("scenario identifiers must be unique")
    return registry, tuple(scenarios)


def load_experiment_context(
    *,
    mapping_path: str | Path,
    access_registry_path: str | Path,
    parameter_registry_path: str | Path,
) -> tuple[ExperimentContext, tuple[ScenarioDefinition, ...]]:
    spaces = load_space_mapping(mapping_path)
    registry, scenarios = load_parameter_registry(parameter_registry_path)
    access = json.loads(Path(access_registry_path).read_text(encoding="utf-8"))
    if access.get("schema_version") != "idfrepair.airport-abm-access-registry.v3":
        raise ExperimentError("access registry schema is invalid")
    groups = {name: tuple(values) for name, values in access["groups"].items()}
    functions = {space.name: space.function for space in spaces}
    for node in access["nodes"]:
        functions[node["name"]] = node["function"]
    allowed = {agent_class: set() for agent_class in AgentClass}
    for edge in (*access["passenger_edges"], *access["staff_edges"]):
        if not edge["routable"]:
            continue
        for role in edge["roles"]:
            allowed[AgentClass(role)].add((edge["from"], edge["to"]))
    detours: dict[str, list[str]] = {}
    for edge in access["passenger_edges"]:
        if (
            edge["routable"]
            and edge["evidence_layer"] == "A_EXPLICIT_DOOR"
            and edge["scenario_condition"] == "time_budgeted_detour_only"
            and functions.get(edge["from"]) == "domestic_waiting"
            and functions.get(edge["to"]) in {"commercial", "restaurant", "restroom"}
        ):
            detours.setdefault(edge["from"], []).append(edge["to"])
    targets = source_person_hour_targets(
        spaces,
        equivalent_full_load_hours=registry.schedule_hours_by_function,
        staff_functions=registry.staff_functions,
    )
    context = ExperimentContext(
        spaces=spaces,
        groups=groups,
        door_detours={name: tuple(sorted(set(values))) for name, values in detours.items()},
        location_functions=functions,
        allowed_edges=allowed,
        targets=targets,
        registry=registry,
    )
    return context, scenarios


def run_seed_matrix(
    context: ExperimentContext,
    scenarios: Sequence[ScenarioDefinition],
    *,
    seed: int,
    raw_output_dir: str | Path | None = None,
) -> tuple[ScenarioSeedResult, ...]:
    if seed not in context.registry.monte_carlo_seeds:
        raise ExperimentError(f"seed is not pre-registered: {seed}")
    base_plans = build_daily_plans(
        spaces=context.spaces,
        groups=context.groups,
        door_detours=context.door_detours,
        counts=context.registry.base_counts,
        parameters=context.registry.base_parameters,
        seed=seed,
    )
    base_result = simulate_agents(base_plans, seed=seed)
    _require_valid(context, base_result)
    supported = {space.name for space in context.spaces if space.bem_people_supported}
    cohort = derive_throughput_cohort_weights(
        base_result,
        target_public_arrivals=context.registry.public_arrivals_per_day,
        targets=context.targets,
        physical_locations=supported,
    )

    output: list[ScenarioSeedResult] = []
    for scenario in scenarios:
        if scenario.family == "timing":
            plans = (
                base_plans
                if scenario.timing_mode is None
                else retime_plans(base_plans, scenario.timing_mode, seed=seed)
            )
        else:
            plans = build_daily_plans(
                spaces=context.spaces,
                groups=context.groups,
                door_detours=context.door_detours,
                counts=scenario.counts,
                parameters=scenario.parameters,
                seed=seed,
            )
        result = simulate_agents(plans, seed=seed)
        validation = _require_valid(context, result)
        weights = weights_by_agent(result, cohort)
        compiled = compile_traces(
            result.traces,
            space_areas_m2={space.name: space.area_m2 for space in context.spaces},
            interval_minutes=15,
            horizon_minutes=1440,
            agent_weights=weights,
            virtual_locations=set(context.location_functions).difference(
                space.name for space in context.spaces
            ),
            periodic=True,
        )
        summary, functions, regions, systems, flows = _summarize(
            context, scenario, seed, result, validation, cohort, compiled, weights
        )
        if raw_output_dir is not None:
            destination = (
                Path(raw_output_dir)
                / scenario.scenario_id
                / f"seed-{seed}.jsonl.gz"
            )
            write_private_traces(destination, result, weights)
        output.append(
            ScenarioSeedResult(
                scenario_id=scenario.scenario_id,
                family=scenario.family,
                seed=seed,
                validation=validation,
                cohort=cohort,
                compiled=compiled,
                summary=summary,
                function_counts=functions,
                region_counts=regions,
                hvac_group_counts=systems,
                function_flows=flows,
            )
        )
    return tuple(output)


def _require_valid(
    context: ExperimentContext, result: SimulationResult
) -> SimulationValidationReport:
    validation = validate_simulation(
        result,
        context.location_functions,
        context.allowed_edges,
    )
    if validation.status != "PASS":
        raise ExperimentError("ABM_INVALID:" + "|".join(validation.violations[:20]))
    return validation


def _series_sum(
    profiles: Iterable[Sequence[float]], interval_count: int
) -> tuple[float, ...]:
    result = [0.0] * interval_count
    for profile in profiles:
        if len(profile) != interval_count:
            raise ExperimentError("profile length mismatch")
        for index, value in enumerate(profile):
            result[index] += float(value)
    return tuple(result)


def _summarize(
    context: ExperimentContext,
    scenario: ScenarioDefinition,
    seed: int,
    result: SimulationResult,
    validation: SimulationValidationReport,
    cohort: CohortWeights,
    compiled: CompiledSchedule,
    weights: Mapping[str, float],
):
    interval_count = len(compiled.interval_labels)
    spaces_by_name = {space.name: space for space in context.spaces}
    supported = {space.name for space in context.spaces if space.bem_people_supported}
    bem_public = 0.0
    bem_staff = 0.0
    for name in supported:
        classes = compiled.class_counts[name]
        bem_public += sum(
            sum(classes[agent_class.value]) * compiled.interval_minutes / 60.0
            for agent_class in PASSENGER_CLASSES
        )
        bem_staff += (
            sum(classes[AgentClass.STAFF.value]) * compiled.interval_minutes / 60.0
        )

    function_names = sorted({space.function for space in context.spaces})
    function_counts = {
        function: _series_sum(
            (
                compiled.space_counts[space.name]
                for space in context.spaces
                if space.function == function
            ),
            interval_count,
        )
        for function in function_names
    }
    region_names = sorted({space.region for space in context.spaces})
    region_counts = {
        region: _series_sum(
            (
                compiled.space_counts[space.name]
                for space in context.spaces
                if space.region == region
            ),
            interval_count,
        )
        for region in region_names
    }

    def system_name(space: SourceSpace) -> str:
        return (
            space.public_air_loop
            or space.office_doas
            or space.zone_hvac
            or "NO_SOURCE_HVAC_GROUP"
        )

    system_names = sorted({system_name(space) for space in context.spaces})
    system_counts = {
        system: _series_sum(
            (
                compiled.space_counts[space.name]
                for space in context.spaces
                if system_name(space) == system
            ),
            interval_count,
        )
        for system in system_names
    }
    function_flow_work: dict[tuple[str, str], list[float]] = {}
    for (source, target), profile in compiled.flow_counts.items():
        source_function = context.location_functions.get(source, source)
        target_function = context.location_functions.get(target, target)
        edge = (source_function, target_function)
        values = function_flow_work.setdefault(edge, [0.0] * interval_count)
        for index, value in enumerate(profile):
            values[index] += value
    function_flows = {
        edge: tuple(values) for edge, values in sorted(function_flow_work.items())
    }

    total_profile = _series_sum(compiled.space_counts.values(), interval_count)
    simulated_by_class = {
        agent_class.value: sum(
            trace.agent_class is agent_class for trace in result.traces.values()
        )
        for agent_class in AgentClass
    }
    equivalent_by_class = {
        agent_class.value: sum(
            weights[agent_id]
            for agent_id, trace in result.traces.items()
            if trace.agent_class is agent_class
        )
        for agent_class in AgentClass
    }
    max_space_name, max_space_peak = max(
        (
            (name, max(profile, default=0.0))
            for name, profile in compiled.space_counts.items()
        ),
        key=lambda item: item[1],
    )
    max_function_name, max_function_peak = max(
        (
            (name, max(profile, default=0.0))
            for name, profile in function_counts.items()
        ),
        key=lambda item: item[1],
    )
    summary: dict[str, object] = {
        "scenario_id": scenario.scenario_id,
        "family": scenario.family,
        "seed": seed,
        "evidence_status": scenario.evidence_status,
        "simulated_agents": len(result.traces),
        "simulated_agents_by_class": simulated_by_class,
        "equivalent_arrivals_by_class": equivalent_by_class,
        "public_cohort_weight": cohort.public_weight,
        "staff_cohort_weight": cohort.staff_weight,
        "public_person_hours_bem": bem_public,
        "staff_person_hours_bem": bem_staff,
        "total_person_hours_bem": bem_public + bem_staff,
        "tracked_person_hours_including_flow_only": compiled.person_hours,
        "whole_building_peak_occupancy": max(total_profile, default=0.0),
        "peak_space_private_name": max_space_name,
        "peak_space_occupancy": max_space_peak,
        "peak_function": max_function_name,
        "peak_function_occupancy": max_function_peak,
        "validation_status": validation.status,
        "violation_count": validation.violation_count,
        "invalid_route_count": validation.violation_count,
        "passenger_office_violations": sum(
            "PASSENGER_FORBIDDEN_FUNCTION:office" in value
            for value in validation.violations
        ),
        "spawn_count": result.spawned_count,
        "terminal_count": result.terminal_count,
        "active_count": result.active_count,
        "volume_factor": scenario.volume_factor,
        "timing_mode": scenario.timing_mode,
        "parameters": asdict(scenario.parameters),
    }
    if not all(math.isfinite(float(value)) for value in total_profile):
        raise ExperimentError("non-finite occupancy profile")
    return summary, function_counts, region_counts, system_counts, function_flows


def write_private_traces(
    path: str | Path,
    result: SimulationResult,
    weights: Mapping[str, float],
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(destination, "wt", encoding="utf-8", newline="\n") as handle:
        for agent_id in sorted(result.traces):
            trace = result.traces[agent_id]
            payload = {
                "agent_id": agent_id,
                "agent_class": trace.agent_class.value,
                "weight": weights[agent_id],
                "terminal_state": trace.terminal_state,
                "terminal_minute": trace.terminal_minute,
                "visits": [
                    [
                        visit.location,
                        visit.stage,
                        visit.start_minute,
                        visit.end_minute,
                        visit.detour_anchor,
                    ]
                    for visit in trace.visits
                ],
                "flows": [
                    [flow.source, flow.target, flow.minute] for flow in trace.flows
                ],
            }
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    return destination
