from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def test_weather_matrix_cli_can_run_directly_from_repo() -> None:
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts/airport_abm/prepare_weather_matrix.py"),
            "--help",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--derivative-root" in result.stdout


RUN_IDD = r"""!IDD_Version 23.1.0
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


def test_dictionary_discovery_and_contract_reject_missing_outputs() -> None:
    from idfrepair.analysis.airport_abm.energyplus_coupling import (
        OutputContractError,
        discover_dictionary,
        validate_dictionary,
    )

    rdd = """
Output:Variable,*,Space People Occupant Count,hourly; !- Zone Average []
Output:Variable,*,Air System Fan Electricity Energy,hourly; !- HVAC Sum [J]
Output:Variable,*,Air System Outdoor Air Mass Flow Rate,hourly; !- HVAC Average [kg/s]
"""
    mdd = """
Output:Meter,Electricity:Facility,hourly; !- [J]
Output:Meter,Fans:Electricity,hourly; !- [J]
"""
    discovered = discover_dictionary(rdd, mdd)

    assert discovered.variables["Space People Occupant Count"] == ""
    assert discovered.variables["Air System Fan Electricity Energy"] == "J"
    assert discovered.meters["Electricity:Facility"] == "J"
    validate_dictionary(
        discovered,
        required_variables={"Space People Occupant Count", "Air System Fan Electricity Energy"},
        required_meters={"Electricity:Facility"},
    )
    with pytest.raises(OutputContractError, match="Pump Electricity Energy"):
        validate_dictionary(
            discovered,
            required_variables={"Pump Electricity Energy"},
            required_meters=set(),
        )


def _make_sqlite(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        create table Time(
          TimeIndex integer primary key,
          Year integer,
          Month integer,
          Day integer,
          Hour integer,
          Minute integer,
          Dst integer,
          Interval integer,
          IntervalType integer,
          SimulationDays integer,
          DayType text,
          EnvironmentPeriodIndex integer,
          WarmupFlag integer
        );
        create table ReportDataDictionary(
          ReportDataDictionaryIndex integer primary key,
          IsMeter integer,
          Type text,
          IndexGroup text,
          TimestepType text,
          KeyValue text,
          Name text,
          ReportingFrequency text,
          ScheduleName text,
          Units text
        );
        create table ReportData(
          ReportDataIndex integer primary key,
          TimeIndex integer,
          ReportDataDictionaryIndex integer,
          Value real
        );
        create table EnvironmentPeriods(
          EnvironmentPeriodIndex integer primary key,
          SimulationIndex integer,
          EnvironmentName text,
          EnvironmentType integer
        );
        """
    )
    connection.executemany(
        "insert into EnvironmentPeriods values (?,?,?,?)",
        [(1, 1, "SUMMER-DESIGN", 1), (2, 1, "WINTER-DESIGN", 1)],
    )
    connection.executemany(
        "insert into Time values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, 2026, 7, 21, 1, 15, 0, 15, 1, 1, "SummerDesignDay", 1, 0),
            (2, 2026, 7, 21, 1, 30, 0, 15, 1, 1, "SummerDesignDay", 1, 0),
            (3, 2026, 7, 21, 1, 45, 0, 15, 1, 1, "SummerDesignDay", 1, 1),
        ],
    )
    dictionary = [
        (1, 1, "Sum", "Facility", "HVAC System", "", "Electricity:Facility", "Zone Timestep", "", "J"),
        (2, 1, "Sum", "Facility", "HVAC System", "", "Fans:Electricity", "Zone Timestep", "", "J"),
        (3, 1, "Sum", "Facility", "HVAC System", "", "Pumps:Electricity", "Zone Timestep", "", "J"),
        (4, 1, "Sum", "Facility", "HVAC System", "", "DistrictCooling:Facility", "Zone Timestep", "", "J"),
        (5, 1, "Sum", "Facility", "HVAC System", "", "DistrictHeating:Facility", "Zone Timestep", "", "J"),
        (6, 0, "Average", "System", "HVAC System", "", "Facility Total HVAC Electricity Demand Rate", "Zone Timestep", "", "W"),
        (7, 0, "Sum", "System", "HVAC System", "C1-VAV", "Air System Fan Electricity Energy", "Zone Timestep", "", "J"),
        (8, 0, "Average", "System", "HVAC System", "C1-VAV", "Air System Outdoor Air Mass Flow Rate", "Zone Timestep", "", "kg/s"),
        (9, 0, "Sum", "Zone", "Zone", "", "Facility Cooling Setpoint Not Met While Occupied Time", "Zone Timestep", "", "hr"),
    ]
    connection.executemany(
        "insert into ReportDataDictionary values (?,?,?,?,?,?,?,?,?,?)",
        dictionary,
    )
    values = {
        1: (3.6e6, 7.2e6, 99e6),
        2: (0.36e6, 0.72e6, 99e6),
        3: (0.18e6, 0.36e6, 99e6),
        4: (1.8e6, 3.6e6, 99e6),
        5: (0.0, 0.9e6, 99e6),
        6: (10_000.0, 12_000.0, 99_000.0),
        7: (0.2e6, 0.4e6, 99e6),
        8: (2.0, 3.0, 99.0),
        9: (0.0, 0.25, 99.0),
    }
    row = 1
    for dictionary_index, series in values.items():
        for time_index, value in enumerate(series, start=1):
            connection.execute(
                "insert into ReportData values (?,?,?,?)",
                (row, time_index, dictionary_index, value),
            )
            row += 1
    connection.commit()
    connection.close()
    return path


