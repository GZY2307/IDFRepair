#!/usr/bin/env python3
"""Build the preregistered V3.1 seasonal schedules and People derivatives."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import json
from pathlib import Path
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.seasonal_schedule import (  # noqa: E402
    write_repeated_daily_schedule,
)
from idfrepair.analysis.airport_abm.source import load_space_mapping  # noqa: E402
from idfrepair.analysis.airport_abm.v31 import (  # noqa: E402
    SEASONAL_SEEDS,
    TIMING_SCENARIOS,
)


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def schedule_is_current(directory: Path, detail: Path) -> bool:
    files = (
        directory / "occupancy.csv",
        directory / "people_manifest.json",
        directory / "seasonal_schedule_summary.json",
    )
    if not all(path.is_file() for path in files):
        return False
    if min(path.stat().st_mtime for path in files) < detail.stat().st_mtime:
        return False
    try:
        summary = load_json(files[2])
    except (OSError, ValueError):
        return False
    return (
        summary.get("schema_version")
        == "idfrepair.airport-abm-seasonal-schedule.v3"
        and summary.get("row_count") == 35040
        and summary.get("seasonal_use_only") is True
    )


def derivative_is_current(directory: Path, manifest: Path, fixed_model: Path) -> bool:
    files = (
        directory / "derived.osm",
        directory / "derived.idf",
        directory / "derivative_summary.json",
    )
    if not all(path.is_file() for path in files):
        return False
    reference_time = max(manifest.stat().st_mtime, fixed_model.stat().st_mtime)
    if min(path.stat().st_mtime for path in files) < reference_time:
        return False
    try:
        summary = load_json(files[2])
    except (OSError, ValueError):
        return False
    return (
        summary.get("schema_version")
        == "idfrepair.airport-abm-people-derivative.v3"
        and summary.get("source_unchanged") is True
        and summary.get("protected_objects_unchanged") is True
        and summary.get("direct_space_people_added") == 276
    )


def build_derivative(
    *,
    openstudio: Path,
    builder: Path,
    fixed_model: Path,
    manifest: Path,
    output_dir: Path,
    allowed_root: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    if derivative_is_current(output_dir, manifest, fixed_model):
        return {"output_dir": str(output_dir), "status": "CACHED"}
    started = time.monotonic()
    result = subprocess.run(
        [
            str(openstudio),
            str(builder),
            "--input",
            str(fixed_model),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output_dir),
            "--allowed-root",
            str(allowed_root),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"People derivative failed: {output_dir}\n{result.stdout}{result.stderr}"
        )
    if not derivative_is_current(output_dir, manifest, fixed_model):
        raise RuntimeError(f"People derivative output contract failed: {output_dir}")
    return {
        "output_dir": str(output_dir),
        "status": "BUILT",
        "wall_seconds": time.monotonic() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--detail-root", required=True)
    parser.add_argument("--fixed-model", required=True)
    parser.add_argument("--schedule-root", required=True)
    parser.add_argument("--derivative-root", required=True)
    parser.add_argument("--allowed-root", required=True)
    parser.add_argument(
        "--openstudio", default="/Applications/OpenStudio/bin/openstudio"
    )
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 4:
        parser.error("jobs must be in [1, 4]")

    mapping = Path(args.mapping)
    detail_root = Path(args.detail_root)
    fixed_model = Path(args.fixed_model)
    schedule_root = Path(args.schedule_root)
    derivative_root = Path(args.derivative_root)
    allowed_root = Path(args.allowed_root).resolve()
    openstudio = Path(args.openstudio)
    builder = PROJECT_ROOT / "scripts/airport_abm/build_people_derivative.rb"
    for path in (mapping, fixed_model, openstudio, builder):
        if not path.is_file():
            raise SystemExit(f"required input not found: {path}")

    spaces = load_space_mapping(mapping)
    schedules: list[dict[str, object]] = []
    derivative_specs = []
    for scenario in TIMING_SCENARIOS:
        for seed in SEASONAL_SEEDS:
            detail = detail_root / "seed_details" / scenario / f"seed-{seed}.json.gz"
            output_dir = schedule_root / scenario / f"seed-{seed}"
            if not detail.is_file():
                raise SystemExit(f"normalized detail not found: {detail}")
            if schedule_is_current(output_dir, detail):
                schedule_status = "CACHED"
            else:
                with gzip.open(detail, "rt", encoding="utf-8") as handle:
                    payload = json.load(handle)
                artifact = write_repeated_daily_schedule(
                    spaces=spaces, detail=payload, output_dir=output_dir
                )
                if artifact.scenario_id != scenario or artifact.seed != seed:
                    raise RuntimeError("seasonal schedule identity changed")
                schedule_status = "BUILT"
            schedules.append(
                {"scenario_id": scenario, "seed": seed, "status": schedule_status}
            )
            derivative_specs.append(
                {
                    "scenario": scenario,
                    "seed": seed,
                    "manifest": output_dir / "people_manifest.json",
                    "output_dir": derivative_root / scenario / f"seed-{seed}",
                }
            )

    derivatives: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                build_derivative,
                openstudio=openstudio,
                builder=builder,
                fixed_model=fixed_model,
                manifest=spec["manifest"],
                output_dir=spec["output_dir"],
                allowed_root=allowed_root,
                timeout_seconds=args.timeout_seconds,
            ): spec
            for spec in derivative_specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            result = future.result()
            result.update({"scenario_id": spec["scenario"], "seed": spec["seed"]})
            derivatives.append(result)

    ledger = {
        "schema_version": "idfrepair.airport-v31-seasonal-input-ledger.v1",
        "cache_basis": "completion_contract_and_input_modification_time",
        "scenario_count": len(TIMING_SCENARIOS),
        "seed_count": len(SEASONAL_SEEDS),
        "schedule_count": len(schedules),
        "derivative_count": len(derivatives),
        "schedules": schedules,
        "derivatives": sorted(
            derivatives, key=lambda row: (str(row["scenario_id"]), int(row["seed"]))
        ),
    }
    ledger_path = Path(args.ledger)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "schedules": len(schedules),
                "derivatives": len(derivatives),
                "cached_derivatives": sum(
                    row["status"] == "CACHED" for row in derivatives
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
