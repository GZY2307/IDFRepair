#!/usr/bin/env python3
"""Build the private 15-minute room-aware viewer payload and snapshot ledger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from idfrepair.analysis.occupancy_room_aware.visualization import (  # noqa: E402
    build_viewer_payload,
    snapshot_records,
    write_viewer_payload,
)


SNAPSHOT_TIMES = ("06:00", "09:00", "13:00", "18:00", "21:00")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _within(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    allowed = root.resolve()
    return resolved == allowed or allowed in resolved.parents


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--people-manifest", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--idf", type=Path, required=True)
    parser.add_argument("--flow-topology", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allowed-root", type=Path, required=True)
    parser.add_argument("--scenario-id", default="baseline_r")
    parser.add_argument("--period-id", default="winter")
    args = parser.parse_args()
    if not _within(args.output_dir, args.allowed_root):
        raise ValueError("viewer_output_outside_allowed_root")
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    manifest = json.loads(args.people_manifest.read_text(encoding="utf-8"))
    flow_topology = json.loads(args.flow_topology.read_text(encoding="utf-8"))
    design = {
        row["source_space_name"]: float(row["target_design_people"])
        for row in manifest["spaces"]
    }
    payload = build_viewer_payload(
        audit,
        args.csv,
        args.idf,
        scenario_id=args.scenario_id,
        period_id=args.period_id,
        design_people_by_space=design,
        flow_topology=flow_topology,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload_path = write_viewer_payload(
        payload,
        args.output_dir / "occupancy_payload.json",
    )
    snapshots = snapshot_records(payload, SNAPSHOT_TIMES)
    snapshot_path = args.output_dir / "snapshot_values.csv"
    with snapshot_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(snapshots[0]))
        writer.writeheader()
        writer.writerows(snapshots)
    validation = {
        "schema_version": "idfrepair.room-aware-viewer-validation.v2",
        "scenario_id": args.scenario_id,
        "period_id": args.period_id,
        "space_count": payload["space_count"],
        "category_counts": payload["category_counts"],
        "orphan_zone_count": payload["orphan_zone_count"],
        "conflict_count": payload["conflict_count"],
        "timestep_count": len(payload["timestamps"]),
        "timestamp_semantics": payload["timestamp_semantics"],
        "first_interval_label": payload["interval_labels"][0],
        "last_interval_label": payload["interval_labels"][-1],
        "payload_sha256": _sha256(payload_path),
        "snapshot_ledger_sha256": _sha256(snapshot_path),
        "source_audit_sha256": _sha256(args.audit),
        "people_manifest_sha256": _sha256(args.people_manifest),
        "energyplus_csv_sha256": _sha256(args.csv),
        "prepared_idf_sha256": _sha256(args.idf),
        "flow_topology_sha256": _sha256(args.flow_topology),
        "entrance_spaces": payload["flow"]["entrance_spaces"],
        "flow_phase_semantics": payload["flow"]["phase_semantics"],
    }
    (args.output_dir / "visualization_manifest.json").write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(validation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
