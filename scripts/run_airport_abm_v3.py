#!/usr/bin/env python3
"""Run the source-constrained Airport Occupancy V3 experiment."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.experiment import (  # noqa: E402
    load_experiment_context,
    run_seed_matrix,
)
from idfrepair.analysis.airport_abm.annual_schedule import (  # noqa: E402
    generate_annual_timing_schedules,
)
from idfrepair.analysis.airport_abm.v31 import (  # noqa: E402
    AIRPORT_WIDE_STRESS_CONTEXT,
    BEM_REFERENCE_NORMALIZED,
)


def _json_ready(value):
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _edge_rows(profiles):
    return [
        {"from": source, "to": target, "values": list(values)}
        for (source, target), values in sorted(profiles.items())
    ]


def _write_detail(path: Path, result) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "idfrepair.airport-abm-seed-detail.v3",
        "scenario_id": result.scenario_id,
        "family": result.family,
        "seed": result.seed,
        "interval_minutes": result.compiled.interval_minutes,
        "interval_labels": list(result.compiled.interval_labels),
        "summary": result.summary,
        "space_counts": result.compiled.space_counts,
        "space_density": result.compiled.space_density,
        "class_counts": result.compiled.class_counts,
        "space_flows": _edge_rows(result.compiled.flow_counts),
        "class_space_flows": [
            {
                "from": source,
                "to": target,
                "classes": classes,
            }
            for (source, target), classes in sorted(
                result.compiled.class_flow_counts.items()
            )
        ],
        "function_counts": result.function_counts,
        "region_counts": result.region_counts,
        "hvac_group_counts": result.hvac_group_counts,
        "function_flows": _edge_rows(result.function_flows),
    }
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        json.dump(_json_ready(payload), handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")


def _flatten_summary(summary: dict[str, object]) -> dict[str, object]:
    output = {
        key: value
        for key, value in summary.items()
        if not isinstance(value, (dict, list, tuple))
    }
    for prefix in ("simulated_agents_by_class", "equivalent_arrivals_by_class"):
        for name, value in summary[prefix].items():
            output[f"{prefix}__{name}"] = value
    return output


def run_matrix(args: argparse.Namespace) -> int:
    context, scenarios = load_experiment_context(
        mapping_path=args.mapping,
        access_registry_path=args.access_registry,
        parameter_registry_path=args.parameter_registry,
    )
    requested = (
        tuple(int(value) for value in args.seeds.split(","))
        if args.seeds
        else context.registry.monte_carlo_seeds
    )
    selected = (
        tuple(scenario for scenario in scenarios if scenario.scenario_id in args.scenario)
        if args.scenario
        else scenarios
    )
    if args.scenario and len(selected) != len(set(args.scenario)):
        available = {scenario.scenario_id for scenario in scenarios}
        missing = sorted(set(args.scenario).difference(available))
        raise SystemExit("unknown scenario: " + ", ".join(missing))

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, object]] = []
    for seed in requested:
        results = run_seed_matrix(
            context,
            selected,
            seed=seed,
            raw_output_dir=(output / "raw_agents") if args.raw_agents else None,
            scale_mode=args.scale_mode,
        )
        for result in results:
            summary_rows.append(_flatten_summary(result.summary))
            _write_detail(
                output
                / "seed_details"
                / result.scenario_id
                / f"seed-{seed}.json.gz",
                result,
            )
        print(
            json.dumps(
                {
                    "status": "seed_complete",
                    "seed": seed,
                    "scenario_count": len(results),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )

    csv_path = output / "seed_summaries.csv"
    fieldnames = sorted({key for row in summary_rows for key in row})
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary_rows)
    manifest = {
        "schema_version": "idfrepair.airport-abm-run.v3",
        "status": "PASS",
        "seeds": list(requested),
        "scenarios": [scenario.scenario_id for scenario in selected],
        "summary_rows": len(summary_rows),
        "airport_wide_context_passengers_per_day": context.registry.public_arrivals_per_day,
        "airport_wide_context_status": context.registry.traffic_context_status,
        "source_public_person_hours_reference": context.targets.public_person_hours,
        "staff_person_hours_target": context.targets.staff_person_hours,
        "flow_only_space_count": len(context.targets.flow_only_spaces),
        "raw_agents_preserved": bool(args.raw_agents),
        "occupancy_scale": args.scale_mode,
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "matrix_complete", **manifest}, separators=(",", ":")))
    return 0


def run_annual_schedules(args: argparse.Namespace) -> int:
    context, scenarios = load_experiment_context(
        mapping_path=args.mapping,
        access_registry_path=args.access_registry,
        parameter_registry_path=args.parameter_registry,
    )
    requested = tuple(args.scenario) or (
        "BASELINE_SPREAD",
        "MORNING_BANK",
        "MIDDAY_BANK",
        "EVENING_BANK",
    )
    by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    missing = sorted(set(requested).difference(by_id))
    if missing:
        raise SystemExit("unknown scenario: " + ", ".join(missing))
    selected = tuple(by_id[name] for name in requested)
    artifacts = generate_annual_timing_schedules(
        context,
        selected,
        output_dir=args.output_dir,
        master_seed=context.registry.annual_seed,
        scale_mode=args.scale_mode,
    )
    print(
        json.dumps(
            {
                "status": "annual_schedules_complete",
                "scenarios": [artifact.scenario_id for artifact in artifacts],
                "row_counts": {
                    artifact.scenario_id: artifact.row_count for artifact in artifacts
                },
                "public_person_hours": {
                    artifact.scenario_id: artifact.public_person_hours
                    for artifact in artifacts
                },
            },
            separators=(",", ":"),
        )
    )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    matrix = sub.add_parser("abm-matrix")
    matrix.add_argument("--mapping", required=True)
    matrix.add_argument("--access-registry", required=True)
    matrix.add_argument("--parameter-registry", required=True)
    matrix.add_argument("--output-dir", required=True)
    matrix.add_argument("--seeds", default="")
    matrix.add_argument("--scenario", action="append", default=[])
    matrix.add_argument("--raw-agents", action="store_true")
    matrix.add_argument(
        "--scale-mode",
        choices=(AIRPORT_WIDE_STRESS_CONTEXT, BEM_REFERENCE_NORMALIZED),
        default=AIRPORT_WIDE_STRESS_CONTEXT,
    )
    matrix.set_defaults(func=run_matrix)
    annual = sub.add_parser("annual-schedules")
    annual.add_argument("--mapping", required=True)
    annual.add_argument("--access-registry", required=True)
    annual.add_argument("--parameter-registry", required=True)
    annual.add_argument("--output-dir", required=True)
    annual.add_argument("--scenario", action="append", default=[])
    annual.add_argument(
        "--scale-mode",
        choices=(AIRPORT_WIDE_STRESS_CONTEXT, BEM_REFERENCE_NORMALIZED),
        default=AIRPORT_WIDE_STRESS_CONTEXT,
    )
    annual.set_defaults(func=run_annual_schedules)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
