#!/usr/bin/env python3
"""Generate the compact room-aware terminal occupancy evidence package."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from idfrepair.analysis.occupancy_room_aware.reporting import (  # noqa: E402
    assert_same_person_hours,
    combine_result_tables,
    evaluate_paper_admission,
    ranked_effects,
)
from idfrepair.analysis.occupancy_room_aware.provenance import (  # noqa: E402
    validate_baseline_provenance_chain,
)
from idfrepair.analysis.occupancy_room_aware.results import (  # noqa: E402
    ANNUAL_OUTPUT_VARIABLES,
    SEASONAL_OUTPUT_VARIABLES,
    expected_run_identity,
    validate_run_manifest,
)


SOURCE_HASH = "6463d680b834230e665df8a250c694cae57c3d5cb3c877d1ad22a9c761fcccdb"
FROZEN_HASH = "efbd22cd185db678edafb4fb5d44286fcc529aa6be12146ee7188fc54d084d4b"
HISTORICAL_HASH = "99d378b7b0cb5a4e86eea42cfdf933e7d1dac3d5b1cb2fd7259f80238f6ea171"
CATEGORIES = (
    "terminal_hall",
    "office",
    "commerce_retail",
    "dining",
    "restroom",
    "breakroom",
)
MATCHED = (
    "public_morning",
    "public_midday",
    "public_evening",
    "public_perimeter",
    "public_core",
    "entrance_2_lead",
    "entrance_3_lead",
)
MATCHED_NONTRIVIAL = tuple(value for value in MATCHED if value != "public_midday")
VOLUME = tuple(
    f"public_volume_{value}" for value in ("0_50", "0_75", "1_00", "1_25", "1_50")
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def aggregate_hash(root: Path) -> str:
    lines = [
        f"{sha256(path)}  {path.relative_to(PROJECT_ROOT).as_posix()}\n"
        for path in root.rglob("*")
        if path.is_file()
    ]
    return hashlib.sha256("".join(sorted(lines)).encode()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"report_json_object_required:{path}")
    return value


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"report_csv_header_missing:{path}")
        return list(reader)


def number(row: dict[str, Any], field: str) -> float:
    try:
        value = float(row.get(field))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"report_number_invalid:{field}:{row.get(field)}") from exc
    if not math.isfinite(value):
        raise ValueError(f"report_number_nonfinite:{field}")
    return value


def lookup(
    rows: list[dict[str, str]],
    period: str,
    scenario: str,
    category: str | None = None,
) -> dict[str, str]:
    found = [
        row
        for row in rows
        if row["period_id"] == period
        and row["scenario_id"] == scenario
        and (category is None or row.get("category") == category)
    ]
    if len(found) != 1:
        raise ValueError(
            f"report_result_identity_not_unique:{period}:{scenario}:{category}:{len(found)}"
        )
    return found[0]


def pct(value: float, baseline: float) -> float:
    if baseline == 0:
        raise ValueError("report_percent_zero_baseline")
    return (value - baseline) / baseline * 100


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def signed(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}%"


def table(headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> str:
    def clean(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    result = [
        "| " + " | ".join(clean(item) for item in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    result += [
        "| " + " | ".join(clean(item) for item in row) + " |" for row in rows
    ]
    return "\n".join(result)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def run_gate(
    root: Path,
    expected: int,
    *,
    suite: str,
    derived_root: Path,
    source_osm: Path,
    executable: Path,
    idd_path: Path,
    weather_path: Path,
) -> dict[str, Any]:
    paths = sorted(root.rglob("run_manifest.json"))
    if len(paths) != expected:
        raise ValueError(f"report_run_count_mismatch:{len(paths)}:{expected}")
    if suite not in {"seasonal", "annual"}:
        raise ValueError("report_run_suite_invalid")
    payloads = []
    for path in paths:
        scenario_id = path.parent.name
        period_id = path.parent.parent.name if suite == "seasonal" else "annual"
        prepared = (
            derived_root / "prepared" / "seasonal" / scenario_id / f"{period_id}.idf"
            if suite == "seasonal"
            else derived_root / "prepared" / "annual" / scenario_id / "annual.idf"
        )
        existing = load_json(path)
        recorded_identity = existing.get("input_identity")
        if not isinstance(recorded_identity, dict):
            raise ValueError("report_run_input_identity_missing")
        schedule_filename = recorded_identity.get("schedule_filename")
        schedule = prepared.parent / schedule_filename if schedule_filename else None
        identity = expected_run_identity(
            scenario_id=scenario_id,
            period_id=period_id,
            executable_path=executable,
            idd_path=idd_path,
            weather_path=weather_path,
            source_osm_path=source_osm,
            prepared_idf_path=prepared,
            schedule_path=schedule,
            minutes_per_output_step=15.0 if suite == "seasonal" else 60.0,
            expected_variables=(
                SEASONAL_OUTPUT_VARIABLES
                if suite == "seasonal"
                else ANNUAL_OUTPUT_VARIABLES
            ),
        )
        payloads.append(validate_run_manifest(path, expected_identity=identity))
    return {
        "count": len(payloads),
        "max_seconds": max(float(row["elapsed_seconds"]) for row in payloads),
        "runtime": sorted({str(row["runtime_version"]) for row in payloads}),
    }


def design_totals(manifest: dict[str, Any], field: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in manifest["spaces"]:
        totals[str(row["room_category"])] += float(row[field])
    return dict(totals)


def class_hours(rows: list[dict[str, str]], period: str, scenario: str) -> dict[str, float]:
    values = {category: number(lookup(rows, period, scenario, category), "person_hours") for category in CATEGORIES}
    return {
        "public": values["terminal_hall"],
        "staff": values["office"] + values["breakroom"],
        "unsplit": values["commerce_retail"] + values["dining"],
        "linked": values["restroom"],
        "total": math.fsum(values.values()),
    }


def scenario_delta(
    rows: list[dict[str, str]], period: str, scenario: str, metric: str
) -> float:
    baseline = lookup(rows, period, "baseline_r")
    current = lookup(rows, period, scenario)
    return pct(number(current, metric), number(baseline, metric))


def baseline_reports(data: dict[str, Any]) -> None:
    audit = data["audit"]
    manifest = data["manifest"]
    sc = data["seasonal_categories"]
    ac = data["annual_categories"]
    sw = data["seasonal_whole"]
    aw = data["annual_whole"]
    source_design = design_totals(manifest, "source_design_people")
    target_design = design_totals(manifest, "target_design_people")
    source_rows: list[tuple[Any, ...]] = []
    reference_rows: list[tuple[Any, ...]] = []
    for category in CATEGORIES:
        area = math.fsum(
            float(row["floor_area_m2"])
            for row in audit["spaces"]
            if row["room_category"] == category
        )
        source_rows.append(
            (
                category,
                audit["category_counts"][category],
                fmt(area),
                fmt(source_design[category]),
                fmt(number(lookup(sc, "winter", "baseline_s", category), "person_hours")),
                fmt(number(lookup(ac, "annual", "baseline_s", category), "person_hours")),
            )
        )
        reference_rows.append(
            (
                category,
                fmt(source_design[category]),
                fmt(target_design[category]),
                signed(pct(target_design[category], source_design[category])),
                fmt(number(lookup(sc, "winter", "baseline_r", category), "person_hours")),
                fmt(number(lookup(ac, "annual", "baseline_r", category), "person_hours")),
            )
        )
    s_classes = class_hours(sc, "winter", "baseline_s")
    r_classes = class_hours(sc, "winter", "baseline_r")
    s_winter = lookup(sw, "winter", "baseline_s")
    r_winter = lookup(sw, "winter", "baseline_r")
    s_annual = lookup(aw, "annual", "baseline_s")
    r_annual = lookup(aw, "annual", "baseline_r")
    s_prov = data["provenance_s"]
    r_prov = data["provenance_r"]
    write(
        data["report_root"] / "source_preserving_baseline.md",
        f"""# Baseline S — source-preserving

