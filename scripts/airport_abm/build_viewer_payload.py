#!/usr/bin/env python3
"""Build a private Airport Occupancy V3 browser payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.visualization import write_viewer_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--detail", required=True)
    parser.add_argument("--access-registry", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--energy-sql")
    parser.add_argument("--environment-period-index", type=int)
    args = parser.parse_args()
    output = write_viewer_payload(
        mapping_path=args.mapping,
        detail_path=args.detail,
        access_path=args.access_registry,
        output_path=args.output,
        energy_sql_path=args.energy_sql,
        environment_period_index=args.environment_period_index,
    )
    print(json.dumps({"status": "PASS", "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
