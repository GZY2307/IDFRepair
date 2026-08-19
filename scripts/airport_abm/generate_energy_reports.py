#!/usr/bin/env python3
"""Generate aggregate Airport ABM V3 energy tables, figures, and narrative."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.reporting import quantile  # noqa: E402


SCENARIOS = (
    "STATIC_SOURCE",
    "BASELINE_SPREAD",
    "MORNING_BANK",
    "MIDDAY_BANK",
    "EVENING_BANK",
    "DOUBLE_BANK",
)
TIMING_SCENARIOS = SCENARIOS[2:]
DISPLAY = {
    "STATIC_SOURCE": "Static source",
    "BASELINE_SPREAD": "Dynamic spread",
    "MORNING_BANK": "Morning bank",
    "MIDDAY_BANK": "Midday bank",
    "EVENING_BANK": "Evening bank",
    "DOUBLE_BANK": "Double bank",
}
PERIODS = ("summer", "winter", "shoulder")
BUILDING_METRICS = (
    "facility_electricity_kwh",
    "fan_electricity_kwh",
    "pump_electricity_kwh",
    "district_cooling_kwh_boundary",
    "district_heating_kwh_boundary",
    "peak_hvac_electric_kw",
    "cooling_unmet_occupied_hours",
    "heating_unmet_occupied_hours",
)
METRIC_LABELS = {
    "facility_electricity_kwh": "Facility electricity (kWh)",
    "fan_electricity_kwh": "Fan electricity (kWh)",
    "pump_electricity_kwh": "Pump electricity (kWh)",
    "district_cooling_kwh_boundary": "District cooling boundary (kWh)",
    "district_heating_kwh_boundary": "District heating boundary (kWh)",
    "peak_hvac_electric_kw": "Peak HVAC electricity (kW)",
    "cooling_unmet_occupied_hours": "Cooling unmet occupied hours (h)",
    "heating_unmet_occupied_hours": "Heating unmet occupied hours (h)",
    "outdoor_air_mass_flow_peak_kg_s": "Peak outdoor air (kg/s)",
    "total_cooling_interval_peak_kw": "Air-system cooling interval peak (kW)",
    "total_heating_interval_peak_kw": "Air-system heating interval peak (kW)",
}
AIR_LOOP_EFFECT_METRICS = (
    "fan_electricity_kwh",
    "outdoor_air_mass_flow_peak_kg_s",
    "total_cooling_interval_peak_kw",
    "total_heating_interval_peak_kw",
)


def load_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            value = float(raw["value"])
            if not math.isfinite(value):
                raise ValueError("energy result contains a non-finite value")
            rows.append(
                {
                    **raw,
                    "seed": int(raw["seed"]) if raw["seed"] else None,
                    "value": value,
                }
            )
    if not rows:
        raise ValueError("energy result table is empty")
    return rows


def grouped_summary(
    rows: list[dict[str, object]],
    *,
    fields: tuple[str, ...],
) -> list[dict[str, object]]:
    grouped: dict[tuple[object, ...], list[float]] = defaultdict(list)
    units: dict[tuple[object, ...], str] = {}
    for row in rows:
        identity = tuple(row[field] for field in fields)
        grouped[identity].append(float(row["value"]))
        unit = str(row["unit"])
        if identity in units and units[identity] != unit:
            raise ValueError("energy aggregation mixes units")
        units[identity] = unit
    output: list[dict[str, object]] = []
    for identity in sorted(grouped, key=repr):
        values = grouped[identity]
        record = {field: value for field, value in zip(fields, identity)}
        record.update(
            {
                "n": len(values),
                "p10": quantile(values, 0.10),
                "p50": quantile(values, 0.50),
                "p90": quantile(values, 0.90),
                "unit": units[identity],
            }
        )
        output.append(record)
    return output


def index_summary(
    rows: list[dict[str, object]],
) -> dict[tuple[object, ...], dict[str, object]]:
    return {
        (
            row["scenario_id"],
            row["run_kind"],
            row["period_id"],
            row["scope"],
            row["group"],
            row["metric"],
        ): row
        for row in rows
    }


def seasonal_run_kind(period: str) -> str:
    return "design_days" if period in {"summer", "winter"} else "shoulder"


def timing_effects(
    raw_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    building = [
        row
        for row in raw_rows
        if row["scope"] == "building"
        and row["group"] == "whole_building"
        and row["scenario_id"] != "STATIC_SOURCE"
        and row["run_kind"] in {"design_days", "shoulder"}
    ]
    indexed = {
        (
            row["scenario_id"],
            row["seed"],
            row["run_kind"],
            row["period_id"],
            row["metric"],
        ): float(row["value"])
        for row in building
    }
    output: list[dict[str, object]] = []
    for scenario in TIMING_SCENARIOS:
        for period in PERIODS:
            run_kind = seasonal_run_kind(period)
            for metric in BUILDING_METRICS:
                seeds = sorted(
                    {
                        int(row["seed"])
                        for row in building
                        if row["seed"] is not None
                        and row["scenario_id"] == "BASELINE_SPREAD"
                        and row["run_kind"] == run_kind
                        and row["period_id"] == period
                        and row["metric"] == metric
                    }
                    & {
                        int(row["seed"])
                        for row in building
                        if row["seed"] is not None
                        and row["scenario_id"] == scenario
                        and row["run_kind"] == run_kind
                        and row["period_id"] == period
                        and row["metric"] == metric
                    }
                )
                pairs: list[tuple[float, float]] = []
                for seed in seeds:
                    base = indexed.get(("BASELINE_SPREAD", seed, run_kind, period, metric))
                    value = indexed.get((scenario, seed, run_kind, period, metric))
                    if base is not None and value is not None:
                        pairs.append((base, value))
                if not pairs:
                    continue
                differences = [value - base for base, value in pairs]
                percentages = [
                    (value - base) / base * 100.0
                    for base, value in pairs
                    if abs(base) > 1e-12
                ]
                output.append(
                    {
                        "scenario_id": scenario,
                        "run_kind": run_kind,
                        "period_id": period,
                        "metric": metric,
                        "paired_seed_count": len(pairs),
                        "difference_p10": quantile(differences, 0.10),
                        "difference_p50": quantile(differences, 0.50),
                        "difference_p90": quantile(differences, 0.90),
                        "percent_p50": (
                            quantile(percentages, 0.50)
                            if len(percentages) == len(pairs)
                            else None
                        ),
                    }
                )
    return output


def maximum_air_loop_effects(
    raw_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    selected = [
        row
        for row in raw_rows
        if row["scope"] == "air_loop"
        and row["metric"] in AIR_LOOP_EFFECT_METRICS
        and row["scenario_id"] != "STATIC_SOURCE"
        and row["run_kind"] in {"design_days", "shoulder"}
    ]
    indexed = {
        (
            row["scenario_id"],
            row["seed"],
            row["run_kind"],
            row["period_id"],
            row["group"],
            row["metric"],
        ): float(row["value"])
        for row in selected
    }
    groups = sorted({str(row["group"]) for row in selected})
    output: list[dict[str, object]] = []
    for scenario in TIMING_SCENARIOS:
        for period in PERIODS:
            run_kind = seasonal_run_kind(period)
            for metric in AIR_LOOP_EFFECT_METRICS:
                candidates: list[dict[str, object]] = []
                for group in groups:
                    seeds = sorted(
                        {
                            int(row["seed"])
                            for row in selected
                            if row["seed"] is not None
                            and row["scenario_id"] == "BASELINE_SPREAD"
                            and row["run_kind"] == run_kind
                            and row["period_id"] == period
                            and row["group"] == group
                            and row["metric"] == metric
                        }
                        & {
                            int(row["seed"])
                            for row in selected
                            if row["seed"] is not None
                            and row["scenario_id"] == scenario
                            and row["run_kind"] == run_kind
                            and row["period_id"] == period
                            and row["group"] == group
                            and row["metric"] == metric
                        }
                    )
                    pairs: list[tuple[float, float]] = []
                    for seed in seeds:
                        base = indexed.get(
                            ("BASELINE_SPREAD", seed, run_kind, period, group, metric)
                        )
                        value = indexed.get(
                            (scenario, seed, run_kind, period, group, metric)
                        )
                        if base is not None and value is not None:
                            pairs.append((base, value))
                    if not pairs:
                        continue
                    differences = [value - base for base, value in pairs]
                    percentages = [
                        (value - base) / base * 100.0
                        for base, value in pairs
                        if abs(base) > 1e-12
                    ]
                    candidates.append(
                        {
                            "scenario_id": scenario,
                            "run_kind": run_kind,
                            "period_id": period,
                            "metric": metric,
                            "group": group,
                            "paired_seed_count": len(pairs),
                            "difference_p50": quantile(differences, 0.50),
                            "percent_p50": (
                                quantile(percentages, 0.50)
                                if len(percentages) == len(pairs)
                                else None
                            ),
                        }
                    )
                if candidates:
                    output.append(
                        max(candidates, key=lambda row: abs(float(row["difference_p50"])))
                    )
    return output


def read_annual_person_hours(root: Path | None) -> dict[str, dict[str, float]]:
    if root is None:
        return {}
    output: dict[str, dict[str, float]] = {}
    for path in sorted(root.glob("*/annual_schedule_summary.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        output[str(payload["scenario_id"])] = {
            "public_person_hours": float(payload["public_person_hours"]),
            "staff_person_hours": float(payload["staff_person_hours"]),
        }
    if output:
        public = {round(row["public_person_hours"], 6) for row in output.values()}
        staff = {round(row["staff_person_hours"], 6) for row in output.values()}
        if len(public) != 1 or len(staff) != 1:
            raise ValueError("annual timing schedules do not match person-hours")
    return output


def write_public_aggregate(
    path: Path,
    summary_rows: list[dict[str, object]],
) -> None:
    loops = sorted(
        {str(row["group"]) for row in summary_rows if row["scope"] == "air_loop"}
    )
    aliases = {name: f"air_loop_{index:02d}" for index, name in enumerate(loops, 1)}
    fields = (
        "scenario_id",
        "run_kind",
        "period_id",
        "scope",
        "group",
        "metric",
        "n",
        "p10",
        "p50",
        "p90",
        "unit",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in summary_rows:
            if row["scope"] not in {"building", "air_loop"}:
                continue
            public = {field: row[field] for field in fields}
            if public["scope"] == "air_loop":
                public["group"] = aliases[str(public["group"])]
            writer.writerow(public)


def fmt(value: object, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f}"


def write_markdown(
    path: Path,
    *,
    summary_rows: list[dict[str, object]],
    effects: list[dict[str, object]],
    loop_effects: list[dict[str, object]],
    annual_person_hours: dict[str, dict[str, float]],
) -> None:
    index = index_summary(summary_rows)
    effect_index = {
        (row["scenario_id"], row["period_id"], row["metric"]): row
        for row in effects
    }
    available_periods = tuple(
        period
        for period in PERIODS
        if any(
            row["period_id"] == period
            and row["run_kind"] == seasonal_run_kind(period)
            for row in summary_rows
        )
    )
    pair_counts = [int(row["paired_seed_count"]) for row in effects]
    fixed_seed_demo = bool(pair_counts) and max(pair_counts) == 1
    has_full_seasonal_evidence = (
        set(available_periods) == set(PERIODS)
        and bool(pair_counts)
        and min(pair_counts) >= 5
    )
    has_annual = any(row["run_kind"] == "annual" for row in summary_rows)
    if has_annual and has_full_seasonal_evidence:
        status = "PASS_SEASONAL_AND_ANNUAL"
    elif has_full_seasonal_evidence:
        status = "PASS_SEASONAL"
    else:
        status = "PASS_CONTROLLED_REPRESENTATIVE_DAY_DEMO"
    effect_heading = (
        "Fixed-seed paired timing effect relative to the dynamic spread case:"
        if fixed_seed_demo
        else "Paired median timing effect relative to the dynamic spread case:"
    )
    lines = [
        "# Airport Occupancy V3 — EnergyPlus Results",
        "",
        f"Status: `{status}`",
        "",
        "## Result boundary",
        "",
        "All results use the source HVAC topology and control sequence; no IdealLoads or demand-controlled ventilation was added. District cooling and heating are building-side boundary quantities, not central-plant production energy. Timing cases are controlled distributions with equal public/staff person-hours, not measured forecasts.",
        (
            "This report is a fixed-seed, one-day shoulder-period mechanism demonstration. It is not a seasonal or annual result and is not admitted as an Energy and Buildings paper result."
            if status == "PASS_CONTROLLED_REPRESENTATIVE_DAY_DEMO"
            else "The seasonal evidence uses paired stochastic seeds and the pre-registered reporting contract."
        ),
        "",
        "## Building results",
        "",
    ]
    for period in available_periods:
        run_kind = seasonal_run_kind(period)
        lines.extend(
            [
                f"### {period.title()}",
                "",
                "| Scenario | Facility kWh | Fan kWh | Pump kWh | Cooling boundary kWh | Heating boundary kWh | Peak HVAC kW | Cooling unmet h | Heating unmet h |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for scenario in SCENARIOS:
            values = []
            for metric in BUILDING_METRICS:
                row = index.get(
                    (scenario, run_kind, period, "building", "whole_building", metric)
                )
                values.append(fmt(row["p50"]) if row else "—")
            if any(value != "—" for value in values):
                lines.append(f"| {DISPLAY[scenario]} | " + " | ".join(values) + " |")
        lines.extend(
            [
                "",
                effect_heading,
                "",
                "| Timing case | Pairs | Facility electricity | Fan electricity | Cooling boundary | Heating boundary | Peak HVAC demand |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for scenario in TIMING_SCENARIOS:
            cells = []
            counts = []
            for metric in (
                "facility_electricity_kwh",
                "fan_electricity_kwh",
                "district_cooling_kwh_boundary",
                "district_heating_kwh_boundary",
                "peak_hvac_electric_kw",
            ):
                effect = effect_index.get((scenario, period, metric))
                if effect:
                    counts.append(int(effect["paired_seed_count"]))
                cells.append(
                    f"{fmt(effect['difference_p50'])} ({fmt(effect['percent_p50'])}%)"
                    if effect
                    else "—"
                )
            pair_label = str(max(counts)) if counts else "—"
            lines.append(
                f"| {DISPLAY[scenario]} | {pair_label} | " + " | ".join(cells) + " |"
            )
        lines.append("")

    lines.extend(
        [
            "## Maximum AirLoop redistribution effects",
            "",
            "For each timing case, period, and system metric, the table selects the AirLoop with the largest absolute paired change. With multiple seeds this is the paired median; with one pair it is an explicit fixed-seed demo value. The selection is made from all 14 source AirLoops; it is not a whole-building meter duplicated across loops.",
            "",
            "| Period | Timing case | Pairs | Metric | AirLoop | Paired difference | Paired percent |",
            "|---|---|---:|---|---|---:|---:|",
        ]
    )
    for row in loop_effects:
        lines.append(
            f"| {str(row['period_id']).title()} | {DISPLAY[str(row['scenario_id'])]} | {int(row['paired_seed_count'])} | {METRIC_LABELS[str(row['metric'])]} | {row['group']} | {fmt(row['difference_p50'])} | {fmt(row['percent_p50'])}% |"
        )

    annual_rows = [row for row in summary_rows if row["run_kind"] == "annual"]
    if annual_rows:
        lines.extend(
            [
                "",
                "## Annual weather results",
                "",
                "The four dynamic annual schedules use the fixed pre-registered seed. Their public and staff person-hours are identical across timing cases.",
                "",
                "| Scenario | Facility kWh | Fan kWh | Pump kWh | Cooling boundary kWh | Heating boundary kWh | Peak HVAC kW | Cooling unmet h | Heating unmet h |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for scenario in SCENARIOS[:-1]:
            values = []
            for metric in BUILDING_METRICS:
                row = index.get(
                    (scenario, "annual", "annual", "building", "whole_building", metric)
                )
                values.append(fmt(row["p50"]) if row else "—")
            if any(value != "—" for value in values):
                lines.append(f"| {DISPLAY[scenario]} | " + " | ".join(values) + " |")
        if annual_person_hours:
            sample = next(iter(annual_person_hours.values()))
            lines.extend(
                [
                    "",
                    f"Matched annual public person-hours: {sample['public_person_hours']:,.3f}; matched annual staff person-hours: {sample['staff_person_hours']:,.3f}.",
                ]
            )

    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "The source model uses autosized equipment. EnergyPlus therefore repeats sizing for each People-only derivative; this preserves the source model fields but means comparisons are not a fixed installed-capacity experiment. The OSM also keeps demand-controlled ventilation disabled, so occupancy timing affects internal gains, zone loads, and existing control responses rather than introducing a new occupancy-driven outdoor-air controller. Results support controlled mechanism and sensitivity analysis, not measured airport energy savings.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_figures(
    directory: Path,
    *,
    summary_rows: list[dict[str, object]],
    effects: list[dict[str, object]],
    loop_effects: list[dict[str, object]],
) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    directory.mkdir(parents=True, exist_ok=True)
    effect_index = {
        (row["scenario_id"], row["period_id"], row["metric"]): row
        for row in effects
    }
    plotted_metrics = (
        "facility_electricity_kwh",
        "fan_electricity_kwh",
        "district_cooling_kwh_boundary",
        "district_heating_kwh_boundary",
        "peak_hvac_electric_kw",
    )
    available_periods = tuple(
        period
        for period in PERIODS
        if any(
            row["period_id"] == period
            and row["run_kind"] == seasonal_run_kind(period)
            for row in summary_rows
        )
    )
    if not available_periods:
        raise ValueError("no seasonal or representative-day periods are available")
    fixed_seed_demo = bool(effects) and max(
        int(row["paired_seed_count"]) for row in effects
    ) == 1
    fig, axes = plt.subplots(
        1,
        len(available_periods),
        figsize=(5.4 * len(available_periods), 5.4),
        constrained_layout=True,
    )
    axes = np.atleast_1d(axes)
    for axis, period in zip(axes, available_periods):
        matrix = np.full((len(TIMING_SCENARIOS), len(plotted_metrics)), np.nan)
        for y, scenario in enumerate(TIMING_SCENARIOS):
            for x, metric in enumerate(plotted_metrics):
                row = effect_index.get((scenario, period, metric))
                if row and row["percent_p50"] is not None:
                    matrix[y, x] = float(row["percent_p50"])
        limit = max(1.0, float(np.nanmax(np.abs(matrix))) if not np.all(np.isnan(matrix)) else 1.0)
        image = axis.imshow(matrix, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
        axis.set_title(period.title())
        axis.set_xticks(range(len(plotted_metrics)), ["Facility", "Fans", "Cooling", "Heating", "Peak"], rotation=35, ha="right")
        axis.set_yticks(range(len(TIMING_SCENARIOS)), [DISPLAY[name] for name in TIMING_SCENARIOS])
        for y in range(matrix.shape[0]):
            for x in range(matrix.shape[1]):
                if math.isfinite(matrix[y, x]):
                    axis.text(x, y, f"{matrix[y, x]:.1f}%", ha="center", va="center", fontsize=8)
        fig.colorbar(image, ax=axis, shrink=0.72, label="Paired median change (%)")
    fig.suptitle(
        "Same-person-hours timing effect on representative-day building metrics"
        if fixed_seed_demo
        else "Same-person-hours timing effect on seasonal building metrics",
        fontsize=15,
    )
    seasonal_path = directory / (
        "representative_shoulder_timing_effects.png"
        if fixed_seed_demo and available_periods == ("shoulder",)
        else "seasonal_timing_energy_effects.png"
    )
    fig.savefig(seasonal_path, dpi=180)
    plt.close(fig)

    period_codes = {"summer": "Su", "winter": "Wi", "shoulder": "Sh"}
    loop_pairs = [
        (period, scenario)
        for period in available_periods
        for scenario in TIMING_SCENARIOS
    ]
    loop_periods = [
        f"{period_codes[period]}-{DISPLAY[scenario].split()[0]}"
        for period, scenario in loop_pairs
    ]
    loop_metrics = list(AIR_LOOP_EFFECT_METRICS)
    loop_matrix = np.full((len(loop_periods), len(loop_metrics)), np.nan)
    loop_index = {
        (row["period_id"], row["scenario_id"], row["metric"]): row
        for row in loop_effects
    }
    for y, (period, scenario) in enumerate(loop_pairs):
        for x, metric in enumerate(loop_metrics):
            row = loop_index.get((period, scenario, metric))
            if row and row["percent_p50"] is not None:
                loop_matrix[y, x] = float(row["percent_p50"])
    fig, axis = plt.subplots(figsize=(9.5, 8), constrained_layout=True)
    limit = max(1.0, float(np.nanmax(np.abs(loop_matrix))) if not np.all(np.isnan(loop_matrix)) else 1.0)
    image = axis.imshow(loop_matrix, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
    axis.set_xticks(range(len(loop_metrics)), ["Fan energy", "OA peak", "Cooling peak", "Heating peak"], rotation=25, ha="right")
    axis.set_yticks(range(len(loop_periods)), loop_periods)
    for y in range(loop_matrix.shape[0]):
        for x in range(loop_matrix.shape[1]):
            if math.isfinite(loop_matrix[y, x]):
                axis.text(x, y, f"{loop_matrix[y, x]:.1f}%", ha="center", va="center", fontsize=8)
    fig.colorbar(image, ax=axis, label="Largest absolute AirLoop paired median change (%)")
    axis.set_title("AirLoop-level redistribution envelope")
    loop_path = directory / (
        "representative_shoulder_airloop_effects.png"
        if fixed_seed_demo and available_periods == ("shoulder",)
        else "airloop_timing_effects.png"
    )
    fig.savefig(loop_path, dpi=180)
    plt.close(fig)

    annual = [
        row
        for row in summary_rows
        if row["run_kind"] == "annual"
        and row["scope"] == "building"
        and row["group"] == "whole_building"
    ]
    output = [str(seasonal_path), str(loop_path)]
    if annual:
        annual_index = {(row["scenario_id"], row["metric"]): row for row in annual}
        scenarios = SCENARIOS[:-1]
        metrics = (
            "facility_electricity_kwh",
            "fan_electricity_kwh",
            "district_cooling_kwh_boundary",
            "district_heating_kwh_boundary",
            "peak_hvac_electric_kw",
        )
        matrix = np.full((len(scenarios), len(metrics)), np.nan)
        for y, scenario in enumerate(scenarios):
            for x, metric in enumerate(metrics):
                base = annual_index.get(("BASELINE_SPREAD", metric))
                row = annual_index.get((scenario, metric))
                if base and row and abs(float(base["p50"])) > 1e-12:
                    matrix[y, x] = (float(row["p50"]) / float(base["p50"]) - 1.0) * 100.0
        fig, axis = plt.subplots(figsize=(10.5, 5.5), constrained_layout=True)
        limit = max(1.0, float(np.nanmax(np.abs(matrix))) if not np.all(np.isnan(matrix)) else 1.0)
        image = axis.imshow(matrix, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
        axis.set_xticks(range(len(metrics)), ["Facility", "Fans", "Cooling", "Heating", "Peak"])
        axis.set_yticks(range(len(scenarios)), [DISPLAY[name] for name in scenarios])
        for y in range(matrix.shape[0]):
            for x in range(matrix.shape[1]):
                if math.isfinite(matrix[y, x]):
                    axis.text(x, y, f"{matrix[y, x]:.1f}%", ha="center", va="center", fontsize=8)
        fig.colorbar(image, ax=axis, label="Change from dynamic spread (%)")
        axis.set_title("Annual weather-run comparison")
        annual_path = directory / "annual_timing_energy_effects.png"
        fig.savefig(annual_path, dpi=180)
        plt.close(fig)
        output.append(str(annual_path))
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--markdown-output", required=True)
    parser.add_argument("--public-output", required=True)
    parser.add_argument("--figure-dir", required=True)
    parser.add_argument("--annual-schedule-root")
    args = parser.parse_args()
    raw = load_rows(Path(args.input))
    summary = grouped_summary(
        raw,
        fields=("scenario_id", "run_kind", "period_id", "scope", "group", "metric"),
    )
    effects = timing_effects(raw)
    loop_effects = maximum_air_loop_effects(raw)
    annual_hours = read_annual_person_hours(
        Path(args.annual_schedule_root) if args.annual_schedule_root else None
    )
    write_public_aggregate(Path(args.public_output), summary)
    write_markdown(
        Path(args.markdown_output),
        summary_rows=summary,
        effects=effects,
        loop_effects=loop_effects,
        annual_person_hours=annual_hours,
    )
    figures = write_figures(
        Path(args.figure_dir),
        summary_rows=summary,
        effects=effects,
        loop_effects=loop_effects,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "summary_rows": len(summary),
                "timing_effect_rows": len(effects),
                "air_loop_effect_rows": len(loop_effects),
                "figures": figures,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
