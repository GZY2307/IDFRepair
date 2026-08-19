#!/usr/bin/env python3
"""Generate compact, source-bounded Airport ABM V3 occupancy reports."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import gzip
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.reporting import (  # noqa: E402
    assert_matched_person_hours,
    quantile,
)


TIMING = (
    "BASELINE_SPREAD",
    "MORNING_BANK",
    "MIDDAY_BANK",
    "EVENING_BANK",
    "DOUBLE_BANK",
)
COMPOSITION = (
    "DEPARTURE_DOMINANT",
    "ARRIVAL_DOMINANT",
    "TRANSFER_DOMINANT",
    "INTERNATIONAL_BOUNDARY_DOMINANT",
)
VOLUME = ("VOLUME_0P50", "VOLUME_0P75", "VOLUME_1P00", "VOLUME_1P25", "VOLUME_1P50")
DWELL = ("WAIT_SHORT", "WAIT_MEDIUM", "WAIT_LONG")
LABELS = {
    "BASELINE_SPREAD": "Baseline spread",
    "MORNING_BANK": "Morning bank",
    "MIDDAY_BANK": "Midday bank",
    "EVENING_BANK": "Evening bank",
    "DOUBLE_BANK": "Double bank",
    "DEPARTURE_DOMINANT": "Departure dominant",
    "ARRIVAL_DOMINANT": "Arrival dominant",
    "TRANSFER_DOMINANT": "Transfer dominant",
    "INTERNATIONAL_BOUNDARY_DOMINANT": "International boundary",
    "VOLUME_0P50": "0.50x",
    "VOLUME_0P75": "0.75x",
    "VOLUME_1P00": "1.00x",
    "VOLUME_1P25": "1.25x",
    "VOLUME_1P50": "1.50x",
    "WAIT_SHORT": "Short wait",
    "WAIT_MEDIUM": "Medium wait",
    "WAIT_LONG": "Long wait",
}


def stats(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("statistics require values")
    return {
        "n": len(values),
        "mean": sum(values) / len(values),
        "p10": quantile(values, 0.10),
        "p50": quantile(values, 0.50),
        "p90": quantile(values, 0.90),
        "minimum": min(values),
        "maximum": max(values),
    }


def load_detail(root: Path, scenario: str, seed: int) -> dict[str, object]:
    path = root / "seed_details" / scenario / f"seed-{seed}.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def grouped_summary(rows: list[dict[str, str]], metric: str) -> dict[str, dict[str, float]]:
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        values[row["scenario_id"]].append(float(row[metric]))
    return {scenario: stats(items) for scenario, items in values.items()}


def profile_metrics(profile: list[float]) -> dict[str, float]:
    return {
        "daily_mean_occupancy": sum(profile) / len(profile),
        "daily_peak_occupancy": max(profile),
        "person_hours": sum(profile) * 0.25,
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "scenario_id",
        "family",
        "scope",
        "group",
        "metric",
        "n",
        "mean",
        "p10",
        "p50",
        "p90",
        "minimum",
        "maximum",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def add_stat_row(
    output: list[dict[str, object]],
    *,
    scenario: str,
    family: str,
    scope: str,
    group: str,
    metric: str,
    values: list[float],
) -> None:
    output.append(
        {
            "scenario_id": scenario,
            "family": family,
            "scope": scope,
            "group": group,
            "metric": metric,
            **stats(values),
        }
    )


def build_aggregate_rows(
    abm_root: Path,
    summary_rows: list[dict[str, str]],
    private_output: Path,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    by_scenario: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in summary_rows:
        by_scenario[row["scenario_id"]].append(row)
    for scenario, rows in sorted(by_scenario.items()):
        family = rows[0]["family"]
        for metric in (
            "whole_building_peak_occupancy",
            "peak_function_occupancy",
            "public_person_hours_bem",
            "staff_person_hours_bem",
            "tracked_person_hours_including_flow_only",
        ):
            add_stat_row(
                output,
                scenario=scenario,
                family=family,
                scope="building",
                group="all_spaces",
                metric=metric,
                values=[float(row[metric]) for row in rows],
            )

    profiles: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    space_profiles: dict[tuple[str, str], list[float]] = defaultdict(list)
    for scenario in TIMING:
        for seed in range(40001, 40031):
            detail = load_detail(abm_root, scenario, seed)
            for scope, key in (
                ("function", "function_counts"),
                ("region", "region_counts"),
                ("hvac_group", "hvac_group_counts"),
            ):
                for group, profile in detail[key].items():
                    for metric, value in profile_metrics(profile).items():
                        profiles[(scenario, scope, group, metric)].append(value)
            if scenario == "BASELINE_SPREAD":
                for space, profile in detail["space_counts"].items():
                    metrics = profile_metrics(profile)
                    space_profiles[(space, "daily_mean_occupancy")].append(
                        metrics["daily_mean_occupancy"]
                    )
                    space_profiles[(space, "daily_peak_occupancy")].append(
                        metrics["daily_peak_occupancy"]
                    )
                    space_profiles[(space, "person_hours")].append(
                        metrics["person_hours"]
                    )
    for (scenario, scope, group, metric), values in sorted(profiles.items()):
        add_stat_row(
            output,
            scenario=scenario,
            family="timing",
            scope=scope,
            group=group,
            metric=metric,
            values=values,
        )

    private_output.parent.mkdir(parents=True, exist_ok=True)
    with private_output.open("w", encoding="utf-8", newline="") as handle:
        fields = (
            "source_space_name",
            "metric",
            "n",
            "mean",
            "p10",
            "p50",
            "p90",
            "minimum",
            "maximum",
        )
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for (space, metric), values in sorted(space_profiles.items()):
            writer.writerow(
                {"source_space_name": space, "metric": metric, **stats(values)}
            )
    return output


def lookup(
    aggregate: list[dict[str, object]],
    scenario: str,
    scope: str,
    group: str,
    metric: str,
) -> dict[str, object]:
    matches = [
        row
        for row in aggregate
        if row["scenario_id"] == scenario
        and row["scope"] == scope
        and row["group"] == group
        and row["metric"] == metric
    ]
    if len(matches) != 1:
        raise ValueError(f"aggregate lookup failed: {scenario}:{scope}:{group}:{metric}")
    return matches[0]


def fmt(value: object, digits: int = 1) -> str:
    return f"{float(value):,.{digits}f}"


def write_validation(path: Path, rows: list[dict[str, str]]) -> None:
    scenarios = sorted({row["scenario_id"] for row in rows})
    seeds = sorted({int(row["seed"]) for row in rows})
    simulated = sum(int(row["simulated_agents"]) for row in rows)
    spawned = sum(int(row["spawn_count"]) for row in rows)
    terminal = sum(int(row["terminal_count"]) for row in rows)
    active = sum(int(row["active_count"]) for row in rows)
    violations = sum(int(row["violation_count"]) for row in rows)
    invalid = sum(int(row["invalid_route_count"]) for row in rows)
    offices = sum(int(row["passenger_office_violations"]) for row in rows)
    text = f"""# Airport Occupancy V3 — ABM Validation

