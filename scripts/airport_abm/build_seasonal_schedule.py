#!/usr/bin/env python3
"""Build one private fixed-seed schedule for seasonal EnergyPlus runs."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.seasonal_schedule import (  # noqa: E402
    write_repeated_daily_schedule,
)
from idfrepair.analysis.airport_abm.source import load_space_mapping  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--detail", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    with gzip.open(args.detail, "rt", encoding="utf-8") as handle:
        detail = json.load(handle)
    artifact = write_repeated_daily_schedule(
        spaces=load_space_mapping(args.mapping),
        detail=detail,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "scenario_id": artifact.scenario_id,
                "seed": artifact.seed,
                "row_count": artifact.row_count,
                "output_dir": str(Path(args.output_dir)),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
