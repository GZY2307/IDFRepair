from __future__ import annotations

from pathlib import Path

from idfrepair.analysis.airport_abm.energyplus_coupling import (
    prepare_design_day_run_idf,
    prepare_weather_run_idf,
)
from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd


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
  A3, \field Use Weather File Holidays and Special Days;
"""


def test_fixed_operation_weather_idf_disables_all_sizing_calculations(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.idf"
    source.write_text(
        "Version,23.1;\n"
        "Timestep,6;\n"
        "SimulationControl,Yes,Yes,Yes,Yes,Yes;\n"
        "RunPeriod,Annual,1,1,2006,12,31,2006,Sunday;\n",
        encoding="utf-8",
    )
    output = tmp_path / "fixed-operation.idf"

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
        variables={"Zone Air Temperature"},
        meters={"Electricity:Facility"},
        fixed_sizing_operation=True,
    )

    controls = parse_idf(output.read_text(encoding="utf-8")).find_objects(
        "SimulationControl"
    )[0]
    assert [field.value for field in controls.fields[:5]] == [
        "No",
        "No",
        "No",
        "No",
        "Yes",
    ]


def test_fixed_operation_design_day_idf_runs_periods_without_resizing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.idf"
    source.write_text(
        "Version,23.1;\n"
        "Timestep,6;\n"
        "SimulationControl,Yes,Yes,Yes,Yes,Yes;\n"
        "SizingPeriod:DesignDay,Summer;\n"
        "Output:Variable,*,Old Variable,Timestep;\n",
        encoding="utf-8",
    )
    before = source.read_bytes()
    output = tmp_path / "fixed-design-days.idf"

    prepare_design_day_run_idf(
        source,
        output,
        idd=parse_idd(RUN_IDD),
        variables={"Zone Air Temperature"},
        meters={"Electricity:Facility"},
        fixed_sizing_operation=True,
    )

    assert source.read_bytes() == before
    document = parse_idf(output.read_text(encoding="utf-8"))
    controls = document.find_objects("SimulationControl")[0]
    assert [field.value for field in controls.fields[:5]] == [
        "No",
        "No",
        "No",
        "Yes",
        "No",
    ]
    assert document.find_objects("Timestep")[0].fields[0].value == "4"
    variables = document.find_objects("Output:Variable")
    meters = document.find_objects("Output:Meter")
    assert [(row.fields[1].value, row.fields[2].value) for row in variables] == [
        ("Zone Air Temperature", "Timestep")
    ]
    assert [(row.fields[0].value, row.fields[1].value) for row in meters] == [
        ("Electricity:Facility", "Timestep")
    ]
