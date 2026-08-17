#!/usr/bin/env python3
"""Run read-only terminal-model inventory and controlled occupancy workflows.

Raw OSM paths, model names, translations, and simulation outputs stay in the
explicit local workspace. Release-facing reports use neutral model aliases.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPARE_SCRIPT = PROJECT_ROOT / "scripts" / "occupancy" / "prepare_terminal_model.rb"
DEFAULT_OPENSTUDIO = Path("/Applications/OpenStudio/bin/openstudio")
_SCENARIO_OUTPUT_VARIABLES = (
    "People Sensible Heating Energy",
    "People Radiant Heating Energy",
    "People Latent Gain Energy",
    "Zone People Occupant Count",
    "Zone Mean Air Temperature",
    "Zone Air Relative Humidity",
    "Zone Ideal Loads Supply Air Total Heating Energy",
    "Zone Ideal Loads Supply Air Total Cooling Energy",
    "Zone Ideal Loads Supply Air Total Heating Rate",
    "Zone Ideal Loads Supply Air Total Cooling Rate",
    "Zone Ideal Loads Outdoor Air Total Heating Energy",
    "Zone Ideal Loads Outdoor Air Total Cooling Energy",
    "Zone Ideal Loads Outdoor Air Mass Flow Rate",
    "Facility Total HVAC Electricity Demand Rate",
    "Zone Heating Setpoint Not Met Time",
    "Zone Cooling Setpoint Not Met Time",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _alias(index: int) -> str:
    if 0 <= index < 26:
        return f"Terminal Model {chr(ord('A') + index)}"
    return f"Terminal Model {index + 1}"


def _collect_models(model_root: Path | None, models: list[Path]) -> tuple[Path, ...]:
    candidates = [Path(value) for value in models]
    if model_root is not None:
        root = Path(model_root)
        if not root.is_dir():
            raise ValueError("model_root_not_found")
        candidates.extend(sorted(root.glob("*.osm"), key=lambda path: path.name.casefold()))
    unique: dict[Path, Path] = {}
    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.is_file():
            raise ValueError("model_not_found")
        unique.setdefault(resolved, resolved)
    if not unique:
        raise ValueError("no_osm_models_selected")
    return tuple(unique.values())


def _run_prepare(
    *,
    openstudio: Path,
    source: Path,
    output_directory: Path,
    timeout_seconds: int,
    mode: str = "translate",
) -> dict[str, Any]:
    before = _sha256(source)
    result = subprocess.run(
        [
            str(openstudio),
            str(PREPARE_SCRIPT),
            "--input",
            str(source),
            "--output-dir",
            str(output_directory),
            "--mode",
            mode,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(f"openstudio_prepare_failed:{result.returncode}")
    provenance_path = output_directory / "provenance.json"
    if not provenance_path.is_file():
        raise RuntimeError("openstudio_provenance_missing")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    after = _sha256(source)
    if before != after or provenance.get("source_sha256_before") != after:
        raise RuntimeError("source_hash_changed_during_inventory")
    return provenance


def _simulation_dict(run: Any) -> dict[str, Any]:
    return {
        "runtime_version": run.runtime_version,
        "runtime_sha256": run.runtime_sha256,
        "idf_sha256": run.idf_sha256,
        "idd_sha256": run.idd_sha256,
        "weather_sha256": run.weather_sha256,
        "return_code": run.return_code,
        "timed_out": run.timed_out,
        "elapsed_seconds": round(run.elapsed_seconds, 6),
        "severe_count": run.severe_count,
        "fatal_count": run.fatal_count,
        "csv_available": run.csv_available,
        "rdd_available": run.rdd_available,
    }


def _run_passed(run: Any) -> bool:
    return bool(
        run.return_code == 0
        and not run.timed_out
        and run.severe_count == 0
        and run.fatal_count == 0
        and run.csv_available
    )


def _frozen_method_check() -> tuple[bool, str]:
    """只读核对 frozen semantic_graph_v2 文件 hashes，不运行 Final。"""

    verification_path = (
        PROJECT_ROOT / "reports" / "semantic_graph_final" / "method_freeze_verification.json"
    )
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    expected = verification.get("source_file_hashes", {})
    protected = {
        name: digest
        for name, digest in expected.items()
        if str(name).startswith("src/idfrepair/semantic_graph_v2/")
    }
    unchanged = bool(protected) and all(
        (PROJECT_ROOT / name).is_file()
        and _sha256(PROJECT_ROOT / name) == str(digest)
        for name, digest in protected.items()
    )
    return unchanged, str(verification.get("method_identity", "unavailable"))


def _metric_series(
    rows: tuple[Any, ...], variable_name: str, *, scale: float = 1.0
) -> list[float]:
    """按 CSV 时序聚合同一变量的所有 Zone/key。"""

    totals: dict[str, list[float]] = {}
    target = " ".join(variable_name.casefold().split())
    for row in rows:
        if (
            " ".join(row.variable_name.casefold().split()) != target
            or row.availability != "available"
            or row.value is None
            or row.timestamp is None
        ):
            continue
        totals.setdefault(row.timestamp, []).append(float(row.value))
    return [math.fsum(values) / scale for values in totals.values()]


def _coupling_markdown(
    *,
    base_idf: Path,
    ideal_idf: Path,
    idd_path: Path,
    rdd_path: Path,
    ideal_provenance: dict[str, Any],
    baseline: dict[str, Any],
) -> str:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from idfrepair.analysis.occupancy.energyplus import (  # noqa: PLC0415
        discover_output_variables,
        select_output_requests,
    )
    from idfrepair.analysis.occupancy.mapping import (  # noqa: PLC0415
        build_semantic_mapping,
    )
    from idfrepair.io.idf import parse_idf  # noqa: PLC0415
    from idfrepair.knowledge.idd import parse_idd  # noqa: PLC0415

    idd = parse_idd(idd_path.read_text(encoding="utf-8", errors="replace"))
    base_document = parse_idf(base_idf.read_text(encoding="utf-8"))
    ideal_document = parse_idf(ideal_idf.read_text(encoding="utf-8"))
    base_mapping = build_semantic_mapping(base_document, idd)
    ideal_mapping = build_semantic_mapping(ideal_document, idd)
    group_sizes = [len(zones) for zones in base_mapping.people_to_zones.values()]
    selected = select_output_requests(
        discover_output_variables(rdd_path.read_text(encoding="utf-8", errors="replace"))
    )
    variables = {request.variable_name for request in selected}
    mechanisms = {request.mechanism for request in selected}
    original_served = sum(bool(value) for value in base_mapping.zone_to_hvac.values())
    synthetic_served = sum(bool(value) for value in ideal_mapping.zone_to_hvac.values())
    baseline_pass = (
        baseline.get("return_code") == 0
        and baseline.get("severe_count") == 0
        and baseline.get("fatal_count") == 0
        and baseline.get("csv_available") is True
    )
    rows = [
        ("People occupant count", "available" if "People Occupant Count" in variables else "unavailable"),
        ("Zone People occupant count", "available" if "Zone People Occupant Count" in variables else "unavailable"),
        ("People sensible/latent/radiant gains", "available" if "people_heat_gain" in mechanisms else "unavailable"),
        ("Zone temperature/humidity", "available" if "zone_state" in mechanisms else "unavailable"),
        ("Synthetic Ideal Loads thermal response", "available" if "ideal_loads" in mechanisms else "unavailable"),
        ("Synthetic Ideal Loads outdoor-air response", "available" if "outdoor_air" in mechanisms else "unavailable"),
        ("Original fan electricity", "available" if "Fan Electricity Energy" in variables else "unavailable"),
        ("Original pump electricity", "available" if "Pump Electricity Energy" in variables else "unavailable"),
        ("Original AirLoop/DCV response", "unavailable"),
    ]
    lines = [
        "# People–Zone–HVAC Coupling Audit",
        "",
        "This audit reuses the frozen semantic relation representation through an "
        "adapter; it does not modify the Formal V2 method or rerun Final100.",
        "",
        "## Source-backed mapping",
        "",
        f"- The user-authored OSM contains {ideal_provenance['before_counts']['people']} "
        f"People instances and {ideal_provenance['before_counts']['people_definitions']} "
        "People definitions.",
        f"- OpenStudio aggregates them into {len(base_mapping.people_to_zones)} translated "
        f"People/SpaceList groups. Neutral group sizes are {group_sizes}; together they "
        f"cover {len(base_mapping.zone_to_hvac)} translated Zones.",
        f"- Original source-backed Zone→HVAC relations: {original_served}/"
        f"{len(base_mapping.zone_to_hvac)} served Zones.",
        f"- Synthetic derivative Zone→Ideal Loads relations: {synthetic_served}/"
        f"{len(ideal_mapping.zone_to_hvac)} served Zones.",
        f"- DesignSpecification:OutdoorAir objects: "
        f"{len(base_document.find_objects('DesignSpecification:OutdoorAir'))}; "
        f"Controller:MechanicalVentilation objects: "
        f"{len(base_document.find_objects('Controller:MechanicalVentilation'))}; "
        f"AirLoopHVAC objects: {len(base_document.find_objects('AirLoopHVAC'))}.",
        f"- The derivative adds {ideal_provenance['synthetic_ideal_loads_added']} Ideal Loads "
        f"systems and skips {ideal_provenance['synthetic_zones_skipped_no_spaces']} "
        "orphan Zone with no Space. These systems are synthetic demo equipment.",
        "",
        "No zone-function labels (check-in, security, gate, arrivals, and so on) are "
        "inferred from opaque object names.",
        "",
        "## Exact EnergyPlus 23.1 RDD availability",
        "",
        "| Mechanism/output family | Availability |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | `{availability}` |" for name, availability in rows)
    lines.extend(
        [
            "",
            "Unavailable means the mechanism is not established by this model/runtime; "
            "it is not a numeric zero. Facility electricity reported by an Ideal Loads "
            "demo is not original terminal HVAC electricity.",
            "",
            "## Baseline smoke",
            "",
            f"- Status: `{'PASS' if baseline_pass else 'FAIL'}`.",
            f"- EnergyPlus: `{baseline['runtime_version']}`.",
            f"- Runtime SHA-256: `{baseline['runtime_sha256']}`.",
            f"- IDD SHA-256: `{baseline['idd_sha256']}`.",
            f"- Weather SHA-256: `{baseline['weather_sha256']}`.",
            f"- Derived baseline IDF SHA-256: `{baseline['idf_sha256']}`.",
            f"- Return/severe/fatal: {baseline['return_code']}/"
            f"{baseline['severe_count']}/{baseline['fatal_count']}; CSV available: "
            f"{str(baseline['csv_available']).lower()}.",
            "",
            "The successful smoke qualifies only the synthetic thermal-load execution "
            "path. It does not qualify a real airport HVAC energy case.",
            "",
        ]
    )
    return "\n".join(lines)


def baseline_command(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from idfrepair.analysis.occupancy.energyplus import (  # noqa: PLC0415
        discover_output_variables,
        prepare_one_day_idf,
        run_energyplus,
        select_output_requests,
    )
    from idfrepair.knowledge.idd import parse_idd  # noqa: PLC0415

    workspace = Path(args.workspace).resolve()
    model_dir = workspace / "model_01"
    translate_dir = model_dir / "translate"
    ideal_dir = model_dir / "ideal_derived"
    source_model = Path(args.source_model).resolve() if args.source_model else None
    openstudio = Path(args.openstudio).resolve()
    if source_model is not None:
        _run_prepare(
            openstudio=openstudio,
            source=source_model,
            output_directory=translate_dir,
            timeout_seconds=args.timeout_seconds,
            mode="translate",
        )
        ideal_provenance = _run_prepare(
            openstudio=openstudio,
            source=source_model,
            output_directory=ideal_dir,
            timeout_seconds=args.timeout_seconds,
            mode="ideal-loads-demo",
        )
    else:
        provenance_path = ideal_dir / "provenance.json"
        if not provenance_path.is_file():
            raise ValueError("source_model_required_without_prepared_ideal_derivative")
        ideal_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    base_idf = translate_dir / "derived.idf"
    ideal_idf = ideal_dir / "derived.idf"
    weather = Path(args.weather).resolve()
    energyplus = Path(args.energyplus).resolve()
    idd_path = Path(args.idd).resolve()
    for path, label in (
        (base_idf, "translated_base_idf"),
        (ideal_idf, "ideal_derivative_idf"),
        (weather, "weather"),
        (energyplus, "energyplus"),
        (idd_path, "idd"),
    ):
        if not path.is_file():
            raise ValueError(f"{label}_not_found")
    config_payload = "|".join(
        (
            "baseline_schema_v2_schedule_value",
            _sha256(ideal_idf),
            _sha256(weather),
            _sha256(energyplus),
            _sha256(idd_path),
            str(args.month),
            str(args.day),
            str(args.day_of_week),
            str(args.resolution_minutes),
        )
    ).encode("ascii")
    case_digest = hashlib.sha256(config_payload).hexdigest()[:16]
    case_dir = model_dir / "baseline_runs" / case_digest
    if case_dir.exists() and any(case_dir.iterdir()):
        raise ValueError(f"baseline_case_already_exists:{case_digest}")
    idd = parse_idd(idd_path.read_text(encoding="utf-8", errors="replace"))
    discovery_idf = case_dir / "discovery.idf"
    prepare_one_day_idf(
        ideal_idf,
        idd,
        discovery_idf,
        month=args.month,
        day=args.day,
        day_of_week=args.day_of_week,
        resolution_minutes=args.resolution_minutes,
    )
    discovery_run = run_energyplus(
        executable=energyplus,
        idf_path=discovery_idf,
        output_directory=case_dir / "discovery_run",
        idd_path=idd_path,
        weather_path=weather,
        timeout_seconds=args.timeout_seconds,
    )
    discovery_rdd = discovery_run.output_directory / "eplusout.rdd"
    if (
        discovery_run.return_code != 0
        or discovery_run.severe_count
        or discovery_run.fatal_count
        or not discovery_rdd.is_file()
    ):
        raise RuntimeError("baseline_discovery_failed")
    requests = select_output_requests(
        discover_output_variables(discovery_rdd.read_text(encoding="utf-8", errors="replace"))
    )
    if not requests:
        raise RuntimeError("baseline_rdd_has_no_supported_outputs")
    baseline_idf = case_dir / "baseline.idf"
    prepare_one_day_idf(
        ideal_idf,
        idd,
        baseline_idf,
        output_requests=requests,
        month=args.month,
        day=args.day,
        day_of_week=args.day_of_week,
        resolution_minutes=args.resolution_minutes,
    )
    final_run = run_energyplus(
        executable=energyplus,
        idf_path=baseline_idf,
        output_directory=case_dir / "baseline_run",
        idd_path=idd_path,
        weather_path=weather,
        timeout_seconds=args.timeout_seconds,
    )
    baseline = _simulation_dict(final_run)
    result = {
        "schema_version": 1,
        "case_digest": case_digest,
        "synthetic_hvac_demo": True,
        "selected_variables": [request.variable_name for request in requests],
        "discovery": _simulation_dict(discovery_run),
        "baseline": baseline,
    }
    result_path = case_dir / "baseline_result.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _coupling_markdown(
            base_idf=base_idf,
            ideal_idf=ideal_idf,
            idd_path=idd_path,
            rdd_path=final_run.output_directory / "eplusout.rdd",
            ideal_provenance=ideal_provenance,
            baseline=baseline,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "baseline_complete",
                "case_digest": case_digest,
                "return_code": final_run.return_code,
                "severe_count": final_run.severe_count,
                "fatal_count": final_run.fatal_count,
                "report": str(report_path),
                "result": str(result_path),
            },
            sort_keys=True,
        )
    )
    return 0 if final_run.return_code == 0 and final_run.fatal_count == 0 else 2


def scenarios_command(args: argparse.Namespace) -> int:
    """编译并运行完整 4+2+8+5 controlled scenario matrix。"""

    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from idfrepair.analysis.occupancy.compiler import compile_scenario  # noqa: PLC0415
    from idfrepair.analysis.occupancy.energyplus import (  # noqa: PLC0415
        discover_output_variables,
        extract_metrics,
        prepare_one_day_idf,
        run_energyplus,
        select_output_requests,
    )
    from idfrepair.analysis.occupancy.mapping import (  # noqa: PLC0415
        build_semantic_mapping,
    )
    from idfrepair.analysis.occupancy.reporting import (  # noqa: PLC0415
        OccupancyAdmissionEvidence,
        decide_occupancy_status,
        render_case_status,
        render_enb_readiness,
        render_scenario_results,
        scenario_records,
        summarize_metric_rows,
        write_scenario_csv,
    )
    from idfrepair.analysis.occupancy.visualization import (  # noqa: PLC0415
        write_occupancy_figures,
    )
    from idfrepair.analysis.occupancy.workflow import (  # noqa: PLC0415
        build_controlled_scenarios,
        extract_baseline_profiles,
    )
    from idfrepair.io.idf import canonical, parse_idf  # noqa: PLC0415
    from idfrepair.knowledge.idd import parse_idd  # noqa: PLC0415

    workspace = Path(args.workspace).resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("scenario_workspace_must_be_empty")
    workspace.mkdir(parents=True, exist_ok=True)
    source_idf = Path(args.source_idf).resolve()
    baseline_case = Path(args.baseline_case).resolve()
    energyplus = Path(args.energyplus).resolve()
    idd_path = Path(args.idd).resolve()
    weather = Path(args.weather).resolve()
    provenance_path = source_idf.parent / "provenance.json"
    baseline_result_path = baseline_case / "baseline_result.json"
    baseline_run_dir = baseline_case / "baseline_run"
    paths = (
        (source_idf, "scenario_source_idf"),
        (baseline_result_path, "scenario_baseline_result"),
        (baseline_run_dir / "eplusout.eio", "scenario_baseline_eio"),
        (baseline_run_dir / "eplusout.csv", "scenario_baseline_csv"),
        (baseline_run_dir / "eplusout.rdd", "scenario_baseline_rdd"),
        (provenance_path, "scenario_source_provenance"),
        (energyplus, "scenario_energyplus"),
        (idd_path, "scenario_idd"),
        (weather, "scenario_weather"),
    )
    for path, label in paths:
        if not path.is_file():
            raise ValueError(f"{label}_not_found")
    if args.jobs <= 0:
        raise ValueError("scenario_jobs_must_be_positive")

    idd = parse_idd(idd_path.read_text(encoding="utf-8", errors="replace"))
    source_before = _sha256(source_idf)
    baseline_result = json.loads(baseline_result_path.read_text(encoding="utf-8"))
    baseline_run_record = baseline_result["baseline"]
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    baseline = extract_baseline_profiles(
        source_idf,
        idd,
        baseline_run_dir / "eplusout.eio",
        baseline_run_dir / "eplusout.csv",
        expected_steps=96,
        minutes_per_step=float(args.resolution_minutes),
    )
    scenarios = build_controlled_scenarios(baseline)
    document = parse_idf(source_idf.read_text(encoding="utf-8"))
    mapping = build_semantic_mapping(document, idd)

    available = discover_output_variables(
        (baseline_run_dir / "eplusout.rdd").read_text(
            encoding="utf-8", errors="replace"
        )
    )
    selected = select_output_requests(available)
    requested_keys = {canonical(name) for name in _SCENARIO_OUTPUT_VARIABLES}
    requests = tuple(
        request
        for request in selected
        if canonical(request.variable_name) in requested_keys
    )
    if not requests:
        raise RuntimeError("scenario_rdd_has_no_supported_outputs")
    expected_names = tuple(_SCENARIO_OUTPUT_VARIABLES)
    baseline_rows = extract_metrics(
        baseline_run_dir / "eplusout.csv",
        mapping,
        expected_variable_names=expected_names,
    )
    baseline_passed = bool(
        baseline_run_record.get("return_code") == 0
        and not baseline_run_record.get("timed_out")
        and baseline_run_record.get("severe_count") == 0
        and baseline_run_record.get("fatal_count") == 0
        and baseline_run_record.get("csv_available") is True
    )
    baseline_summary = summarize_metric_rows(
        scenario_name="existing_baseline",
        kind="existing_baseline",
        rows=baseline_rows,
        compiled_passenger_hours=baseline.passenger_hours,
        reference_passenger_hours=baseline.passenger_hours,
        minutes_per_step=baseline.minutes_per_step,
        run_status="PASS" if baseline_passed else "FAIL",
    )
    time_series: dict[str, dict[str, list[float]]] = {
        "existing_baseline": {
            "occupancy": _metric_series(
                baseline_rows, "Zone People Occupant Count"
            ),
            "synthetic_heating_kw": _metric_series(
                baseline_rows,
                "Zone Ideal Loads Supply Air Total Heating Rate",
                scale=1000.0,
            ),
            "synthetic_cooling_kw": _metric_series(
                baseline_rows,
                "Zone Ideal Loads Supply Air Total Cooling Rate",
                scale=1000.0,
            ),
        }
    }
    profiles = {"existing_baseline": dict(baseline.profiles)}
    prepared: list[tuple[Any, Any, Path]] = []
    for scenario in scenarios:
        case_dir = workspace / "cases" / scenario.name
        compiled = compile_scenario(
            source_idf,
            idd,
            scenario,
            case_dir / "compiled",
        )
        one_day_idf = compiled.idf_path.parent / "one_day.idf"
        prepare_one_day_idf(
            compiled.idf_path,
            idd,
            one_day_idf,
            output_requests=requests,
            month=args.month,
            day=args.day,
            day_of_week=args.day_of_week,
            resolution_minutes=args.resolution_minutes,
        )
        prepared.append((scenario, compiled, one_day_idf))
        profiles[scenario.name] = dict(scenario.profiles)
    if _sha256(source_idf) != source_before:
        raise RuntimeError("scenario_source_idf_changed")

    def execute(item: tuple[Any, Any, Path]) -> tuple[str, Any]:
        scenario, _compiled, one_day_idf = item
        run = run_energyplus(
            executable=energyplus,
            idf_path=one_day_idf,
            output_directory=one_day_idf.parent.parent / "run",
            idd_path=idd_path,
            weather_path=weather,
            timeout_seconds=args.timeout_seconds,
        )
        return scenario.name, run

    runs: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(execute, item): item[0].name for item in prepared}
        for future in as_completed(futures):
            scenario_name, run = future.result()
            runs[scenario_name] = run
            print(
                json.dumps(
                    {
                        "scenario": scenario_name,
                        "status": "PASS" if _run_passed(run) else "FAIL",
                        "return_code": run.return_code,
                        "severe": run.severe_count,
                        "fatal": run.fatal_count,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    summaries = [baseline_summary]
    run_records: dict[str, dict[str, Any]] = {
        "existing_baseline": dict(baseline_run_record)
    }
    for scenario, compiled, _one_day_idf in prepared:
        run = runs[scenario.name]
        rows = (
            extract_metrics(
                run.output_directory / "eplusout.csv",
                mapping,
                expected_variable_names=expected_names,
            )
            if run.csv_available
            else ()
        )
        summary = summarize_metric_rows(
            scenario_name=scenario.name,
            kind=scenario.kind,
            rows=rows,
            compiled_passenger_hours=compiled.passenger_hours,
            reference_passenger_hours=(
                scenario.reference_person_hours
                if scenario.conserves_passenger_hours
                else None
            ),
            minutes_per_step=scenario.minutes_per_step,
            run_status="PASS" if _run_passed(run) else "FAIL",
        )
        summaries.append(summary)
        time_series[scenario.name] = {
            "occupancy": _metric_series(rows, "Zone People Occupant Count"),
            "synthetic_heating_kw": _metric_series(
                rows,
                "Zone Ideal Loads Supply Air Total Heating Rate",
                scale=1000.0,
            ),
            "synthetic_cooling_kw": _metric_series(
                rows,
                "Zone Ideal Loads Supply Air Total Cooling Rate",
                scale=1000.0,
            ),
        }
        run_records[scenario.name] = {
            **_simulation_dict(run),
            "scenario_digest": compiled.scenario_digest,
            "compiled_idf_sha256": compiled.idf_sha256,
            "schedule_sha256": compiled.schedule_sha256,
            "compiled_passenger_hours": compiled.passenger_hours,
            "modified_people_schedule_fields": len(compiled.modified_fields),
        }

    summary_tuple = tuple(summaries)
    records = scenario_records(summary_tuple)
    same_person_hours_rows = [
        row
        for row in records
        if row["kind"] in {
            "temporal_redistribution",
            "spatial_redistribution",
            "spatiotemporal_redistribution",
        }
    ]
    tolerance = max(1e-6, baseline.passenger_hours * 1e-9)
    same_ph_reproducible = bool(same_person_hours_rows) and all(
        row["run_status"] == "PASS"
        and row["conservation_error"] is not None
        and abs(float(row["conservation_error"])) <= tolerance
        for row in same_person_hours_rows
    )
    distribution_deltas = [
        abs(float(row["synthetic_total_thermal_delta_pct"]))
        for row in same_person_hours_rows
        if row["synthetic_total_thermal_delta_pct"] is not None
    ]
    interpretable_distribution_response = bool(distribution_deltas) and max(
        distribution_deltas
    ) >= 0.1
    frozen_unchanged, method_identity = _frozen_method_check()
    all_runs_pass = all(summary.run_status == "PASS" for summary in summary_tuple)
    counts = provenance.get("before_counts", {})
    real_hvac = any(
        int(counts.get(key, 0)) > 0
        for key in ("air_loops", "plant_loops", "real_zone_equipment")
    )
    evidence = OccupancyAdmissionEvidence(
        provenance_clear=bool(provenance.get("source_unchanged")),
        annual_baseline_stable=False,
        spatial_people_difference=(
            len(baseline.profiles) > 1
            and len({value for value in baseline.group_zone_counts.values()}) > 1
        ),
        original_real_hvac=real_hvac,
        same_person_hours_reproducible=same_ph_reproducible,
        interpretable_distribution_response=interpretable_distribution_response,
        frozen_method_unchanged=frozen_unchanged,
        controlled_demo_stable=all_runs_pass,
        only_commonplace_volume_result=not interpretable_distribution_response,
    )
    occupancy_status = decide_occupancy_status(evidence)

    report_directory = Path(args.report_directory)
    figure_directory = report_directory / "figures"
    group_aliases = {
        name: f"neutral_group_{index:02d}"
        for index, name in enumerate(baseline.profiles, start=1)
    }
    figure_paths = write_occupancy_figures(
        summaries=summary_tuple,
        time_series=time_series,
        profiles=profiles,
        design_people=baseline.design_people,
        group_aliases=group_aliases,
        output_directory=figure_directory,
    )
    report_directory.mkdir(parents=True, exist_ok=True)
    write_scenario_csv(summary_tuple, report_directory / "scenario_results.csv")
    metadata = {
        "people_source_count": counts.get("people", 0),
        "people_group_count": len(baseline.profiles),
        "served_zone_count": len(mapping.zone_to_hvac),
        "baseline_day_label": (
            f"controlled {args.day_of_week}, month {args.month}, day {args.day}"
        ),
        "runtime_version": baseline_run_record.get("runtime_version", "unavailable"),
        "runtime_sha256": baseline_run_record.get("runtime_sha256", "unavailable"),
        "idd_sha256": baseline_run_record.get("idd_sha256", "unavailable"),
        "weather_sha256": baseline_run_record.get("weather_sha256", "unavailable"),
    }
    (report_directory / "scenario_results.md").write_text(
        render_scenario_results(
            summaries=summary_tuple,
            occupancy_status=occupancy_status,
            metadata=metadata,
        ),
        encoding="utf-8",
    )
    (report_directory / "occupancy_case_status.md").write_text(
        render_case_status(evidence, method_identity=method_identity),
        encoding="utf-8",
    )
    publication_report = Path(args.publication_report)
    publication_report.parent.mkdir(parents=True, exist_ok=True)
    publication_report.write_text(
        render_enb_readiness(occupancy_status), encoding="utf-8"
    )
    compact_profiles = {
        scenario_name: {
            group_aliases[group_name]: list(values)
            for group_name, values in scenario_profiles.items()
        }
        for scenario_name, scenario_profiles in profiles.items()
    }
    local_result = {
        "schema_version": 1,
        "occupancy_status": occupancy_status,
        "method_identity": method_identity,
        "frozen_method_unchanged": frozen_unchanged,
        "source_idf_sha256": source_before,
        "source_osm_sha256": provenance.get("source_sha256_before"),
        "group_aliases": list(group_aliases.values()),
        "group_design_people": {
            group_aliases[name]: value for name, value in baseline.design_people.items()
        },
        "group_zone_counts": {
            group_aliases[name]: value
            for name, value in baseline.group_zone_counts.items()
        },
        "summaries": [asdict(summary) for summary in summary_tuple],
        "time_series": time_series,
        "profiles": compact_profiles,
        "runs": run_records,
        "evidence": asdict(evidence),
        "figure_sha256": {
            path.name: _sha256(path) for path in figure_paths
        },
    }
    result_path = workspace / "scenario_suite_result.json"
    result_path.write_text(
        json.dumps(local_result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": occupancy_status,
                "scenario_count": len(scenarios),
                "all_runs_pass": all_runs_pass,
                "same_person_hours_reproducible": same_ph_reproducible,
                "report": str(report_directory / "scenario_results.md"),
                "result": str(result_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if occupancy_status != "OCCUPANCY_NO_GO" else 2


def _has_real_hvac(counts: dict[str, Any]) -> bool:
    return any(
        int(counts.get(key, 0)) > 0
        for key in ("air_loops", "plant_loops", "real_zone_equipment")
    )


def _inventory_markdown(records: list[dict[str, Any]]) -> str:
    lines = [
        "# Terminal Model Inventory",
        "",
        "The inputs are two user-authored models from one terminal modelling project; "
        "they are not an open dataset. Raw OSM names, paths, geometry, and translated "
        "IDF files are intentionally withheld from public distribution.",
        "",
        "Every source was opened read-only. SHA-256 was checked before and after "
        "translation; generated IDFs remain in an ignored local workspace.",
        "",
        "| Alias | Source SHA-256 | Runtime | Spaces | Zones | People | People definitions | Schedules | Air loops | "
        "Plant loops | Real zone HVAC | Weather | Translation errors | Source unchanged |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|",
    ]
    for record in records:
        counts = record["counts"]
        lines.append(
            "| {alias} | `{sha}` | OpenStudio {version} / OSM {osm_version} | {spaces} | {zones} | "
            "{people} | {people_definitions} | {schedules} | {air} | {plant} | {zone_hvac} | {weather} | {errors} | {unchanged} |".format(
                alias=record["alias"],
                sha=record["source_sha256"],
                version=record["openstudio_version"],
                osm_version=record["osm_schema_version"],
                spaces=counts.get("spaces", 0),
                zones=counts.get("thermal_zones", 0),
                people=counts.get("people", 0),
                people_definitions=counts.get("people_definitions", 0),
                schedules=counts.get("schedules", 0),
                air=counts.get("air_loops", 0),
                plant=counts.get("plant_loops", 0),
                zone_hvac=counts.get("real_zone_equipment", 0),
                weather="assigned" if counts.get("weather_assigned") else "missing",
                errors=record["translation_error_count"],
                unchanged="yes" if record["source_unchanged"] else "no",
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "Object names alone are not used to infer check-in, security, gate, "
            "arrivals, baggage, or other terminal functions. Any later spatial "
            "groups are neutral controlled groups unless backed by an explicit "
            "user-authored mapping. Translation success does not establish HVAC "
            "or operational validity.",
            "",
        ]
    )
    return "\n".join(lines)


def _qualification_markdown(records: list[dict[str, Any]]) -> str:
    primary = max(
        records,
        key=lambda row: (
            int(row["counts"].get("thermal_zones", 0)),
            int(row["counts"].get("people", 0)),
            int(row["counts"].get("spaces", 0)),
        ),
    )
    counts = primary["counts"]
    gates = {
        "Source byte identity": primary["source_unchanged"],
        "Translated without fatal translator errors": primary["translation_error_count"] == 0,
        "Has ThermalZones": int(counts.get("thermal_zones", 0)) > 0,
        "Has People objects": int(counts.get("people", 0)) > 0,
        "Has weather assignment": bool(counts.get("weather_assigned")),
        "Has original real HVAC": _has_real_hvac(counts),
    }
    lines = [
        "# Terminal Baseline Qualification",
        "",
        f"Primary controlled candidate: **{primary['alias']}** (selected by source-backed "
        "zone and People counts, not by filename).",
        "",
        "| Gate | Result |",
        "|---|---|",
    ]
    lines.extend(
        f"| {name} | {'PASS' if passed else 'FAIL'} |" for name, passed in gates.items()
    )
    real_hvac = gates["Has original real HVAC"]
    if not real_hvac:
        lines.extend(
            [
                "",
                "## Qualification: `NO_REAL_HVAC`",
                "",
                "The source model cannot support claims about original terminal HVAC "
                "electricity, fan, pump, coil, outdoor-air, or DCV response. A derived "
                "Ideal Loads system may be used only for thermal-load mechanics and is "
                "classified `DEMO_DERIVATIVE_ELIGIBLE`. It cannot upgrade the evidence "
                "to a real terminal HVAC case.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Qualification: `REAL_HVAC_BASELINE_REQUIRES_SIMULATION`",
                "",
                "HVAC objects are present, but baseline stability and output mechanisms "
                "must still be demonstrated before any case-level decision.",
            ]
        )
    lines.extend(
        [
            "",
            "Occupancy weakness does not block the frozen semantic-repair paper; the "
            "occupancy extension remains an independent downstream evaluation.",
            "",
        ]
    )
    return "\n".join(lines)


def inventory_command(args: argparse.Namespace) -> int:
    openstudio = Path(args.openstudio).resolve()
    if not openstudio.is_file():
        raise ValueError("openstudio_cli_not_found")
    models = _collect_models(
        Path(args.model_root) if args.model_root else None,
        [Path(value) for value in args.model],
    )
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index, source in enumerate(models):
        alias = _alias(index)
        provenance = _run_prepare(
            openstudio=openstudio,
            source=source,
            output_directory=workspace / f"model_{index + 1:02d}" / "translate",
            timeout_seconds=args.timeout_seconds,
        )
        records.append(
            {
                "alias": alias,
                "source_sha256": provenance["source_sha256_before"],
                "source_unchanged": provenance["source_unchanged"],
                "openstudio_version": provenance["openstudio_version"],
                "osm_schema_version": provenance["osm_schema_version"],
                "counts": provenance["before_counts"],
                "translation_error_count": provenance[
                    "forward_translation_error_count"
                ],
                "translation_warning_count": provenance[
                    "forward_translation_warning_count"
                ],
                "derived_idf_sha256": provenance["derived_idf_sha256"],
            }
        )
    inventory_json = workspace / "inventory.json"
    inventory_json.write_text(
        json.dumps({"schema_version": 1, "models": records}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    report = Path(args.report)
    qualification = Path(args.qualification_report)
    report.parent.mkdir(parents=True, exist_ok=True)
    qualification.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(_inventory_markdown(records), encoding="utf-8")
    qualification.write_text(_qualification_markdown(records), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "inventory_complete",
                "model_count": len(records),
                "inventory_json": str(inventory_json),
                "report": str(report),
                "qualification_report": str(qualification),
            },
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory", help="inventory read-only OSM inputs")
    inventory.add_argument("--model-root")
    inventory.add_argument("--model", action="append", default=[])
    inventory.add_argument("--workspace", required=True)
    inventory.add_argument(
        "--report",
        default=str(PROJECT_ROOT / "reports" / "occupancy" / "terminal_model_inventory.md"),
    )
    inventory.add_argument(
        "--qualification-report",
        default=str(PROJECT_ROOT / "reports" / "occupancy" / "baseline_qualification.md"),
    )
    inventory.add_argument("--openstudio", default=str(DEFAULT_OPENSTUDIO))
    inventory.add_argument("--timeout-seconds", type=int, default=600)
    inventory.set_defaults(handler=inventory_command)
    baseline = subparsers.add_parser(
        "baseline", help="run a one-day synthetic Ideal Loads baseline"
    )
    baseline.add_argument("--workspace", required=True)
    baseline.add_argument("--source-model")
    baseline.add_argument("--weather", required=True)
    baseline.add_argument("--openstudio", default=str(DEFAULT_OPENSTUDIO))
    baseline.add_argument(
        "--energyplus", default="/Applications/EnergyPlus-23-1-0/energyplus"
    )
    baseline.add_argument(
        "--idd", default="/Applications/EnergyPlus-23-1-0/Energy+.idd"
    )
    baseline.add_argument("--month", type=int, default=1)
    baseline.add_argument("--day", type=int, default=15)
    baseline.add_argument("--day-of-week")
    baseline.add_argument("--resolution-minutes", type=int, default=15)
    baseline.add_argument("--timeout-seconds", type=int, default=1200)
    baseline.add_argument(
        "--report",
        default=str(
            PROJECT_ROOT / "reports" / "occupancy" / "people_hvac_coupling_audit.md"
        ),
    )
    baseline.set_defaults(handler=baseline_command)
    scenarios = subparsers.add_parser(
        "scenarios", help="run the complete controlled occupancy scenario matrix"
    )
    scenarios.add_argument("--workspace", required=True)
    scenarios.add_argument("--source-idf", required=True)
    scenarios.add_argument("--baseline-case", required=True)
    scenarios.add_argument("--weather", required=True)
    scenarios.add_argument(
        "--energyplus", default="/Applications/EnergyPlus-23-1-0/energyplus"
    )
    scenarios.add_argument(
        "--idd", default="/Applications/EnergyPlus-23-1-0/Energy+.idd"
    )
    scenarios.add_argument("--month", type=int, default=1)
    scenarios.add_argument("--day", type=int, default=18)
    scenarios.add_argument("--day-of-week", default="Wednesday")
    scenarios.add_argument("--resolution-minutes", type=int, default=15)
    scenarios.add_argument("--jobs", type=int, default=2)
    scenarios.add_argument("--timeout-seconds", type=int, default=1200)
    scenarios.add_argument(
        "--report-directory",
        default=str(PROJECT_ROOT / "reports" / "occupancy"),
    )
    scenarios.add_argument(
        "--publication-report",
        default=str(PROJECT_ROOT / "reports" / "publication" / "enb_readiness.md"),
    )
    scenarios.set_defaults(handler=scenarios_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"occupancy_workflow_failed:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