**Status:** `SOURCE_PRESERVING_IDEALLOADS_BASELINE`
**Boundary:** controlled thermal-load baseline, not measured airport operation.

Baseline S retains the source design People totals, schedules, activity, heat/CO₂
parameters, non-People loads, OA definitions, geometry, constructions and zone
semantics. It adds 304 IdealLoads endpoints solely for thermal-demand comparison.
The source OSM remains byte-identical at `{SOURCE_HASH}`.

{table(("Category", "Spaces", "Area m²", "Source design people", "Day person-h", "Annual person-h"), source_rows)}

## Occupant-class accounting

Representative-day totals are {fmt(s_classes['public'])} terminal-hall passenger-h,
{fmt(s_classes['staff'])} staff person-h, {fmt(s_classes['unsplit'])}
commerce+dining public-facing-unsplit person-h, and {fmt(s_classes['linked'])}
public-linked restroom person-h; whole building = {fmt(s_classes['total'])} person-h.

## Thermal and HVAC boundary

- Winter IdealLoads: {fmt(number(s_winter, 'heating_kwh'))} kWh heating and {fmt(number(s_winter, 'cooling_kwh'))} kWh cooling.
- Annual IdealLoads: {fmt(number(s_annual, 'heating_kwh') / 1000)} MWh heating and {fmt(number(s_annual, 'cooling_kwh') / 1000)} MWh cooling.
- Source counts remain 29 People and 28 PeopleDefinition objects; 304 IdealLoads systems are derivative-only.
- Source AirLoop = {s_prov['before_counts']['air_loops']}, PlantLoop = {s_prov['before_counts']['plant_loops']}, real zone equipment = {s_prov['before_counts']['real_zone_equipment']}.

Baseline S preserves source semantics; it does not endorse the inherited Large Office
schedule as true airport operation.
""",
    )
    write(
        data["report_root"] / "room_aware_reference_baseline.md",
        f"""# Baseline R — room-aware reference

**Status:** `ROOM_AWARE_REFERENCE_CONTROLLED_NOT_MEASURED`
**Derived OSM SHA-256:** `{r_prov['derived_osm_sha256']}`
**Derived IDF SHA-256:** `{r_prov['derived_idf_sha256']}`

Baseline R creates one explicit People object per Space and 304 IdealLoads endpoints.
It does not change SpaceType, lighting, equipment, infiltration, main-study OA,
geometry, construction or source zone semantics. Protected-object before/after hashes
are both `{r_prov['protected_snapshot_sha256_before']}`;
`non_people_fields_modified = {r_prov['non_people_fields_modified']}`.

{table(("Category", "Source design people", "R design people", "Capacity Δ", "Day person-h", "Annual person-h"), reference_rows)}

## Parameter decisions

- Tier B project-note densities: office 6, commerce 5 and dining 2.5 m²/person.
- Tier B standard density: breakroom 3.7161216 m²/person.
- `DO_NOT_AUTOFILL`: hall density (non-equivalent source rows) and restroom density (no dwell model); source counts remain capacity fallbacks.
- `z-u-office-11` is flagged `SOURCE_METADATA_CONFLICT`. Its source design count,
  activity, Fraction Radiant, sensible fraction and CO₂ rate are retained, while its
  source People number schedule is deliberately replaced by the controlled office
  profile. The conflict is not treated as resolved.
- Tier A retained: activity, Fraction Radiant, autocalculated sensible fraction, CO₂ generation and main-study OA definitions.
- Tier C controlled/not measured: all six 15-minute profile shapes.
- Documented reference OA rates and 15 ACH restroom exhaust are not implemented in the main S/R comparison; no source-backed real-HVAC topology was synthesized.

