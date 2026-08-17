"""验证 People-only OpenStudio derivative 的精确修改边界。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from idfrepair.analysis.occupancy_room_aware.compiler import build_people_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = (
    PROJECT_ROOT
    / "scripts"
    / "occupancy_room_aware"
    / "build_people_derivative.rb"
)
AUDIT_SCRIPT = (
    PROJECT_ROOT
    / "scripts"
    / "occupancy_room_aware"
    / "audit_terminal_model.rb"
)
OPENSTUDIO = Path("/Applications/OpenStudio/bin/openstudio")


def _require_openstudio() -> Path:
    if not OPENSTUDIO.is_file():
        pytest.skip("OpenStudio CLI is not installed")
    return OPENSTUDIO


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "fixture.osm"
    generator = tmp_path / "generate_derivative_fixture.rb"
    generator.write_text(
        """model = OpenStudio::Model::Model.new
building = model.getBuilding

fraction = OpenStudio::Model::ScheduleConstant.new(model)
fraction.setName('Fixture Occupancy Fraction')
fraction.setValue(0.5)
activity = OpenStudio::Model::ScheduleConstant.new(model)
activity.setName('Fixture Activity')
activity.setValue(125.0)

default_type = OpenStudio::Model::SpaceType.new(model)
default_type.setName('Fixture Large Office Default')
building.setSpaceType(default_type)
definition = OpenStudio::Model::PeopleDefinition.new(model)
definition.setName('Fixture Default People Definition')
definition.setPeopleperSpaceFloorArea(0.05)
definition.setFractionRadiant(0.31)
definition.setSensibleHeatFraction(0.54)
definition.setCarbonDioxideGenerationRate(3.9e-8)
people = OpenStudio::Model::People.new(definition)
people.setName('Fixture Default People')
people.setNumberofPeopleSchedule(fraction)
people.setActivityLevelSchedule(activity)
people.setSpaceType(default_type)

lights_definition = OpenStudio::Model::LightsDefinition.new(model)
lights_definition.setName('Fixture Lights Definition')
lights_definition.setWattsperSpaceFloorArea(9.0)
lights = OpenStudio::Model::Lights.new(lights_definition)
lights.setName('Fixture Lights')
lights.setSpaceType(default_type)

equipment_definition = OpenStudio::Model::ElectricEquipmentDefinition.new(model)
equipment_definition.setName('Fixture Equipment Definition')
equipment_definition.setWattsperSpaceFloorArea(12.0)
equipment = OpenStudio::Model::ElectricEquipment.new(equipment_definition)
equipment.setName('Fixture Equipment')
equipment.setSpaceType(default_type)

oa = OpenStudio::Model::DesignSpecificationOutdoorAir.new(model)
oa.setName('Fixture OA')
oa.setOutdoorAirMethod('Sum')
oa.setOutdoorAirFlowperPerson(0.003)
oa.setOutdoorAirFlowperFloorArea(0.0004)
default_type.setDesignSpecificationOutdoorAir(oa)

it_type = OpenStudio::Model::SpaceType.new(model)
it_type.setName('189.1-2009 - Office - IT_Room - CZ1-3')
it_definition = OpenStudio::Model::PeopleDefinition.new(model)
it_definition.setName('Fixture IT People Definition')
it_definition.setNumberofPeople(2.5)
it_definition.setFractionRadiant(0.42)
it_definition.setCarbonDioxideGenerationRate(4.2e-8)
it_people = OpenStudio::Model::People.new(it_definition)
it_people.setName('Fixture IT People')
it_people.setNumberofPeopleSchedule(fraction)
it_people.setActivityLevelSchedule(activity)
it_people.setSpaceType(it_type)

hall_zone = OpenStudio::Model::ThermalZone.new(model)
hall_zone.setName('Hall Zone')
hall = OpenStudio::Model::Space.new(model)
hall.setName('p1-hall-1')
hall.setThermalZone(hall_zone)

office_zone = OpenStudio::Model::ThermalZone.new(model)
office_zone.setName('Office Zone')
office = OpenStudio::Model::Space.new(model)
office.setName('z-u-office-11')
office.setThermalZone(office_zone)
office.setSpaceType(it_type)

raise 'save_failed' unless model.save(OpenStudio::Path.new(ARGV.fetch(0)), true)
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(_require_openstudio()), str(generator), str(source)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return source


