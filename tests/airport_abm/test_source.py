from __future__ import annotations

import csv
import importlib
from pathlib import Path

import pytest


def _write_mapping(path: Path) -> None:
    fields = (
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
    )
    rows = (
        {
            "space": "entry-1",
            "thermal_zone": "Zone entry-1",
            "region": "central",
            "function": "departure_entry",
            "original_space_type": "Airport Hall",
            "area_m2": "100.0",
            "people_m2_per_person": "10.0",
            "public_air_loop": "CENTRAL-VAV",
            "office_doas": "",
            "zone_hvac": "",
        },
        {
            "space": "shop-1",
            "thermal_zone": "Zone shop-1",
            "region": "east",
            "function": "general_commercial",
            "original_space_type": "Retail Retail",
            "area_m2": "25.0",
            "people_m2_per_person": "5.0",
            "public_air_loop": "E-VAV",
            "office_doas": "",
            "zone_hvac": "",
        },
        {
            "space": "toilet-1",
            "thermal_zone": "Zone toilet-1",
            "region": "east",
            "function": "restroom",
            "original_space_type": "Office Restroom",
            "area_m2": "30.0",
            "people_m2_per_person": "",
            "public_air_loop": "E-VAV",
            "office_doas": "",
            "zone_hvac": "",
        },
        {
            "space": "it-1",
            "thermal_zone": "Zone it-1",
            "region": "central",
            "function": "information_room",
            "original_space_type": "IT Room",
            "area_m2": "10.0",
            "people_m2_per_person": "",
            "public_air_loop": "",
            "office_doas": "CENTRAL-DOAS",
            "zone_hvac": "it-1-FCU",
        },
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_mapping_loads_canonical_functions_and_source_people_capacity(
    tmp_path: Path,
) -> None:
    mapping_path = tmp_path / "mapping.csv"
    _write_mapping(mapping_path)

    module = importlib.import_module("idfrepair.analysis.airport_abm.source")
    spaces = module.load_space_mapping(mapping_path)

    assert [space.name for space in spaces] == [
        "entry-1",
        "shop-1",
        "toilet-1",
        "it-1",
    ]
    assert spaces[0].function == "departure_entry"
    assert spaces[0].source_design_people == pytest.approx(10.0)
    assert spaces[1].function == "commercial"
    assert spaces[1].source_function == "general_commercial"
    assert spaces[1].source_design_people == pytest.approx(5.0)
    assert spaces[2].source_design_people is None
    assert spaces[3].function == "info"
    assert spaces[3].source_design_people is None


def test_spaces_without_source_people_are_flow_only_for_bem(tmp_path: Path) -> None:
    mapping_path = tmp_path / "mapping.csv"
    _write_mapping(mapping_path)

    module = importlib.import_module("idfrepair.analysis.airport_abm.source")
    spaces = {row.name: row for row in module.load_space_mapping(mapping_path)}

    assert spaces["entry-1"].bem_people_supported is True
    assert spaces["shop-1"].bem_people_supported is True
    assert spaces["toilet-1"].bem_people_supported is False
    assert spaces["toilet-1"].occupancy_evidence_status == "FLOW_ONLY_NO_SOURCE_PEOPLE"
    assert spaces["it-1"].bem_people_supported is False
    assert spaces["it-1"].occupancy_evidence_status == "FLOW_ONLY_NO_SOURCE_PEOPLE"


def test_mapping_inventory_is_literal_and_rejects_duplicate_space_names(
    tmp_path: Path,
) -> None:
    mapping_path = tmp_path / "mapping.csv"
    _write_mapping(mapping_path)
    module = importlib.import_module("idfrepair.analysis.airport_abm.source")

    spaces = module.load_space_mapping(mapping_path)
    assert module.mapping_inventory(spaces) == {
        "commercial": 1,
        "departure_entry": 1,
        "info": 1,
        "restroom": 1,
    }

    text = mapping_path.read_text(encoding="utf-8")
    mapping_path.write_text(text + text.splitlines()[1] + "\n", encoding="utf-8")
    with pytest.raises(module.SourceMappingError, match="duplicate space: entry-1"):
        module.load_space_mapping(mapping_path)
