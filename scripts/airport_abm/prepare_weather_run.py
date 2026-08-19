#!/usr/bin/env python3
"""Prepare a private weather-period IDF for an Airport ABM V3 case."""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--idd", required=True)
    parser.add_argument("--begin", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--weekday", required=True)
    parser.add_argument("--annual-compact", action="store_true")
    args = parser.parse_args()
    begin = tuple(int(part) for part in args.begin.split("-"))
    end = tuple(int(part) for part in args.end.split("-"))
    if len(begin) != 3 or len(end) != 3:
        parser.error("dates must use YYYY-MM-DD")
    variables = ANNUAL_VARIABLES if args.annual_compact else REQUIRED_VARIABLES
    frequency = "Timestep"
    output = prepare_weather_run_idf(
        args.input,
        args.output,
        idd=parse_idd(Path(args.idd).read_text(encoding="utf-8", errors="replace")),
        begin_month=begin[1],
        begin_day=begin[2],
        begin_year=begin[0],
        end_month=end[1],
        end_day=end[2],
        end_year=end[0],
        day_of_week=args.weekday,
        variables=variables,
        meters=REQUIRED_METERS,
        reporting_frequency=frequency,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(Path(output)),
                "reporting_frequency": frequency,
                "variable_count": len(variables),
                "meter_count": len(REQUIRED_METERS),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
