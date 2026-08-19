#!/usr/bin/env python3
"""Add the V3 timestep output contract to a translated static IDF."""

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
    instrument_idf,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = instrument_idf(
        args.input,
        args.output,
        variables=REQUIRED_VARIABLES,
        meters=REQUIRED_METERS,
    )
    print(json.dumps({"status": "PASS", "output": str(Path(output))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
