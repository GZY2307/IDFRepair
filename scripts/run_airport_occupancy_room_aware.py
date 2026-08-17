#!/usr/bin/env python3
"""Build and run the source-backed room-aware terminal occupancy suite.

All generated model and EnergyPlus artifacts stay below an explicit derived
root. The source OSM is only hashed/read and is never passed as an output path.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from idfrepair.analysis.occupancy.energyplus import (  # noqa: E402
    discover_output_variables,
    run_energyplus,
)
from idfrepair.analysis.occupancy.models import OutputRequest  # noqa: E402
from idfrepair.analysis.occupancy_room_aware.compiler import (  # noqa: E402
    CompiledRoomScenario,
    RoomAwareScenario,
    compile_room_scenario,
)
from idfrepair.analysis.occupancy_room_aware.flow import (  # noqa: E402
    build_source_flow_topology,
    write_flow_artifacts,
)
from idfrepair.analysis.occupancy_room_aware.profiles import (  # noqa: E402
    PUBLIC_DYNAMIC_CATEGORIES,
    PUBLIC_FACING_UNSPLIT_CATEGORIES,
    PUBLIC_LINKED_CATEGORIES,
    PUBLIC_ONLY_CATEGORIES,
    STAFF_CATEGORIES,
    SpaceCapacity,
    allocate_spatial_counts,
    apply_entrance_phase_profiles,
    apply_public_volume_by_space,
    build_category_profiles,
    build_entrance_region_scenarios,
    build_space_temporal_scenarios,
)
from idfrepair.analysis.occupancy_room_aware.provenance import (  # noqa: E402
    validate_baseline_provenance_chain,
)
from idfrepair.analysis.occupancy_room_aware.results import (  # noqa: E402
    ANNUAL_OUTPUT_VARIABLES,
    SEASONAL_OUTPUT_VARIABLES,
    ExtractedRoomResults,
    bindings_from_audit,
    build_run_manifest,
    expected_run_identity,
    extract_room_results,
    ideal_loads_key_to_zone,
    migrate_v1_run_manifest,
    prepare_annual_idf,
    prepare_controlled_day_idf,
    validate_run_manifest,
)
from idfrepair.knowledge.idd import IDDSchema, parse_idd  # noqa: E402


SOURCE_SHA256 = "6463d680b834230e665df8a250c694cae57c3d5cb3c877d1ad22a9c761fcccdb"
SEASONAL_PERIODS = {
    "winter": (1, 15, "Wednesday"),
    "summer": (7, 15, "Wednesday"),
    "shoulder": (4, 15, "Wednesday"),
}
ANNUAL_SCENARIOS = (
    "baseline_s",
    "baseline_r",
    "public_morning",
    "public_midday",
    "public_evening",
    "public_perimeter",
    "public_core",
    "entrance_2_lead",
    "entrance_3_lead",
)


@dataclass(frozen=True, slots=True)
class ScenarioArtifact:
    scenario_id: str
    scenario_kind: str
    idf_path: Path
    schedule_path: Path | None
    compiled_person_hours: float | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RunJob:
    scenario: ScenarioArtifact
    period_id: str
    prepared_idf: Path
    output_directory: Path
    minutes_per_output_step: float
    expected_variables: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"json_object_required:{path}")
    return payload


def _guard_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    allowed = root.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise ValueError(f"runner_path_outside_derived_root:{resolved}")
    return resolved


def _person_hour_metadata(
    profiles_by_space: dict[str, tuple[float, ...]],
    design_by_space: dict[str, float],
    category_by_space: dict[str, str],
) -> dict[str, float]:
    totals = {
        "public_person_hours": 0.0,
        "staff_person_hours": 0.0,
        "public_facing_unsplit_person_hours": 0.0,
        "public_linked_person_hours": 0.0,
        "total_person_hours": 0.0,
    }
    for space_name, profile in profiles_by_space.items():
        value = math.fsum(profile) * design_by_space[space_name] * 0.25
        category = category_by_space[space_name]
        totals["total_person_hours"] += value
        if category in PUBLIC_ONLY_CATEGORIES:
            totals["public_person_hours"] += value
        elif category in STAFF_CATEGORIES:
            totals["staff_person_hours"] += value
        elif category in PUBLIC_FACING_UNSPLIT_CATEGORIES:
            totals["public_facing_unsplit_person_hours"] += value
        elif category in PUBLIC_LINKED_CATEGORIES:
            totals["public_linked_person_hours"] += value
    return totals


def _spatial_profiles(
    *,
    mode: str,
    baseline_by_space: dict[str, tuple[float, ...]],
    capacities: tuple[SpaceCapacity, ...],
    design_by_space: dict[str, float],
    category_by_space: dict[str, str],
) -> dict[str, tuple[float, ...]]:
    values: dict[str, list[float]] = {
        space_name: list(baseline_by_space[space_name])
        for space_name in category_by_space
    }
    for category in PUBLIC_DYNAMIC_CATEGORIES:
        selected = tuple(row for row in capacities if row.category == category)
        for step in range(96):
            category_total = math.fsum(
                row.design_people * baseline_by_space[row.space_name][step]
                for row in selected
            )
            allocation = allocate_spatial_counts(
                {category: category_total},
                selected,
                mode=mode,
            )
            for row in selected:
                values[row.space_name][step] = (
                    allocation[row.space_name] / design_by_space[row.space_name]
                )
    return {name: tuple(profile) for name, profile in values.items()}


def build_scenario_definitions(
    audit: dict[str, Any],
    people_manifest: dict[str, Any],
    flow_topology: dict[str, Any],
) -> dict[str, RoomAwareScenario]:
    """Expand six category profiles to exact Space schedules and counterfactuals."""

    audit_by_name = {row["source_space_name"]: row for row in audit["spaces"]}
    manifest_rows = people_manifest["spaces"]
    if len(audit_by_name) != 304 or len(manifest_rows) != 304:
        raise ValueError("runner_space_count_mismatch")
    design_by_space = {
        row["source_space_name"]: float(row["target_design_people"])
        for row in manifest_rows
    }
    category_by_space = {
        name: str(row["room_category"]) for name, row in audit_by_name.items()
    }
    if set(design_by_space) != set(category_by_space):
        raise ValueError("runner_manifest_audit_space_mismatch")
    category_profiles = build_category_profiles()
    capacities = tuple(
        SpaceCapacity(
            space_name=name,
            category=category_by_space[name],
            design_people=design_by_space[name],
            exterior_area_m2=float(audit_by_name[name]["exterior_area_m2"]),
            floor_area_m2=float(audit_by_name[name]["floor_area_m2"]),
        )
        for name in sorted(audit_by_name, key=str.casefold)
    )

    scenario_profiles: dict[str, tuple[str, dict[str, tuple[float, ...]]]] = {}
    baseline = apply_entrance_phase_profiles(
        category_profiles,
        category_by_space,
        flow_topology,
    )
    scenario_profiles["baseline_r"] = ("room_aware_reference", baseline)
    for scenario_id, profiles in build_space_temporal_scenarios(
        baseline,
        category_by_space,
    ).items():
        scenario_profiles[scenario_id] = (
            "temporal_public_redistribution",
            profiles,
        )
    for scenario_id, profiles in build_entrance_region_scenarios(
        baseline,
        category_by_space,
        flow_topology,
    ).items():
        scenario_profiles[scenario_id] = (
            "entrance_region_temporal_redistribution",
            profiles,
        )
    for mode in ("perimeter", "core"):
        scenario_profiles[f"public_{mode}"] = (
            "within_category_spatial_redistribution",
            _spatial_profiles(
                mode=mode,
                baseline_by_space=baseline,
                capacities=capacities,
                design_by_space=design_by_space,
                category_by_space=category_by_space,
            ),
        )
    for multiplier in (0.50, 0.75, 1.00, 1.25, 1.50):
        scenario_profiles[f"public_volume_{multiplier:.2f}".replace(".", "_")] = (
            "public_volume_sensitivity",
            apply_public_volume_by_space(
                baseline,
                category_by_space,
                multiplier,
            ),
        )

    result = {}
    for scenario_id, (kind, profiles) in scenario_profiles.items():
        metadata = {
            "evidence_tier": "TIER_C_CONTROLLED_NOT_MEASURED",
            "staff_fixed": kind != "room_aware_reference",
            "entrance_spaces": list(flow_topology["entrance_spaces"]),
            "flow_phase_semantics": flow_topology["phase_semantics"],
            "walking_route_claim": False,
            **_person_hour_metadata(profiles, design_by_space, category_by_space),
        }
        result[scenario_id] = RoomAwareScenario(
            scenario_id=scenario_id,
            scenario_kind=kind,
            profiles_by_space=profiles,
            design_people_by_space=design_by_space,
            metadata=metadata,
        )
    return result


def compile_scenarios(
    *,
    baseline_r_idf: Path,
    idd: IDDSchema,
    definitions: dict[str, RoomAwareScenario],
    derived_root: Path,
) -> dict[str, ScenarioArtifact]:
    output_root = _guard_root(derived_root / "compiled", derived_root)
    artifacts: dict[str, ScenarioArtifact] = {}
    registry: list[dict[str, Any]] = []
    for scenario_id in sorted(definitions):
        definition = definitions[scenario_id]
        compiled: CompiledRoomScenario = compile_room_scenario(
            baseline_r_idf,
            idd,
            definition,
            output_root / scenario_id,
            allowed_root=derived_root,
        )
        metadata = dict(definition.metadata or {})
        artifacts[scenario_id] = ScenarioArtifact(
            scenario_id=scenario_id,
            scenario_kind=definition.scenario_kind,
            idf_path=compiled.idf_path,
            schedule_path=compiled.schedule_path,
            compiled_person_hours=compiled.daily_person_hours,
            metadata=metadata,
        )
        registry.append(
            {
                "scenario_id": scenario_id,
                "scenario_kind": definition.scenario_kind,
                "scenario_digest": compiled.scenario_digest,
                "people_count": compiled.people_count,
                "unique_profile_count": compiled.unique_profile_count,
                "daily_person_hours": compiled.daily_person_hours,
                **metadata,
            }
        )
    registry_path = derived_root / "scenario_registry.json"
    registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifacts


def _select_requests(
    rdd_path: Path,
    desired: tuple[str, ...],
    *,
    frequency: str,
) -> tuple[OutputRequest, ...]:
    available = discover_output_variables(
        Path(rdd_path).read_text(encoding="utf-8", errors="replace")
    )
    return tuple(
        OutputRequest(variable, "room_aware", frequency=frequency)
        for variable in desired
        if variable in available
    )


def _prepare_seasonal_jobs(
    *,
    artifacts: dict[str, ScenarioArtifact],
    baseline_s_idf: Path,
    idd: IDDSchema,
    requests: tuple[OutputRequest, ...],
    derived_root: Path,
) -> list[RunJob]:
    all_artifacts = {
        "baseline_s": ScenarioArtifact(
            scenario_id="baseline_s",
            scenario_kind="source_preserving",
            idf_path=baseline_s_idf,
            schedule_path=None,
            compiled_person_hours=None,
            metadata={"evidence_tier": "TIER_A_SOURCE_BACKED"},
        ),
        **artifacts,
    }
    jobs = []
    for scenario_id in sorted(all_artifacts):
        artifact = all_artifacts[scenario_id]
        prepared_root = _guard_root(
            derived_root / "prepared" / "seasonal" / scenario_id,
            derived_root,
        )
        for period_id, (month, day, day_of_week) in SEASONAL_PERIODS.items():
            destination = prepared_root / f"{period_id}.idf"
            prepare_controlled_day_idf(
                artifact.idf_path,
                idd,
                destination,
                output_requests=requests,
                month=month,
                day=day,
                day_of_week=day_of_week,
                resolution_minutes=15,
            )
            if artifact.schedule_path is not None:
                shutil.copy2(
                    artifact.schedule_path,
                    destination.parent / artifact.schedule_path.name,
                )
            jobs.append(
                RunJob(
                    scenario=artifact,
                    period_id=period_id,
                    prepared_idf=destination,
                    output_directory=derived_root
                    / "runs"
                    / "seasonal_weekday_v2"
                    / period_id
                    / scenario_id,
                    minutes_per_output_step=15.0,
                    expected_variables=SEASONAL_OUTPUT_VARIABLES,
                )
            )
    return jobs


def _prepare_annual_jobs(
    *,
    artifacts: dict[str, ScenarioArtifact],
    baseline_s_idf: Path,
    idd: IDDSchema,
    requests: tuple[OutputRequest, ...],
    derived_root: Path,
) -> dict[str, RunJob]:
    selected = {
        "baseline_s": ScenarioArtifact(
            scenario_id="baseline_s",
            scenario_kind="source_preserving",
            idf_path=baseline_s_idf,
            schedule_path=None,
            compiled_person_hours=None,
            metadata={"evidence_tier": "TIER_A_SOURCE_BACKED"},
        ),
        **{name: artifacts[name] for name in ANNUAL_SCENARIOS if name != "baseline_s"},
    }
    jobs = {}
    for scenario_id in ANNUAL_SCENARIOS:
        artifact = selected[scenario_id]
        destination = (
            derived_root / "prepared" / "annual" / scenario_id / "annual.idf"
        )
        prepare_annual_idf(
            artifact.idf_path,
            idd,
            destination,
            output_requests=requests,
            resolution_minutes=15,
        )
        if artifact.schedule_path is not None:
            shutil.copy2(
                artifact.schedule_path,
                destination.parent / artifact.schedule_path.name,
            )
        jobs[scenario_id] = RunJob(
            scenario=artifact,
            period_id="annual",
            prepared_idf=destination,
            output_directory=derived_root / "runs" / "annual_compact_v2" / scenario_id,
            minutes_per_output_step=60.0,
            expected_variables=ANNUAL_OUTPUT_VARIABLES,
        )
    return jobs


def _run_one(
    job: RunJob,
    *,
    executable: Path,
    idd_path: Path,
    weather_path: Path,
    source_osm: Path,
    derived_root: Path,
    timeout_seconds: int,
) -> Path:
    output = _guard_root(job.output_directory, derived_root)
    existing_manifest = output / "run_manifest.json"
    schedule_path = (
        job.prepared_idf.parent / job.scenario.schedule_path.name
        if job.scenario.schedule_path is not None
        else None
    )
    identity = expected_run_identity(
        scenario_id=job.scenario.scenario_id,
        period_id=job.period_id,
        executable_path=executable,
        idd_path=idd_path,
        weather_path=weather_path,
        source_osm_path=source_osm,
        prepared_idf_path=job.prepared_idf,
        schedule_path=schedule_path,
        minutes_per_output_step=job.minutes_per_output_step,
        expected_variables=job.expected_variables,
    )
    if existing_manifest.is_file():
        payload = _load_json(existing_manifest)
        if payload.get("schema_version") == "idfrepair.room-aware-run.v1":
            migrate_v1_run_manifest(
                existing_manifest,
                expected_identity=identity,
            )
            return output
        validate_run_manifest(existing_manifest, expected_identity=identity)
        return output
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"runner_nonempty_failed_output:{output}")
    run = run_energyplus(
        executable=executable,
        idf_path=job.prepared_idf,
        output_directory=output,
        idd_path=idd_path,
        weather_path=weather_path,
        timeout_seconds=timeout_seconds,
    )
    build_run_manifest(
        run,
        scenario_id=job.scenario.scenario_id,
        period_id=job.period_id,
        source_osm_path=source_osm,
        schedule_path=schedule_path,
        idd_path=idd_path,
        weather_path=weather_path,
        derived_root=derived_root,
        minutes_per_output_step=job.minutes_per_output_step,
        expected_variables=job.expected_variables,
    )
    return output


def _run_jobs(
    jobs: list[RunJob],
    *,
    max_workers: int,
    executable: Path,
    idd_path: Path,
    weather_path: Path,
    source_osm: Path,
    derived_root: Path,
    timeout_seconds: int,
) -> dict[tuple[str, str], Path]:
    if not 1 <= max_workers <= 2:
        raise ValueError("runner_max_workers_must_be_one_or_two")
    outputs: dict[tuple[str, str], Path] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _run_one,
                job,
                executable=executable,
                idd_path=idd_path,
                weather_path=weather_path,
                source_osm=source_osm,
                derived_root=derived_root,
                timeout_seconds=timeout_seconds,
            ): job
            for job in jobs
        }
        for future in as_completed(futures):
            job = futures[future]
            try:
                output = future.result()
                manifest = _load_json(output / "run_manifest.json")
                if manifest.get("status") != "PASS":
                    errors.append(f"{job.period_id}/{job.scenario.scenario_id}:simulation_failed")
                else:
                    outputs[(job.period_id, job.scenario.scenario_id)] = output
                print(
                    json.dumps(
                        {
                            "period": job.period_id,
                            "scenario": job.scenario.scenario_id,
                            "status": manifest.get("status"),
                            "elapsed_seconds": manifest.get("elapsed_seconds"),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            except Exception as exc:  # preserve all peer run outcomes before failing
                errors.append(f"{job.period_id}/{job.scenario.scenario_id}:{exc}")
    if errors:
        raise RuntimeError("runner_jobs_failed:" + "|".join(errors))
    return outputs


def _result_payload(result: ExtractedRoomResults) -> dict[str, Any]:
    return {
        "scenario_id": result.scenario_id,
        "period_id": result.period_id,
        "timestamps": list(result.timestamps),
        "zones": [asdict(row) for row in result.zones],
        "categories": [asdict(row) for row in result.categories],
        "whole_building": asdict(result.whole_building),
        "occupancy_by_space": {
            name: list(values) for name, values in result.occupancy_by_space.items()
        },
    }


def _extract_all(
    jobs: list[RunJob],
    outputs: dict[tuple[str, str], Path],
    *,
    audit: dict[str, Any],
    reference_design_people: dict[str, float],
    derived_root: Path,
    suite_id: str,
) -> list[ExtractedRoomResults]:
    results = []
    compact_root = derived_root / "compact" / suite_id
    compact_root.mkdir(parents=True, exist_ok=True)
    for job in sorted(jobs, key=lambda item: (item.period_id, item.scenario.scenario_id)):
        key = (job.period_id, job.scenario.scenario_id)
        if key not in outputs:
            continue
        bindings = bindings_from_audit(
            audit,
            design_people_by_space=(
                None
                if job.scenario.scenario_id == "baseline_s"
                else reference_design_people
            ),
        )
        capture = suite_id == "seasonal" and key == ("winter", "baseline_r")
        result = extract_room_results(
            outputs[key] / "eplusout.csv",
            bindings,
            scenario_id=job.scenario.scenario_id,
            period_id=job.period_id,
            expected_variables=job.expected_variables,
            minutes_per_step=job.minutes_per_output_step,
            capture_occupancy=capture,
            key_to_zone=ideal_loads_key_to_zone(job.prepared_idf),
        )
        payload = _result_payload(result)
        (compact_root / f"{job.period_id}__{job.scenario.scenario_id}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        results.append(result)
    return results


def _write_result_tables(
    results: list[ExtractedRoomResults],
    *,
    derived_root: Path,
    suite_id: str,
) -> None:
    compact_root = derived_root / "compact" / suite_id
    compact_root.mkdir(parents=True, exist_ok=True)
    payload = [_result_payload(result) for result in results]
    (compact_root / "results.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for grouping, filename in (
        ("category", "category_results.csv"),
        ("whole_building", "scenario_results.csv"),
        ("zone", "zone_results.csv"),
    ):
        rows: list[dict[str, Any]] = []
        for result in results:
            selected = {
                "category": result.categories,
                "whole_building": (result.whole_building,),
                "zone": result.zones,
            }[grouping]
            for item in selected:
                row = asdict(item)
                row["available_variables"] = "|".join(item.available_variables)
                row["unavailable_variables"] = "|".join(item.unavailable_variables)
                rows.append(row)
        if not rows:
            continue
        with (compact_root / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def _run_annual_with_gate(
    jobs_by_name: dict[str, RunJob],
    **run_kwargs: Any,
) -> tuple[list[RunJob], dict[tuple[str, str], Path], dict[str, Any]]:
    baseline_job = jobs_by_name["baseline_r"]
    baseline_output = _run_jobs([baseline_job], **run_kwargs)
    output_path = baseline_output[("annual", "baseline_r")]
    manifest = _load_json(output_path / "run_manifest.json")
    footprint = sum(path.stat().st_size for path in output_path.rglob("*") if path.is_file())
    projected_suite = footprint * len(ANNUAL_SCENARIOS)
    free_bytes = shutil.disk_usage(run_kwargs["derived_root"]).free
    gate = {
        "schema_version": "idfrepair.room-aware-annual-gate.v1",
        "baseline_r_elapsed_seconds": float(manifest["elapsed_seconds"]),
        "baseline_r_output_bytes": footprint,
        "projected_suite_bytes": projected_suite,
        "available_disk_bytes": free_bytes,
        "runtime_limit_seconds_per_run": 1800,
        "footprint_limit_bytes_per_run": 2 * 1024**3,
        "disk_safety_factor": 2.5,
    }
    gate["passed"] = bool(
        manifest.get("status") == "PASS"
        and float(manifest["elapsed_seconds"]) <= 1800
        and footprint <= 2 * 1024**3
        and free_bytes >= 2.5 * projected_suite
    )
    gate_path = run_kwargs["derived_root"] / "annual_runtime_gate_v2.json"
    gate_path.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not gate["passed"]:
        return [baseline_job], baseline_output, gate
    remaining = [jobs_by_name[name] for name in ANNUAL_SCENARIOS if name != "baseline_r"]
    outputs = {**baseline_output, **_run_jobs(remaining, **run_kwargs)}
    return [jobs_by_name[name] for name in ANNUAL_SCENARIOS], outputs, gate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("prepare", "seasonal", "annual", "all"), default="all")
    parser.add_argument("--source-osm", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--people-manifest", type=Path, required=True)
    parser.add_argument("--baseline-s-idf", type=Path, required=True)
    parser.add_argument("--baseline-r-idf", type=Path, required=True)
    parser.add_argument("--baseline-s-provenance", type=Path, required=True)
    parser.add_argument("--baseline-r-provenance", type=Path, required=True)
    parser.add_argument("--rdd", type=Path, required=True)
    parser.add_argument("--derived-root", type=Path, required=True)
    parser.add_argument("--energyplus", type=Path, required=True)
    parser.add_argument("--idd", type=Path, required=True)
    parser.add_argument("--weather", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source_osm = args.source_osm.resolve()
    if _sha256(source_osm) != SOURCE_SHA256:
        raise ValueError("runner_source_osm_hash_mismatch")
    derived_root = args.derived_root.resolve()
    derived_root.mkdir(parents=True, exist_ok=True)
    audit = _load_json(args.audit)
    manifest = _load_json(args.people_manifest)
    if audit.get("source_sha256_after") != SOURCE_SHA256 or manifest.get("source_sha256") != SOURCE_SHA256:
        raise ValueError("runner_source_provenance_hash_mismatch")
    provenance_chain = validate_baseline_provenance_chain(
        source_osm_path=source_osm,
        expected_source_sha256=SOURCE_SHA256,
        baseline_s_idf_path=args.baseline_s_idf,
        baseline_s_provenance_path=args.baseline_s_provenance,
        baseline_r_idf_path=args.baseline_r_idf,
        baseline_r_provenance_path=args.baseline_r_provenance,
        people_manifest_path=args.people_manifest,
    )
    (derived_root / "provenance_chain.json").write_text(
        json.dumps(provenance_chain, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    idd = parse_idd(args.idd.read_text(encoding="utf-8", errors="replace"))
    flow_topology = build_source_flow_topology(audit, args.baseline_r_idf, idd)
    if flow_topology["space_count"] != 304 or flow_topology["zone_count"] != 304:
        raise ValueError("runner_flow_space_count_mismatch")
    write_flow_artifacts(
        flow_topology,
        private_json_path=derived_root / "flow_topology.json",
        public_mapping_path=derived_root / "flow_mapping_public.csv",
    )
    definitions = build_scenario_definitions(audit, manifest, flow_topology)
    reference_design_people = {
        row["source_space_name"]: float(row["target_design_people"])
        for row in manifest["spaces"]
    }
    artifacts = compile_scenarios(
        baseline_r_idf=args.baseline_r_idf,
        idd=idd,
        definitions=definitions,
        derived_root=derived_root,
    )
    if args.mode == "prepare":
        print(json.dumps({"status": "prepared", "scenario_count": len(artifacts)}))
        return 0
    run_kwargs = {
        "max_workers": args.max_workers,
        "executable": args.energyplus,
        "idd_path": args.idd,
        "weather_path": args.weather,
        "source_osm": source_osm,
        "derived_root": derived_root,
        "timeout_seconds": args.timeout_seconds,
    }
    if args.mode in {"seasonal", "all"}:
        requests = _select_requests(args.rdd, SEASONAL_OUTPUT_VARIABLES, frequency="Timestep")
        jobs = _prepare_seasonal_jobs(
            artifacts=artifacts,
            baseline_s_idf=args.baseline_s_idf,
            idd=idd,
            requests=requests,
            derived_root=derived_root,
        )
        outputs = _run_jobs(jobs, **run_kwargs)
        results = _extract_all(
            jobs,
            outputs,
            audit=audit,
            reference_design_people=reference_design_people,
            derived_root=derived_root,
            suite_id="seasonal",
        )
        _write_result_tables(results, derived_root=derived_root, suite_id="seasonal")
    if args.mode in {"annual", "all"}:
        requests = _select_requests(args.rdd, ANNUAL_OUTPUT_VARIABLES, frequency="Hourly")
        annual_jobs = _prepare_annual_jobs(
            artifacts=artifacts,
            baseline_s_idf=args.baseline_s_idf,
            idd=idd,
            requests=requests,
            derived_root=derived_root,
        )
        jobs, outputs, gate = _run_annual_with_gate(annual_jobs, **run_kwargs)
        results = _extract_all(
            jobs,
            outputs,
            audit=audit,
            reference_design_people=reference_design_people,
            derived_root=derived_root,
            suite_id="annual",
        )
        _write_result_tables(results, derived_root=derived_root, suite_id="annual")
        print(json.dumps({"annual_runtime_gate": gate}, sort_keys=True))
    print(json.dumps({"status": "complete", "source_sha256": _sha256(source_osm)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