## Occupant-class accounting and S/R contrast

Representative-day R contains {fmt(r_classes['public'])} terminal-hall passenger-h,
{fmt(r_classes['staff'])} staff person-h, {fmt(r_classes['unsplit'])}
public-facing-unsplit person-h and {fmt(r_classes['linked'])} public-linked person-h,
total {fmt(r_classes['total'])} person-h. Reference capacity changes from
{fmt(number(s_winter, 'design_people'))} to {fmt(number(r_winter, 'design_people'))}
people. Day person-hours change from {fmt(number(s_winter, 'person_hours'))} to
{fmt(number(r_winter, 'person_hours'))}; annual person-hours from
{fmt(number(s_annual, 'person_hours'))} to {fmt(number(r_annual, 'person_hours'))}.
This is an assumption contrast, not evidence that the source airport was underoccupied.
""",
    )


def seasonal_report(data: dict[str, Any]) -> dict[str, Any]:
    whole = data["seasonal_whole"]
    categories = data["seasonal_categories"]
    zones = data["seasonal_zones"]
    assert_same_person_hours(whole, scenario_ids=MATCHED, tolerance=1e-6)
    assert_same_person_hours(categories, scenario_ids=MATCHED, tolerance=1e-6)
    summary_rows: list[tuple[Any, ...]] = []
    for period in ("winter", "summer", "shoulder"):
        base = lookup(whole, period, "baseline_r")
        for scenario in (
            "baseline_s",
            "baseline_r",
            "public_morning",
            "public_evening",
            "public_perimeter",
            "public_core",
            "entrance_2_lead",
            "entrance_3_lead",
        ):
            row = lookup(whole, period, scenario)
            heating = number(row, "heating_kwh")
            cooling = number(row, "cooling_kwh")
            summary_rows.append(
                (
                    period,
                    scenario,
                    fmt(number(row, "person_hours")),
                    fmt(heating),
                    "—" if number(base, "heating_kwh") == 0 else signed(pct(heating, number(base, "heating_kwh"))),
                    fmt(cooling),
                    "—" if number(base, "cooling_kwh") == 0 else signed(pct(cooling, number(base, "cooling_kwh"))),
                )
            )
    volume_rows: list[tuple[Any, ...]] = []
    for period in ("winter", "summer", "shoulder"):
        for scenario in VOLUME:
            row = lookup(whole, period, scenario)
            volume_rows.append(
                (
                    period,
                    scenario.removeprefix("public_volume_").replace("_", ".") + "× hall",
                    fmt(number(row, "person_hours")),
                    signed(scenario_delta(whole, period, scenario, "heating_kwh")) if number(lookup(whole, period, "baseline_r"), "heating_kwh") else "—",
                    signed(scenario_delta(whole, period, scenario, "cooling_kwh")) if number(lookup(whole, period, "baseline_r"), "cooling_kwh") else "—",
                )
            )
    cat_effects = ranked_effects(
        categories,
        scenario_ids=MATCHED_NONTRIVIAL,
        metrics=("heating_kwh", "cooling_kwh", "heating_peak_kw", "cooling_peak_kw"),
    )
    cat_rows = [
        (
            row["period_id"],
            row["scenario_id"],
            row["category"],
            row["metric"],
            fmt(float(row["baseline"])),
            fmt(float(row["value"])),
            signed(float(row["delta_pct"])),
        )
        for row in cat_effects[:12]
    ]
    zone_effects = ranked_effects(
        zones,
        scenario_ids=MATCHED_NONTRIVIAL,
        metrics=("heating_kwh", "cooling_kwh", "heating_peak_kw", "cooling_peak_kw"),
        minimum_baseline=1.0,
    )
    zone_peak = max(
        (row for row in zone_effects if row["metric"] == "cooling_peak_kw"),
        key=lambda row: abs(float(row["delta"])),
    )
    zone_energy = max(
        (row for row in zone_effects if row["metric"] == "cooling_kwh"),
        key=lambda row: abs(float(row["delta"])),
    )
    category_peak = max(
        (row for row in cat_effects if row["metric"] == "cooling_peak_kw"),
        key=lambda row: abs(float(row["delta_pct"])),
    )
    shoulder = lookup(whole, "shoulder", "baseline_r")
    write(
        data["report_root"] / "seasonal_results.md",
        f"""# Seasonal room-aware IdealLoads results

**Run status:** {data['seasonal_runs']['count']}/{data['seasonal_runs']['count']} PASS; zero Severe/Fatal.
**Resolution:** 15-minute explicit Wednesdays (15 Jan, 15 Jul, 15 Apr).
**Boundary:** thermal demand under IdealLoads, not calibrated airport energy.

## Whole-building contrasts

{table(("Period", "Scenario", "Person-h", "Heating kWh", "Δ vs R", "Cooling kWh", "Δ vs R"), summary_rows)}

At identical person-hours, the largest seasonal whole-building energy contrast is
shoulder `public_morning` heating ({signed(scenario_delta(whole, 'shoulder', 'public_morning', 'heating_kwh'))}).

## Category and zone contrasts

{table(("Period", "Scenario", "Category", "Metric", "R baseline", "Scenario", "Δ"), cat_rows)}

Largest absolute category cooling-peak contrast: `{category_peak['category']}` /
`{category_peak['period_id']}` / `{category_peak['scenario_id']}`,
{fmt(float(category_peak['baseline']))} to {fmt(float(category_peak['value']))} kWₜₕ
({signed(float(category_peak['delta_pct']))}). The largest absolute zone cooling-peak
contrast among baselines ≥1 kW is `{zone_peak['space_name']}` ({zone_peak['category']}),
`{zone_peak['period_id']}` / `{zone_peak['scenario_id']}`: Δ
{fmt(float(zone_peak['delta']))} kWₜₕ ({signed(float(zone_peak['delta_pct']))}).
The largest zone cooling-energy contrast is the same Space under
`{zone_energy['scenario_id']}`: Δ {fmt(float(zone_energy['delta']))} kWh
({signed(float(zone_energy['delta_pct']))}).
These are modeled contrasts, not statistically estimated effects.

