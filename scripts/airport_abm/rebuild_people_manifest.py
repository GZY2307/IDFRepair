#!/usr/bin/env python3
"""Regenerate a People manifest for an already compiled annual CSV."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.annual_schedule import write_people_manifest  # noqa: E402
from idfrepair.analysis.airport_abm.source import load_space_mapping  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = write_people_manifest(
        args.output,
        schedule_path=args.schedule,
        spaces=load_space_mapping(args.mapping),
        days=365,
        interval_minutes=15,
    )
    print(json.dumps({"status": "PASS", "output": str(Path(output))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