def _manifest(source: Path, path: Path) -> Path:
    payload = {
        "schema_version": "idfrepair.room-aware-people-manifest.v1",
        "scenario_id": "baseline_r_fixture",
        "source_alias": "Terminal Model A",
        "source_sha256": _sha256(source),
        "spaces": [
            {
                "source_space_name": "p1-hall-1",
                "room_category": "terminal_hall",
                "target_design_people": 10.0,
                "source_design_people": 0.0,
                "metadata_status": "SOURCE_METADATA_DEFAULTED",
                "preserve_source_people_parameters": False,
                "fraction_radiant": 0.31,
                "sensible_heat_fraction": 0.54,
                "co2_generation_rate_m3_s_person": 3.9e-8,
                "activity_schedule": "Fixture Activity",
                "count_evidence_id": "fixture-hall-source",
            },
            {
                "source_space_name": "z-u-office-11",
                "room_category": "office",
                "target_design_people": 2.5,
                "source_design_people": 2.5,
                "metadata_status": "SOURCE_METADATA_CONFLICT",
                "preserve_source_people_parameters": True,
                "fraction_radiant": 0.42,
                "sensible_heat_fraction": None,
                "co2_generation_rate_m3_s_person": 4.2e-8,
                "activity_schedule": "Fixture Activity",
                "count_evidence_id": "fixture-conflict-source",
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _build(source: Path, manifest: Path, output: Path):
    return subprocess.run(
        [
            str(_require_openstudio()),
            str(BUILD_SCRIPT),
            "--input",
            str(source),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output),
            "--allowed-root",
            str(output.parent),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_people_only_derivative_preserves_source_and_protected_objects(
    tmp_path: Path,
) -> None:
    source = _make_source(tmp_path)
    before = _sha256(source)
    manifest = _manifest(source, tmp_path / "manifest.json")
    output = tmp_path / "derived" / "baseline_r"

    result = _build(source, manifest, output)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _sha256(source) == before
    provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["source_unchanged"] is True
    assert provenance["protected_source_objects_unchanged"] is True
    assert provenance["protected_snapshot_sha256_before"] == provenance[
        "protected_snapshot_sha256_after"
    ]
    assert provenance["thermal_zone_source_semantics_unchanged"] is True
    assert provenance["thermal_zone_semantics_sha256_before"] == provenance[
        "thermal_zone_semantics_sha256_after"
    ]
    assert provenance["people_removed"] == 2
    assert provenance["people_definitions_removed"] == 2
    assert provenance["people_added"] == 2
    assert provenance["people_definitions_added"] == 2
    assert provenance["ideal_loads_added"] == 2
    assert provenance["non_people_fields_modified"] == 0
    assert (output / "derived.osm").is_file()
    assert (output / "derived.idf").is_file()


def test_derivative_people_are_explicit_per_space_and_conflict_is_preserved(
    tmp_path: Path,
) -> None:
    source = _make_source(tmp_path)
    manifest = _manifest(source, tmp_path / "manifest.json")
    output = tmp_path / "derived" / "baseline_r"
    result = _build(source, manifest, output)
    assert result.returncode == 0, result.stdout + result.stderr
    audit_path = tmp_path / "derived_audit.json"
    audit_result = subprocess.run(
        [
            str(_require_openstudio()),
            str(AUDIT_SCRIPT),
            "--input",
            str(output / "derived.osm"),
            "--output",
            str(audit_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert audit_result.returncode == 0, audit_result.stdout + audit_result.stderr
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    rows = {row["source_space_name"]: row for row in audit["spaces"]}
    for row in rows.values():
        assert len(row["people_sources"]) == 1
        assert row["people_sources"][0]["source_kind"] == "direct_space"
        assert row["people_sources"][0]["definition"]["method"] == "People"
        assert row["people_sources"][0]["count_schedule"] == (
            "IDFRepair Room-Aware Placeholder Fraction"
        )
    assert rows["p1-hall-1"]["design_people"] == pytest.approx(10.0)
    conflict = rows["z-u-office-11"]
    assert conflict["design_people"] == pytest.approx(2.5)
    definition = conflict["people_sources"][0]["definition"]
    assert definition["fraction_radiant"] == pytest.approx(0.42)
    assert definition["sensible_heat_fraction"] is None
    assert definition["co2_generation_rate_m3_s_person"] == pytest.approx(4.2e-8)
    assert conflict["metadata_status"] == "SOURCE_METADATA_CONFLICT"


def test_manifest_builder_uses_evidence_and_preserves_metadata_conflict() -> None:
    audit = {
        "schema_version": "idfrepair.room-aware-source-audit.v1",
        "source_sha256_after": "a" * 64,
        "spaces": [
            {
                "source_space_name": "office-1",
                "room_category": "office",
                "floor_area_m2": 60.0,
                "design_people": 3.0,
                "metadata_status": "SOURCE_METADATA_CONSISTENT",
                "people_sources": [
                    {
                        "activity_schedule": "Office Activity",
                        "definition": {
                            "fraction_radiant": 0.3,
                            "sensible_heat_fraction": None,
                            "co2_generation_rate_m3_s_person": 3.82e-8,
                        },
                    }
                ],
            },
            {
                "source_space_name": "office-2",
                "room_category": "office",
                "floor_area_m2": 60.0,
                "design_people": 3.1,
                "metadata_status": "SOURCE_METADATA_CONFLICT",
                "people_sources": [
                    {
                        "activity_schedule": "IT Activity",
                        "definition": {
                            "fraction_radiant": 0.4,
                            "sensible_heat_fraction": 0.5,
                            "co2_generation_rate_m3_s_person": 4e-8,
                        },
                    }
                ],
            },
        ],
    }

    manifest = build_people_manifest(audit, scenario_id="baseline_r")
    rows = {row["source_space_name"]: row for row in manifest["spaces"]}

    assert rows["office-1"]["target_design_people"] == pytest.approx(10.0)
    assert rows["office-1"]["count_evidence_id"] == "density.office.project_notes"
    assert rows["office-1"]["preserve_source_people_parameters"] is False
    assert rows["office-2"]["target_design_people"] == pytest.approx(3.1)
    assert rows["office-2"]["count_evidence_id"] == "SOURCE_METADATA_CONFLICT_PRESERVE"
    assert rows["office-2"]["preserve_source_people_parameters"] is True
