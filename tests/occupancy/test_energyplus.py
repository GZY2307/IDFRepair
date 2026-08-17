"""验证 EnergyPlus output discovery、受限运行与缺失机制表达。"""

from __future__ import annotations

import csv
from pathlib import Path

from idfrepair.analysis.occupancy.energyplus import (
    discover_output_variables,
    extract_metrics,
    prepare_one_day_idf,
    render_output_requests,
    run_energyplus,
    select_output_requests,
)
from idfrepair.analysis.occupancy.models import OutputRequest, ZoneServiceMap
from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd


RDD_FIXTURE = """Program Version,EnergyPlus, Version 23.1.0
Output:Variable,*,Schedule Value,hourly; !- Zone Average []
Output:Variable,*,People Occupant Count,hourly; !- Zone Average [person]
Output:Variable,*,People Sensible Heating Energy,hourly; !- Zone Sum [J]
Output:Variable,*,Zone People Occupant Count,hourly; !- Zone Average [person]
Output:Variable,*,Zone Air System Sensible Cooling Energy,hourly; !- HVAC Sum [J]
Output:Variable,*,Zone Ideal Loads Outdoor Air Total Cooling Energy,hourly; !- HVAC Sum [J]
Output:Variable,*,Zone Mean Air Temperature,hourly; !- Zone Average [C]
Output:Variable,*,Fan Electricity Energy,hourly; !- System Sum [J]
"""

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


def test_select_output_requests_uses_only_rdd_available_names() -> None:
    """请求集合必须是实际 RDD 的子集，且包含可用 People occupant 变量。"""

    available = discover_output_variables(RDD_FIXTURE)
    requests = select_output_requests(available)

    assert all(row.variable_name in available for row in requests)
    assert "Schedule Value" in {row.variable_name for row in requests}
    assert "People Occupant Count" in {row.variable_name for row in requests}
    assert "Zone People Occupant Count" in {row.variable_name for row in requests}
    assert "Zone Air System Sensible Cooling Energy" in {
        row.variable_name for row in requests
    }
    assert "Zone Ideal Loads Outdoor Air Total Cooling Energy" in {
        row.variable_name for row in requests
    }
    assert "Pump Electricity Energy" not in {row.variable_name for row in requests}


def test_render_output_requests_is_deterministic_and_exact() -> None:
    """输出请求保留 RDD 名称，不用模糊匹配创造变量。"""

    requests = select_output_requests(discover_output_variables(RDD_FIXTURE))

    first = render_output_requests(requests)
    second = render_output_requests(requests)

    assert first == second
    assert "Output:Variable,*,People Occupant Count,Timestep;" in first
    assert "Pump Electricity Energy" not in first


def test_extract_metrics_marks_missing_mechanism_unavailable(tmp_path: Path) -> None:
    """CSV 中没有 fan/pump/OA 时返回 unavailable，而不是数值零。"""

    csv_path = tmp_path / "eplusout.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "Date/Time",
                "PASSENGERS:People Occupant Count [](TimeStep)",
                "TERMINAL HALL:Zone Mean Air Temperature [C](TimeStep)",
            ]
        )
        writer.writerow(["01/01  00:15:00", "10", "21.5"])
        writer.writerow(["01/01  00:30:00", "20", "22.0"])
    mapping = ZoneServiceMap(
        people_to_zones={"Passengers": ("Terminal Hall",)},
        zone_to_hvac={"Terminal Hall": ()},
    )

    rows = extract_metrics(
        csv_path,
        mapping,
        expected_variable_names=(
            "People Occupant Count",
            "Zone Mean Air Temperature",
            "Fan Electricity Energy",
            "Pump Electricity Energy",
            "Air System Outdoor Air Mass Flow Rate",
        ),
    )

    occupant = [row for row in rows if row.variable_name == "People Occupant Count"]
    assert [row.value for row in occupant] == [10.0, 20.0]
    assert all(row.availability == "available" for row in occupant)
    missing = [row for row in rows if row.availability == "unavailable"]
    assert {row.variable_name for row in missing} == {
        "Fan Electricity Energy",
        "Pump Electricity Energy",
        "Air System Outdoor Air Mass Flow Rate",
    }
    assert all(row.value is None for row in missing)


