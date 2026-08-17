"""Build a private, exact Space-keyed payload for the local Three.js viewer."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import csv
import json
import math
from pathlib import Path
import re
from typing import Any

from idfrepair.analysis.occupancy_room_aware.results import (
    COOLING_RATE,
    HEATING_RATE,
    OCCUPANT_COUNT,
    bindings_from_audit,
    ideal_loads_key_to_zone,
)
from idfrepair.io.idf import canonical


VIEWER_PAYLOAD_SCHEMA = "idfrepair.room-aware-viewer.v2"
VIEWER_VARIABLES = (OCCUPANT_COUNT, HEATING_RATE, COOLING_RATE)
_HEADER = re.compile(
    r"^(?P<body>.*?)(?:\s+\[(?P<unit>[^]]*)\])?"
    r"\((?P<frequency>[^()]*)\)\s*$"
)


def _parse_header(raw: str) -> tuple[str, str] | None:
    match = _HEADER.match(raw.strip())
    if match is None:
        return None
    body = match.group("body").strip()
    for variable in sorted(VIEWER_VARIABLES, key=len, reverse=True):
        suffix = ":" + variable
        if canonical(body).endswith(canonical(suffix)):
            return body[: -len(suffix)].strip(), variable
    return None


def _clock_labels() -> list[str]:
    return [f"{index // 4:02d}:{(index % 4) * 15:02d}" for index in range(96)]


def _interval_metadata(energyplus_timestamps: Sequence[str]) -> dict[str, list[str]]:
    """Bind each EnergyPlus interval-end stamp to its exact 15-minute interval."""

    starts = _clock_labels()
    ends: list[str] = []
    labels: list[str] = []
    pattern = re.compile(
        r"^\s*(?P<month>\d{2})/(?P<day>\d{2})\s+"
        r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})\s*$"
    )
    for index, timestamp in enumerate(energyplus_timestamps):
        match = pattern.match(timestamp)
        if match is None:
            raise ValueError(f"viewer_energyplus_timestamp_invalid:{timestamp}")
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        second = int(match.group("second"))
        end_minutes = hour * 60 + minute
        expected_end = (index + 1) * 15
        if second != 0 or end_minutes != expected_end:
            raise ValueError(
                f"viewer_energyplus_timestamp_sequence_invalid:{index}:{timestamp}"
            )
        end = f"{hour:02d}:{minute:02d}"
        ends.append(end)
        labels.append(f"{starts[index]}–{end}")
    return {
        "interval_start_times": starts,
        "interval_end_times": ends,
        "interval_labels": labels,
    }


def build_viewer_payload(
    audit: Mapping[str, Any],
    csv_path: Path,
    idf_path: Path,
    *,
    scenario_id: str,
    period_id: str,
    design_people_by_space: Mapping[str, float] | None = None,
    flow_topology: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile seasonal EnergyPlus rows to all audited Spaces for local display."""

    bindings = bindings_from_audit(audit)
    if int(audit.get("space_count", len(bindings))) != len(bindings):
        raise ValueError("viewer_audit_space_count_mismatch")
    path = Path(csv_path)
    if not path.is_file():
        raise ValueError("viewer_csv_not_found")
    if not scenario_id.strip() or not period_id.strip():
        raise ValueError("viewer_scenario_identity_missing")
    binding_by_zone = {canonical(row.zone_name): row for row in bindings}
    alias_to_zone = {
        canonical(key): canonical(zone)
        for key, zone in ideal_loads_key_to_zone(idf_path).items()
    }
    values_by_zone = {
        zone_key: {variable: [] for variable in VIEWER_VARIABLES}
        for zone_key in binding_by_zone
    }
    energyplus_timestamps: list[str] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("viewer_csv_empty") from exc
        columns: dict[int, tuple[str, str]] = {}
        coverage = {variable: set() for variable in VIEWER_VARIABLES}
        for index, raw in enumerate(header[1:], start=1):
            parsed = _parse_header(raw)
            if parsed is None:
                continue
            key_name, variable = parsed
            zone_key = canonical(key_name)
            if zone_key not in binding_by_zone:
                zone_key = alias_to_zone.get(zone_key, "")
            if zone_key not in binding_by_zone:
                raise ValueError(f"viewer_output_key_unmapped:{key_name}")
            if zone_key in coverage[variable]:
                raise ValueError(f"viewer_output_key_duplicate:{key_name}:{variable}")
            columns[index] = (zone_key, variable)
            coverage[variable].add(zone_key)
        expected_zones = set(binding_by_zone)
        for variable, actual in coverage.items():
            if actual != expected_zones:
                raise ValueError(f"viewer_variable_coverage_incomplete:{variable}")
        for record in reader:
            if not record:
                continue
            timestamp = record[0].strip()
            row_values: dict[tuple[str, str], float] = {}
            for index, identity in columns.items():
                if index >= len(record):
                    raise ValueError(f"viewer_row_short:{timestamp}")
                try:
                    value = float(record[index])
                except ValueError as exc:
                    raise ValueError(f"viewer_value_invalid:{timestamp}:{identity}") from exc
                if not math.isfinite(value):
                    raise ValueError(f"viewer_value_nonfinite:{timestamp}:{identity}")
                row_values[identity] = value
            if not row_values:
                continue
            if len(row_values) != len(columns):
                raise ValueError(f"viewer_row_partial:{timestamp}")
            energyplus_timestamps.append(timestamp)
            for (zone_key, variable), value in row_values.items():
                values_by_zone[zone_key][variable].append(value)
    if len(energyplus_timestamps) != 96:
        raise ValueError(
            f"viewer_timestep_count_mismatch:{len(energyplus_timestamps)}:96"
        )
    intervals = _interval_metadata(energyplus_timestamps)

    design_override = {
        canonical(name): float(value)
        for name, value in (design_people_by_space or {}).items()
    }
    if design_override and design_override.keys() != {
        canonical(row.space_name) for row in bindings
    }:
        raise ValueError("viewer_design_people_space_mismatch")
    flow_by_space: dict[str, Mapping[str, Any]] = {}
    flow_summary: dict[str, Any] | None = None
    if flow_topology is not None:
        raw_flow_spaces = flow_topology.get("spaces")
        if not isinstance(raw_flow_spaces, Mapping):
            raise ValueError("viewer_flow_spaces_missing")
        flow_by_space = {
            canonical(str(name)): row
            for name, row in raw_flow_spaces.items()
            if isinstance(row, Mapping)
        }
        expected_space_keys = {canonical(row.space_name) for row in bindings}
        if set(flow_by_space) != expected_space_keys:
            raise ValueError("viewer_flow_space_mismatch")
        flow_summary = {
            "schema_version": str(flow_topology.get("schema_version", "")),
            "entrance_spaces": list(flow_topology.get("entrance_spaces", ())),
            "phase_semantics": str(flow_topology.get("phase_semantics", "")),
            "topology_method": str(flow_topology.get("topology_method", "")),
            "walking_route_claim": bool(flow_topology.get("walking_route_claim", False)),
            "measured_flow_claim": bool(flow_topology.get("measured_flow_claim", False)),
        }
    spaces: dict[str, dict[str, Any]] = {}
    for binding in sorted(bindings, key=lambda row: canonical(row.space_name)):
        zone_values = values_by_zone[canonical(binding.zone_name)]
        design_people = design_override.get(
            canonical(binding.space_name), binding.design_people
        )
        if not math.isfinite(design_people) or design_people <= 0.0:
            raise ValueError(f"viewer_design_people_invalid:{binding.space_name}")
        audit_row = next(
            row
            for row in audit["spaces"]
            if canonical(row["source_space_name"]) == canonical(binding.space_name)
        )
        status = str(audit_row.get("metadata_status", ""))
        space_payload = {
            "source_space_name": binding.space_name,
            "zone_name": binding.zone_name,
            "category": binding.category,
            "floor_area_m2": binding.floor_area_m2,
            "design_people": design_people,
            "metadata_status": status,
            "conflict": status == "SOURCE_METADATA_CONFLICT",
            "occupancy": list(zone_values[OCCUPANT_COUNT]),
            "heating_kw": [value / 1000.0 for value in zone_values[HEATING_RATE]],
            "cooling_kw": [value / 1000.0 for value in zone_values[COOLING_RATE]],
        }
        if flow_topology is not None:
            flow_row = flow_by_space[canonical(binding.space_name)]
            space_payload.update(
                {
                    "nearest_entrance_space": str(
                        flow_row.get("nearest_entrance_space", "")
                    ),
                    "adjacency_hops": int(flow_row.get("adjacency_hops", -1)),
                    "flow_distance_band": int(
                        flow_row.get("flow_distance_band", -1)
                    ),
                    "flow_phase_steps": int(flow_row.get("flow_phase_steps", -1)),
                    "flow_phase_minutes": int(
                        flow_row.get("flow_phase_minutes", -1)
                    ),
                    "is_flow_entrance": bool(
                        flow_row.get("is_flow_entrance", False)
                    ),
                    "phase_basis": str(flow_row.get("phase_basis", "")),
                }
            )
        spaces[binding.space_name] = space_payload
    counts = Counter(row.category for row in bindings)
    payload = {
        "schema_version": VIEWER_PAYLOAD_SCHEMA,
        "scenario_id": scenario_id,
        "period_id": period_id,
        "minutes_per_step": 15,
        "space_count": len(spaces),
        "orphan_zone_count": len(audit.get("orphan_zones", [])),
        "category_counts": dict(sorted(counts.items())),
        "conflict_count": sum(bool(row["conflict"]) for row in spaces.values()),
        "timestamp_semantics": "interval_start_to_end; EnergyPlus timestamp is interval end",
        "timestamps": intervals["interval_labels"],
        **intervals,
        "energyplus_timestamps": energyplus_timestamps,
        "units": {
            "occupancy": "people",
            "density": "people/m2",
            "capacity": "percent",
            "heating": "kW thermal",
            "cooling": "kW thermal",
        },
        "spaces": spaces,
    }
    if flow_summary is not None:
        payload["flow"] = flow_summary
    return payload


