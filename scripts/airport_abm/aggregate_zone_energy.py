#!/usr/bin/env python3
"""Aggregate private Zone outputs into public-safe function/region/HVAC groups."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import sys
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.reporting import quantile  # noqa: E402


DIMENSIONS = ("function", "region", "hvac_group")
TIMING_SCENARIOS = (
    "MORNING_BANK",
    "MIDDAY_BANK",
    "EVENING_BANK",
    "DOUBLE_BANK",
)


def load_mapping(path: Path) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            zone = row["thermal_zone"].strip()
            if not zone or zone in output:
                raise ValueError("zone-function mapping is not one-to-one")
            hvac = (
                row.get("public_air_loop", "").strip()
                or row.get("office_doas", "").strip()
                or "zone_only"
            )
            output[zone] = {
                "function": row["function"].strip(),
                "region": row["region"].strip(),
                "hvac_group": hvac,
                "area_m2": float(row["area_m2"]),
            }
    if not output:
        raise ValueError("zone-function mapping is empty")
    return output


def load_zone_rows(path: Path) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            output.append(
                {
                    **row,
                    "seed": int(row["seed"]) if row["seed"] else None,
                    "value": float(row["value"]),
                }
            )
    return output


def reducer(metric: str) -> tuple[str, str] | None:
    if metric.endswith("_kwh"):
        return metric, "sum"
    if metric == "outdoor_air_mean_m3_s":
        return metric, "sum"
    if metric.endswith("_interval_peak_kw"):
        return f"maximum_zone_{metric}", "maximum"
    if metric.endswith("_mean_c") or metric.endswith("_mean_percent"):
        return metric, "area_weighted_mean"
    if "_minimum_" in metric:
        return metric, "minimum"
    if "_maximum_" in metric:
        return metric, "maximum"
    return None


def mapping_lookup(
    mapping: Mapping[str, Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    """Build the case-insensitive lookup used by EnergyPlus output keys."""

    output: dict[str, Mapping[str, object]] = {}
    for name, row in mapping.items():
        key = name.strip().casefold()
        if not key or (key in output and output[key] is not row):
            raise ValueError("zone-function mapping has an ambiguous name")
        output[key] = row
    return output


def resolve_mapping(
    group: str,
    metric: str,
    lookup: Mapping[str, Mapping[str, object]],
) -> Mapping[str, object] | None:
    key = group.strip().casefold()
    if key in lookup:
        return lookup[key]
    if metric.startswith("outdoor_air_"):
        for suffix in ("-vav", "-doas"):
            if key.endswith(suffix) and key[: -len(suffix)] in lookup:
                return lookup[key[: -len(suffix)]]
    return None


def aggregate_mapped_runs(
    rows: list[dict[str, object]],
    mapping: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    values: dict[tuple[object, ...], list[tuple[float, float]]] = defaultdict(list)
    methods: dict[tuple[object, ...], str] = {}
    lookup = mapping_lookup(mapping)
    for row in rows:
        if row["scope"] != "thermal_zone":
            continue
        zone = str(row["group"])
        mapped = resolve_mapping(zone, str(row["metric"]), lookup)
        if mapped is None:
            raise ValueError(f"zone result is not mapped: {zone}")
        reduction = reducer(str(row["metric"]))
        if reduction is None:
            continue
        output_metric, method = reduction
        value = float(row["value"])
        if not math.isfinite(value):
            raise ValueError("zone result is not finite")
        for dimension in DIMENSIONS:
            identity = (
                row["scenario_id"],
                row["seed"],
                row["run_kind"],
                row["period_id"],
                dimension,
                mapped[dimension],
                output_metric,
                row["unit"],
            )
            values[identity].append((value, float(mapped["area_m2"])))
            methods[identity] = method
    output: list[dict[str, object]] = []
    for identity in sorted(values, key=repr):
        method = methods[identity]
        pairs = values[identity]
        if method == "sum":
            value = sum(item for item, _area in pairs)
        elif method == "maximum":
            value = max(item for item, _area in pairs)
        elif method == "minimum":
            value = min(item for item, _area in pairs)
        elif method == "area_weighted_mean":
            total_area = sum(area for _item, area in pairs)
            if total_area <= 0:
                raise ValueError("mapped Zone area must be positive")
            value = sum(item * area for item, area in pairs) / total_area
        else:
            raise AssertionError(method)
        output.append(
            {
                "scenario_id": identity[0],
                "seed": identity[1],
                "run_kind": identity[2],
                "period_id": identity[3],
                "scope": identity[4],
                "group": identity[5],
                "metric": identity[6],
                "value": value,
                "unit": identity[7],
                "aggregation": method,
            }
        )
    return output


def summarize_runs(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[object, ...], list[float]] = defaultdict(list)
    aggregations: dict[tuple[object, ...], str] = {}
    for row in rows:
        identity = (
            row["scenario_id"],
            row["run_kind"],
            row["period_id"],
            row["scope"],
            row["group"],
            row["metric"],
            row["unit"],
        )
        grouped[identity].append(float(row["value"]))
        aggregations[identity] = str(row["aggregation"])
    output: list[dict[str, object]] = []
    for identity in sorted(grouped, key=repr):
        values = grouped[identity]
        output.append(
            {
                "scenario_id": identity[0],
                "run_kind": identity[1],
                "period_id": identity[2],
                "scope": identity[3],
                "group": identity[4],
                "metric": identity[5],
                "n": len(values),
                "p10": quantile(values, 0.10),
                "p50": quantile(values, 0.50),
                "p90": quantile(values, 0.90),
                "unit": identity[6],
                "aggregation": aggregations[identity],
            }
        )
    return output


def maximum_timing_effects(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    indexed = {
        (
            row["scenario_id"],
            row["seed"],
            row["run_kind"],
            row["period_id"],
            row["scope"],
            row["group"],
            row["metric"],
        ): float(row["value"])
        for row in rows
    }
    identities = sorted(
        {
            (row["run_kind"], row["period_id"], row["scope"], row["group"], row["metric"], row["unit"])
            for row in rows
            if row["scenario_id"] == "BASELINE_SPREAD"
        },
        key=repr,
    )
    output: list[dict[str, object]] = []
    for scenario in TIMING_SCENARIOS:
        candidates: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
        for run_kind, period, scope, group, metric, unit in identities:
            seeds = sorted(
                {
                    int(row["seed"])
                    for row in rows
                    if row["seed"] is not None
                    and row["scenario_id"] == "BASELINE_SPREAD"
                    and row["run_kind"] == run_kind
                    and row["period_id"] == period
                    and row["scope"] == scope
                    and row["group"] == group
                    and row["metric"] == metric
                }
                & {
                    int(row["seed"])
                    for row in rows
                    if row["seed"] is not None
                    and row["scenario_id"] == scenario
                    and row["run_kind"] == run_kind
                    and row["period_id"] == period
                    and row["scope"] == scope
                    and row["group"] == group
                    and row["metric"] == metric
                }
            )
            differences = []
            percentages = []
            for seed in seeds:
                base = indexed.get(("BASELINE_SPREAD", seed, run_kind, period, scope, group, metric))
                value = indexed.get((scenario, seed, run_kind, period, scope, group, metric))
                if base is None or value is None:
                    continue
                differences.append(value - base)
                if abs(base) > 1e-12:
                    percentages.append((value - base) / base * 100.0)
            if not differences:
                continue
            row = {
                "scenario_id": scenario,
                "run_kind": run_kind,
                "period_id": period,
                "scope": scope,
                "group": group,
                "metric": metric,
                "paired_seed_count": len(differences),
                "difference_p50": quantile(differences, 0.50),
                "percent_p50": (
                    quantile(percentages, 0.50)
                    if len(percentages) == len(differences)
                    else None
                ),
                "unit": unit,
            }
            candidates[(run_kind, period, scope, metric)].append(row)
        for candidate_rows in candidates.values():
            output.append(
                max(candidate_rows, key=lambda item: abs(float(item["difference_p50"])))
            )
    return sorted(output, key=lambda row: (str(row["period_id"]), str(row["scope"]), str(row["metric"]), str(row["scenario_id"])))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
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
        "aggregation",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, effects: list[dict[str, object]]) -> None:
    fixed_seed_demo = bool(effects) and max(
        int(row["paired_seed_count"]) for row in effects
    ) == 1
    lines = [
        "# Airport Occupancy V3 — Zone/Function/HVAC Load Redistribution",
        "",
        (
            "Status: `PASS_CONTROLLED_REPRESENTATIVE_DAY_DEMO`"
            if fixed_seed_demo
            else "Status: `PASS_PAIRED_SENSITIVITY`"
        ),
        "",
        "The table selects the public-safe function, region, or HVAC group with the largest absolute paired effect for each metric. Energy is summed across member Zones. A reported peak is the maximum individual Zone peak, not a falsely summed coincident peak.",
        "",
        "| Period | Scenario | Pairs | Scope | Group | Metric | Paired difference | Paired percent |",
        "|---|---|---:|---|---|---|---:|---:|",
    ]
    for row in effects:
        percent = "—" if row["percent_p50"] is None else f"{float(row['percent_p50']):.2f}%"
        lines.append(
            f"| {row['period_id']} | {row['scenario_id']} | {int(row['paired_seed_count'])} | {row['scope']} | {row['group']} | {row['metric']} | {float(row['difference_p50']):,.3f} {row['unit']} | {percent} |"
        )
    lines.extend(
        [
            "",
            "Temperature and relative-humidity means are area-weighted. Outdoor-air means and extensive heat/energy quantities are summed. A one-pair table is a fixed-seed mechanism demo, not uncertainty evidence. These are controlled model responses, not measured airport conditions.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zone-results", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()
    runs = aggregate_mapped_runs(
        load_zone_rows(Path(args.zone_results)),
        load_mapping(Path(args.mapping)),
    )
    summary = summarize_runs(runs)
    effects = maximum_timing_effects(runs)
    write_csv(Path(args.output), summary)
    write_markdown(Path(args.markdown_output), effects)
    print(
        json.dumps(
            {
                "status": "PASS",
                "run_rows": len(runs),
                "summary_rows": len(summary),
                "maximum_effect_rows": len(effects),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
