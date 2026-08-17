"""Room-aware 3D payload and snapshot reconciliation tests."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from idfrepair.analysis.occupancy_room_aware.visualization import (
    build_viewer_payload,
    snapshot_records,
)


def _audit() -> dict:
    return {
        "space_count": 2,
        "category_counts": {"terminal_hall": 1, "office": 1},
        "orphan_zones": ["orphan"],
        "spaces": [
            {
                "source_space_name": "hall-1",
                "thermal_zone": "Zone A",
                "room_category": "terminal_hall",
                "floor_area_m2": 100.0,
                "design_people": 10.0,
                "metadata_status": "SOURCE_METADATA_CONSISTENT",
            },
            {
                "source_space_name": "office-1",
                "thermal_zone": "Zone B",
                "room_category": "office",
                "floor_area_m2": 20.0,
                "design_people": 5.0,
                "metadata_status": "SOURCE_METADATA_CONFLICT",
            },
        ],
    }


def _idf(path: Path) -> Path:
    path.write_text(
        "ZoneHVAC:EquipmentConnections,Zone A,List A,Inlets,Exhaust,Air Node;\n"
        "ZoneHVAC:EquipmentConnections,Zone B,List B,Inlets,Exhaust,Air Node;\n"
        "ZoneHVAC:EquipmentList,List A,SequentialLoad,"
        "ZoneHVAC:IdealLoadsAirSystem,Ideal A,1,1,,;\n"
        "ZoneHVAC:EquipmentList,List B,SequentialLoad,"
        "ZoneHVAC:IdealLoadsAirSystem,Ideal B,1,1,,;\n"
        "ZoneHVAC:IdealLoadsAirSystem,Ideal A;\n"
        "ZoneHVAC:IdealLoadsAirSystem,Ideal B;\n",
        encoding="utf-8",
    )
    return path


def _csv(path: Path) -> Path:
    header = ["Date/Time"]
    for variable, keys, unit in (
        ("Zone People Occupant Count", ("Zone A", "Zone B"), ""),
        ("Zone Ideal Loads Supply Air Total Heating Rate", ("Ideal A", "Ideal B"), "W"),
        ("Zone Ideal Loads Supply Air Total Cooling Rate", ("Ideal A", "Ideal B"), "W"),
    ):
        header.extend(f"{key}:{variable} [{unit}](TimeStep)" for key in keys)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for index in range(96):
            end_minutes = (index + 1) * 15
            writer.writerow(
                [
                    f"01/15  {end_minutes // 60:02d}:{end_minutes % 60:02d}:00",
                    float(index),
                    float(index) / 2,
                    index * 1000.0,
                    index * 2000.0,
                    index * 3000.0,
                    index * 4000.0,
                ]
            )
    return path


def test_payload_has_exact_space_mapping_conflict_and_csv_values(tmp_path: Path) -> None:
    flow_topology = {
        "schema_version": "idfrepair.room-aware-flow-topology.v1",
        "entrance_spaces": ["z-u-hall-2", "z-u-hall-3"],
        "phase_semantics": "controlled_occupancy_response_not_travel_time",
        "spaces": {
            "hall-1": {
                "nearest_entrance_space": "z-u-hall-2",
                "adjacency_hops": 2,
                "flow_distance_band": 1,
                "flow_phase_steps": 1,
                "flow_phase_minutes": 15,
                "is_flow_entrance": False,
            },
            "office-1": {
                "nearest_entrance_space": "z-u-hall-3",
                "adjacency_hops": 4,
                "flow_distance_band": 2,
                "flow_phase_steps": 0,
                "flow_phase_minutes": 0,
                "is_flow_entrance": False,
            },
        },
    }
    payload = build_viewer_payload(
        _audit(),
        _csv(tmp_path / "eplusout.csv"),
        _idf(tmp_path / "case.idf"),
        scenario_id="baseline_r",
        period_id="winter",
        flow_topology=flow_topology,
    )

    assert payload["schema_version"] == "idfrepair.room-aware-viewer.v2"
    assert payload["space_count"] == 2
    assert payload["orphan_zone_count"] == 1
    assert set(payload["spaces"]) == {"hall-1", "office-1"}
    assert len(payload["timestamps"]) == 96
    assert payload["interval_start_times"][24] == "06:00"
    assert payload["interval_labels"][24] == "06:00–06:15"
    assert payload["energyplus_timestamps"][24] == "01/15  06:15:00"
    assert payload["timestamps"][24] == "06:00–06:15"
    hall = payload["spaces"]["hall-1"]
    assert hall["occupancy"][24] == pytest.approx(24.0)
    assert hall["heating_kw"][24] == pytest.approx(24.0)
    assert hall["cooling_kw"][24] == pytest.approx(72.0)
    assert payload["spaces"]["office-1"]["conflict"] is True
    assert payload["flow"]["entrance_spaces"] == ["z-u-hall-2", "z-u-hall-3"]
    assert payload["flow"]["phase_semantics"] == (
        "controlled_occupancy_response_not_travel_time"
    )
    assert hall["nearest_entrance_space"] == "z-u-hall-2"
    assert hall["flow_phase_minutes"] == 15
    assert payload["spaces"]["office-1"]["flow_phase_steps"] == 0


def test_five_snapshot_records_reconcile_to_payload_values(tmp_path: Path) -> None:
    payload = build_viewer_payload(
        _audit(),
        _csv(tmp_path / "eplusout.csv"),
        _idf(tmp_path / "case.idf"),
        scenario_id="baseline_r",
        period_id="winter",
    )

    records = snapshot_records(payload, ("06:00", "09:00", "13:00", "18:00", "21:00"))

    assert [row["time"] for row in records] == [
        "06:00",
        "09:00",
        "13:00",
        "18:00",
        "21:00",
    ]
    assert [row["time_index"] for row in records] == [24, 36, 52, 72, 84]
    first = records[0]
    assert first["space_count"] == 2
    assert first["interval_start"] == "06:00"
    assert first["interval_label"] == "06:00–06:15"
    assert first["energyplus_timestamp"] == "01/15  06:15:00"
    assert first["total_people"] == pytest.approx(36.0)
    assert first["total_heating_kw"] == pytest.approx(72.0)
    assert first["total_cooling_kw"] == pytest.approx(168.0)


def test_payload_rejects_shifted_energyplus_interval_end_timestamp(
    tmp_path: Path,
) -> None:
    csv_path = _csv(tmp_path / "eplusout.csv")
    text = csv_path.read_text(encoding="utf-8")
    csv_path.write_text(
        text.replace("01/15  06:15:00", "01/15  06:00:00"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="timestamp_sequence_invalid:24"):
        build_viewer_payload(
            _audit(),
            csv_path,
            _idf(tmp_path / "case.idf"),
            scenario_id="baseline_r",
            period_id="winter",
        )
