#!/usr/bin/env python3
"""Extract validated Airport ABM V3 EnergyPlus outputs into compact tables."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.energyplus_coupling import (  # noqa: E402
    OutputContractError,
    aggregate_output_statistics,
    energy_kwh_by_key,
    interval_peak_kw_by_key,
    list_environment_periods,
    summarize_energyplus,
    value_statistics_by_key,
)


SEVERE = re.compile(r"\*\*\s*Severe\s*\*\*", re.IGNORECASE)
FATAL = re.compile(r"\*\*\s*Fatal\s*\*\*", re.IGNORECASE)
COMPACT_ANNUAL_OUTPUTS = frozenset(
    {
        "Electricity:Facility",
        "Fans:Electricity",
        "Pumps:Electricity",
        "DistrictCooling:Facility",
        "DistrictHeating:Facility",
        "Facility Total HVAC Electricity Demand Rate",
        "Facility Cooling Setpoint Not Met While Occupied Time",
        "Facility Heating Setpoint Not Met While Occupied Time",
        "Air System Fan Electricity Energy",
        "Air System Outdoor Air Mass Flow Rate",
        "Air System Total Heating Energy",
        "Air System Total Cooling Energy",
    }
)


def successful_run(path: Path) -> tuple[bool, int, int, int]:
    error_path = path.parent / "eplusout.err"
    if not error_path.is_file():
        return False, 0, 0, 0
    text = error_path.read_text(encoding="utf-8", errors="replace")
    severe = len(SEVERE.findall(text))
    fatal = len(FATAL.findall(text))
    warning_match = re.search(r"Completed Successfully--\s*(\d+) Warning", text)
    warnings = int(warning_match.group(1)) if warning_match else 0
    return "EnergyPlus Completed Successfully" in text and severe == 0 and fatal == 0, warnings, severe, fatal


def run_identity(root: Path, sql: Path) -> tuple[str, int | None, str, int]:
    parts = sql.relative_to(root).parts
    parent = sql.parent.name
    if parts[0] == "static_source":
        scenario = "STATIC_SOURCE"
        seed = None
    elif parts[0] in {"seasonal", "annual"} and len(parts) >= 4:
        scenario = parts[1]
        seed_token = parts[2]
        seed = int(seed_token.removeprefix("seed-")) if seed_token.startswith("seed-") else None
    else:
        raise ValueError(f"unrecognized energy output path: {sql}")
    if parent.startswith("design-days"):
        kind = "design_days"
    elif parent == "shoulder":
        kind = "shoulder"
    elif parent == "annual":
        kind = "annual"
    else:
        raise ValueError(f"unrecognized run directory: {sql.parent}")
    rank = {
        "design-days-v2": 4,
        "design-days": 3,
        "design-days-02": 2,
        "shoulder": 1,
        "annual": 1,
    }.get(parent, 0)
    return scenario, seed, kind, rank


def select_runs(root: Path) -> list[tuple[str, int | None, str, Path, int]]:
    selected: dict[tuple[str, int | None, str], tuple[Path, int]] = {}
    for sql in root.rglob("eplusout.sql"):
        try:
            scenario, seed, kind, rank = run_identity(root, sql)
        except ValueError:
            continue
        passed, _, _, _ = successful_run(sql)
        if not passed:
            continue
        key = (scenario, seed, kind)
        if key not in selected or rank > selected[key][1]:
            selected[key] = (sql, rank)
    return [
        (scenario, seed, kind, selected[(scenario, seed, kind)][0], selected[(scenario, seed, kind)][1])
        for scenario, seed, kind in sorted(selected, key=lambda item: (item[2], item[0], item[1] or 0))
    ]


def period_id(kind: str, environment_name: str) -> str:
    lowered = environment_name.casefold()
    if "summer" in lowered:
        return "summer"
    if "winter" in lowered:
        return "winter"
    return kind


def public_row(
    *,
    scenario: str,
    seed: int | None,
    run_kind: str,
    period: str,
    scope: str,
    group: str,
    metric: str,
    value: float,
    unit: str,
) -> dict[str, object]:
    return {
        "scenario_id": scenario,
        "seed": "" if seed is None else seed,
        "run_kind": run_kind,
        "period_id": period,
        "scope": scope,
        "group": group,
        "metric": metric,
        "value": value,
        "unit": unit,
    }


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ("scenario_id", "seed", "run_kind", "period_id", "scope", "group", "metric", "value", "unit")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def required_statistics(
    statistics: dict[str, dict[str, dict[str, float | int | str]]],
    name: str,
    *,
    units: str | None = None,
) -> dict[str, dict[str, float | int | str]]:
    rows = statistics.get(name)
    if not rows:
        raise OutputContractError(f"required EnergyPlus output missing: {name}")
    if units is not None and any(row["units"] != units for row in rows.values()):
        raise OutputContractError(f"unexpected EnergyPlus output unit: {name}")
    return rows


def append_compact_annual_rows(
    public: list[dict[str, object]],
    *,
    scenario: str,
    seed: int | None,
    period: str,
    statistics: dict[str, dict[str, dict[str, float | int | str]]],
) -> int:
    def total(name: str, units: str | None = None) -> float:
        return sum(
            float(row["sum"])
            for row in required_statistics(statistics, name, units=units).values()
        )

    def maximum(name: str, units: str | None = None) -> float:
        return max(
            float(row["maximum"])
            for row in required_statistics(statistics, name, units=units).values()
        )

    building = {
        "facility_electricity_kwh": ("kWh", total("Electricity:Facility", "J") / 3_600_000.0),
        "fan_electricity_kwh": ("kWh", total("Fans:Electricity", "J") / 3_600_000.0),
        "pump_electricity_kwh": ("kWh", total("Pumps:Electricity", "J") / 3_600_000.0),
        "district_cooling_kwh_boundary": ("kWh", total("DistrictCooling:Facility", "J") / 3_600_000.0),
        "district_heating_kwh_boundary": ("kWh", total("DistrictHeating:Facility", "J") / 3_600_000.0),
        "peak_hvac_electric_kw": ("kW", maximum("Facility Total HVAC Electricity Demand Rate", "W") / 1000.0),
        "cooling_unmet_occupied_hours": ("h", total("Facility Cooling Setpoint Not Met While Occupied Time")),
        "heating_unmet_occupied_hours": ("h", total("Facility Heating Setpoint Not Met While Occupied Time")),
    }
    for metric, (unit, value) in building.items():
        public.append(public_row(scenario=scenario, seed=seed, run_kind="annual", period=period, scope="building", group="whole_building", metric=metric, value=value, unit=unit))

    fan = required_statistics(statistics, "Air System Fan Electricity Energy", units="J")
    outdoor_air = required_statistics(statistics, "Air System Outdoor Air Mass Flow Rate", units="kg/s")
    for loop in sorted(set(fan) | set(outdoor_air)):
        if loop not in fan or loop not in outdoor_air:
            raise OutputContractError("annual AirLoop output key sets do not match")
        public.extend(
            [
                public_row(scenario=scenario, seed=seed, run_kind="annual", period=period, scope="air_loop", group=loop, metric="fan_electricity_kwh", value=float(fan[loop]["sum"]) / 3_600_000.0, unit="kWh"),
                public_row(scenario=scenario, seed=seed, run_kind="annual", period=period, scope="air_loop", group=loop, metric="outdoor_air_mass_flow_peak_kg_s", value=float(outdoor_air[loop]["maximum"]), unit="kg/s"),
                public_row(scenario=scenario, seed=seed, run_kind="annual", period=period, scope="air_loop", group=loop, metric="outdoor_air_mass_flow_mean_kg_s", value=float(outdoor_air[loop]["mean"]), unit="kg/s"),
            ]
        )
    for name, metric in (
        ("Air System Total Heating Energy", "total_heating_kwh"),
        ("Air System Total Cooling Energy", "total_cooling_kwh"),
    ):
        values = required_statistics(statistics, name, units="J")
        for loop in sorted(values):
            public.append(public_row(scenario=scenario, seed=seed, run_kind="annual", period=period, scope="air_loop", group=loop, metric=metric, value=float(values[loop]["sum"]) / 3_600_000.0, unit="kWh"))
            public.append(public_row(scenario=scenario, seed=seed, run_kind="annual", period=period, scope="air_loop", group=loop, metric=metric.replace("_kwh", "_interval_peak_kw"), value=float(values[loop]["interval_peak_kw"]), unit="kW"))
    return len(set(fan) | set(outdoor_air))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--energy-root", required=True)
    parser.add_argument("--public-output", required=True)
    parser.add_argument("--private-zone-output", required=True)
    parser.add_argument("--summary-output", required=True)
    args = parser.parse_args()
    root = Path(args.energy_root)
    public: list[dict[str, object]] = []
    private: list[dict[str, object]] = []
    run_rows: list[dict[str, object]] = []
    for scenario, seed, kind, sql, _rank in select_runs(root):
        passed, warnings, severe, fatal = successful_run(sql)
        if not passed:
            raise SystemExit(f"selected EnergyPlus run is not successful: {sql}")
        environments = list_environment_periods(sql)
        for environment_index, environment_name in environments.items():
            period = period_id(kind, environment_name)
            if kind == "annual":
                statistics = aggregate_output_statistics(
                    sql,
                    COMPACT_ANNUAL_OUTPUTS,
                    environment_period_index=environment_index,
                )
                air_loop_count = append_compact_annual_rows(
                    public,
                    scenario=scenario,
                    seed=seed,
                    period=period,
                    statistics=statistics,
                )
                run_rows.append(
                    {
                        "scenario_id": scenario,
                        "seed": seed,
                        "run_kind": kind,
                        "period_id": period,
                        "environment_name": environment_name,
                        "warning_count": warnings,
                        "severe_count": severe,
                        "fatal_count": fatal,
                        "air_loop_count": air_loop_count,
                    }
                )
                continue
            summary = summarize_energyplus(sql, environment_period_index=environment_index)
            metrics = {
                "facility_electricity_kwh": ("kWh", summary["facility_electricity_kwh"]),
                "fan_electricity_kwh": ("kWh", summary["fan_electricity_kwh"]),
                "pump_electricity_kwh": ("kWh", summary["pump_electricity_kwh"]),
                "district_cooling_kwh_boundary": ("kWh", summary["district_cooling_kwh_boundary"]),
                "district_heating_kwh_boundary": ("kWh", summary["district_heating_kwh_boundary"]),
                "peak_hvac_electric_kw": ("kW", summary["peak_hvac_electric_kw"]),
                "cooling_unmet_occupied_hours": ("h", summary["cooling_unmet_occupied_hours"]),
                "heating_unmet_occupied_hours": ("h", summary["heating_unmet_occupied_hours"]),
            }
            for metric, (unit, value) in metrics.items():
                public.append(public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope="building", group="whole_building", metric=metric, value=float(value), unit=unit))
            for loop, values in summary["air_loops"].items():
                public.extend(
                    [
                        public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope="air_loop", group=loop, metric="fan_electricity_kwh", value=float(values["fan_electricity_kwh"]), unit="kWh"),
                        public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope="air_loop", group=loop, metric="outdoor_air_mass_flow_peak_kg_s", value=float(values["outdoor_air_mass_flow_peak_kg_s"]), unit="kg/s"),
                        public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope="air_loop", group=loop, metric="outdoor_air_mass_flow_mean_kg_s", value=float(values["outdoor_air_mass_flow_mean_kg_s"]), unit="kg/s"),
                    ]
                )
            for variable, metric in (
                ("Air System Total Heating Energy", "total_heating_kwh"),
                ("Air System Total Cooling Energy", "total_cooling_kwh"),
            ):
                try:
                    energies = energy_kwh_by_key(sql, variable, environment_period_index=environment_index)
                    peaks = interval_peak_kw_by_key(sql, variable, environment_period_index=environment_index)
                except OutputContractError:
                    continue
                for loop in sorted(energies):
                    public.append(public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope="air_loop", group=loop, metric=metric, value=energies[loop], unit="kWh"))
                    public.append(public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope="air_loop", group=loop, metric=metric.replace("_kwh", "_interval_peak_kw"), value=peaks[loop], unit="kW"))
            for variable, metric in (
                ("Zone Air System Sensible Heating Energy", "sensible_heating_kwh"),
                ("Zone Air System Sensible Cooling Energy", "sensible_cooling_kwh"),
                ("Zone People Sensible Heating Energy", "people_sensible_gain_kwh"),
                ("Zone People Latent Gain Energy", "people_latent_gain_kwh"),
                ("Zone People Radiant Heating Energy", "people_radiant_gain_kwh"),
            ):
                try:
                    energies = energy_kwh_by_key(sql, variable, environment_period_index=environment_index)
                    peaks = interval_peak_kw_by_key(sql, variable, environment_period_index=environment_index)
                except OutputContractError:
                    continue
                for zone in sorted(energies):
                    private.append(public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope="thermal_zone", group=zone, metric=metric, value=energies[zone], unit="kWh"))
                    private.append(public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope="thermal_zone", group=zone, metric=metric.replace("_kwh", "_interval_peak_kw"), value=peaks[zone], unit="kW"))
            try:
                space_energy = energy_kwh_by_key(
                    sql,
                    "Space People Total Heating Energy",
                    environment_period_index=environment_index,
                )
                space_peaks = interval_peak_kw_by_key(
                    sql,
                    "Space People Total Heating Energy",
                    environment_period_index=environment_index,
                )
            except OutputContractError:
                space_energy = {}
                space_peaks = {}
            for space in sorted(space_energy):
                private.append(public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope="space", group=space, metric="people_total_heating_kwh", value=space_energy[space], unit="kWh"))
                private.append(public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope="space", group=space, metric="people_total_heating_interval_peak_kw", value=space_peaks[space], unit="kW"))
            for variable, scope, metrics, unit in (
                (
                    "Space People Occupant Count",
                    "space",
                    ("occupant_count_minimum", "occupant_count_mean", "occupant_count_maximum"),
                    "people",
                ),
                (
                    "Zone Air Temperature",
                    "thermal_zone",
                    ("air_temperature_minimum_c", "air_temperature_mean_c", "air_temperature_maximum_c"),
                    "C",
                ),
                (
                    "Zone Air Relative Humidity",
                    "thermal_zone",
                    ("relative_humidity_minimum_percent", "relative_humidity_mean_percent", "relative_humidity_maximum_percent"),
                    "%",
                ),
                (
                    "Zone Air Terminal Outdoor Air Volume Flow Rate",
                    "thermal_zone",
                    ("outdoor_air_minimum_m3_s", "outdoor_air_mean_m3_s", "outdoor_air_maximum_m3_s"),
                    "m3/s",
                ),
            ):
                try:
                    statistics = value_statistics_by_key(
                        sql,
                        variable,
                        environment_period_index=environment_index,
                    )
                except OutputContractError:
                    continue
                for group, values in statistics.items():
                    for metric, statistic in zip(metrics, ("minimum", "mean", "maximum")):
                        private.append(public_row(scenario=scenario, seed=seed, run_kind=kind, period=period, scope=scope, group=group, metric=metric, value=values[statistic], unit=unit))
            run_rows.append(
                {
                    "scenario_id": scenario,
                    "seed": seed,
                    "run_kind": kind,
                    "period_id": period,
                    "environment_name": environment_name,
                    "warning_count": warnings,
                    "severe_count": severe,
                    "fatal_count": fatal,
                    "air_loop_count": len(summary["air_loops"]),
                }
            )
    write_rows(Path(args.public_output), public)
    write_rows(Path(args.private_zone_output), private)
    Path(args.summary_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary_output).write_text(
        json.dumps(
            {
                "schema_version": "idfrepair.airport-abm-energy-summary.v3",
                "status": "PASS",
                "run_period_rows": run_rows,
                "public_result_rows": len(public),
                "private_zone_rows": len(private),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "run_periods": len(run_rows), "public_rows": len(public), "private_zone_rows": len(private)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
