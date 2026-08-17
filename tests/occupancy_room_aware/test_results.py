"""Room-aware EnergyPlus extraction and reconciliation contracts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from idfrepair.analysis.occupancy.models import SimulationRun
from idfrepair.analysis.occupancy_room_aware.results import (
    SpaceResultBinding,
    bindings_from_audit,
    build_run_manifest,
    expected_run_identity,
    extract_room_results,
    ideal_loads_key_to_zone,
    migrate_v1_run_manifest,
    prepare_annual_idf,
    prepare_controlled_day_idf,
    validate_run_manifest,
    validate_bindings,
)
from idfrepair.analysis.occupancy.models import OutputRequest
from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd


VARIABLES = (
    "Zone People Occupant Count",
    "Zone People Sensible Heating Energy",
    "Zone People Latent Gain Energy",
    "Zone People Radiant Heating Energy",
    "Zone Ideal Loads Supply Air Total Heating Energy",
    "Zone Ideal Loads Supply Air Total Cooling Energy",
    "Zone Ideal Loads Supply Air Total Heating Rate",
    "Zone Ideal Loads Supply Air Total Cooling Rate",
    "Zone Mean Air Temperature",
    "Zone Air Relative Humidity",
    "Zone Heating Setpoint Not Met Time",
    "Zone Cooling Setpoint Not Met Time",
    "Zone Ideal Loads Outdoor Air Total Heating Energy",
)

PERIOD_IDD = r"""!IDD_Version 23.1.0
Timestep,
  N1, \field Number of Timesteps per Hour
      \default 6;
SimulationControl,
  A1, \field Do Zone Sizing Calculation
  A2, \field Do System Sizing Calculation
  A3, \field Do Plant Sizing Calculation
  A4, \field Run Simulation for Sizing Periods
  A5, \field Run Simulation for Weather File Run Periods
  A6, \field Do HVAC Sizing Simulation for Sizing Periods
  N1, \field Maximum Number of HVAC Sizing Simulation Passes
      \default 1;
RunPeriod,
  A1, \field Name
  N1, \field Begin Month
  N2, \field Begin Day of Month
  N3, \field Begin Year
  N4, \field End Month
  N5, \field End Day of Month
  N6, \field End Year
  A2, \field Day of Week for Start Day
      \default Sunday;