## Result

All {len(rows)} pre-registered seed–scenario runs passed the hard route and
conservation gate. The run set contains {len(scenarios)} scenarios and
{len(seeds)} seeds per scenario (`40001..40030`).

| Check | Result |
|---|---:|
| Representative agents simulated | {simulated:,} |
| Spawned | {spawned:,} |
| Boarded/exited/staff-terminal | {terminal:,} |
| Active after horizon | {active:,} |
| Hard violations | {violations:,} |
| Invalid routes | {invalid:,} |
| Passenger-through-office violations | {offices:,} |

The equality `spawned = terminal` and zero final active agents establishes
agent conservation for this experiment matrix. Validation also enforces
domestic-departure boarding, domestic-arrival baggage-before-exit,
domestic-transfer no-baggage behavior, international Level-1 boundary exit,
role-specific access, detour return to anchor, and boarding deadlines.

## Claim boundary

Passing these checks proves internal route logic and bookkeeping consistency;
it does not validate controlled dwell/choice inputs or forecast measured airport
throughput. Every scenario therefore remains `CONTROLLED_NOT_MEASURED`.
"""
    path.write_text(text, encoding="utf-8")


def timing_table(
    peak: dict[str, dict[str, float]],
    public_person_hours: dict[str, dict[str, float]],
) -> str:
    lines = [
        "| Timing scenario | Public person-hours/day P50 | Peak P10 | Peak P50 | Peak P90 |",
        "|---|---:|---:|---:|---:|",
    ]
    for scenario in TIMING:
        row = peak[scenario]
        lines.append(
            f"| {LABELS[scenario]} | {fmt(public_person_hours[scenario]['p50'])} | "
            f"{fmt(row['p10'])} | "
            f"{fmt(row['p50'])} | {fmt(row['p90'])} |"
        )
    return "\n".join(lines)


def write_occupancy_report(
    path: Path,
    rows: list[dict[str, str]],
    aggregate: list[dict[str, object]],
) -> None:
    peak = grouped_summary(rows, "whole_building_peak_occupancy")
    public_person_hours = grouped_summary(rows, "public_person_hours_bem")
    staff_person_hours = grouped_summary(rows, "staff_person_hours_bem")
    baseline = peak["BASELINE_SPREAD"]["p50"]
    timing_ratios = {
        scenario: peak[scenario]["p50"] / baseline for scenario in TIMING[1:]
    }
    wait = {scenario: peak[scenario]["p50"] for scenario in DWELL}
    volume = {scenario: peak[scenario]["p50"] for scenario in VOLUME}
    base_gate = lookup(
        aggregate,
        "BASELINE_SPREAD",
        "function",
        "domestic_waiting",
        "daily_peak_occupancy",
    )
    text = f"""# Airport Occupancy V3 — Occupancy Results

