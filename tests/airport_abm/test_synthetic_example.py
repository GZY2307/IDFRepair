from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_public_synthetic_fixture_runs_all_five_agent_classes() -> None:
    runner = PROJECT_ROOT / "examples/airport_abm_v3/run_synthetic.py"
    fixture = PROJECT_ROOT / "examples/airport_abm_v3/synthetic_terminal.json"

    result = subprocess.run(
        [sys.executable, str(runner), "--fixture", str(fixture)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["spawned"] == payload["terminal"] == 5
    assert payload["active"] == 0
    assert payload["violations"] == 0
    assert set(payload["classes"]) == {
        "DOMESTIC_DEPARTURE",
        "DOMESTIC_ARRIVAL",
        "DOMESTIC_TRANSFER",
        "INTERNATIONAL_ARRIVAL",
        "STAFF",
    }
