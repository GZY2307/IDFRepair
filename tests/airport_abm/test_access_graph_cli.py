from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "airport_abm" / "build_access_graph.py"


def test_access_graph_cli_expands_private_inputs_without_copying_paths(
    tmp_path: Path,
) -> None:
    mapping = tmp_path / "mapping.csv"
    fields = [
        "space",
        "thermal_zone",
        "region",
        "function",
        "original_space_type",
        "area_m2",
        "people_m2_per_person",
        "public_air_loop",
        "office_doas",
        "zone_hvac",
    ]
    with mapping.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for name, function in (
            ("entry", "departure_entry"),
            ("gate", "domestic_waiting"),
            ("shop", "general_commercial"),
        ):
            writer.writerow(
                {
                    "space": name,
                    "thermal_zone": "Zone " + name,
                    "region": "east",
                    "function": function,
                    "original_space_type": "Fixture",
                    "area_m2": "10",
                    "people_m2_per_person": "5",
                    "public_air_loop": "E-VAV",
                    "office_doas": "",
                    "zone_hvac": "",
                }
            )
    audit = tmp_path / "model-audit.json"
    audit.write_text(
        json.dumps(
            {
                "door_audit": {
                    "space_connections": [
                        {
                            "space_names": ["gate", "shop"],
                            "physical_door_pairs": [["a", "b"]],
                        }
                    ]
                },
                "surface_audit": {
                    "candidate_space_connections": [
                        {"space_names": ["entry", "gate"]}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    group_config = tmp_path / "groups.json"
    group_config.write_text(
        json.dumps(
            {
                "schema_version": "idfrepair.airport-abm-group-config.v3",
                "virtual_nodes": [
                    {"name": "BOARDING", "function": "boarding_sink", "region": "off"}
                ],
                "groups": {
                    "entries": {"names": ["entry"]},
                    "gates": {"names": ["gate"]},
                    "boarding": {"names": ["BOARDING"]},
                },
                "edge_templates": [
                    {
                        "from_group": "entries",
                        "to_group": "gates",
                        "roles": ["DOMESTIC_DEPARTURE"],
                        "evidence_ref": "fixture process",
                    },
                    {
                        "from_group": "gates",
                        "to_group": "boarding",
                        "roles": ["DOMESTIC_DEPARTURE"],
                        "evidence_ref": "fixture boundary",
                    },
                ],
                "blocked_surface_rules": [],
                "default_door_roles": ["STAFF"],
                "door_rules": [
                    {
                        "function_pair": ["commercial", "domestic_waiting"],
                        "roles": ["DOMESTIC_DEPARTURE", "STAFF"],
                    }
                ],
                "checks": [
                    {
                        "id": "departure",
                        "kind": "staged_route",
                        "graph": "passenger",
                        "role": "DOMESTIC_DEPARTURE",
                        "sources_group": "entries",
                        "stages": [
                            {"name": "gate", "group": "gates"},
                            {"name": "boarding", "group": "boarding"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "expanded.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mapping",
            str(mapping),
            "--model-audit",
            str(audit),
            "--group-config",
            str(group_config),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "idfrepair.airport-abm-access-registry.v3"
    assert payload["node_count"] == 4
    assert payload["groups"]["gates"] == ["gate"]
    assert payload["audit"]["layer_c_routing_input_count"] == 0
    assert payload["passenger_graph"]["routable"] == 4
    assert payload["staff_graph"]["routable"] == 2
    assert payload["validation"] == {
        "status": "PASS",
        "check_count": 1,
        "checks": [{"id": "departure", "status": "PASS", "route_count": 1}],
    }
    assert str(tmp_path) not in output.read_text(encoding="utf-8")