## Technical summary

The directed ABM changes **where and when** a fixed daily public occupancy
integral appears. For each seed, all five timing cases retain exactly matched
public and staff person-hours. Across the 30 stochastic seeds, public
person-hours/day have a median of
{fmt(public_person_hours['BASELINE_SPREAD']['p50'])} (range
{fmt(public_person_hours['BASELINE_SPREAD']['minimum'])}–
{fmt(public_person_hours['BASELINE_SPREAD']['maximum'])}); staff person-hours/day
remain {fmt(staff_person_hours['BASELINE_SPREAD']['p50'])}. The median
whole-building 15-minute peak rises from {fmt(baseline)} in the spread case to
{fmt(peak['MORNING_BANK']['p50'])}, {fmt(peak['MIDDAY_BANK']['p50'])}, and
{fmt(peak['EVENING_BANK']['p50'])} in the concentrated morning, midday, and
evening cases. These are controlled stress distributions, not ordinary
morning/noon/evening head-count sensitivity and not measured airport forecasts.

## Same passenger-hours produce different peaks

{timing_table(peak, public_person_hours)}

Relative to the spread median, the morning, midday, evening, and double-bank
median peaks are {timing_ratios['MORNING_BANK']:.2f}x,
{timing_ratios['MIDDAY_BANK']:.2f}x,
{timing_ratios['EVENING_BANK']:.2f}x, and
{timing_ratios['DOUBLE_BANK']:.2f}x. Figure
`figures/timing_profiles_seed40015.png` shows the complete 96-point profiles,
while `figures/timing_peak_uncertainty.png` shows the 30-seed P10–P90 intervals.

## Function-level concentration is explicit

The baseline domestic-waiting peak has a median of
{fmt(base_gate['p50'])} occupants across the 30 seeds (P10
{fmt(base_gate['p10'])}, P90 {fmt(base_gate['p90'])}). The category, region, and
HVAC-group rows in `occupancy_results.csv` preserve the same statistics without
publishing Space names; exact Space-level uncertainty stays in the private
analysis directory.

## Volume and dwell change different mechanisms

The volume matrix changes passenger arrivals while keeping staff fixed. Its
whole-building peak median spans {fmt(min(volume.values()))}–{fmt(max(volume.values()))}
from 0.50x to 1.50x. The gate-wait matrix holds the route structure and volume
fixed; its median peak spans {fmt(min(wait.values()))}–{fmt(max(wait.values()))}.
The paired panels in `figures/volume_and_dwell_sensitivity.png` keep these two
mechanisms separate.

## Interpretation limit