def test_sqlite_extraction_excludes_warmup_and_keeps_airloop_keys(tmp_path: Path) -> None:
    from idfrepair.analysis.airport_abm.energyplus_coupling import (
        extract_series,
        list_environment_periods,
        summarize_energyplus,
    )

    sql = _make_sqlite(tmp_path / "fixture.sql")
    fan = extract_series(sql, "Air System Fan Electricity Energy")

    assert [record.key for record in fan] == ["C1-VAV", "C1-VAV"]
    assert [record.value for record in fan] == [0.2e6, 0.4e6]
    assert list_environment_periods(sql) == {
        1: "SUMMER-DESIGN",
        2: "WINTER-DESIGN",
    }
    summary = summarize_energyplus(sql, environment_period_index=1)
    assert summary["facility_electricity_kwh"] == pytest.approx(3.0)
    assert summary["fan_electricity_kwh"] == pytest.approx(0.3)
    assert summary["pump_electricity_kwh"] == pytest.approx(0.15)
    assert summary["district_cooling_kwh_boundary"] == pytest.approx(1.5)
    assert summary["district_heating_kwh_boundary"] == pytest.approx(0.25)
    assert summary["peak_hvac_electric_kw"] == pytest.approx(12.0)
    assert summary["cooling_unmet_occupied_hours"] == pytest.approx(0.25)
    assert summary["air_loops"]["C1-VAV"]["fan_electricity_kwh"] == pytest.approx(
        1 / 6
    )
    assert summary["air_loops"]["C1-VAV"]["outdoor_air_mass_flow_peak_kg_s"] == 3


def test_missing_required_sql_output_fails_closed(tmp_path: Path) -> None:
    from idfrepair.analysis.airport_abm.energyplus_coupling import (
        OutputContractError,
        extract_series,
    )

    sql = _make_sqlite(tmp_path / "fixture.sql")
    with pytest.raises(OutputContractError, match="not found"):
        extract_series(sql, "Zone Air Temperature")


