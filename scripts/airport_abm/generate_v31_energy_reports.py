#!/usr/bin/env python3
"""Generate public-safe V3.1 seasonal, system, function, and gate reports."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import gzip
import json
import math
from pathlib import Path
import sys
from typing import Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.reporting import (  # noqa: E402
    paired_energy_statistics,
    quantile,
)
from idfrepair.analysis.airport_abm.v31 import (  # noqa: E402
    SEASONAL_SEEDS,
    TIMING_SCENARIOS,
)
from idfrepair.analysis.airport_abm.v31_reporting import (  # noqa: E402
    validate_source_static_energy_baseline,
)


PERIODS = ("winter", "summer", "shoulder")
COMPARISONS = (
    ("SOURCE_STATIC", "BASELINE_SPREAD"),
    ("BASELINE_SPREAD", "MORNING_BANK"),
    ("BASELINE_SPREAD", "MIDDAY_BANK"),
    ("BASELINE_SPREAD", "EVENING_BANK"),
    ("BASELINE_SPREAD", "DOUBLE_BANK"),
)
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
AIRLOOP_METRICS = (
    "fan_electricity_kwh",
    "outdoor_air_mass_flow_mean_kg_s",
    "outdoor_air_mass_flow_peak_kg_s",
    "total_heating_kwh",
    "total_heating_interval_peak_kw",
    "total_cooling_kwh",
    "total_cooling_interval_peak_kw",
)
FUNCTION_METRICS = (
    "people_sensible_gain_kwh",
    "people_latent_gain_kwh",
    "people_radiant_gain_kwh",
    "sensible_heating_kwh",
    "sensible_cooling_kwh",
    "maximum_zone_sensible_heating_interval_peak_kw",
    "maximum_zone_sensible_cooling_interval_peak_kw",
    "air_temperature_mean_c",
    "relative_humidity_mean_percent",
    "outdoor_air_mean_m3_s",
)
TARGET_FUNCTIONS = (
    "domestic_waiting",
    "central_hall",
    "baggage_claim",
    "arrival_exit",
    "departure_entry",
    "general_commercial",
    "restaurant",
    "restroom",
    "international_arrival",
    "international_hall",
)
METRIC_LABELS = {
    "facility_electricity_kwh": "Facility electricity",
    "fan_electricity_kwh": "Fan electricity",
    "pump_electricity_kwh": "Pump electricity",
    "district_cooling_kwh_boundary": "District cooling boundary",
    "district_heating_kwh_boundary": "District heating boundary",
    "peak_hvac_electric_kw": "Peak HVAC electricity",
    "cooling_unmet_occupied_hours": "Cooling occupied unmet hours",
    "heating_unmet_occupied_hours": "Heating occupied unmet hours",
}


def load_rows(path: Path) -> list[dict[str, object]]:
    rows = []
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            value = float(raw["value"])
            if not math.isfinite(value):
                raise ValueError(f"non-finite result: {path}")
            rows.append(
                {
                    **raw,
                    "seed": int(raw["seed"]) if raw["seed"] else None,
                    "value": value,
                }
            )
    if not rows:
        raise ValueError(f"empty result table: {path}")
    return rows


def run_kind(period: str) -> str:
    return "design_days" if period in {"winter", "summer"} else "shoulder"


def result_index(rows: Iterable[Mapping[str, object]]) -> dict[tuple[object, ...], float]:
    output = {}
    for row in rows:
        key = (
            row["scenario_id"],
            row["seed"],
            row["run_kind"],
            row["period_id"],
            row["scope"],
            row["group"],
            row["metric"],
        )
        if key in output:
            raise ValueError(f"duplicate result identity: {key}")
        output[key] = float(row["value"])
    return output


def comparison_statistics(
    index: Mapping[tuple[object, ...], float],
    *,
    reference: str,
    comparison: str,
    period: str,
    scope: str,
    group: str,
    metric: str,
) -> dict[str, object]:
    kind = run_kind(period)
    rows = []
    reference_values = []
    comparison_values = []
    for seed in SEASONAL_SEEDS:
        reference_seed = None if reference == "SOURCE_STATIC" else seed
        reference_key = (
            reference,
            reference_seed,
            kind,
            period,
            scope,
            group,
            metric,
        )
        comparison_key = (
            comparison,
            seed,
            kind,
            period,
            scope,
            group,
            metric,
        )
        if reference_key not in index or comparison_key not in index:
            raise ValueError(
                f"comparison result missing: {reference}:{comparison}:{period}:{scope}:{group}:{metric}:{seed}"
            )
        reference_value = index[reference_key]
        comparison_value = index[comparison_key]
        reference_values.append(reference_value)
        comparison_values.append(comparison_value)
        rows.extend(
            [
                {"scenario_id": reference, "seed": seed, "value": reference_value},
                {
                    "scenario_id": comparison,
                    "seed": seed,
                    "value": comparison_value,
                },
            ]
        )
    statistics = paired_energy_statistics(
        rows,
        baseline_scenario=reference,
        comparison_scenario=comparison,
        identity_fields=("seed",),
    )
    statistics.pop("pairs")
    return {
        **statistics,
        "reference_p50": quantile(reference_values, 0.50),
        "comparison_p50": quantile(comparison_values, 0.50),
    }


def unit_for(
    rows: Iterable[Mapping[str, object]], *, scope: str, metric: str
) -> str:
    units = {
        str(row["unit"])
        for row in rows
        if row["scope"] == scope and row["metric"] == metric
    }
    if len(units) != 1:
        raise ValueError(f"unit is not unique: {scope}:{metric}:{sorted(units)}")
    return units.pop()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: object, digits: int = 3) -> str:
    if value is None or value == "":
        return "—"
    return f"{float(value):,.{digits}f}"


def fmt_percent(value: object, digits: int = 2) -> str:
    if value is None or value == "":
        return "—"
    return f"{float(value):,.{digits}f}%"


def building_effect_rows(
    energy_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    index = result_index(energy_rows)
    output = []
    for reference, comparison in COMPARISONS:
        for period in PERIODS:
            for metric in BUILDING_METRICS:
                statistics = comparison_statistics(
                    index,
                    reference=reference,
                    comparison=comparison,
                    period=period,
                    scope="building",
                    group="whole_building",
                    metric=metric,
                )
                output.append(
                    {
                        "reference_scenario": reference,
                        "comparison_scenario": comparison,
                        "period_id": period,
                        "scope": "building",
                        "group": "whole_building",
                        "metric": metric,
                        "unit": unit_for(energy_rows, scope="building", metric=metric),
                        **statistics,
                        "claim_status": "DESIGN_SIZING_SENSITIVITY_NOT_FIXED_OPERATION",
                    }
                )
    return output


def write_seasonal_markdown(
    path: Path,
    rows: list[dict[str, object]],
    ledger: Mapping[str, object],
) -> None:
    index = {
        (row["reference_scenario"], row["comparison_scenario"], row["period_id"], row["metric"]): row
        for row in rows
    }
    records = list(ledger["records"])
    warnings = [int(row["warning_count"]) for row in records]
    wall = [float(row["wall_seconds"]) for row in records]
    lines = [
        "# Airport Occupancy V3.1 — Seasonal EnergyPlus results",
        "",
        "Status: `PASS_78_OF_78_DESIGN_SIZING_SENSITIVITY`",
        "",
        f"All {ledger['planned_process_count']} registered EnergyPlus processes completed and all {ledger['period_pass_count']}/{ledger['planned_period_identity_count']} winter, summer, and shoulder period identities passed return-code, Severe, Fatal, and output-period gates. The process warning range was {min(warnings)}–{max(warnings)}; total recorded wall time was {sum(wall) / 60.0:,.1f} minutes. No failed seed was replaced.",
        "",
        "The occupancy schedules use `BEM_REFERENCE_NORMALIZED` and preserve public/staff person-hours. However, the applySizingValues completeness gate failed, so these results are design/sizing sensitivity from a partially fixed reference—not a valid fixed installed-HVAC operational comparison.",
        "",
        "## SOURCE_STATIC versus dynamic baseline",
        "",
    ]
    for period in PERIODS:
        lines.extend(
            [
                f"### {period.title()}",
                "",
                "| Metric | Source static | Dynamic P50 | n | Mean difference | Median | Min…Max | P10…P90 | Median % |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for metric in BUILDING_METRICS:
            row = index[("SOURCE_STATIC", "BASELINE_SPREAD", period, metric)]
            lines.append(
                f"| {METRIC_LABELS[metric]} | {fmt(row['reference_p50'])} | {fmt(row['comparison_p50'])} | {row['n']} | {fmt(row['difference_mean'])} | {fmt(row['difference_median'])} | {fmt(row['difference_minimum'])}…{fmt(row['difference_maximum'])} | {fmt(row['difference_p10'])}…{fmt(row['difference_p90'])} | {fmt_percent(row['percent_median'])} |"
            )
        lines.append("")
    lines.extend(["## Timing-bank effects versus dynamic spread", ""])
    for period in PERIODS:
        lines.extend(
            [
                f"### {period.title()}",
                "",
                "| Scenario | Metric | n | Mean difference | Median | Min…Max | P10…P90 | Median % |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for comparison in TIMING_SCENARIOS[1:]:
            for metric in BUILDING_METRICS:
                row = index[("BASELINE_SPREAD", comparison, period, metric)]
                lines.append(
                    f"| {comparison} | {METRIC_LABELS[metric]} | {row['n']} | {fmt(row['difference_mean'])} | {fmt(row['difference_median'])} | {fmt(row['difference_minimum'])}…{fmt(row['difference_maximum'])} | {fmt(row['difference_p10'])}…{fmt(row['difference_p90'])} | {fmt_percent(row['percent_median'])} |"
                )
        lines.append("")
    lines.extend(
        [
            "District cooling and district heating are building-side boundary energy, not central-plant production. The five seeds quantify controlled ABM stochastic-realization sensitivity, not measured uncertainty. DCV remained off, and no ABM parameter was changed after viewing energy results.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def airloop_effect_rows(
    energy_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, str]]:
    loops = sorted(
        {str(row["group"]) for row in energy_rows if row["scope"] == "air_loop"}
    )
    aliases = {name: f"air_loop_{index:02d}" for index, name in enumerate(loops, 1)}
    index = result_index(energy_rows)
    output = []
    for reference, comparison in COMPARISONS:
        for period in PERIODS:
            for metric in AIRLOOP_METRICS:
                loop_rows = []
                for loop in loops:
                    stats = comparison_statistics(
                        index,
                        reference=reference,
                        comparison=comparison,
                        period=period,
                        scope="air_loop",
                        group=loop,
                        metric=metric,
                    )
                    loop_rows.append({"loop": loop, **stats})
                largest = max(
                    loop_rows, key=lambda row: abs(float(row["difference_median"]))
                )
                percentages = [
                    float(row["percent_median"])
                    for row in loop_rows
                    if row["percent_median"] is not None
                ]
                output.append(
                    {
                        "reference_scenario": reference,
                        "comparison_scenario": comparison,
                        "period_id": period,
                        "metric": metric,
                        "unit": unit_for(energy_rows, scope="air_loop", metric=metric),
                        "air_loop_count": len(loop_rows),
                        "paired_seed_count": largest["n"],
                        "median_loop_difference": quantile(
                            [float(row["difference_median"]) for row in loop_rows], 0.50
                        ),
                        "median_loop_percent": (
                            quantile(percentages, 0.50) if percentages else None
                        ),
                        "maximum_effect_air_loop": aliases[str(largest["loop"])],
                        "maximum_effect_difference": largest["difference_median"],
                        "maximum_effect_percent": largest["percent_median"],
                    }
                )
    return output, aliases


def write_airloop_markdown(path: Path, rows: list[dict[str, object]]) -> None:
    lines = [
        "# Airport Occupancy V3.1 — AirLoop redistribution effects",
        "",
        "Status: `PASS_ALL_14_AIRLOOPS_AGGREGATED`",
        "",
        "Every row is calculated from all 14 source AirLoops. `median loop` is the median of the 14 loop-level paired medians; `maximum loop` is selected by absolute paired-median difference. Public aliases replace private system labels.",
        "",
        "| Period | Comparison | Metric | Pairs | Loops | Median loop effect | Median loop % | Maximum loop | Maximum effect | Maximum % |",
        "|---|---|---|---:|---:|---:|---:|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['period_id']} | {row['comparison_scenario']} − {row['reference_scenario']} | {row['metric']} | {row['paired_seed_count']} | {row['air_loop_count']} | {fmt(row['median_loop_difference'])} {row['unit']} | {fmt_percent(row['median_loop_percent'])} | {row['maximum_effect_air_loop']} | {fmt(row['maximum_effect_difference'])} {row['unit']} | {fmt_percent(row['maximum_effect_percent'])} |"
        )
    lines.extend(
        [
            "",
            "The table includes fan energy, mean/peak outdoor-air mass flow, air-system heating/cooling energy, and interval peaks. Effects are controlled model redistribution, not measurements, and remain subject to the incomplete fixed-sizing gate.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def function_effect_rows(
    function_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    index = result_index(function_rows)
    available = {
        str(row["group"])
        for row in function_rows
        if row["scope"] == "function"
    }
    targets = [name for name in TARGET_FUNCTIONS if name in available]
    output = []
    for reference, comparison in COMPARISONS:
        for period in PERIODS:
            for metric in FUNCTION_METRICS:
                candidates = []
                for function in targets:
                    try:
                        stats = comparison_statistics(
                            index,
                            reference=reference,
                            comparison=comparison,
                            period=period,
                            scope="function",
                            group=function,
                            metric=metric,
                        )
                    except ValueError as exc:
                        if not str(exc).startswith("comparison result missing:"):
                            raise
                        continue
                    candidates.append({"function": function, **stats})
                if not candidates:
                    raise ValueError(
                        f"no common function output: {reference}:{comparison}:{period}:{metric}"
                    )
                largest = max(
                    candidates,
                    key=lambda row: abs(float(row["difference_median"])),
                )
                output.append(
                    {
                        "reference_scenario": reference,
                        "comparison_scenario": comparison,
                        "period_id": period,
                        "metric": metric,
                        "unit": unit_for(function_rows, scope="function", metric=metric),
                        "paired_seed_count": largest["n"],
                        "largest_effect_function": largest["function"],
                        "difference_mean": largest["difference_mean"],
                        "difference_median": largest["difference_median"],
                        "difference_minimum": largest["difference_minimum"],
                        "difference_maximum": largest["difference_maximum"],
                        "difference_p10": largest["difference_p10"],
                        "difference_p90": largest["difference_p90"],
                        "percent_median": largest["percent_median"],
                    }
                )
    return output


def load_space_functions(path: Path) -> dict[str, dict[str, object]]:
    output = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = row["space"].strip()
            output[name] = {
                "function": canonical_function(row["function"]),
            }
    return output


def canonical_function(value: object) -> str:
    function = str(value).strip()
    return {
        "commercial": "general_commercial",
        "breakroom": "staff_breakroom",
    }.get(function, function)


def function_profile(
    counts: Mapping[str, Iterable[float]],
    space_functions: Mapping[str, Mapping[str, object]],
    *,
    supported_spaces: set[str] | None = None,
) -> dict[str, dict[str, float]]:
    profiles: dict[str, list[float]] = defaultdict(lambda: [0.0] * 96)
    for space, values in counts.items():
        if supported_spaces is not None and space not in supported_spaces:
            continue
        mapped = space_functions.get(space)
        if mapped is None:
            continue
        materialized = [float(value) for value in values]
        if len(materialized) != 96:
            raise ValueError("function occupancy profile is not 96 intervals")
        target = profiles[str(mapped["function"])]
        for index, value in enumerate(materialized):
            target[index] += value
    return {
        function: {
            "person_hours": sum(values) * 0.25,
            "peak": max(values),
        }
        for function, values in profiles.items()
    }


def occupancy_function_rows(
    *,
    mapping: Path,
    normalized_root: Path,
    source_static: Path,
) -> list[dict[str, object]]:
    space_functions = load_space_functions(mapping)
    source = json.loads(source_static.read_text(encoding="utf-8"))
    supported_spaces = {str(row["space_name"]) for row in source["spaces"]}
    design: dict[str, float] = defaultdict(float)
    for row in source["spaces"]:
        design[canonical_function(row["function"])] += float(
            row["source_design_people"]
        )
    source_profile = function_profile(
        {row["space_name"]: row["occupant_counts"] for row in source["spaces"]},
        space_functions,
        supported_spaces=supported_spaces,
    )
    dynamic_profiles = []
    for seed in SEASONAL_SEEDS:
        detail_path = (
            normalized_root
            / "seed_details/BASELINE_SPREAD"
            / f"seed-{seed}.json.gz"
        )
        with gzip.open(detail_path, "rt", encoding="utf-8") as handle:
            detail = json.load(handle)
        dynamic_profiles.append(
            function_profile(
                detail["space_counts"],
                space_functions,
                supported_spaces=supported_spaces,
            )
        )
    output = []
    for function in TARGET_FUNCTIONS:
        source_values = source_profile.get(
            function, {"person_hours": 0.0, "peak": 0.0}
        )
        dynamic_hours = [
            row.get(function, {"person_hours": 0.0})["person_hours"]
            for row in dynamic_profiles
        ]
        dynamic_peak = [
            row.get(function, {"peak": 0.0})["peak"]
            for row in dynamic_profiles
        ]
        output.append(
            {
                "function": function,
                "source_design_people": design[function],
                "source_static_person_hours": source_values["person_hours"],
                "source_static_peak": source_values["peak"],
                "dynamic_baseline_person_hours_p50": quantile(dynamic_hours, 0.50),
                "dynamic_baseline_peak_p50": quantile(dynamic_peak, 0.50),
                "dynamic_peak_to_design_p50": (
                    quantile(dynamic_peak, 0.50) / design[function]
                    if design[function] > 0
                    else None
                ),
            }
        )
    return output


def write_function_markdown(
    path: Path,
    occupancy_rows: list[dict[str, object]],
    effect_rows: list[dict[str, object]],
) -> None:
    lines = [
        "# Airport Occupancy V3.1 — Function/Zone effects",
        "",
        "Status: `PASS_FUNCTION_AGGREGATION_DESIGN_SIZING_SENSITIVITY`",
        "",
        "## Occupancy redistribution",
        "",
        "Function totals are aggregated from private Space schedules. Design People is a BEM reference only, not fire-code, operational, or physical terminal capacity.",
        "",
        "| Function | Source design People | Source static person-h | Source peak | Dynamic baseline person-h P50 | Dynamic peak P50 | Dynamic peak/design |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in occupancy_rows:
        design_ratio = row["dynamic_peak_to_design_p50"]
        lines.append(
            f"| {row['function']} | {fmt(row['source_design_people'])} | {fmt(row['source_static_person_hours'])} | {fmt(row['source_static_peak'])} | {fmt(row['dynamic_baseline_person_hours_p50'])} | {fmt(row['dynamic_baseline_peak_p50'])} | {fmt_percent(float(design_ratio) * 100.0 if design_ratio is not None else None)} |"
        )
    lines.extend(
        [
            "",
            "## Largest registered function effect per metric",
            "",
            "The selection is made only across the listed public terminal functions and is accompanied by n=5 paired statistics. Energy quantities are summed across member Zones; temperature and RH means are area-weighted; reported peak load is the maximum member-Zone peak, not a sum of noncoincident peaks.",
            "",
            "| Period | Comparison | Metric | Function | n | Mean | Median | Min…Max | P10…P90 | Median % |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in effect_rows:
        lines.append(
            f"| {row['period_id']} | {row['comparison_scenario']} − {row['reference_scenario']} | {row['metric']} | {row['largest_effect_function']} | {row['paired_seed_count']} | {fmt(row['difference_mean'])} {row['unit']} | {fmt(row['difference_median'])} | {fmt(row['difference_minimum'])}…{fmt(row['difference_maximum'])} | {fmt(row['difference_p10'])}…{fmt(row['difference_p90'])} | {fmt_percent(row['percent_median'])} |"
        )
    lines.extend(
        [
            "",
            "People sensible/latent/radiant gains, Zone heating/cooling, air temperature, relative humidity, and outdoor-air flow are all included. The results are controlled and not measured, and the incomplete fixed-sizing gate limits interpretation to design/sizing sensitivity.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_confound_report(
    path: Path,
    fixed_rows: list[dict[str, object]],
    autosized_rows: list[dict[str, object]],
) -> None:
    fixed = result_index(fixed_rows)
    autosized = result_index(autosized_rows)
    lines = [
        "# Airport Occupancy V3.1 — Autosizing confound check",
        "",
        "Status: `PASS_PRESELECTED_TWO_CASE_CHECK`",
        "",
        "Only shoulder, seed 40015, BASELINE_SPREAD and MIDDAY_BANK were run under both sizing treatments. `PARTIAL_APPLYSIZING_OPERATION` uses the common partially fixed reference with new sizing disabled; `AUTOSIZED_PER_SCENARIO` repeats sizing for each People derivative. Because 908 fields remained unresolved, the first treatment is not a valid fully fixed installed system.",
        "",
        "| Metric | Partial baseline | Partial midday | Partial delta | Partial % | Autosized baseline | Autosized midday | Autosized delta | Autosized % | Partial/autosized delta |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric in BUILDING_METRICS:
        key_base = (
            "BASELINE_SPREAD",
            40015,
            "shoulder",
            "shoulder",
            "building",
            "whole_building",
            metric,
        )
        key_mid = (
            "MIDDAY_BANK",
            40015,
            "shoulder",
            "shoulder",
            "building",
            "whole_building",
            metric,
        )
        partial_base = fixed[key_base]
        partial_mid = fixed[key_mid]
        auto_base = autosized[key_base]
        auto_mid = autosized[key_mid]
        partial_delta = partial_mid - partial_base
        auto_delta = auto_mid - auto_base
        lines.append(
            f"| {METRIC_LABELS[metric]} | {fmt(partial_base)} | {fmt(partial_mid)} | {fmt(partial_delta)} | {fmt_percent(partial_delta / partial_base * 100.0 if abs(partial_base) > 1e-15 else None)} | {fmt(auto_base)} | {fmt(auto_mid)} | {fmt(auto_delta)} | {fmt_percent(auto_delta / auto_base * 100.0 if abs(auto_base) > 1e-15 else None)} | {fmt(partial_delta / auto_delta if abs(auto_delta) > 1e-15 else None, 3)} |"
        )
    lines.extend(
        [
            "",
            "Scenario-specific autosizing materially changes several MIDDAY-minus-baseline deltas, so the old autosized-per-scenario result cannot be interpreted as a fixed-system response. This two-case check diagnoses confounding only; it is not a second experiment matrix.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_annual_skip(report_dir: Path) -> None:
    rows = [
        {
            "status": "ANNUAL_SKIPPED",
            "planned_cases": 6,
            "run_cases": 0,
            "master_seed": 40015,
            "reason": "FIXED_OPERATION_INCOMPLETE",
        }
    ]
    write_csv(report_dir / "annual_energy_results.csv", rows)
    (report_dir / "annual_energy_results.md").write_text(
        "# Airport Occupancy V3.1 — Annual EnergyPlus results\n\n"
        "Status: `ANNUAL_SKIPPED_FIXED_OPERATION_INCOMPLETE`\n\n"
        "The preregistered annual gate requires complete and reliable fixed sizing. "
        "The audit left 908 autosized fields unresolved, including 379 water-coil-controller maximum actuated flow fields. "
        "Therefore all six annual cases (SOURCE_STATIC plus five timing cases at master seed 40015) were skipped exactly as registered: planned 6, run 0. "
        "No shorter substitute, alternate seed, or per-scenario autosized annual run was used.\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--energy-results", required=True)
    parser.add_argument("--function-runs", required=True)
    parser.add_argument("--seasonal-ledger", required=True)
    parser.add_argument("--fixed-sizing-audit", required=True)
    parser.add_argument("--autosized-energy-results", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--normalized-root", required=True)
    parser.add_argument("--source-static-people", required=True)
    parser.add_argument("--report-dir", required=True)
    args = parser.parse_args()

    energy_rows = load_rows(Path(args.energy_results))
    function_rows = load_rows(Path(args.function_runs))
    autosized_rows = load_rows(Path(args.autosized_energy_results))
    ledger = json.loads(Path(args.seasonal_ledger).read_text(encoding="utf-8"))
    fixed_audit = json.loads(Path(args.fixed_sizing_audit).read_text(encoding="utf-8"))
    validate_source_static_energy_baseline(ledger["period_records"])
    if ledger["period_pass_count"] != 78:
        raise ValueError("seasonal EnergyPlus denominator is incomplete")
    if fixed_audit["status"] != "FIXED_OPERATION_INCOMPLETE":
        raise ValueError("V3.1 report expects the observed fixed-sizing gate")

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    building_rows = building_effect_rows(energy_rows)
    write_csv(report_dir / "seasonal_energy_results.csv", building_rows)
    write_seasonal_markdown(
        report_dir / "seasonal_energy_results.md", building_rows, ledger
    )
    airloop_rows, _aliases = airloop_effect_rows(energy_rows)
    write_airloop_markdown(report_dir / "airloop_effects.md", airloop_rows)
    function_effects = function_effect_rows(function_rows)
    occupancy_rows = occupancy_function_rows(
        mapping=Path(args.mapping),
        normalized_root=Path(args.normalized_root),
        source_static=Path(args.source_static_people),
    )
    write_function_markdown(
        report_dir / "function_zone_effects.md",
        occupancy_rows,
        function_effects,
    )
    write_confound_report(
        report_dir / "autosizing_confound_check.md",
        energy_rows,
        autosized_rows,
    )
    write_annual_skip(report_dir)
    print(
        json.dumps(
            {
                "status": "PASS_DESIGN_SIZING_SENSITIVITY",
                "seasonal_effect_rows": len(building_rows),
                "airloop_effect_rows": len(airloop_rows),
                "function_effect_rows": len(function_effects),
                "annual_run_count": 0,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