The official 2025 airport-wide passenger total provides throughput context, but
mapping that airport-wide total into this simplified second-floor BEM is a
controlled Level-2 assumption rather than measured floor, route, gate, or
15-minute demand. The source static People schedules retain the staff target.
Dwell, choice, class mix, and timing-bank shapes remain
`CONTROLLED_NOT_MEASURED`; therefore these results support mechanism and
sensitivity analysis only. Energy conclusions are reported separately after
EnergyPlus stability and output-contract checks.
"""
    path.write_text(text, encoding="utf-8")


def write_uncertainty(path: Path, rows: list[dict[str, str]]) -> None:
    peak = grouped_summary(rows, "whole_building_peak_occupancy")
    lines = [
        "# Airport Occupancy V3 — Stochastic Uncertainty",
        "",
        "## Result",
        "",
        "Thirty pre-registered seeds were retained for every scenario. The table",
        "reports seed uncertainty in the 15-minute whole-building peak; it does not",
        "represent uncertainty in measured airport behavior.",
        "",
        "| Scenario | Family | P10 | P50 | P90 | Minimum | Maximum |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    family = {row["scenario_id"]: row["family"] for row in rows}
    order = (*TIMING, *COMPOSITION, *VOLUME, *DWELL, "DETOUR_LOW", "DETOUR_BASE", "DETOUR_HIGH")
    for scenario in order:
        row = peak[scenario]
        lines.append(
            f"| {LABELS.get(scenario, scenario.replace('_', ' ').title())} | "
            f"{family[scenario]} | {fmt(row['p10'])} | {fmt(row['p50'])} | "
            f"{fmt(row['p90'])} | {fmt(row['minimum'])} | {fmt(row['maximum'])} |"
        )
    lines.extend(
        [
            "",
            "## Robustness boundary",
            "",
            "The timing cases are paired by seed and exactly matched on BEM public and",
            "staff person-hours. Seed spread therefore reflects stochastic route, gate,",
            "dwell, and detour realization under fixed controlled inputs. Parameter",
            "uncertainty is represented separately by the dwell, volume, composition, and",
            "discretionary sensitivity families; no posterior calibration or energy-result",
            "tuning was performed.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_figures(
    output: Path,
    abm_root: Path,
    rows: list[dict[str, str]],
    aggregate: list[dict[str, object]],
) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    output.mkdir(parents=True, exist_ok=True)
    colors = ["#185FA5", "#D29E00", "#E46C2B", "#667A2C", "#B04A7A"]
    linestyles = ["-", "--", "-.", ":", (0, (5, 2))]
    markers = ["o", "s", "^", "D", "P"]
    hours = np.arange(96) / 4

    fig, ax = plt.subplots(figsize=(10.5, 5.8), constrained_layout=True)
    for index, scenario in enumerate(TIMING):
        detail = load_detail(abm_root, scenario, 40015)
        profile = np.sum(np.array(list(detail["space_counts"].values())), axis=0)
        ax.plot(
            hours,
            profile,
            label=LABELS[scenario],
            color=colors[index],
            linestyle=linestyles[index],
            linewidth=2,
            marker=markers[index],
            markevery=8,
            markersize=4,
        )
    ax.set_title("Whole-building occupancy profiles", loc="left", pad=34)
    ax.text(
        0,
        1.012,
        "Seed 40015; 15-minute intervals; matched daily public and staff person-hours",
        transform=ax.transAxes,
        color="#525A61",
        fontsize=9,
    )
    ax.set(xlabel="Hour of day", ylabel="Occupants in BEM-supported Spaces", xlim=(0, 24))
    ax.grid(axis="y", color="#D9DEE3", linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(ncol=3, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.16))
    fig.savefig(output / "timing_profiles_seed40015.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    peak = grouped_summary(rows, "whole_building_peak_occupancy")
    x = np.arange(len(TIMING))
    medians = np.array([peak[scenario]["p50"] for scenario in TIMING])
    lower = medians - np.array([peak[scenario]["p10"] for scenario in TIMING])
    upper = np.array([peak[scenario]["p90"] for scenario in TIMING]) - medians
    fig, ax = plt.subplots(figsize=(9.5, 5.5), constrained_layout=True)
    ax.errorbar(
        x,
        medians,
        yerr=np.vstack([lower, upper]),
        fmt="o",
        color="#185FA5",
        ecolor="#33404D",
        capsize=5,
        linewidth=1.5,
        markersize=7,
    )
    ax.set_title("Whole-building peak occupancy uncertainty", loc="left", pad=34)
    ax.text(0, 1.012, "Median and P10–P90 across 30 pre-registered seeds", transform=ax.transAxes, color="#525A61", fontsize=9)
    ax.set_xticks(x, [LABELS[s] for s in TIMING], rotation=18, ha="right")
    ax.set_ylabel("15-minute peak occupants")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color="#D9DEE3", linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(output / "timing_peak_uncertainty.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    functions = ("departure_entry", "central_hall", "concourse", "domestic_waiting", "baggage_claim", "arrival_exit", "international_arrival", "office")
    matrix = np.array(
        [
            [
                float(lookup(aggregate, scenario, "function", group, "daily_peak_occupancy")["p50"])
                for group in functions
            ]
            for scenario in TIMING
        ]
    )
    fig, ax = plt.subplots(figsize=(11, 5.8), constrained_layout=True)
    image = ax.imshow(matrix, aspect="auto", cmap="Blues")
    ax.set_title("Median function-level peak occupancy", loc="left", pad=34)
    ax.text(0, 1.012, "P50 across 30 seeds; controlled timing cases", transform=ax.transAxes, color="#525A61", fontsize=9)
    ax.set_xticks(np.arange(len(functions)), [name.replace("_", " ") for name in functions], rotation=25, ha="right")
    ax.set_yticks(np.arange(len(TIMING)), [LABELS[s] for s in TIMING])
    fig.colorbar(image, ax=ax, label="Peak occupants")
    fig.savefig(output / "function_peak_matrix.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    peak = grouped_summary(rows, "whole_building_peak_occupancy")
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), constrained_layout=True)
    for ax, scenarios, title, color in (
        (axes[0], VOLUME, "Passenger-volume sensitivity", "#185FA5"),
        (axes[1], DWELL, "Gate-wait sensitivity", "#D29E00"),
    ):
        values = [peak[s]["p50"] for s in scenarios]
        lo = [peak[s]["p50"] - peak[s]["p10"] for s in scenarios]
        hi = [peak[s]["p90"] - peak[s]["p50"] for s in scenarios]
        y = np.arange(len(scenarios))
        ax.barh(y, values, color=color, edgecolor="#33404D", linewidth=0.8)
        ax.errorbar(values, y, xerr=np.vstack([lo, hi]), fmt="none", ecolor="#33404D", capsize=3)
        ax.set_yticks(y, [LABELS[s] for s in scenarios])
        ax.invert_yaxis()
        ax.set_xlim(left=0)
        ax.set_xlabel("Median 15-minute peak occupants")
        ax.set_title(title)
        ax.grid(axis="x", color="#D9DEE3", linewidth=0.7)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Whole-building peak sensitivity", fontsize=14)
    fig.savefig(output / "volume_and_dwell_sensitivity.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_chart_map(path: Path) -> None:
    path.write_text(
        """# Occupancy V3 Chart Map

