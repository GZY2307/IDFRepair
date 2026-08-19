from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("IDFREPAIR_AIRPORT_OSM", "private-input-not-configured"))
MAPPING = Path(
    os.environ.get("IDFREPAIR_AIRPORT_MAPPING", "private-input-not-configured")
)
OPENSTUDIO = Path("/Applications/OpenStudio/bin/openstudio")


@pytest.mark.skipif(
    not all(path.is_file() for path in (SOURCE, MAPPING, OPENSTUDIO)),
    reason="private OpenStudio integration inputs are not present",
)
def test_source_static_export_reads_inherited_people_without_changing_source(
    tmp_path: Path,
) -> None:
    output = tmp_path / "source-static.json"
    result = subprocess.run(
        [
            str(OPENSTUDIO),
            str(PROJECT_ROOT / "scripts/airport_abm/export_source_static_people.rb"),
            "--input",
            str(SOURCE),
            "--mapping",
            str(MAPPING),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "idfrepair.airport-source-static-people.v31"
    assert payload["source_unchanged"] is True
    assert payload["source_supported_space_count"] == 276
    assert payload["flow_only_space_count"] == 28
    assert payload["public_person_hours"] == pytest.approx(585765.75135, rel=1e-9)
    assert payload["staff_person_hours"] == pytest.approx(26510.8557, rel=1e-9)
    assert {len(row["occupant_counts"]) for row in payload["spaces"]} == {96}