def test_viewer_energy_extraction_requires_complete_96_step_zone_bijection(
    tmp_path: Path,
) -> None:
    from idfrepair.analysis.airport_abm.energyplus_coupling import (
        extract_viewer_energy_by_space,
    )
    from idfrepair.analysis.airport_abm.source import SourceSpace

    sql = tmp_path / "viewer.sql"
    connection = sqlite3.connect(sql)
    connection.executescript(
        """
        create table Time(TimeIndex integer primary key, Year integer, Month integer,
          Day integer, Hour integer, Minute integer, Dst integer, Interval integer,
          IntervalType integer, SimulationDays integer, DayType text,
          EnvironmentPeriodIndex integer, WarmupFlag integer);
        create table ReportDataDictionary(ReportDataDictionaryIndex integer primary key,
          IsMeter integer, Type text, IndexGroup text, TimestepType text, KeyValue text,
          Name text, ReportingFrequency text, ScheduleName text, Units text);
        create table ReportData(ReportDataIndex integer primary key, TimeIndex integer,
          ReportDataDictionaryIndex integer, Value real);
        """
    )
    for index in range(1, 97):
        minute_of_day = index * 15
        hour = min(24, (minute_of_day - 1) // 60 + 1)
        minute = minute_of_day - (hour - 1) * 60
        connection.execute(
            "insert into Time values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (index, 2026, 4, 15, hour, minute, 0, 15, 1, 1, "Wednesday", 3, 0),
        )
    variables = (
        "Zone Air System Sensible Heating Energy",
        "Zone Air System Sensible Cooling Energy",
    )
    dictionary_index = 1
    report_index = 1
    for variable_index, variable in enumerate(variables, start=1):
        for zone in ("ZONE-A", "ZONE-B"):
            connection.execute(
                "insert into ReportDataDictionary values (?,?,?,?,?,?,?,?,?,?)",
                (dictionary_index, 0, "Sum", "Zone", "Zone", zone, variable,
                 "Zone Timestep", "", "J"),
            )
            for time_index in range(1, 97):
                connection.execute(
                    "insert into ReportData values (?,?,?,?)",
                    (report_index, time_index, dictionary_index,
                     variable_index * time_index * 900_000.0),
                )
                report_index += 1
            dictionary_index += 1
    connection.commit()
    connection.close()

    def space(name: str, zone: str) -> SourceSpace:
        return SourceSpace(name, zone, "r", "central_hall", "central_hall", "Hall",
                           10, 1, 10, "VAV", None, None)

    output = extract_viewer_energy_by_space(
        sql,
        spaces=(space("a", "zone-a"), space("b", "zone-b")),
        environment_period_index=3,
    )
    assert output["a"]["heating_kw"][0] == pytest.approx(1.0)
    assert output["a"]["cooling_kw"][-1] == pytest.approx(192.0)

    with pytest.raises(Exception, match="zone coverage"):
        extract_viewer_energy_by_space(
            sql,
            spaces=(space("a", "zone-a"),),
            environment_period_index=3,
        )


def test_energy_and_interval_peak_are_grouped_by_output_key(tmp_path: Path) -> None:
    from idfrepair.analysis.airport_abm.energyplus_coupling import (
        aggregate_output_statistics,
        energy_kwh_by_key,
        interval_peak_kw_by_key,
        value_statistics_by_key,
    )

    sql = _make_sqlite(tmp_path / "fixture.sql")

    assert energy_kwh_by_key(
        sql,
        "Air System Fan Electricity Energy",
        environment_period_index=1,
    ) == pytest.approx({"C1-VAV": 1 / 6})
    assert interval_peak_kw_by_key(
        sql,
        "Air System Fan Electricity Energy",
        environment_period_index=1,
    ) == pytest.approx({"C1-VAV": 0.4e6 / (15 * 60 * 1000)})
    assert value_statistics_by_key(
        sql,
        "Air System Outdoor Air Mass Flow Rate",
        environment_period_index=1,
    ) == {
        "C1-VAV": pytest.approx(
            {"minimum": 2.0, "mean": 2.5, "maximum": 3.0}
        )
    }
    aggregated = aggregate_output_statistics(
        sql,
        {
            "Air System Fan Electricity Energy",
            "Air System Outdoor Air Mass Flow Rate",
        },
        environment_period_index=1,
    )
    fan = aggregated["Air System Fan Electricity Energy"]["C1-VAV"]
    assert fan["count"] == 2
    assert fan["units"] == "J"
    assert fan["sum"] == pytest.approx(0.6e6)
    assert fan["interval_peak_kw"] == pytest.approx(0.4e6 / (15 * 60 * 1000))
    outdoor_air = aggregated["Air System Outdoor Air Mass Flow Rate"]["C1-VAV"]
    assert outdoor_air["units"] == "kg/s"
    assert {key: value for key, value in outdoor_air.items() if key != "units"} == pytest.approx(
        {
            "count": 2,
            "sum": 5.0,
            "minimum": 2.0,
            "mean": 2.5,
            "maximum": 3.0,
            "interval_peak_kw": 0.0,
        }
    )


def test_static_idf_instrumentation_is_source_immutable_and_deduplicated(
    tmp_path: Path,
) -> None:
    from idfrepair.analysis.airport_abm.energyplus_coupling import instrument_idf

    source = tmp_path / "source.idf"
    source.write_text(
        "Version,23.1;\n"
        "Output:Variable,*,Space People Occupant Count,Hourly;\n"
        "Output:Meter,Electricity:Facility,Hourly;\n",
        encoding="utf-8",
    )
    before = source.read_bytes()
    output = tmp_path / "instrumented.idf"

    instrument_idf(
        source,
        output,
        variables={"Space People Occupant Count", "Zone Air Temperature"},
        meters={"Electricity:Facility", "Fans:Electricity"},
    )

    assert source.read_bytes() == before
    text = output.read_text(encoding="utf-8")
    assert text.count("Space People Occupant Count") == 2
    assert text.count("Electricity:Facility") == 2
    assert "Output:Variable,*,Space People Occupant Count,Timestep;" in text
    assert "Output:Meter,Electricity:Facility,Timestep;" in text
    assert "Output:Variable,*,Zone Air Temperature,Timestep;" in text
    assert "Output:Meter,Fans:Electricity,Timestep;" in text


def test_weather_run_preparation_is_source_immutable_and_replaces_output_contract(
    tmp_path: Path,
) -> None:
    from idfrepair.analysis.airport_abm.energyplus_coupling import (
        prepare_weather_run_idf,
    )
    from idfrepair.io.idf import parse_idf
    from idfrepair.knowledge.idd import parse_idd

    source = tmp_path / "source.idf"
    source.write_text(
        "Version,23.1;\n"
        "Timestep,6;\n"
        "SimulationControl,Yes,Yes,Yes,Yes,Yes,No,;\n"
        "RunPeriod,Annual,1,1,2006,12,31,2006,Sunday;\n"
        "Output:Variable,*,Old Variable,Timestep;\n"
        "Output:Meter,Old Meter,Timestep;\n",
        encoding="utf-8",
    )
    before = source.read_bytes()
    output = tmp_path / "derived" / "shoulder.idf"

    prepare_weather_run_idf(
        source,
        output,
        idd=parse_idd(RUN_IDD),
        begin_month=4,
        begin_day=15,
        begin_year=2006,
        end_month=4,
        end_day=15,
        end_year=2006,
        day_of_week="Saturday",
        variables={"Zone Air Temperature", "Air System Fan Electricity Energy"},
        meters={"Electricity:Facility"},
        reporting_frequency="Hourly",
    )

    assert source.read_bytes() == before
    document = parse_idf(output.read_text(encoding="utf-8"))
    assert document.find_objects("Timestep")[0].fields[0].value == "4"
    controls = document.find_objects("SimulationControl")[0]
    assert [field.value for field in controls.fields[:5]] == [
        "Yes",
        "Yes",
        "Yes",
        "No",
        "Yes",
    ]
    period = document.find_objects("RunPeriod")[0]
    assert [period.fields[index].value for index in (1, 2, 3, 4, 5, 6, 7)] == [
        "4",
        "15",
        "2006",
        "4",
        "15",
        "2006",
        "Saturday",
    ]
    variables = {
        (row.fields[1].value, row.fields[2].value)
        for row in document.find_objects("Output:Variable")
    }
    meters = {
        (row.fields[0].value, row.fields[1].value)
        for row in document.find_objects("Output:Meter")
    }
    assert variables == {
        ("Air System Fan Electricity Energy", "Hourly"),
        ("Zone Air Temperature", "Hourly"),
    }
    assert meters == {("Electricity:Facility", "Hourly")}
