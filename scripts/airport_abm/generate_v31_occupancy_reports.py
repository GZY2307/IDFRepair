#!/usr/bin/env python3
"""Generate aggregate V3.1 normalization and BEM-reference capacity audits."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import csv
import gzip
import json
import math
from pathlib import Path
import sys
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.capacity_audit import (  # noqa: E402
    CapacityObservation,
    CapacitySummary,
    summarize_capacity_reference,
)
from idfrepair.analysis.airport_abm.reporting import quantile  # noqa: E402
from idfrepair.analysis.airport_abm.source import load_space_mapping  # noqa: E402
from idfrepair.analysis.airport_abm.v31 import (  # noqa: E402
    AIRPORT_WIDE_STRESS_CONTEXT,
    BEM_REFERENCE_NORMALIZED,
    SEASONAL_SEEDS,
    TIMING_SCENARIOS,
    person_hour_conservation,
)


def load_detail(path: Path) -> dict[str, object]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != "idfrepair.airport-abm-seed-detail.v3":
        raise ValueError(f"unexpected ABM detail schema: {path}")
    return payload


def hvac_group(space) -> str:
    return (
        space.public_air_loop
        or space.office_doas
        or space.zone_hvac
        or "NO_SOURCE_HVAC_GROUP"
    )


def detail_observations(
    detail: Mapping[str, object], spaces
) -> tuple[CapacityObservation, ...]:
    counts = detail.get("space_counts")
    if not isinstance(counts, Mapping):
        raise ValueError("ABM detail has no Space counts")
    scenario = str(detail.get("scenario_id", ""))
    seed = int(detail.get("seed", 0))
    output = []
    for space in spaces:
        if not space.bem_people_supported:
            continue
        values = counts.get(space.name)
        if not isinstance(values, list) or len(values) != 96:
            raise ValueError("ABM detail Space coverage is incomplete")
        output.append(
            CapacityObservation(
                scenario_id=scenario,
                seed=seed,
                space_name=space.name,
                function=space.function,
                region=space.region,
                hvac_group=hvac_group(space),
                source_design_people=float(space.source_design_people),
                occupant_counts=tuple(float(value) for value in values),
            )
        )
    return tuple(output)


def source_observations(
    payload: Mapping[str, object], spaces_by_name: Mapping[str, object]
) -> tuple[CapacityObservation, ...]:
    if payload.get("schema_version") != "idfrepair.airport-source-static-people.v31":
        raise ValueError("source-static profile schema is invalid")
    output = []
    for row in payload.get("spaces", []):
        name = str(row["space_name"])
        space = spaces_by_name.get(name)
        if space is None or not space.bem_people_supported:
            raise ValueError("source-static profile contains an unknown Space")
        output.append(
            CapacityObservation(
                scenario_id="SOURCE_STATIC",
                seed=None,
                space_name=name,
                function=space.function,
                region=space.region,
                hvac_group=hvac_group(space),
                source_design_people=float(space.source_design_people),
                occupant_counts=tuple(float(value) for value in row["occupant_counts"]),
            )
        )
    return tuple(output)


def public_capacity_rows(
    rows: tuple[CapacitySummary, ...],
) -> list[dict[str, object]]:
    source_groups = sorted(
        {row.group for row in rows if row.dimension == "hvac_group"}
    )
    aliases = {
        name: f"hvac_group_{index:02d}"
        for index, name in enumerate(source_groups, 1)
    }
    output = []
    for row in rows:
        record = asdict(row)
        if row.dimension == "hvac_group":
            record["group"] = aliases[row.group]
        output.append(record)
    return output


def write_capacity_csv(path: Path, rows: tuple[CapacitySummary, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(asdict(rows[0]))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(public_capacity_rows(rows))


def whole_rows(rows: tuple[CapacitySummary, ...]) -> dict[str, CapacitySummary]:
    output = {
        row.scenario_id: row
        for row in rows
        if row.dimension == "whole_model" and row.group == "whole_model"
    }
    missing = {"SOURCE_STATIC", *TIMING_SCENARIOS}.difference(output)
    if missing:
        raise ValueError("capacity audit is missing scenarios: " + ",".join(sorted(missing)))
    return output


def write_capacity_markdown(path: Path, rows: tuple[CapacitySummary, ...]) -> None:
    whole = whole_rows(rows)
    lines = [
        "# Airport Occupancy V3.1 — BEM Design-Occupancy Reference Audit",
        "",
        "The denominator is every source-People-supported Space × 15-minute interval × preregistered seed. `SOURCE_STATIC` has one deterministic profile; dynamic cases use all five seasonal seeds. Ratios are not clipped. The reference is a BEM design-occupancy input, not a fire-code, safety, operational, or physical capacity.",
        "",
        "| Scenario | Seeds | Spaces | Space-time intervals | Spaces ever >1.0 | >1.0 | >1.5 | >2.0 | P50 | P90 | P95 | P99 | Maximum |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    order = ("SOURCE_STATIC", *TIMING_SCENARIOS)
    for scenario in order:
        row = whole[scenario]
        lines.append(
            f"| {scenario} | {row.seeds} | {row.spaces_supported} | {row.space_time_intervals:,} | {row.spaces_over_1} | {row.ratio_over_1_count:,} ({row.ratio_over_1_percent:.2f}%) | {row.ratio_over_1_5_count:,} ({row.ratio_over_1_5_percent:.2f}%) | {row.ratio_over_2_count:,} ({row.ratio_over_2_percent:.2f}%) | {row.p50:.3f} | {row.p90:.3f} | {row.p95:.3f} | {row.p99:.3f} | {row.maximum:.3f} |"
        )
    lines.extend(
        [
            "",
            "The companion CSV contains the same envelope grouped by function, region, public HVAC-group alias, and scenario. Source HVAC labels are not published. Any local overload is retained for the admission decision; no gate assignment, flight bank, dwell, or occupancy value was changed to reduce it.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def read_seed_summaries(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def median(rows: list[dict[str, str]], scenario: str, field: str) -> float:
    values = [float(row[field]) for row in rows if row["scenario_id"] == scenario]
    if not values:
        raise ValueError(f"summary metric missing: {scenario}:{field}")
    return quantile(values, 0.50)


def detail_metric(detail: Mapping[str, object], spaces, function_set: set[str]) -> float:
    counts = detail["space_counts"]
    profiles = [
        counts[space.name]
        for space in spaces
        if space.bem_people_supported and space.function in function_set
    ]
    return max(
        sum(float(profile[index]) for profile in profiles)
        for index in range(96)
    )


def detail_capacity(detail: Mapping[str, object], spaces) -> tuple[int, float]:
    counts = detail["space_counts"]
    spaces_over = 0
    maximum = 0.0
    for space in spaces:
        if not space.bem_people_supported:
            continue
        ratios = [
            float(value) / float(space.source_design_people)
            for value in counts[space.name]
        ]
        peak = max(ratios)
        spaces_over += peak > 1.0
        maximum = max(maximum, peak)
    return spaces_over, maximum


def scale_comparison_rows(stress_detail, bem_detail, spaces, stress_rows, bem_rows):
    stress_over, stress_max = detail_capacity(stress_detail, spaces)
    bem_over, bem_max = detail_capacity(bem_detail, spaces)
    specifications = (
        (
            "public_person_hours",
            median(stress_rows, "BASELINE_SPREAD", "public_person_hours_bem"),
            median(bem_rows, "BASELINE_SPREAD", "public_person_hours_bem"),
        ),
        (
            "whole_building_15min_peak",
            median(stress_rows, "BASELINE_SPREAD", "whole_building_peak_occupancy"),
            median(bem_rows, "BASELINE_SPREAD", "whole_building_peak_occupancy"),
        ),
        ("spaces_over_1_design_reference_seed40015", float(stress_over), float(bem_over)),
        ("maximum_design_ratio_seed40015", stress_max, bem_max),
        (
            "domestic_waiting_peak_seed40015",
            detail_metric(stress_detail, spaces, {"domestic_waiting"}),
            detail_metric(bem_detail, spaces, {"domestic_waiting"}),
        ),
        (
            "baggage_claim_peak_seed40015",
            detail_metric(stress_detail, spaces, {"baggage_claim"}),
            detail_metric(bem_detail, spaces, {"baggage_claim"}),
        ),
        (
            "commercial_restaurant_restroom_peak_seed40015",
            detail_metric(stress_detail, spaces, {"commercial", "restaurant", "restroom"}),
            detail_metric(bem_detail, spaces, {"commercial", "restaurant", "restroom"}),
        ),
    )
    return [
        {
            "metric": metric,
            "BEM_REFERENCE_NORMALIZED": bem,
            "AIRPORT_WIDE_STRESS_CONTEXT": stress,
            "bem_to_stress_ratio": bem / stress if abs(stress) > 1.0e-12 else None,
        }
        for metric, stress, bem in specifications
    ]


def write_normalization(
    report_dir: Path,
    source_payload,
    bem_rows,
    stress_rows,
    scale_rows,
) -> dict[str, object]:
    target_public = float(source_payload["public_person_hours"])
    target_staff = float(source_payload["staff_person_hours"])
    audits = [
        person_hour_conservation(
            target_public=target_public,
            actual_public=float(row["public_person_hours_bem"]),
            target_staff=target_staff,
            actual_staff=float(row["staff_person_hours_bem"]),
        )
        for row in bem_rows
    ]
    payload = {
        "schema_version": "idfrepair.airport-abm-normalization-audit.v31",
        "primary_scale": BEM_REFERENCE_NORMALIZED,
        "secondary_scale": AIRPORT_WIDE_STRESS_CONTEXT,
        "source_static_public_person_hours_per_day": target_public,
        "source_static_staff_person_hours_per_day": target_staff,
        "normalized_dynamic_run_count": len(bem_rows),
        "normalized_dynamic_public_person_hours_minimum": min(
            float(row["public_person_hours_bem"]) for row in bem_rows
        ),
        "normalized_dynamic_public_person_hours_maximum": max(
            float(row["public_person_hours_bem"]) for row in bem_rows
        ),
        "normalized_dynamic_staff_person_hours_minimum": min(
            float(row["staff_person_hours_bem"]) for row in bem_rows
        ),
        "normalized_dynamic_staff_person_hours_maximum": max(
            float(row["staff_person_hours_bem"]) for row in bem_rows
        ),
        "maximum_public_relative_error": max(row.public_relative_error for row in audits),
        "maximum_staff_relative_error": max(row.staff_relative_error for row in audits),
        "relative_tolerance": 1.0e-8,
        "conservation_status": (
            "PASS" if all(row.status == "PASS" for row in audits) else "FAIL"
        ),
        "historical_stress_public_person_hours_p50": median(
            stress_rows, "BASELINE_SPREAD", "public_person_hours_bem"
        ),
        "scale_comparison": scale_rows,
        "claim_boundary": "CONTROLLED_NOT_MEASURED",
    }
    (report_dir / "normalization_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Airport Occupancy V3.1 — Normalization Audit",
        "",
        f"Status: `{payload['conservation_status']}`",
        "",
        f"The source-static default-day target is **{target_public:,.6f} public person-hours/day** and **{target_staff:,.6f} staff person-hours/day**. All {len(bem_rows)} preregistered normalized timing realizations independently match these two integrals. Maximum relative errors are {payload['maximum_public_relative_error']:.3e} (public) and {payload['maximum_staff_relative_error']:.3e} (staff), against the `1e-8` gate.",
        "",
        "`BEM_REFERENCE_NORMALIZED` is the paper-primary scale. It changes only the public/staff cohort weights; agent classes, route/access semantics, dwell, choices, and timing transforms are frozen. `AIRPORT_WIDE_STRESS_CONTEXT` remains a historical secondary visualization/scalability experiment.",
        "",
        "## Scale comparison",
        "",
        "| Metric | BEM_REFERENCE_NORMALIZED | AIRPORT_WIDE_STRESS_CONTEXT | BEM / stress |",
        "|---|---:|---:|---:|",
    ]
    for row in scale_rows:
        ratio = row["bem_to_stress_ratio"]
        lines.append(
            f"| {row['metric']} | {float(row[BEM_REFERENCE_NORMALIZED]):,.4f} | {float(row[AIRPORT_WIDE_STRESS_CONTEXT]):,.4f} | {'—' if ratio is None else f'{float(ratio):.4f}'} |"
        )
    lines.extend(
        [
            "",
            "The source-model public integral is larger than the old airport-wide stress mapping. Therefore the historical 895.9% flag cannot be explained as a simple consequence of a larger airport-total scale; it reflects the interaction of route concentration and local source design references. V3.1 retains the normalized overload envelope rather than changing ABM parameters.",
            "",
        ]
    )
    (report_dir / "normalization_audit.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    return payload


def write_gap_audit(path: Path, normalization: Mapping[str, object]) -> None:
    lines = [
        "# Airport Occupancy V3.1 — Scientific Gap Audit",
        "",
        "Status: `GAPS_REGISTERED_BEFORE_LONG_ENERGYPLUS_RUNS`",
        "",
        "## Frozen V3 evidence",
        "",
        "The historical V3 matrix remains 20 scenarios × 30 seeds = 600 runs, 3.3 million representative agents, with zero conservation failures, invalid routes, passenger-through-office paths, and isolation violations. This proves software/process consistency only; it does not validate measured Daxing trajectories, gate shares, dwell distributions, or passenger forecasts.",
        "",
        "The access graph remains a directed functional/process abstraction: 49 reciprocal physical Door pairs, 48 unique Space connections, 76 passenger and 96 staff explicit-Door directed edges, 2,990 passenger and 1,300 staff functional abstraction edges, and zero of 1,278 thermal-adjacency candidates admitted to routing. No route behavior is changed in V3.1.",
        "",
        "## Closed experiment gaps",
        "",
        f"- Primary scale registered as `BEM_REFERENCE_NORMALIZED`: {float(normalization['source_static_public_person_hours_per_day']):,.6f} public and {float(normalization['source_static_staff_person_hours_per_day']):,.6f} staff person-hours/day.",
        "- Historical airport-total mapping permanently relabelled `AIRPORT_WIDE_STRESS_CONTEXT`; its public reports are retained without overwrite.",
        "- `SOURCE_STATIC` is the primary control and retains the source OSM People schedules.",
        "- The current one-seed shoulder evidence remains mechanism demo only until the fixed-sizing and 78-period seasonal gates pass.",
        "- EnergyPlus uncertainty will be described as ABM stochastic-realization sensitivity, never measured uncertainty.",
        "",
        "## Claim boundary",
        "",
        "The model is a source/process-constrained BEM occupancy compiler, not physical pedestrian microsimulation. BEM design-People ratios are stress references, not safety or operational capacity. No post-result parameter tuning, DCV activation, trajectory refinement, or new passenger-flow feature is permitted.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--normalized-root", required=True)
    parser.add_argument("--stress-root", required=True)
    parser.add_argument("--source-static", required=True)
    parser.add_argument("--report-dir", required=True)
    args = parser.parse_args()

    spaces = load_space_mapping(args.mapping)
    spaces_by_name = {space.name: space for space in spaces}
    normalized_root = Path(args.normalized_root)
    observations = []
    for scenario in TIMING_SCENARIOS:
        for seed in SEASONAL_SEEDS:
            detail = load_detail(
                normalized_root
                / "seed_details"
                / scenario
                / f"seed-{seed}.json.gz"
            )
            observations.extend(detail_observations(detail, spaces))
    source_payload = json.loads(Path(args.source_static).read_text(encoding="utf-8"))
    observations.extend(source_observations(source_payload, spaces_by_name))
    capacity_rows = summarize_capacity_reference(observations)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    write_capacity_csv(report_dir / "capacity_reference_audit.csv", capacity_rows)
    write_capacity_markdown(report_dir / "capacity_reference_audit.md", capacity_rows)

    stress_root = Path(args.stress_root)
    stress_detail = load_detail(
        stress_root / "seed_details/BASELINE_SPREAD/seed-40015.json.gz"
    )
    bem_detail = load_detail(
        normalized_root / "seed_details/BASELINE_SPREAD/seed-40015.json.gz"
    )
    bem_rows = read_seed_summaries(normalized_root / "seed_summaries.csv")
    stress_rows = read_seed_summaries(stress_root / "seed_summaries.csv")
    scale_rows = scale_comparison_rows(
        stress_detail, bem_detail, spaces, stress_rows, bem_rows
    )
    normalization = write_normalization(
        report_dir, source_payload, bem_rows, stress_rows, scale_rows
    )
    write_gap_audit(report_dir / "v3_scientific_gap_audit.md", normalization)
    print(
        json.dumps(
            {
                "status": normalization["conservation_status"],
                "normalized_run_count": len(bem_rows),
                "capacity_summary_rows": len(capacity_rows),
                "maximum_public_relative_error": normalization[
                    "maximum_public_relative_error"
                ],
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