"""


def _bindings() -> tuple[SpaceResultBinding, ...]:
    return (
        SpaceResultBinding("office-1", "Zone A", "office", 100.0, 8.0),
        SpaceResultBinding("hall-1", "Zone B", "terminal_hall", 50.0, 10.0),
    )


def test_audit_bindings_accept_exact_reference_design_capacity_override() -> None:
    audit = {
        "spaces": [
            {
                "source_space_name": "office-1",
                "thermal_zone": "Zone A",
                "room_category": "office",
                "floor_area_m2": 100.0,
                "design_people": 8.0,
            },
            {
                "source_space_name": "hall-1",
                "thermal_zone": "Zone B",
                "room_category": "terminal_hall",
                "floor_area_m2": 50.0,
                "design_people": 10.0,
            },
        ]
    }

    source = bindings_from_audit(audit)
    reference = bindings_from_audit(
        audit,
        design_people_by_space={"office-1": 20.0, "hall-1": 5.0},
    )

    assert sum(row.design_people for row in source) == pytest.approx(18.0)
    assert sum(row.design_people for row in reference) == pytest.approx(25.0)
    with pytest.raises(ValueError, match="result_design_people_space_mismatch"):
        bindings_from_audit(
            audit,
            design_people_by_space={"office-1": 20.0},
        )


def _header(variable: str, zone: str) -> str:
    units = {
        "Zone People Occupant Count": "",
        "Zone Mean Air Temperature": "C",
        "Zone Air Relative Humidity": "%",
        "Zone Ideal Loads Supply Air Total Heating Rate": "W",
        "Zone Ideal Loads Supply Air Total Cooling Rate": "W",
        "Zone Heating Setpoint Not Met Time": "hr",
        "Zone Cooling Setpoint Not Met Time": "hr",
    }
    unit = units.get(variable, "J")
    return f"{zone.upper()}:{variable} [{unit}](TimeStep)"


def _write_fixture(path: Path) -> None:
    present = VARIABLES[:-1]
    header = ["Date/Time"] + [
        _header(
            variable,
            ("Ideal A", "Ideal B")[index]
            if variable.startswith("Zone Ideal Loads")
            else zone,
        )
        for variable in present
        for index, zone in enumerate(("Zone A", "Zone B"))
    ]
    values = {
        "Zone People Occupant Count": ((2.0, 3.0), (4.0, 1.0)),
        "Zone People Sensible Heating Energy": ((3.6e6, 7.2e6), (3.6e6, 3.6e6)),
        "Zone People Latent Gain Energy": ((1.8e6, 1.8e6), (1.8e6, 1.8e6)),
        "Zone People Radiant Heating Energy": ((0.9e6, 0.9e6), (0.9e6, 0.9e6)),
        "Zone Ideal Loads Supply Air Total Heating Energy": (
            (3.6e6, 0.0),
            (0.0, 7.2e6),
        ),
        "Zone Ideal Loads Supply Air Total Cooling Energy": (
            (0.0, 3.6e6),
            (3.6e6, 0.0),
        ),
        "Zone Ideal Loads Supply Air Total Heating Rate": (
            (1000.0, 2000.0),
            (4000.0, 1000.0),
        ),
        "Zone Ideal Loads Supply Air Total Cooling Rate": (
            (3000.0, 1000.0),
            (2000.0, 4000.0),
        ),
        "Zone Mean Air Temperature": ((20.0, 24.0), (22.0, 26.0)),
        "Zone Air Relative Humidity": ((40.0, 50.0), (50.0, 60.0)),
        "Zone Heating Setpoint Not Met Time": ((0.0, 0.25), (0.0, 0.0)),
        "Zone Cooling Setpoint Not Met Time": ((0.0, 0.0), (0.25, 0.0)),
    }
    rows = []
    for step, timestamp in enumerate(("01/15  09:00:00", "01/15  09:15:00")):
        row: list[object] = [timestamp]
        for variable in present:
            row.extend(values[variable][step])
        rows.append(row)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_extracts_energy_rates_density_weighted_state_and_unavailable(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "eplusout.csv"
    _write_fixture(csv_path)

    result = extract_room_results(
        csv_path,
        _bindings(),
        scenario_id="baseline_r",
        period_id="winter",
        expected_variables=VARIABLES,
        minutes_per_step=15,
        capture_occupancy=True,
        key_to_zone={"Ideal A": "Zone A", "Ideal B": "Zone B"},
    )

    whole = result.whole_building
    assert whole.person_hours == pytest.approx(2.5)
    assert whole.occupant_peak == pytest.approx(5.0)
    assert whole.occupant_peak_time == "01/15  09:00:00"
    assert whole.occupant_density_peak_per_m2 == pytest.approx(5.0 / 150.0)
    assert whole.people_sensible_kwh == pytest.approx(5.0)
    assert whole.people_latent_kwh == pytest.approx(2.0)
    assert whole.people_radiant_kwh == pytest.approx(1.0)
    assert whole.heating_kwh == pytest.approx(3.0)
    assert whole.cooling_kwh == pytest.approx(2.0)
    assert whole.heating_peak_kw == pytest.approx(5.0)
    assert whole.heating_peak_time == "01/15  09:15:00"
    assert whole.cooling_peak_kw == pytest.approx(6.0)
    assert whole.cooling_peak_time == "01/15  09:15:00"
    assert whole.temperature_area_weighted_mean_c == pytest.approx(22.3333333333)
    assert whole.rh_area_weighted_mean_pct == pytest.approx(48.3333333333)
    assert whole.heating_unmet_zone_hours == pytest.approx(0.25)
    assert whole.cooling_unmet_zone_hours == pytest.approx(0.25)
    assert "Zone Ideal Loads Outdoor Air Total Heating Energy" in (
        whole.unavailable_variables
    )
    assert result.occupancy_by_space["office-1"] == pytest.approx((2.0, 4.0))
    assert result.timestamps == ("01/15  09:00:00", "01/15  09:15:00")


def test_category_and_zone_summaries_reconcile_to_whole(tmp_path: Path) -> None:
    csv_path = tmp_path / "eplusout.csv"
    _write_fixture(csv_path)
    result = extract_room_results(
        csv_path,
        _bindings(),
        scenario_id="baseline_r",
        period_id="winter",
        expected_variables=VARIABLES,
        minutes_per_step=15,
        key_to_zone={"Ideal A": "Zone A", "Ideal B": "Zone B"},
    )

    assert {row.category for row in result.categories} == {
        "office",
        "terminal_hall",
    }
    for field in (
        "floor_area_m2",
        "design_people",
        "person_hours",
        "people_sensible_kwh",
        "people_latent_kwh",
        "people_radiant_kwh",
        "heating_kwh",
        "cooling_kwh",
        "heating_unmet_zone_hours",
        "cooling_unmet_zone_hours",
    ):
        assert sum(float(getattr(row, field) or 0.0) for row in result.categories) == pytest.approx(
            float(getattr(result.whole_building, field) or 0.0)
        )
    assert len(result.zones) == 2


def test_mapping_fails_closed_for_duplicate_or_unmapped_zone(tmp_path: Path) -> None:
    duplicate = _bindings() + (
        SpaceResultBinding("hall-2", "Zone B", "terminal_hall", 40.0, 5.0),
    )
    with pytest.raises(ValueError, match="result_zone_identity_duplicate"):
        validate_bindings(duplicate)

    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(
        "Date/Time,UNKNOWN:Zone People Occupant Count [](TimeStep)\n"
        "01/15  09:00:00,1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="result_header_zone_unmapped:UNKNOWN"):
        extract_room_results(
            csv_path,
            _bindings(),
            scenario_id="bad",
            period_id="winter",
            expected_variables=("Zone People Occupant Count",),
        )


def test_ideal_loads_equipment_mapping_follows_explicit_idf_relations(
    tmp_path: Path,
) -> None:
    idf = tmp_path / "mapping.idf"
    idf.write_text(
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

    assert ideal_loads_key_to_zone(idf) == {
        "Ideal A": "Zone A",
        "Ideal B": "Zone B",
    }


def test_hourly_columns_skip_all_blank_timestep_rows_but_not_partial_rows(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "mixed.csv"
    csv_path.write_text(
        "Date/Time,ZONE A:Zone People Occupant Count [](Hourly),"
        "ZONE B:Zone People Occupant Count [](Hourly)\n"
        "01/01  00:15:00\n"
        "01/01  01:00:00,2,3\n",
        encoding="utf-8",
    )
    result = extract_room_results(
        csv_path,
        _bindings(),
        scenario_id="annual",
        period_id="annual",
        expected_variables=("Zone People Occupant Count",),
        minutes_per_step=60,
    )
    assert result.timestamps == ("01/01  01:00:00",)
    assert result.whole_building.person_hours == pytest.approx(5.0)

    csv_path.write_text(
        "Date/Time,ZONE A:Zone People Occupant Count [](Hourly),"
        "ZONE B:Zone People Occupant Count [](Hourly)\n"
        "01/01  01:00:00,2,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="result_row_partial_reporting"):
        extract_room_results(
            csv_path,
            _bindings(),
            scenario_id="annual",
            period_id="annual",
            expected_variables=("Zone People Occupant Count",),
            minutes_per_step=60,
        )


def test_run_manifest_hashes_inputs_and_guards_derived_root(tmp_path: Path) -> None:
    derived = tmp_path / "derived"
    inputs = derived / "inputs"
    outputs = derived / "runs" / "winter"
    inputs.mkdir(parents=True)
    outputs.mkdir(parents=True)
    executable = inputs / "energyplus"
    idf = inputs / "case.idf"
    idd = inputs / "Energy+.idd"
    weather = inputs / "weather.epw"
    schedule = inputs / "schedule.csv"
    source = inputs / "source.osm"
    for path, payload in (
        (executable, b"runtime"),
        (idf, b"idf"),
        (idd, b"idd"),
        (weather, b"weather"),
        (schedule, b"schedule"),
        (source, b"source"),
    ):
        path.write_bytes(payload)
    for name, payload in (
        ("eplusout.csv", b"Date/Time,value\n01/15  00:15:00,1\n"),
        ("eplusout.err", b"EnergyPlus Completed Successfully\n"),
        ("eplusout.rdd", b"Program Version,EnergyPlus\n"),
    ):
        (outputs / name).write_bytes(payload)
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    run = SimulationRun(
        executable=executable,
        runtime_version="EnergyPlus 23.1",
        runtime_sha256=sha(executable),
        idf_path=idf,
        idf_sha256=sha(idf),
        idd_sha256=sha(idd),
        weather_sha256=sha(weather),
        output_directory=outputs,
        return_code=0,
        timed_out=False,
        elapsed_seconds=1.25,
        severe_count=0,
        fatal_count=0,
        csv_available=True,
        rdd_available=True,
        err_available=True,
    )

    manifest_path = build_run_manifest(
        run,
        scenario_id="baseline_r",
        period_id="winter",
        source_osm_path=source,
        schedule_path=schedule,
        idd_path=idd,
        weather_path=weather,
        derived_root=derived,
        minutes_per_output_step=15.0,
        expected_variables=("Zone People Occupant Count",),
    )
    identity = expected_run_identity(
        scenario_id="baseline_r",
        period_id="winter",
        executable_path=executable,
        idd_path=idd,
        weather_path=weather,
        source_osm_path=source,
        prepared_idf_path=idf,
        schedule_path=schedule,
        minutes_per_output_step=15.0,
        expected_variables=("Zone People Occupant Count",),
    )
    payload = validate_run_manifest(manifest_path, expected_identity=identity)
    assert payload["schema_version"] == "idfrepair.room-aware-run.v2"
    assert payload["status"] == "PASS"
    assert payload["source_osm_sha256"] != payload["schedule_sha256"]
    assert payload["runtime_sha256"] == sha(executable)
    assert payload["result_files"]["eplusout.csv"]["sha256"] == sha(
        outputs / "eplusout.csv"
    )

    (outputs / "eplusout.csv").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="result_manifest_file_(size|hash)_mismatch"):
        validate_run_manifest(manifest_path, expected_identity=identity)
    (outputs / "eplusout.csv").write_bytes(
        b"Date/Time,value\n01/15  00:15:00,1\n"
    )
    stale_identity = {**identity, "weather_sha256": "0" * 64}
    with pytest.raises(ValueError, match="result_manifest_input_identity_mismatch"):
        validate_run_manifest(manifest_path, expected_identity=stale_identity)

    with pytest.raises(ValueError, match="result_path_outside_derived_root"):
        build_run_manifest(
            run,
            scenario_id="baseline_r",
            period_id="winter",
            source_osm_path=source,
            schedule_path=tmp_path / "outside.csv",
            idd_path=idd,
            weather_path=weather,
            derived_root=derived,
            minutes_per_output_step=15.0,
            expected_variables=("Zone People Occupant Count",),
        )


def test_legacy_run_manifest_migrates_only_when_every_recorded_hash_matches(
    tmp_path: Path,
) -> None:
    output = tmp_path / "run"
    output.mkdir()
    paths = {}
    for name in ("energyplus", "Energy+.idd", "weather.epw", "source.osm", "case.idf", "schedule.csv"):
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        paths[name] = path
    for name in ("eplusout.csv", "eplusout.err", "eplusout.rdd"):
        (output / name).write_text(name, encoding="utf-8")
    identity = expected_run_identity(
        scenario_id="baseline_r",
        period_id="winter",
        executable_path=paths["energyplus"],
        idd_path=paths["Energy+.idd"],
        weather_path=paths["weather.epw"],
        source_osm_path=paths["source.osm"],
        prepared_idf_path=paths["case.idf"],
        schedule_path=paths["schedule.csv"],
        minutes_per_output_step=15.0,
        expected_variables=("Zone People Occupant Count",),
    )
    legacy = {
        "schema_version": "idfrepair.room-aware-run.v1",
        "scenario_id": "baseline_r",
        "period_id": "winter",
        "runtime_sha256": identity["runtime_sha256"],
        "idd_sha256": identity["idd_sha256"],
        "weather_sha256": identity["weather_sha256"],
        "source_osm_sha256": identity["source_osm_sha256"],
        "derived_idf_sha256": identity["prepared_idf_sha256"],
        "schedule_sha256": identity["schedule_sha256"],
        "status": "PASS",
        "return_code": 0,
        "timed_out": False,
        "severe_count": 0,
        "fatal_count": 0,
        "csv_available": True,
        "rdd_available": True,
        "err_available": True,
    }
    manifest = output / "run_manifest.json"
    manifest.write_text(json.dumps(legacy), encoding="utf-8")
    migrated = migrate_v1_run_manifest(manifest, expected_identity=identity)
    assert migrated["schema_version"] == "idfrepair.room-aware-run.v2"
    assert migrated["migration"]["from_schema"].endswith("v1")

    manifest.write_text(json.dumps({**legacy, "weather_sha256": "bad"}), encoding="utf-8")
    with pytest.raises(ValueError, match="legacy_identity_mismatch:weather_sha256"):
        migrate_v1_run_manifest(manifest, expected_identity=identity)


def test_prepare_annual_idf_is_full_year_and_source_immutable(tmp_path: Path) -> None:
    source = tmp_path / "source.idf"
    source.write_text(
        "Version,23.1;\n"
        "Timestep,6;\n"
        "SimulationControl,Yes,No,No,No,Yes,,;\n"
        "RunPeriod,Annual,2,3,2006,4,5,2006,Sunday;\n"
        "Output:Variable,*,Zone Air Temperature,Timestep;\n",
        encoding="utf-8",
    )
    before = source.read_bytes()
    destination = tmp_path / "derived" / "annual.idf"

    prepare_annual_idf(
        source,
        parse_idd(PERIOD_IDD),
        destination,
        output_requests=(
            OutputRequest(
                "Zone People Occupant Count", "occupancy", frequency="Hourly"
            ),
        ),
    )

    assert source.read_bytes() == before
    document = parse_idf(destination.read_text(encoding="utf-8"))
    assert document.find_objects("Timestep")[0].fields[0].value == "4"
    period = document.find_objects("RunPeriod")[0]
    assert [period.fields[index].value for index in (1, 2, 4, 5)] == [
        "1",
        "1",
        "12",
        "31",
    ]
    outputs = document.find_objects("Output:Variable")
    assert len(outputs) == 1
    output = outputs[0]
    assert output.fields[1].value == "Zone People Occupant Count"
    assert output.fields[2].value == "Hourly"


def test_controlled_day_clears_year_so_requested_weekday_is_authoritative(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.idf"
    source.write_text(
        "Version,23.1;\n"
        "Timestep,6;\n"
        "SimulationControl,Yes,No,No,No,Yes,,;\n"
        "RunPeriod,Annual,1,1,2006,12,31,2006,Sunday;\n",
        encoding="utf-8",
    )
    destination = tmp_path / "derived" / "winter.idf"

    prepare_controlled_day_idf(
        source,
        parse_idd(PERIOD_IDD),
        destination,
        output_requests=(),
        month=1,
        day=15,
        day_of_week="Wednesday",
    )

    period = parse_idf(destination.read_text(encoding="utf-8")).find_objects(
        "RunPeriod"
    )[0]
    assert [period.fields[index].value for index in (1, 2, 4, 5, 7)] == [
        "1",
        "15",
        "1",
        "15",
        "Wednesday",
    ]
    assert period.fields[3].value == ""
    assert period.fields[6].value == ""