| Report segment | Analytical question | Family / type | Fields | Claim supported | Palette / non-color cue | Artifact |
|---|---|---|---|---|---|---|
| Same passenger-hours | How does the full daily profile move under timing banks? | Trend / highlighted multi-series line | hour, BEM occupant count, scenario | Timing redistributes the same daily integral | Five bounded roots plus distinct line styles and markers | `figures/timing_profiles_seed40015.png` |
| Seed uncertainty | Does the peak ordering survive stochastic seeds? | Uncertainty / point interval | scenario, P10, P50, P90, n=30 | Concentrated timing peaks exceed spread timing across seed intervals | Single blue root, dark interval bars | `figures/timing_peak_uncertainty.png` |
| Spatial concentration | Which process functions carry the timing peak? | Matrix / heatmap | scenario, function, peak P50 | Domestic waiting and public-process functions are affected unevenly | Single blue sequential scale plus labelled axes | `figures/function_peak_matrix.png` |
| Parameter sensitivities | Do volume and dwell alter the same mechanism? | Comparison / paired horizontal bars | scenario, peak P10/P50/P90 | Volume and gate dwell remain separate sensitivity families | Blue versus gold roots, direct category labels, interval bars | `figures/volume_and_dwell_sensitivity.png` |

All charts use controlled simulations rather than measured throughput. Absolute bar scales start at zero; timing trends retain all 96 intervals. Source data are the validated 600-row seed summary and selected source-bounded aggregate profiles.
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--abm-root", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--private-space-output", required=True)
    args = parser.parse_args()
    abm_root = Path(args.abm_root)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    with (abm_root / "seed_summaries.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 600:
        raise SystemExit(f"expected 600 seed rows, found {len(rows)}")
    if any(row["validation_status"] != "PASS" for row in rows):
        raise SystemExit("ABM validation gate failed")
    for value_field in ("public_person_hours_bem", "staff_person_hours_bem"):
        assert_matched_person_hours(
            rows,
            scenario_ids=TIMING,
            value_field=value_field,
            tolerance=1e-6,
        )
    aggregate = build_aggregate_rows(abm_root, rows, Path(args.private_space_output))
    write_csv(report_dir / "occupancy_results.csv", aggregate)
    write_validation(report_dir / "abm_validation.md", rows)
    write_occupancy_report(report_dir / "occupancy_results.md", rows, aggregate)
    write_uncertainty(report_dir / "uncertainty_results.md", rows)
    make_figures(report_dir / "figures", abm_root, rows, aggregate)
    write_chart_map(report_dir / "chart_map.md")
    print(
        json.dumps(
            {
                "status": "PASS",
                "seed_rows": len(rows),
                "aggregate_rows": len(aggregate),
                "figure_count": 4,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