def test_run_energyplus_records_hashes_version_and_err_counts(tmp_path: Path) -> None:
    """受限 runner 记录 runtime/input hashes、版本、severe/fatal 与输出存在性。"""

    executable = tmp_path / "fake_energyplus.py"
    executable.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys
if '--version' in sys.argv:
    print('EnergyPlus, Version 99.1.0-test, YMD=2026.08.17 00:00')
    raise SystemExit(0)
out = pathlib.Path(sys.argv[sys.argv.index('-d') + 1])
out.mkdir(parents=True, exist_ok=True)
(out / 'eplusout.err').write_text('** Severe  ** fixture severe\\n', encoding='utf-8')
(out / 'eplusout.csv').write_text('Date/Time\\n', encoding='utf-8')
(out / 'eplusout.rdd').write_text('Output:Variable,*,People Occupant Count,hourly;\\n', encoding='utf-8')
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    idf = tmp_path / "input.idf"
    idf.write_text("Version,99.1;\n", encoding="utf-8")
    idd = tmp_path / "Energy+.idd"
    idd.write_text("!IDD_Version 99.1.0\n", encoding="utf-8")
    before = idf.read_bytes()

    run = run_energyplus(
        executable=executable,
        idf_path=idf,
        output_directory=tmp_path / "run",
        idd_path=idd,
        timeout_seconds=10,
    )

    assert idf.read_bytes() == before
    assert run.return_code == 0
    assert run.runtime_version == "EnergyPlus, Version 99.1.0-test"
    assert len(run.runtime_sha256) == 64
    assert len(run.idf_sha256) == 64
    assert len(run.idd_sha256) == 64
    assert run.severe_count == 1
    assert run.fatal_count == 0
    assert run.csv_available is True
    assert run.rdd_available is True


def test_prepare_one_day_idf_is_source_immutable_and_idd_bound(tmp_path: Path) -> None:
    """一日 smoke patch 用 IDD 字段名定位，不覆盖源 IDF，并按需追加输出。"""

    source = tmp_path / "annual.idf"
    source.write_text(
        """Version,23.1;
Timestep,6;
SimulationControl,Yes,No,No,No,Yes,,;
RunPeriod,Annual,1,1,2006,12,31,2006,Sunday;
Output:Variable,*,People Occupant Count,Timestep;
""",
        encoding="utf-8",
    )
    before = source.read_bytes()
    destination = tmp_path / "derived" / "one_day.idf"
    requests = (
        OutputRequest("People Occupant Count", "occupancy"),
        OutputRequest("Zone Mean Air Temperature", "zone_state"),
    )

    result = prepare_one_day_idf(
        source,
        parse_idd(RUN_IDD),
        destination,
        output_requests=requests,
        month=1,
        day=18,
        day_of_week="Wednesday",
        resolution_minutes=15,
    )

    assert source.read_bytes() == before
    assert result == destination
    derived = parse_idf(destination.read_text(encoding="utf-8"))
    assert derived.find_objects("Timestep")[0].fields[0].value == "4"
    run_period = derived.find_objects("RunPeriod")[0]
    assert [run_period.fields[index].value for index in (1, 2, 4, 5)] == [
        "1",
        "18",
        "1",
        "18",
    ]
    assert run_period.fields[7].value == "Wednesday"
    variables = [obj.fields[1].value for obj in derived.find_objects("Output:Variable")]
    assert variables.count("People Occupant Count") == 1
    assert variables.count("Zone Mean Air Temperature") == 1


def test_extract_metrics_accepts_energyplus_expanded_people_keys(
    tmp_path: Path,
) -> None:
    """EnergyPlus 在 SpaceList 展开后给 People key 加 Zone 前缀，仍须匹配。"""

    csv_path = tmp_path / "eplusout.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "Date/Time",
                "ZONE A PASSENGER GROUP:People Occupant Count [](TimeStep)",
            ]
        )
        writer.writerow(["01/18  00:15:00", "12.5"])
    mapping = ZoneServiceMap(
        people_to_zones={"Passenger Group": ("Zone A",)},
        zone_to_hvac={"Zone A": ()},
    )

    rows = extract_metrics(
        csv_path,
        mapping,
        expected_variable_names=("People Occupant Count",),
    )

    assert len(rows) == 1
    assert rows[0].availability == "available"
    assert rows[0].key_name == "ZONE A PASSENGER GROUP"
    assert rows[0].value == 12.5