def snapshot_records(
    payload: Mapping[str, Any],
    times: Sequence[str],
) -> list[dict[str, Any]]:
    """Create exact five-time reconciliation rows used by screenshot QA."""

    if payload.get("schema_version") != VIEWER_PAYLOAD_SCHEMA:
        raise ValueError("viewer_payload_schema_invalid")
    records = []
    for clock in times:
        try:
            hour_text, minute_text = clock.split(":", 1)
            hour = int(hour_text)
            minute = int(minute_text)
        except (AttributeError, ValueError) as exc:
            raise ValueError(f"viewer_snapshot_time_invalid:{clock}") from exc
        if not 0 <= hour < 24 or minute not in (0, 15, 30, 45):
            raise ValueError(f"viewer_snapshot_time_invalid:{clock}")
        interval_start_times = payload.get("interval_start_times")
        if not isinstance(interval_start_times, list):
            raise ValueError("viewer_interval_start_times_missing")
        try:
            index = interval_start_times.index(clock)
        except ValueError as exc:
            raise ValueError(f"viewer_snapshot_interval_missing:{clock}") from exc
        spaces = payload["spaces"]
        records.append(
            {
                "time": clock,
                "time_index": index,
                "interval_start": clock,
                "interval_label": payload["interval_labels"][index],
                "energyplus_timestamp": payload["energyplus_timestamps"][index],
                "space_count": len(spaces),
                "total_people": math.fsum(row["occupancy"][index] for row in spaces.values()),
                "total_heating_kw": math.fsum(row["heating_kw"][index] for row in spaces.values()),
                "total_cooling_kw": math.fsum(row["cooling_kw"][index] for row in spaces.values()),
                "max_density_people_m2": max(
                    row["occupancy"][index] / row["floor_area_m2"]
                    for row in spaces.values()
                ),
            }
        )
    return records


def write_viewer_payload(payload: Mapping[str, Any], destination: Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


__all__ = [
    "VIEWER_PAYLOAD_SCHEMA",
    "build_viewer_payload",
    "snapshot_records",
    "write_viewer_payload",
]