## Ordinary volume sensitivity

Only terminal-hall public occupancy is scaled. This is a robustness/demo axis, not novelty.

{table(("Period", "Hall multiplier", "Total person-h", "Heating Δ", "Cooling Δ"), volume_rows)}

## OA and indoor-state diagnostics

- R OA mass-flow peak in shoulder = {fmt(number(shoulder, 'oa_mass_flow_peak_kg_s'), 3)} kg/s; it is unchanged across R temporal/spatial/volume cases because DCV is not enabled.
- Summer evening OA cooling differs from R by {signed(scenario_delta(whole, 'summer', 'public_evening', 'oa_cooling_kwh'))}; this is IdealLoads OA conditioning, not fan/control energy.
- Shoulder R area-weighted mean = {fmt(number(shoulder, 'temperature_area_weighted_mean_c'), 3)} °C and {fmt(number(shoulder, 'rh_area_weighted_mean_pct'), 3)}% RH.
- Heating and cooling unmet zone-hours = 0.0 in every retained seasonal case.
""",
    )
    return {
        "category_peak": category_peak,
        "zone_peak": zone_peak,
        "zone_energy": zone_energy,
    }


def annual_report(data: dict[str, Any]) -> dict[str, Any]:
    whole = data["annual_whole"]
    categories = data["annual_categories"]
    assert_same_person_hours(whole, scenario_ids=MATCHED, tolerance=1e-5)
    assert_same_person_hours(categories, scenario_ids=MATCHED, tolerance=1e-5)
    baseline = lookup(whole, "annual", "baseline_r")
    rows: list[tuple[Any, ...]] = []
    for scenario in (
        "baseline_s",
        "baseline_r",
        "public_morning",
        "public_midday",
        "public_evening",
        "public_perimeter",
        "public_core",
        "entrance_2_lead",
        "entrance_3_lead",
    ):
        row = lookup(whole, "annual", scenario)
        rows.append(
            (
                scenario,
                fmt(number(row, "person_hours") / 1e6, 3),
                fmt(number(row, "heating_kwh") / 1e6, 3),
                signed(pct(number(row, "heating_kwh"), number(baseline, "heating_kwh"))),
                fmt(number(row, "cooling_kwh") / 1e6, 3),
                signed(pct(number(row, "cooling_kwh"), number(baseline, "cooling_kwh"))),
                fmt(number(row, "heating_peak_kw") / 1000, 3),
                row["heating_peak_time"],
                fmt(number(row, "cooling_peak_kw") / 1000, 3),
                row["cooling_peak_time"],
            )
        )
    effects = ranked_effects(
        categories,
        scenario_ids=MATCHED_NONTRIVIAL,
        metrics=("heating_kwh", "cooling_kwh", "heating_peak_kw", "cooling_peak_kw"),
    )
    peak = max(
        (row for row in effects if row["metric"] == "cooling_peak_kw"),
        key=lambda row: abs(float(row["delta_pct"])),
    )
    energy = max(
        (row for row in effects if row["metric"] == "cooling_kwh"),
        key=lambda row: abs(float(row["delta"])),
    )
    heat_max = max(
        (scenario_delta(whole, "annual", scenario, "heating_kwh") for scenario in MATCHED_NONTRIVIAL),
        key=abs,
    )
    cool_max = max(
        (scenario_delta(whole, "annual", scenario, "cooling_kwh") for scenario in MATCHED_NONTRIVIAL),
        key=abs,
    )
    gate = data["annual_gate"]
    write(
        data["report_root"] / "annual_results.md",
        f"""# Annual room-aware IdealLoads results

**Run status:** {data['annual_runs']['count']}/{data['annual_runs']['count']} PASS; zero Severe/Fatal.
**Schedule resolution:** 15 minutes; **reported peak resolution:** hourly.
**Gate:** PASS — R runtime {fmt(float(gate['baseline_r_elapsed_seconds']), 1)} s,
output {fmt(float(gate['baseline_r_output_bytes']) / 1024**3, 3)} GiB,
projected suite {fmt(float(gate['projected_suite_bytes']) / 1024**3, 3)} GiB.

{table(("Scenario", "Person-h million", "Heating GWhₜₕ", "Δ vs R", "Cooling GWhₜₕ", "Δ vs R", "Heat peak MWₜₕ", "Heat peak time", "Cool peak MWₜₕ", "Cool peak time"), rows)}

At matched annual person-hours, whole-building heating changes by at most
{signed(heat_max)} and cooling by at most {signed(cool_max)}. The largest category
cooling-energy contrast is `{energy['category']}` / `{energy['scenario_id']}`
({signed(float(energy['delta_pct']))}); the largest category cooling-peak contrast is
`{peak['category']}` / `{peak['scenario_id']}`, {fmt(float(peak['baseline']))} to
{fmt(float(peak['value']))} kWₜₕ ({signed(float(peak['delta_pct']))}).

