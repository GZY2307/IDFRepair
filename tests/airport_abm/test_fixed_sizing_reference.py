from pathlib import Path
import json
import os
import subprocess

import pytest

from idfrepair.analysis.airport_abm.fixed_sizing import evaluate_fixed_sizing_audit


def _payload() -> dict[str, object]:
    return {
        "schema_version": "idfrepair.airport-fixed-sizing-audit.v31",
        "source_unchanged": True,
        "protected_objects_unchanged": True,
        "autosizable_fields_before": 12,
        "autosized_values_available": 12,
        "values_applied": 12,
        "autosizable_fields_unresolved": 0,
        "categories": {
            "Fan": {"before": 2, "available": 2, "applied": 2, "unresolved": 0},
            "Coil": {"before": 8, "available": 8, "applied": 8, "unresolved": 0},
            "Pump": {"before": 2, "available": 2, "applied": 2, "unresolved": 0},
        },
    }


def test_complete_apply_sizing_values_audit_admits_fixed_operation() -> None:
    decision = evaluate_fixed_sizing_audit(_payload())

    assert decision.status == "FIXED_OPERATION_COMPARISON_VALID"
    assert decision.unresolved_critical_fields == 0
    assert decision.reasons == ()


def test_unresolved_critical_capacity_field_blocks_fixed_operation() -> None:
    payload = _payload()
    payload["autosizable_fields_unresolved"] = 1
    payload["values_applied"] = 11
    payload["autosized_values_available"] = 11
    payload["categories"]["Fan"] = {
        "before": 2,
        "available": 1,
        "applied": 1,
        "unresolved": 1,
    }

    decision = evaluate_fixed_sizing_audit(payload)

    assert decision.status == "FIXED_OPERATION_INCOMPLETE"
    assert decision.unresolved_critical_fields == 1
    assert "critical_autosized_fields_unresolved" in decision.reasons


def test_openstudio_apply_sizing_values_builds_a_separate_fixed_reference(
    tmp_path: Path,
) -> None:
    project = Path(__file__).resolve().parents[2]
    source_value = os.environ.get("IDFREPAIR_AIRPORT_OSM")
    if not source_value:
        pytest.skip("IDFREPAIR_AIRPORT_OSM is not configured")
    source = Path(source_value)
    sql = project / ".private/occupancy_v3/energyplus/static_source/design-days-v2/eplusout.sql"
    openstudio = Path("/Applications/OpenStudio/bin/openstudio")
    if not all(path.is_file() for path in (source, sql, openstudio)):
        pytest.skip("private OpenStudio sizing inputs are not present")
    output = tmp_path / "fixed.osm"
    audit = tmp_path / "audit.json"

    result = subprocess.run(
        [
            str(openstudio),
            str(project / "scripts/airport_abm/build_fixed_sizing_reference.rb"),
            "--input",
            str(source),
            "--sql",
            str(sql),
            "--output",
            str(output),
            "--audit",
            str(audit),
        ],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert output.is_file()
    assert payload["source_unchanged"] is True
    assert payload["protected_objects_unchanged"] is True
    assert payload["autosizable_fields_before"] == 3944
    assert payload["autosized_values_available"] == 3036
    assert payload["values_applied"] == 3036
    assert payload["autosizable_fields_unresolved"] == 908
    decision = evaluate_fixed_sizing_audit(payload)
    assert decision.status == "FIXED_OPERATION_INCOMPLETE"
    assert decision.unresolved_critical_fields == 908
