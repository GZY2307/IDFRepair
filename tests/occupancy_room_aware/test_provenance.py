"""S/R provenance chain must be byte-bound and fail closed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from idfrepair.analysis.occupancy_room_aware.provenance import (
    validate_baseline_provenance_chain,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Path | str]:
    source = tmp_path / "source.osm"
    s_idf = tmp_path / "s.idf"
    r_idf = tmp_path / "r.idf"
    manifest = tmp_path / "people.json"
    for path, value in ((source, "source"), (s_idf, "s"), (r_idf, "r")):
        path.write_text(value, encoding="utf-8")
    source_sha = _sha(source)
    manifest.write_text(
        json.dumps({"source_sha256": source_sha, "space_count": 2, "spaces": [{}, {}]}),
        encoding="utf-8",
    )
    s_prov = tmp_path / "s_provenance.json"
    s_prov.write_text(
        json.dumps(
            {
                "schema_version": "idfrepair.source-preserving-ideal-loads.v2",
                "mode": "ideal-loads-demo",
                "source_sha256_before": source_sha,
                "source_sha256_after": source_sha,
                "source_unchanged": True,
                "synthetic_hvac_demo": True,
                "synthetic_ideal_loads_added": 2,
                "protected_source_objects_unchanged": True,
                "protected_snapshot_sha256_before": "p",
                "protected_snapshot_sha256_after": "p",
                "thermal_zone_source_semantics_unchanged": True,
                "thermal_zone_semantics_sha256_before": "z",
                "thermal_zone_semantics_sha256_after": "z",
                "source_fields_modified": 0,
                "derived_idf_sha256": _sha(s_idf),
                "before_counts": {
                    "spaces": 2,
                    "thermal_zones": 2,
                    "people": 1,
                    "people_definitions": 1,
                    "ideal_loads": 0,
                },
                "after_counts": {
                    "spaces": 2,
                    "thermal_zones": 2,
                    "people": 1,
                    "people_definitions": 1,
                    "ideal_loads": 2,
                },
            }
        ),
        encoding="utf-8",
    )
    r_prov = tmp_path / "r_provenance.json"
    stable = {
        "spaces": 2,
        "thermal_zones": 2,
        "space_types": 1,
        "lights": 1,
        "electric_equipment": 1,
        "infiltration": 1,
        "dsoa": 1,
        "air_loops": 0,
        "plant_loops": 0,
    }
    r_prov.write_text(
        json.dumps(
            {
                "schema_version": "idfrepair.room-aware-people-derivative.v1",
                "scenario_id": "baseline_r",
                "source_sha256_before": source_sha,
                "source_sha256_after": source_sha,
                "source_unchanged": True,
                "manifest_sha256": _sha(manifest),
                "protected_source_objects_unchanged": True,
                "protected_snapshot_sha256_before": "p2",
                "protected_snapshot_sha256_after": "p2",
                "thermal_zone_source_semantics_unchanged": True,
                "thermal_zone_semantics_sha256_before": "z2",
                "thermal_zone_semantics_sha256_after": "z2",
                "non_people_fields_modified": 0,
                "derived_idf_sha256": _sha(r_idf),
                "before_counts": {
                    **stable,
                    "people": 1,
                    "people_definitions": 1,
                    "ideal_loads": 0,
                },
                "after_counts": {
                    **stable,
                    "people": 2,
                    "people_definitions": 2,
                    "ideal_loads": 2,
                },
                "people_removed": 1,
                "people_definitions_removed": 1,
                "people_added": 2,
                "people_definitions_added": 2,
                "ideal_loads_added": 2,
            }
        ),
        encoding="utf-8",
    )
    return {
        "source": source,
        "source_sha": source_sha,
        "s_idf": s_idf,
        "r_idf": r_idf,
        "manifest": manifest,
        "s_prov": s_prov,
        "r_prov": r_prov,
    }


def _validate(paths: dict[str, Path | str]) -> dict:
    return validate_baseline_provenance_chain(
        source_osm_path=Path(paths["source"]),
        expected_source_sha256=str(paths["source_sha"]),
        baseline_s_idf_path=Path(paths["s_idf"]),
        baseline_s_provenance_path=Path(paths["s_prov"]),
        baseline_r_idf_path=Path(paths["r_idf"]),
        baseline_r_provenance_path=Path(paths["r_prov"]),
        people_manifest_path=Path(paths["manifest"]),
    )


def test_provenance_chain_links_source_s_r_and_manifest(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    result = _validate(paths)
    assert result["status"] == "PASS"
    assert result["source_osm_sha256"] == paths["source_sha"]
    assert result["baseline_s"]["source_fields_modified"] == 0
    assert result["baseline_r"]["non_people_fields_modified"] == 0


@pytest.mark.parametrize(
    ("target", "field", "value", "message"),
    (
        ("s_prov", "protected_source_objects_unchanged", False, "protected_objects_changed"),
        ("r_prov", "thermal_zone_semantics_sha256_after", "different", "zone_snapshot_mismatch"),
        ("r_prov", "manifest_sha256", "different", "manifest_hash_mismatch"),
    ),
)
def test_provenance_chain_rejects_broken_links(
    tmp_path: Path, target: str, field: str, value: object, message: str
) -> None:
    paths = _fixture(tmp_path)
    path = Path(paths[target])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        _validate(paths)


def test_provenance_chain_rejects_modified_derived_idf(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    Path(paths["r_idf"]).write_text("modified", encoding="utf-8")
    with pytest.raises(ValueError, match="r_idf_hash_mismatch"):
        _validate(paths)