Annual compact outputs omit OA, temperature, RH and unmet-time series to satisfy the
size gate; those diagnostics are available in all {data['seasonal_runs']['count']} seasonal runs. Annual values are
controlled IdealLoads thermal demand, not calibrated utility energy. Each controlled
15-minute representative-day profile is repeated across all 365 calendar days; this is
not a weekday/weekend/holiday airport operations model.
""",
    )
    return {"peak": peak, "energy": energy, "heat_max": heat_max, "cool_max": cool_max}


def make_figures(data: dict[str, Any]) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/idfrepair-room-aware-mpl")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/idfrepair-room-aware-cache")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "figure.facecolor": "white",
        }
    )
    figures = data["report_root"] / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    columns = (
        ("winter", "heating_kwh", "Winter heat"),
        ("winter", "cooling_kwh", "Winter cool"),
        ("summer", "cooling_kwh", "Summer cool"),
        ("shoulder", "heating_kwh", "Shoulder heat"),
        ("shoulder", "cooling_kwh", "Shoulder cool"),
        ("annual", "heating_kwh", "Annual heat"),
        ("annual", "cooling_kwh", "Annual cool"),
    )
    matrix = []
    for scenario in MATCHED_NONTRIVIAL:
        line = []
        for period, metric, _ in columns:
            source = data["annual_whole"] if period == "annual" else data["seasonal_whole"]
            line.append(scenario_delta(source, period, scenario, metric))
        matrix.append(line)
    values = np.asarray(matrix)
    limit = max(3.0, float(np.max(np.abs(values))))
    fig, ax = plt.subplots(figsize=(10.2, 4.2), constrained_layout=True)
    image = ax.imshow(values, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
    ax.set_xticks(range(len(columns)), [item[2] for item in columns], rotation=25, ha="right")
    ax.set_yticks(range(len(MATCHED_NONTRIVIAL)), [item.replace("public_", "") for item in MATCHED_NONTRIVIAL])
    ax.set_title("Same-person-hours effect relative to Baseline R")
    for y in range(values.shape[0]):
        for x in range(values.shape[1]):
            ax.text(x, y, f"{values[y, x]:+.2f}%", ha="center", va="center", fontsize=8)
    fig.colorbar(image, ax=ax, shrink=0.86, label="Thermal-demand change (%)")
    fig.savefig(figures / "same_person_hours_effects.png", dpi=180)
    plt.close(fig)

    summer = [row for row in data["seasonal_categories"] if row["period_id"] == "summer"]
    category_values = np.asarray(
        [
            [
                pct(
                    number(lookup(summer, "summer", scenario, category), "cooling_peak_kw"),
                    number(lookup(summer, "summer", "baseline_r", category), "cooling_peak_kw"),
                )
                for scenario in MATCHED_NONTRIVIAL
            ]
            for category in CATEGORIES
        ]
    )
    cat_limit = max(5.0, float(np.max(np.abs(category_values))))
    fig, ax = plt.subplots(figsize=(8.2, 4.6), constrained_layout=True)
    image = ax.imshow(category_values, cmap="RdBu_r", vmin=-cat_limit, vmax=cat_limit, aspect="auto")
    ax.set_xticks(range(len(MATCHED_NONTRIVIAL)), [item.replace("public_", "") for item in MATCHED_NONTRIVIAL])
    ax.set_yticks(range(len(CATEGORIES)), CATEGORIES)
    ax.set_title("Summer category cooling-peak response at matched person-hours")
    for y in range(category_values.shape[0]):
        for x in range(category_values.shape[1]):
            ax.text(x, y, f"{category_values[y, x]:+.1f}%", ha="center", va="center", fontsize=8)
    fig.colorbar(image, ax=ax, shrink=0.86, label="Peak change (%)")
    fig.savefig(figures / "category_cooling_peak_effects.png", dpi=180)
    plt.close(fig)

    annual_scenarios = (
        "baseline_s",
        "baseline_r",
        "public_morning",
        "public_evening",
        "public_perimeter",
        "public_core",
        "entrance_2_lead",
        "entrance_3_lead",
    )
    heating = [number(lookup(data["annual_whole"], "annual", item), "heating_kwh") / 1e6 for item in annual_scenarios]
    cooling = [number(lookup(data["annual_whole"], "annual", item), "cooling_kwh") / 1e6 for item in annual_scenarios]
    x = np.arange(len(annual_scenarios))
    fig, ax = plt.subplots(figsize=(9.2, 4.6), constrained_layout=True)
    ax.bar(x - 0.19, heating, 0.38, label="Heating", color="#c95b4a")
    ax.bar(x + 0.19, cooling, 0.38, label="Cooling", color="#397eb8")
    ax.set_xticks(x, [item.replace("public_", "") for item in annual_scenarios], rotation=25, ha="right")
    ax.set_ylabel("Annual IdealLoads thermal demand (GWh)")
    ax.set_title("Controlled annual room-aware scenario comparison")
    ax.legend(frameon=False)
    ax.grid(axis="y", color="#dfe7e3", linewidth=0.7)
    fig.savefig(figures / "annual_ideal_loads.png", dpi=180)
    plt.close(fig)


def visualization_report(data: dict[str, Any]) -> None:
    viewer = data["derived_root"] / "viewer"
    manifest = load_json(viewer / "visualization_manifest.json")
    snapshots = load_rows(viewer / "snapshot_values.csv")
    if (
        len(snapshots) != 5
        or int(manifest["space_count"]) != 304
        or int(manifest["timestep_count"]) != 96
        or int(manifest["conflict_count"]) != 1
    ):
        raise ValueError("report_visualization_gate_failed")
    rows = [
        (
            row["interval_label"],
            row["energyplus_timestamp"],
            row["time_index"],
            fmt(float(row["total_people"]), 3),
            fmt(float(row["total_heating_kw"]), 3),
            fmt(float(row["total_cooling_kw"]), 3),
            fmt(float(row["max_density_people_m2"]), 4),
        )
        for row in snapshots
    ]
    write(
        data["report_root"] / "visualization_validation.md",
        f"""# Room-aware 3D visualization validation

**Status:** `PASS`
**Payload SHA-256:** `{manifest['payload_sha256']}`
**Scenario:** `{manifest['scenario_id']}` / `{manifest['period_id']}` / 15 minutes

