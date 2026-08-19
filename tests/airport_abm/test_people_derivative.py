from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "airport_abm" / "build_people_derivative.rb"
OPENSTUDIO = Path("/Applications/OpenStudio/bin/openstudio")


def _runtime() -> Path:
    if not OPENSTUDIO.is_file():
        pytest.skip("OpenStudio CLI is not installed")
    return OPENSTUDIO


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "source.osm"
    generator = tmp_path / "make_fixture.rb"
    generator.write_text(
        """model = OpenStudio::Model::Model.new
fraction = OpenStudio::Model::ScheduleConstant.new(model)
fraction.setName('Source People Fraction')
fraction.setValue(0.5)
activity = OpenStudio::Model::ScheduleConstant.new(model)
activity.setName('Source Activity')
activity.setValue(120.0)

people_type = OpenStudio::Model::SpaceType.new(model)
people_type.setName('domestic-wait')
definition = OpenStudio::Model::PeopleDefinition.new(model)
definition.setName('Source People Definition')
definition.setNumberofPeople(10.0)
definition.setFractionRadiant(0.31)
definition.setSensibleHeatFraction(0.55)
definition.setCarbonDioxideGenerationRate(3.9e-8)
people = OpenStudio::Model::People.new(definition)
people.setName('Source SpaceType People')
people.setMultiplier(1.25)
people.setNumberofPeopleSchedule(fraction)
people.setActivityLevelSchedule(activity)
people.setSpaceType(people_type)

zone = OpenStudio::Model::ThermalZone.new(model)
zone.setName('Gate Zone')
gate = OpenStudio::Model::Space.new(model)
gate.setName('gate')
gate.setThermalZone(zone)
gate.setSpaceType(people_type)

restroom_zone = OpenStudio::Model::ThermalZone.new(model)
restroom_zone.setName('Restroom Zone')
restroom = OpenStudio::Model::Space.new(model)
restroom.setName('restroom')
restroom.setThermalZone(restroom_zone)

lights_definition = OpenStudio::Model::LightsDefinition.new(model)
lights_definition.setName('Protected Lights Definition')
lights_definition.setLightingLevel(100.0)
lights = OpenStudio::Model::Lights.new(lights_definition)
lights.setName('Protected Lights')
lights.setSpace(gate)

raise 'save failed' unless model.save(OpenStudio::Path.new(ARGV.fetch(0)), true)
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(_runtime()), str(generator), str(source)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return source


def _build(tmp_path: Path) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
    source = _make_source(tmp_path)
    output = tmp_path / "derived"
    output.mkdir()
    schedule = output / "occupancy.csv"
    schedule.write_text("gate\n" + "0.5\n" * (365 * 96), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "idfrepair.airport-abm-people-manifest.v3",
                "calendar_days": 365,
                "interval_minutes": 15,
                "schedule_file": str(schedule),
                "spaces": [
                    {
                        "source_space_name": "gate",
                        "schedule_column": 1,
                        "source_design_people": 12.5,
                        "source_design_people_tolerance": 0.000001,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            str(_runtime()),
            str(BUILD_SCRIPT),
            "--input",
            str(source),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output),
            "--allowed-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return source, output, result


def test_people_only_derivative_keeps_source_bytes_and_adds_no_ideal_loads(
    tmp_path: Path,
) -> None:
    source = _make_source(tmp_path)
    before = source.read_bytes()
    output = tmp_path / "derived"
    output.mkdir()
    schedule = output / "occupancy.csv"
    schedule.write_text("gate\n" + "0.5\n" * (365 * 96), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "idfrepair.airport-abm-people-manifest.v3",
                "calendar_days": 365,
                "interval_minutes": 15,
                "schedule_file": str(schedule),
                "spaces": [
                    {
                        "source_space_name": "gate",
                        "schedule_column": 1,
                        "source_design_people": 12.5,
                        "source_design_people_tolerance": 0.000001,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            str(_runtime()),
            str(BUILD_SCRIPT),
            "--input",
            str(source),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output),
            "--allowed-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_bytes() == before
    summary = json.loads((output / "derivative_summary.json").read_text())
    assert summary["source_unchanged"] is True
    assert summary["protected_objects_unchanged"] is True
    assert summary["people_removed_from_space_types"] == 1
    assert summary["direct_space_people_added"] == 1
    assert summary["flow_only_spaces_without_people"] == ["restroom"]
    assert summary["before_counts"]["ideal_loads"] == 0
    assert summary["after_counts"]["ideal_loads"] == 0
    assert (output / "derived.osm").is_file()
    assert (output / "derived.idf").is_file()


def test_derivative_has_one_direct_people_and_preserves_people_semantics(
    tmp_path: Path,
) -> None:
    _, output, result = _build(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    inspector = tmp_path / "inspect.rb"
    inspection = tmp_path / "inspection.json"
    inspector.write_text(
        """require 'json'
translator = OpenStudio::OSVersion::VersionTranslator.new
model = translator.loadModel(OpenStudio::Path.new(ARGV.fetch(0))).get
people = model.getPeoples
p = people.fetch(0)
schedule = p.numberofPeopleSchedule.get.to_ScheduleFile.get
limits = schedule.scheduleTypeLimits.get
payload = {
  'people_count' => people.size,
  'people_definition_count' => model.getPeopleDefinitions.size,
  'direct_space' => p.space.is_initialized ? p.space.get.nameString : nil,
  'space_type_assignment' => p.spaceType.is_initialized,
  'number_schedule_is_file' => p.numberofPeopleSchedule.get.to_ScheduleFile.is_initialized,
  'schedule_limits_name' => limits.nameString,
  'schedule_lower_limit' => limits.lowerLimitValue.get,
  'schedule_upper_limit_present' => limits.upperLimitValue.is_initialized,
  'activity_schedule' => p.activityLevelSchedule.get.nameString,
  'multiplier' => p.multiplier,
  'fraction_radiant' => p.peopleDefinition.fractionRadiant,
  'sensible_fraction' => p.peopleDefinition.sensibleHeatFraction.get,
  'co2' => p.peopleDefinition.carbonDioxideGenerationRate,
  'ideal_loads' => model.getZoneHVACIdealLoadsAirSystems.size,
  'lights' => model.getLightss.size
}
File.write(ARGV.fetch(1), JSON.generate(payload))
""",
        encoding="utf-8",
    )
    inspected = subprocess.run(
        [
            str(_runtime()),
            str(inspector),
            str(output / "derived.osm"),
            str(inspection),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert inspected.returncode == 0, inspected.stdout + inspected.stderr
    payload = json.loads(inspection.read_text())
    assert payload["people_count"] == 1
    assert payload["people_definition_count"] == 1
    assert payload["direct_space"] == "gate"
    assert payload["space_type_assignment"] is False
    assert payload["number_schedule_is_file"] is True
    assert payload["schedule_limits_name"] == "IDFRepair V3 Occupancy Multiplier"
    assert payload["schedule_lower_limit"] == 0.0
    assert payload["schedule_upper_limit_present"] is False
    assert payload["activity_schedule"] == "Source Activity"
    assert payload["multiplier"] == pytest.approx(1.25)
    assert payload["fraction_radiant"] == pytest.approx(0.31)
    assert payload["sensible_fraction"] == pytest.approx(0.55)
    assert payload["co2"] == pytest.approx(3.9e-8)
    assert payload["ideal_loads"] == 0
    assert payload["lights"] == 1


def test_builder_accepts_only_the_declared_source_rounding_tolerance(
    tmp_path: Path,
) -> None:
    source = _make_source(tmp_path)
    output = tmp_path / "rounding-derived"
    output.mkdir()
    schedule = output / "occupancy.csv"
    schedule.write_text("gate\n" + "0.5\n" * (365 * 96), encoding="utf-8")
    manifest = tmp_path / "rounding-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "idfrepair.airport-abm-people-manifest.v3",
                "calendar_days": 365,
                "interval_minutes": 15,
                "schedule_file": str(schedule),
                "spaces": [
                    {
                        "source_space_name": "gate",
                        "schedule_column": 1,
                        "source_design_people": 12.50005,
                        "source_design_people_tolerance": 0.000051,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(_runtime()),
            str(BUILD_SCRIPT),
            "--input",
            str(source),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output),
            "--allowed-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
