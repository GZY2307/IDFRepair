#!/usr/bin/env python3
"""Run the complete preregistered V3.1 seasonal EnergyPlus matrix."""

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

from idfrepair.analysis.airport_abm.energyplus_runner import (  # noqa: E402
    run_energyplus_case,
    seasonal_case_registry,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--energy-root", required=True)
    parser.add_argument("--epw", required=True)
    parser.add_argument("--energyplus", default="/usr/local/bin/energyplus")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 3:
        parser.error("jobs must be in [1, 3]")
    if args.timeout_seconds < 60:
        parser.error("timeout must be at least 60 seconds")
    energyplus = Path(args.energyplus)
    epw = Path(args.epw)
    if not energyplus.is_file() or not epw.is_file():
        raise SystemExit("EnergyPlus executable or EPW is missing")

    cases = seasonal_case_registry(args.energy_root)
    records: list[dict[str, object]] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                run_energyplus_case,
                case,
                energyplus=energyplus,
                epw=epw,
                timeout_seconds=args.timeout_seconds,
            ): case
            for case in cases
        }
        for future in as_completed(futures):
            case = futures[future]
            try:
                record = future.result()
            except Exception as exc:  # preserve the registered denominator
                record = {
                    "schema_version": "idfrepair.airport-v31-energyplus-completion.v1",
                    "scenario_id": case.scenario_id,
                    "seed": case.seed,
                    "run_kind": case.run_kind,
                    "expected_periods": list(case.expected_periods),
                    "return_code": -1,
                    "warning_count": 0,
                    "severe_count": 0,
                    "fatal_count": 0,
                    "wall_seconds": 0.0,
                    "passed": False,
                    "period_contract_passed": False,
                    "output_contract_error": f"runner_exception:{type(exc).__name__}:{exc}",
                    "periods": [],
                    "execution_status": "RUNNER_EXCEPTION",
                }
            records.append(record)
            completed += 1
            print(
                json.dumps(
                    {
                        "progress": f"{completed}/{len(cases)}",
                        "scenario_id": case.scenario_id,
                        "seed": case.seed,
                        "run_kind": case.run_kind,
                        "passed": record["passed"],
                        "execution_status": record["execution_status"],
                    }
                ),
                flush=True,
            )

    records.sort(
        key=lambda row: (
            str(row["run_kind"]),
            str(row["scenario_id"]),
            int(row["seed"] or 0),
        )
    )
    period_rows = []
    for row in records:
        actual_by_period = {
            period["period_id"]: period for period in row.get("periods", [])
        }
        for period_id in row["expected_periods"]:
            period = actual_by_period.get(period_id, {})
            period_rows.append(
                {
                    "scenario_id": row["scenario_id"],
                    "seed": row["seed"],
                    "run_kind": row["run_kind"],
                    "period_id": period_id,
                    "return_code": row["return_code"],
                    "warning_count": row["warning_count"],
                    "severe_count": row["severe_count"],
                    "fatal_count": row["fatal_count"],
                    "wall_seconds": row["wall_seconds"],
                    "passed": bool(row["passed"] and period),
                    "heating_unmet_occupied_hours": period.get(
                        "heating_unmet_occupied_hours"
                    ),
                    "cooling_unmet_occupied_hours": period.get(
                        "cooling_unmet_occupied_hours"
                    ),
                    "occupied_unmet_hours": period.get("occupied_unmet_hours"),
                }
            )
    ledger = {
        "schema_version": "idfrepair.airport-v31-seasonal-energyplus-ledger.v1",
        "cache_basis": "completion_marker_and_input_modification_time",
        "planned_process_count": len(cases),
        "planned_period_identity_count": 78,
        "process_run_count": sum(row["execution_status"] == "RAN" for row in records),
        "process_cached_count": sum(
            str(row["execution_status"]).startswith("CACHED") for row in records
        ),
        "process_pass_count": sum(bool(row["passed"]) for row in records),
        "period_pass_count": sum(bool(row["passed"]) for row in period_rows),
        "records": records,
        "period_records": period_rows,
    }
    ledger_path = Path(args.ledger)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": (
                    "PASS"
                    if ledger["period_pass_count"] == 78
                    else "INCOMPLETE"
                ),
                "process_pass_count": ledger["process_pass_count"],
                "period_pass_count": ledger["period_pass_count"],
            }
        )
    )
    return 0 if ledger["period_pass_count"] == 78 else 2


if __name__ == "__main__":
    raise SystemExit(main())
