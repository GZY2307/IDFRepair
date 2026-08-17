"""Fail-closed provenance gates for the S and R occupancy baselines."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


S_SCHEMA = "idfrepair.source-preserving-ideal-loads.v2"
R_SCHEMA = "idfrepair.room-aware-people-derivative.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path, label: str) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError(f"baseline_provenance_{label}_not_found")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"baseline_provenance_{label}_invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"baseline_provenance_{label}_not_object")
    return payload


def _require(condition: bool, error: str) -> None:
    if not condition:
        raise ValueError(error)


def _snapshot_gate(payload: Mapping[str, Any], *, source_field: str) -> None:
    _require(
        payload.get("protected_source_objects_unchanged") is True,
        "baseline_provenance_protected_objects_changed",
    )
    _require(
        payload.get("protected_snapshot_sha256_before")
        == payload.get("protected_snapshot_sha256_after"),
        "baseline_provenance_protected_snapshot_mismatch",
    )
    _require(
        payload.get("thermal_zone_source_semantics_unchanged") is True,
        "baseline_provenance_zone_semantics_changed",
    )
    _require(
        payload.get("thermal_zone_semantics_sha256_before")
        == payload.get("thermal_zone_semantics_sha256_after"),
        "baseline_provenance_zone_snapshot_mismatch",
    )
    _require(
        payload.get(source_field) == 0,
        f"baseline_provenance_{source_field}_nonzero",
    )


def _source_gate(payload: Mapping[str, Any], expected_source_sha256: str) -> None:
    _require(payload.get("source_unchanged") is True, "baseline_provenance_source_changed")
    _require(
        payload.get("source_sha256_before") == expected_source_sha256
        and payload.get("source_sha256_after") == expected_source_sha256,
        "baseline_provenance_source_hash_mismatch",
    )


def validate_baseline_provenance_chain(
    *,
    source_osm_path: Path,
    expected_source_sha256: str,
    baseline_s_idf_path: Path,
    baseline_s_provenance_path: Path,
    baseline_r_idf_path: Path,
    baseline_r_provenance_path: Path,
    people_manifest_path: Path,
) -> dict[str, Any]:
    """Validate byte identity and semantic-preservation evidence for S→R."""

    source = Path(source_osm_path)
    s_idf = Path(baseline_s_idf_path)
    r_idf = Path(baseline_r_idf_path)
    manifest_path = Path(people_manifest_path)
    for path, label in (
        (source, "source_osm"),
        (s_idf, "baseline_s_idf"),
        (r_idf, "baseline_r_idf"),
        (manifest_path, "people_manifest"),
    ):
        _require(path.is_file() and not path.is_symlink(), f"baseline_provenance_{label}_not_found")
    _require(_sha256(source) == expected_source_sha256, "baseline_provenance_source_hash_mismatch")

    s = _load(baseline_s_provenance_path, "s")
    r = _load(baseline_r_provenance_path, "r")
    _require(s.get("schema_version") == S_SCHEMA, "baseline_provenance_s_schema_invalid")
    _require(r.get("schema_version") == R_SCHEMA, "baseline_provenance_r_schema_invalid")
    _source_gate(s, expected_source_sha256)
    _source_gate(r, expected_source_sha256)
    _snapshot_gate(s, source_field="source_fields_modified")
    _snapshot_gate(r, source_field="non_people_fields_modified")
    _require(s.get("mode") == "ideal-loads-demo", "baseline_provenance_s_mode_invalid")
    _require(s.get("synthetic_hvac_demo") is True, "baseline_provenance_s_demo_flag_invalid")
    _require(r.get("scenario_id") == "baseline_r", "baseline_provenance_r_scenario_invalid")
    _require(s.get("derived_idf_sha256") == _sha256(s_idf), "baseline_provenance_s_idf_hash_mismatch")
    _require(r.get("derived_idf_sha256") == _sha256(r_idf), "baseline_provenance_r_idf_hash_mismatch")
    _require(r.get("manifest_sha256") == _sha256(manifest_path), "baseline_provenance_manifest_hash_mismatch")

    s_before = s.get("before_counts")
    s_after = s.get("after_counts")
    r_before = r.get("before_counts")
    r_after = r.get("after_counts")
    for counts, label in (
        (s_before, "s_before"),
        (s_after, "s_after"),
        (r_before, "r_before"),
        (r_after, "r_after"),
    ):
        _require(isinstance(counts, Mapping), f"baseline_provenance_{label}_counts_invalid")
    for field in ("spaces", "thermal_zones", "people", "people_definitions"):
        _require(s_before.get(field) == s_after.get(field), f"baseline_provenance_s_count_changed:{field}")
    for field in ("spaces", "thermal_zones", "space_types", "lights", "electric_equipment", "infiltration", "dsoa", "air_loops", "plant_loops"):
        _require(r_before.get(field) == r_after.get(field), f"baseline_provenance_r_count_changed:{field}")
    _require(
        s_after.get("ideal_loads") == s_before.get("ideal_loads", 0) + s.get("synthetic_ideal_loads_added", -1),
        "baseline_provenance_s_ideal_loads_count_mismatch",
    )
    _require(
        r_after.get("ideal_loads") == r_before.get("ideal_loads", 0) + r.get("ideal_loads_added", -1),
        "baseline_provenance_r_ideal_loads_count_mismatch",
    )
    _require(
        r_after.get("people") == r.get("people_added")
        and r_before.get("people") == r.get("people_removed"),
        "baseline_provenance_r_people_count_mismatch",
    )
    _require(
        r_after.get("people_definitions") == r.get("people_definitions_added")
        and r_before.get("people_definitions") == r.get("people_definitions_removed"),
        "baseline_provenance_r_people_definition_count_mismatch",
    )
    manifest = _load(manifest_path, "people_manifest")
    _require(
        manifest.get("source_sha256") == expected_source_sha256,
        "baseline_provenance_manifest_source_mismatch",
    )
    _require(
        manifest.get("space_count") == r.get("people_added") == r_after.get("spaces"),
        "baseline_provenance_manifest_space_count_mismatch",
    )
    return {
        "schema_version": "idfrepair.room-aware-provenance-chain.v1",
        "status": "PASS",
        "source_osm_sha256": expected_source_sha256,
        "baseline_s": {
            "derived_idf_sha256": s["derived_idf_sha256"],
            "protected_snapshot_sha256": s["protected_snapshot_sha256_after"],
            "thermal_zone_semantics_sha256": s["thermal_zone_semantics_sha256_after"],
            "source_fields_modified": 0,
            "synthetic_ideal_loads_added": s["synthetic_ideal_loads_added"],
        },
        "baseline_r": {
            "derived_idf_sha256": r["derived_idf_sha256"],
            "manifest_sha256": r["manifest_sha256"],
            "protected_snapshot_sha256": r["protected_snapshot_sha256_after"],
            "thermal_zone_semantics_sha256": r["thermal_zone_semantics_sha256_after"],
            "non_people_fields_modified": 0,
            "people_added": r["people_added"],
            "ideal_loads_added": r["ideal_loads_added"],
        },
    }


__all__ = ["R_SCHEMA", "S_SCHEMA", "validate_baseline_provenance_chain"]