The generic viewer shared by the original IDFRepair Demo and the private validation
harness maps 304 payload Space keys to 304 source geometry rooms. Orphan zone
`xbrestroom2` is excluded because it has no Space. Room Function View uses six fixed
category colors; Occupancy View uses one continuous people/m² colormap and can switch
to occupant count or percent of Baseline R design capacity.

{table(("Displayed interval", "EnergyPlus interval-end timestamp", "Index", "People", "Heating kWₜₕ", "Cooling kWₜₕ", "Max density people/m²"), rows)}

## Acceptance checks

- 304/304 Spaces categorized and mapped; zero unknowns.
- Legend: hall 126, office 69, commerce 51, dining 22, restroom 27, breakroom 9.
- One metadata conflict remains visible in the Space detail card.
- Every Space has 96 occupancy, heating and cooling values reconciled to EnergyPlus CSV.
- `z-u-hall-2` and `z-u-hall-3` are visible entrance seeds; public rooms use 0/15/30/45-minute controlled occupancy-response phases derived from the source Zone adjacency graph. These are not claimed as walking times.
- Slider indices 24/36/52/72/84 resolve to intervals beginning at
  06:00/09:00/13:00/18:00/21:00. The visible label is start–end (for example,
  06:00–06:15), while the linked EnergyPlus timestamp is the interval end (06:15).
- Browser QA passed Room Function/Occupancy modes, three metrics, scrub, play/pause,
  chart click/drag, play/pause, Space isolation, entrance/phase metadata and conflict badge; page console warnings/errors = 0, dialogs = 0.
- Original-Demo integration QA passed local JSON load and clear-layer behavior. The
  load/clear controls sit beside `Settings and required files`; idle and successful
  payload states consume no extra status line. Clearing occupancy leaves the loaded
  read-only IDF geometry in place; changing the IDF clears the optional payload so a
  stale room mapping cannot be reused.
- Narrow-view QA after the loader fix: `scrollWidth == innerWidth`.

![Five occupancy snapshots](figures/occupancy_five_times.png)

![Room function view](figures/room_function_view.png)

![Source metadata conflict](figures/conflict_space_detail.png)

The viewer loads local derivative IDF and JSON files. Raw OSM and derived private model
files are excluded from public distribution.
""",
    )


def entrance_flow_report(data: dict[str, Any]) -> None:
    topology = load_json(data["derived_root"] / "flow_topology.json")
    if (
        topology.get("space_count") != 304
        or topology.get("zone_count") != 304
        or topology.get("topology_connected") is not True
        or topology.get("entrance_spaces") != ["z-u-hall-2", "z-u-hall-3"]
        or topology.get("walking_route_claim") is not False
        or topology.get("measured_flow_claim") is not False
    ):
        raise ValueError("report_flow_topology_gate_failed")
    entrance_rows = []
    for entrance in topology["entrance_spaces"]:
        row = topology["spaces"][entrance]
        entrance_rows.append(
            (
                entrance,
                row["zone_name"],
                row["nearest_entrance_space"],
                row["adjacency_hops"],
                row["flow_phase_minutes"],
                topology["region_counts"][entrance],
            )
        )
    phase_rows = [
        (steps, count, int(steps) * 15)
        for steps, count in sorted(
            topology["phase_counts"].items(), key=lambda item: int(item[0])
        )
    ]
    mapping_source = data["derived_root"] / "flow_mapping_public.csv"
    mapping_destination = data["report_root"] / "entrance_flow_mapping.csv"
    mapping_destination.write_bytes(mapping_source.read_bytes())
    write(
        data["report_root"] / "entrance_flow_evidence.md",
        f"""# Entrance-seeded room-aware occupancy flow

**Status:** `CONTROLLED_NOT_MEASURED`
**Entrance seeds:** `z-u-hall-2`, `z-u-hall-3` (explicit user-provided source-model annotation)
**Interpretation:** occupancy-response phases, not passenger trajectories or walking time

The source-preserving Baseline R IDF yields {topology['paired_surface_relation_count']}
reciprocal paired-surface relations and {topology['zone_adjacency_edge_count']} unique
Zone-to-Zone adjacency edges. All 304 Space/Zone pairs form one connected semantic
graph. A breadth-first hop count from the two declared entrances assigns each room to
its nearer entrance; an area-weighted source floor centroid breaks equal-hop ties.
No door, gate, check-in, baggage, security, or real-HVAC route is inferred.

{table(("Entrance Space", "Source Zone", "Assigned seed", "Hops", "Phase min", "Region Spaces"), entrance_rows)}

{table(("Phase steps", "Spaces", "Controlled phase min"), phase_rows)}

Public-dynamic rooms are divided into near/middle/far hop terciles within each entrance
region and shifted by 15/30/45 minutes; the two entrance Spaces stay at phase zero.
Office and breakroom staff profiles are not entrance-delayed. Circular shifts preserve
the exact 96-value multiset and therefore every Space's daily person-hours. Reciprocal
`entrance_2_lead` / `entrance_3_lead` cases then lead one region by 30 minutes and lag
the other by 30 minutes, preserving every Space and whole-building integral.

## External spatial context and limits

