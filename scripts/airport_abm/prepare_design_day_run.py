#!/usr/bin/env python3
"""Prepare one private Airport ABM V3.1 design-period IDF."""

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
    REQUIRED_METERS,
    REQUIRED_VARIABLES,
    prepare_design_day_run_idf,
)
from idfrepair.knowledge.idd import parse_idd  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--idd", required=True)
    parser.add_argument("--fixed-sizing-operation", action="store_true")
    args = parser.parse_args()
    output = prepare_design_day_run_idf(
        args.input,
        args.output,
        idd=parse_idd(Path(args.idd).read_text(encoding="utf-8", errors="replace")),
        variables=REQUIRED_VARIABLES,
        meters=REQUIRED_METERS,
        fixed_sizing_operation=args.fixed_sizing_operation,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(output),
                "variable_count": len(REQUIRED_VARIABLES),
                "meter_count": len(REQUIRED_METERS),
                "fixed_sizing_operation": args.fixed_sizing_operation,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
