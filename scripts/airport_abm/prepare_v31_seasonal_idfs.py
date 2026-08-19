#!/usr/bin/env python3
"""Prepare all preregistered fixed-operation V3.1 seasonal IDFs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.energyplus_coupling import (  # noqa: E402
    REQUIRED_METERS,
    REQUIRED_VARIABLES,
    prepare_design_day_run_idf,
    prepare_weather_run_idf,
)
from idfrepair.analysis.airport_abm.v31 import (  # noqa: E402
    SEASONAL_SEEDS,
    TIMING_SCENARIOS,
)
from idfrepair.knowledge.idd import parse_idd  # noqa: E402


def prepare_case(source: Path, output_dir: Path, idd) -> dict[str, object]:
    shoulder = output_dir / "shoulder.idf"
    design_days = output_dir / "design-days.idf"
    prepare_weather_run_idf(
        source,
        shoulder,
        idd=idd,
        begin_month=4,
        begin_day=15,
        begin_year=2006,
        end_month=4,
        end_day=15,
        end_year=2006,
        day_of_week="Saturday",
        variables=REQUIRED_VARIABLES,
        meters=REQUIRED_METERS,
        fixed_sizing_operation=True,
    )
    prepare_design_day_run_idf(
        source,
        design_days,
        idd=idd,
        variables=REQUIRED_VARIABLES,
        meters=REQUIRED_METERS,
        fixed_sizing_operation=True,
    )
    return {
        "source": str(source),
        "shoulder": str(shoulder),
        "design_days": str(design_days),
        "status": "PREPARED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derivative-root", required=True)
    parser.add_argument("--static-idf", required=True)
    parser.add_argument("--energy-root", required=True)
    parser.add_argument("--idd", required=True)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 4:
        parser.error("jobs must be in [1, 4]")

    derivative_root = Path(args.derivative_root)
    static_idf = Path(args.static_idf)
    energy_root = Path(args.energy_root)
    if not static_idf.is_file():
        raise SystemExit(f"static fixed IDF not found: {static_idf}")
    idd = parse_idd(Path(args.idd).read_text(encoding="utf-8", errors="replace"))
    specs: list[tuple[str, int | None, Path, Path]] = [
        ("SOURCE_STATIC", None, static_idf, energy_root / "static_source")
    ]
    for scenario in TIMING_SCENARIOS:
        for seed in SEASONAL_SEEDS:
            source = derivative_root / scenario / f"seed-{seed}" / "derived.idf"
            if not source.is_file():
                raise SystemExit(f"seasonal derivative not found: {source}")
            specs.append(
                (
                    scenario,
                    seed,
                    source,
                    energy_root / "seasonal" / scenario / f"seed-{seed}",
                )
            )

    rows: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(prepare_case, source, output, idd): (scenario, seed)
            for scenario, seed, source, output in specs
        }
        for future in as_completed(futures):
            scenario, seed = futures[future]
            row = future.result()
            row.update({"scenario_id": scenario, "seed": seed})
            rows.append(row)

    ledger = {
        "schema_version": "idfrepair.airport-v31-seasonal-idf-ledger.v1",
        "fixed_sizing_operation_requested": True,
        "shoulder_period": "2006-04-15 Beijing weather",
        "design_periods": ["SUMMER-DESIGN", "WINTER-DESIGN"],
        "case_count": len(rows),
        "period_identity_count": 3 * len(rows),
        "cases": sorted(
            rows,
            key=lambda row: (str(row["scenario_id"]), int(row["seed"] or 0)),
        ),
    }
    ledger_path = Path(args.ledger)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "case_count": len(rows),
                "period_identity_count": 3 * len(rows),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