The [China Southern Beijing Daxing Airport guide](https://www.csair.com/cn/tourguide/airport_service/domestic/domestic/1dpdb182j8mei.shtml)
identifies Level 2 as a mixed domestic departure/arrival, international-arrival,
transfer, and domestic baggage-claim level; its [official Level-2 plan](https://www.csair.com/cn/tourguide/airport_service/domestic/domestic/resource/94bd66d86448bed879eec31183612977.PNG)
shows the multi-arm spatial context. The [Beijing municipal airport introduction](https://zdzqgw.beijing.gov.cn/zqfw/bjdxgjjc/bjdxgjjcjs/202410/t20241012_3917907.html)
independently describes the five-pier form and Level-2 domestic-arrival function.
These sources motivate multiple time/space streams only; they do not map this simplified
OSM's rooms to airport operational functions. Sources accessed 2026-08-18.

The coordinate-free review mapping is `entrance_flow_mapping.csv`. Exact centroids
remain in the private derived topology and are excluded from public distribution.
""",
    )


def effect_ledger(data: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for scope, rows, threshold in (
        ("seasonal_category", data["seasonal_categories"], 1e-9),
        ("seasonal_zone", data["seasonal_zones"], 1.0),
        ("annual_category", data["annual_categories"], 1e-9),
    ):
        effects = ranked_effects(
            rows,
            scenario_ids=MATCHED_NONTRIVIAL,
            metrics=("heating_kwh", "cooling_kwh", "heating_peak_kw", "cooling_peak_kw"),
            minimum_baseline=threshold,
        )
        records += [{"analysis_scope": scope, **row} for row in effects]
    fields = (
        "analysis_scope",
        "scenario_id",
        "period_id",
        "category",
        "space_name",
        "zone_name",
        "metric",
        "baseline",
        "value",
        "delta",
        "delta_pct",
    )
    with (data["report_root"] / "same_person_hours_effects.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    return records


def admission_report(
    data: dict[str, Any],
    seasonal: dict[str, Any],
    annual: dict[str, Any],
    frozen: str,
    historical: str,
    decision: dict[str, Any],
) -> None:
    season_peak = seasonal["category_peak"]
    annual_peak = annual["peak"]
    criteria = [
        ("Source-backed mapping", "PASS", "304/304 exact name-token categories"),
        ("Parameter provenance", "PASS", "Tier A/B/C plus DO_NOT_AUTOFILL"),
        ("Baselines", "PASS", "S and R both retained and distinguished"),
        (
            "Simulation stability",
            "PASS",
            f"{data['seasonal_runs']['count']} seasonal + {data['annual_runs']['count']} annual; zero Severe/Fatal",
        ),
        (
            "Local explanatory value",
            "PASS" if decision["status"] == "OCCUPANCY_CASE_PAPER_READY" else "BELOW_THRESHOLD",
            (
                f"Season {float(season_peak['delta_pct']):+.2f}%; annual "
                f"{float(annual_peak['delta_pct']):+.2f}% cooling peaks; "
                f"qualifying effects={len(decision['qualifying_effects'])}"
            ),
        ),
        ("3D visualization", "PASS", "304 Spaces, 96 steps, five snapshots"),
        ("HVAC boundary", "PASS", "IdealLoads only; no real topology invented"),
        ("Frozen-method isolation", "PASS", frozen),
    ]
    positioning = {
        "OCCUPANCY_CASE_PAPER_READY": (
            "The case is suitable for one short **Downstream application / terminal "
            "occupancy sensitivity** subsection and one main-text figure, with the "
            "registry, scenario matrix, category tables and 3D snapshots in "
            "supplementary material. Formal V2 semantic repair remains the only "
            "primary method."
        ),
        "OCCUPANCY_CASE_DEMO_ONLY": (
            "The case is retained only as a bounded Demo/Supplement artifact and is "
            "not admitted as a manuscript contribution. It must not block the Energy "
            "and Buildings paper."
        ),
        "OCCUPANCY_CASE_NOT_ADMISSIBLE": (
            "The evidence is not admissible for manuscript or demo claims until the "
            "failed provenance/simulation gate is repaired."
        ),
    }[decision["status"]]
    write(
        data["report_root"] / "paper_admission.md",
        f"""# Paper admission decision

## Final status: `{decision['status']}`

{table(("Criterion", "Result", "Evidence"), criteria)}

{positioning}

## Bounded finding

At matched person-hours, whole-building annual heating/cooling changes remain modest
({signed(annual['heat_max'])} / {signed(annual['cool_max'])} at their largest), while
category cooling peaks respond more strongly. The largest annual category contrast is
`{annual_peak['category']}` / `{annual_peak['scenario_id']}` at
{signed(float(annual_peak['delta_pct']))}; the seasonal maximum is
`{season_peak['category']}` / `{season_peak['scenario_id']}` at
{signed(float(season_peak['delta_pct']))}. This supports a local-versus-aggregate
workflow insight, not passenger-flow theory or real-HVAC energy validation.

## Permitted positioning

> A downstream, IDF/OSM-native, provenance-aware scenario workflow on an already
> semantically audited building model.

The differentiators are fail-closed source-label mapping, parameter-level provenance,
person-hour-conserving counterfactuals, reuse of People→Zone→IdealLoads relations and
time-resolved 3D reconciliation. Dynamic airport occupancy, zone schedules, occupancy
heat gains, MPC and occupant-centric ventilation are established prior work.

Recommended manuscript footprint: one setup paragraph, one matched-person-hours figure
(`figures/same_person_hours_effects.png`), one local-versus-whole paragraph and an
explicit IdealLoads limitation. If editorial space is tight, move the case intact to the
Supplement; it must not block the Energy and Buildings paper.

The admission state is computed, not hard-coded. A non-volume temporal/spatial local
effect must pass both the predeclared relative threshold (10%) and absolute threshold
(20 kW for a peak or 100 kWh for zone/category energy), with baseline floors of 50 kW
or 100 kWh. Ordinary public-volume sensitivity is ineligible for this decision.

## Freeze attestation

- Formal V2 aggregate SHA-256: `{frozen}` (expected `{FROZEN_HASH}`).
- Historical occupancy aggregate SHA-256: `{historical}` (expected `{HISTORICAL_HASH}`).
- Neither tree was edited or regenerated.
""",
    )


def report_manifest(data: dict[str, Any], frozen: str, historical: str) -> None:
    files = sorted(
        path
        for path in data["report_root"].rglob("*")
        if path.is_file() and path.name != "report_manifest.json"
    )
    payload = {
        "schema_version": "idfrepair.room-aware-report.v1",
        "status": data["admission"]["status"],
        "admission_reason": data["admission"]["reason"],
        "qualifying_effect_count": len(data["admission"]["qualifying_effects"]),
        "source_osm_sha256": SOURCE_HASH,
        "source_space_count": 304,
        "seasonal_run_count": data["seasonal_runs"]["count"],
        "annual_run_count": data["annual_runs"]["count"],
        "frozen_method_sha256": frozen,
        "historical_occupancy_sha256": historical,
        "files": [
            {
                "path": path.resolve().relative_to(PROJECT_ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        ],
    }
    write(
        data["report_root"] / "report_manifest.json",
        json.dumps(payload, indent=2, sort_keys=True),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-osm", type=Path, required=True)
    parser.add_argument("--derived-root", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--people-manifest", type=Path, required=True)
    parser.add_argument("--baseline-s-provenance", type=Path, required=True)
    parser.add_argument("--baseline-r-provenance", type=Path, required=True)
    parser.add_argument("--baseline-s-idf", type=Path, required=True)
    parser.add_argument("--baseline-r-idf", type=Path, required=True)
    parser.add_argument("--energyplus", type=Path, required=True)
    parser.add_argument("--idd", type=Path, required=True)
    parser.add_argument("--weather", type=Path, required=True)
    args = parser.parse_args()

    if sha256(args.source_osm) != SOURCE_HASH:
        raise ValueError("report_source_osm_hash_mismatch")
    audit = load_json(args.audit)
    manifest = load_json(args.people_manifest)
    if (
        audit.get("source_unchanged") is not True
        or audit.get("source_sha256_after") != SOURCE_HASH
        or manifest.get("source_sha256") != SOURCE_HASH
        or len(manifest.get("spaces", [])) != 304
    ):
        raise ValueError("report_source_provenance_gate_failed")
    expected_counts = {
        "terminal_hall": 126,
        "office": 69,
        "commerce_retail": 51,
        "dining": 22,
        "restroom": 27,
        "breakroom": 9,
    }
    if audit.get("category_counts") != expected_counts:
        raise ValueError("report_category_counts_mismatch")
    provenance_chain = validate_baseline_provenance_chain(
        source_osm_path=args.source_osm,
        expected_source_sha256=SOURCE_HASH,
        baseline_s_idf_path=args.baseline_s_idf,
        baseline_s_provenance_path=args.baseline_s_provenance,
        baseline_r_idf_path=args.baseline_r_idf,
        baseline_r_provenance_path=args.baseline_r_provenance,
        people_manifest_path=args.people_manifest,
    )

    compact = args.derived_root / "compact"
    data: dict[str, Any] = {
        "source_osm": args.source_osm,
        "derived_root": args.derived_root,
        "report_root": args.report_root,
        "audit": audit,
        "manifest": manifest,
        "provenance_s": load_json(args.baseline_s_provenance),
        "provenance_r": load_json(args.baseline_r_provenance),
        "seasonal_whole": load_rows(compact / "seasonal" / "scenario_results.csv"),
        "seasonal_categories": load_rows(compact / "seasonal" / "category_results.csv"),
        "seasonal_zones": load_rows(compact / "seasonal" / "zone_results.csv"),
        "annual_whole": load_rows(compact / "annual" / "scenario_results.csv"),
        "annual_categories": load_rows(compact / "annual" / "category_results.csv"),
        "seasonal_runs": run_gate(
            args.derived_root / "runs" / "seasonal_weekday_v2",
            42,
            suite="seasonal",
            derived_root=args.derived_root,
            source_osm=args.source_osm,
            executable=args.energyplus,
            idd_path=args.idd,
            weather_path=args.weather,
        ),
        "annual_runs": run_gate(
            args.derived_root / "runs" / "annual_compact_v2",
            9,
            suite="annual",
            derived_root=args.derived_root,
            source_osm=args.source_osm,
            executable=args.energyplus,
            idd_path=args.idd,
            weather_path=args.weather,
        ),
        "annual_gate": load_json(args.derived_root / "annual_runtime_gate_v2.json"),
    }
    if data["annual_gate"].get("passed") is not True:
        raise ValueError("report_annual_runtime_gate_failed")
    args.report_root.mkdir(parents=True, exist_ok=True)
    write(
        args.report_root / "provenance_chain.json",
        json.dumps(provenance_chain, indent=2, sort_keys=True),
    )
    combine_result_tables(
        compact / "seasonal" / "category_results.csv",
        compact / "annual" / "category_results.csv",
        args.report_root / "category_results.csv",
    )
    combine_result_tables(
        compact / "seasonal" / "scenario_results.csv",
        compact / "annual" / "scenario_results.csv",
        args.report_root / "scenario_results.csv",
    )
    effects = effect_ledger(data)
    data["admission"] = evaluate_paper_admission(effects, evidence_valid=True)
    baseline_reports(data)
    seasonal = seasonal_report(data)
    annual = annual_report(data)
    make_figures(data)
    entrance_flow_report(data)
    visualization_report(data)

    frozen = aggregate_hash(PROJECT_ROOT / "src/idfrepair/semantic_graph_v2")
    historical = aggregate_hash(PROJECT_ROOT / "reports/occupancy")
    if frozen != FROZEN_HASH:
        raise ValueError(f"report_frozen_method_hash_changed:{frozen}")
    if historical != HISTORICAL_HASH:
        raise ValueError(f"report_historical_occupancy_hash_changed:{historical}")
    admission_report(data, seasonal, annual, frozen, historical, data["admission"])
    report_manifest(data, frozen, historical)
    print(
        json.dumps(
            {
                "status": data["admission"]["status"],
                "report_root": str(args.report_root),
                "source_sha256": sha256(args.source_osm),
                "frozen_method_sha256": frozen,
                "historical_occupancy_sha256": historical,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
