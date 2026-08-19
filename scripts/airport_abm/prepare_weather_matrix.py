#!/usr/bin/env python3
"""Prepare a matrix of private Airport ABM V3 weather-period IDFs."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.energyplus_coupling import (  # noqa: E402
    ANNUAL_VARIABLES,
    REQUIRED_METERS,
    REQUIRED_VARIABLES,
    prepare_weather_run_idf,
)
from idfrepair.knowledge.idd import parse_idd  # noqa: E402


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derivative-root", required=True)
    parser.add_argument("--energy-root", required=True)
    parser.add_argument("--idd", required=True)
    parser.add_argument("--begin", required=True, type=parse_date)
    parser.add_argument("--end", required=True, type=parse_date)
    parser.add_argument("--weekday", required=True)
    parser.add_argument("--run-kind", required=True, choices=("shoulder", "annual"))
    parser.add_argument("--annual-compact", action="store_true")
    parser.add_argument("--fixed-sizing-operation", action="store_true")
    parser.add_argument("--static-input")
    parser.add_argument("--static-output")
    args = parser.parse_args()
    if bool(args.static_input) != bool(args.static_output):
        parser.error("static input and output must be provided together")
    idd = parse_idd(Path(args.idd).read_text(encoding="utf-8", errors="replace"))
    variables = ANNUAL_VARIABLES if args.annual_compact else REQUIRED_VARIABLES
    derivative_root = Path(args.derivative_root)
    energy_root = Path(args.energy_root)
    outputs: list[str] = []
    for source in sorted(derivative_root.glob("*/seed-*/derived.idf")):
        scenario = source.parents[1].name
        seed = source.parent.name
        output = energy_root / scenario / seed / f"{args.run_kind}.idf"
        prepare_weather_run_idf(
            source,
            output,
            idd=idd,
            begin_month=args.begin.month,
            begin_day=args.begin.day,
            begin_year=args.begin.year,
            end_month=args.end.month,
            end_day=args.end.day,
            end_year=args.end.year,
            day_of_week=args.weekday,
            variables=variables,
            meters=REQUIRED_METERS,
            reporting_frequency="Timestep",
            fixed_sizing_operation=args.fixed_sizing_operation,
        )
        outputs.append(str(output))
    if args.static_input:
        prepare_weather_run_idf(
            args.static_input,
            args.static_output,
            idd=idd,
            begin_month=args.begin.month,
            begin_day=args.begin.day,
            begin_year=args.begin.year,
            end_month=args.end.month,
            end_day=args.end.day,
            end_year=args.end.year,
            day_of_week=args.weekday,
            variables=variables,
            meters=REQUIRED_METERS,
            reporting_frequency="Timestep",
            fixed_sizing_operation=args.fixed_sizing_operation,
        )
        outputs.append(str(Path(args.static_output)))
    if not outputs:
        raise SystemExit("no weather-period inputs were prepared")
    print(
        json.dumps(
            {
                "status": "PASS",
                "run_kind": args.run_kind,
                "output_count": len(outputs),
                "variable_count": len(variables),
                "fixed_sizing_operation": args.fixed_sizing_operation,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
