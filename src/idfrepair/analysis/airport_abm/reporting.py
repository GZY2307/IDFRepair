"""Hand-checkable aggregation and uncertainty statistics for Airport ABM V3."""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Iterable, Mapping, Sequence


class ReportingError(ValueError):
    """Raised when a report would violate a comparison invariant."""


def quantile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ReportingError("quantile requires at least one value")
    if not 0 <= probability <= 1:
        raise ReportingError("quantile probability must lie in [0, 1]")
    if any(not math.isfinite(value) for value in ordered):
        raise ReportingError("quantile values must be finite")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def summarize_seed_metric(
    rows: Iterable[Mapping[str, object]],
    *,
    metric: str,
    scenario_field: str = "scenario_id",
) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        scenario = str(row[scenario_field])
        value = float(row[metric])
        if not math.isfinite(value):
            raise ReportingError(f"non-finite report metric: {scenario}:{metric}")
        grouped[scenario].append(value)
    output: dict[str, dict[str, float]] = {}
    for scenario, values in sorted(grouped.items()):
        output[scenario] = {
            "mean": sum(values) / len(values),
            "p10": quantile(values, 0.10),
            "p50": quantile(values, 0.50),
            "p90": quantile(values, 0.90),
            "minimum": min(values),
            "maximum": max(values),
        }
    return output


def assert_matched_person_hours(
    rows: Iterable[Mapping[str, object]],
    *,
    scenario_ids: Sequence[str],
    value_field: str,
    tolerance: float,
    seed_field: str = "seed",
    scenario_field: str = "scenario_id",
) -> None:
    if tolerance < 0:
        raise ReportingError("tolerance must not be negative")
    requested = tuple(scenario_ids)
    if len(requested) < 2:
        raise ReportingError("matched comparison requires at least two scenarios")
    by_seed: dict[object, dict[str, float]] = defaultdict(dict)
    for row in rows:
        scenario = str(row[scenario_field])
        if scenario in requested:
            seed = row[seed_field]
            if scenario in by_seed[seed]:
                raise ReportingError(f"duplicate scenario/seed row: {scenario}:{seed}")
            by_seed[seed][scenario] = float(row[value_field])
    if not by_seed:
        raise ReportingError("no matched person-hour rows")
    for seed, values in by_seed.items():
        missing = set(requested).difference(values)
        if missing:
            raise ReportingError(
                f"missing matched person-hours for seed {seed}: {sorted(missing)}"
            )
        reference = values[requested[0]]
        for scenario in requested[1:]:
            if abs(values[scenario] - reference) > tolerance:
                raise ReportingError(
                    "matched person-hours differ: "
                    f"seed={seed}:{requested[0]}={reference}:{scenario}={values[scenario]}"
                )


def paired_deltas(
    rows: Iterable[Mapping[str, object]],
    *,
    baseline_scenario: str,
    comparison_scenario: str,
    identity_fields: Sequence[str],
    scenario_field: str = "scenario_id",
    value_field: str = "value",
) -> tuple[dict[str, object], ...]:
    """Return exact-pair absolute and percentage differences for two scenarios."""

    if baseline_scenario == comparison_scenario:
        raise ReportingError("paired scenarios must be distinct")
    if not identity_fields:
        raise ReportingError("paired identities require at least one field")
    selected: dict[str, dict[tuple[object, ...], float]] = {
        baseline_scenario: {},
        comparison_scenario: {},
    }
    for row in rows:
        scenario = str(row[scenario_field])
        if scenario not in selected:
            continue
        identity = tuple(row[field] for field in identity_fields)
        if identity in selected[scenario]:
            raise ReportingError(f"duplicate paired identity: {scenario}:{identity}")
        value = float(row[value_field])
        if not math.isfinite(value):
            raise ReportingError(f"non-finite paired value: {scenario}:{identity}")
        selected[scenario][identity] = value
    baseline = selected[baseline_scenario]
    comparison = selected[comparison_scenario]
    if not baseline or set(baseline) != set(comparison):
        raise ReportingError("paired identities differ between scenarios")
    output: list[dict[str, object]] = []
    for identity in sorted(baseline, key=repr):
        reference = baseline[identity]
        if abs(reference) <= 1e-15:
            raise ReportingError(f"zero baseline in paired identity: {identity}")
        value = comparison[identity]
        difference = value - reference
        row = {field: item for field, item in zip(identity_fields, identity)}
        row.update(
            {
                "baseline_value": reference,
                "comparison_value": value,
                "difference": difference,
                "percent_difference": difference / reference * 100.0,
            }
        )
        output.append(row)
    return tuple(output)


def summarize_delta_rows(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, float]:
    """Summarize a paired-difference table using the registered linear quantiles."""

    materialized = tuple(rows)
    if not materialized:
        raise ReportingError("paired delta summary requires at least one row")
    differences = [float(row["difference"]) for row in materialized]
    percentages = [float(row["percent_difference"]) for row in materialized]
    if any(not math.isfinite(value) for value in (*differences, *percentages)):
        raise ReportingError("paired delta summary values must be finite")
    return {
        "count": len(materialized),
        "difference_p10": quantile(differences, 0.10),
        "difference_p50": quantile(differences, 0.50),
        "difference_p90": quantile(differences, 0.90),
        "percent_p10": quantile(percentages, 0.10),
        "percent_p50": quantile(percentages, 0.50),
        "percent_p90": quantile(percentages, 0.90),
    }


def paired_energy_statistics(
    rows: Iterable[Mapping[str, object]],
    *,
    baseline_scenario: str,
    comparison_scenario: str,
    identity_fields: Sequence[str],
    scenario_field: str = "scenario_id",
    value_field: str = "value",
) -> dict[str, object]:
    """Return full preregistered paired statistics without dropping zero bases."""

    if baseline_scenario == comparison_scenario:
        raise ReportingError("paired scenarios must be distinct")
    if not identity_fields:
        raise ReportingError("paired identities require at least one field")
    selected: dict[str, dict[tuple[object, ...], float]] = {
        baseline_scenario: {},
        comparison_scenario: {},
    }
    for row in rows:
        scenario = str(row[scenario_field])
        if scenario not in selected:
            continue
        identity = tuple(row[field] for field in identity_fields)
        if identity in selected[scenario]:
            raise ReportingError(f"duplicate paired identity: {scenario}:{identity}")
        value = float(row[value_field])
        if not math.isfinite(value):
            raise ReportingError(f"non-finite paired value: {scenario}:{identity}")
        selected[scenario][identity] = value
    baseline = selected[baseline_scenario]
    comparison = selected[comparison_scenario]
    if not baseline or set(baseline) != set(comparison):
        raise ReportingError("paired identities differ between scenarios")

    pairs = []
    differences = []
    percentages = []
    for identity in sorted(baseline, key=repr):
        reference = baseline[identity]
        value = comparison[identity]
        difference = value - reference
        percentage = (
            difference / reference * 100.0 if abs(reference) > 1.0e-15 else None
        )
        pair = {field: item for field, item in zip(identity_fields, identity)}
        pair.update(
            {
                "baseline_value": reference,
                "comparison_value": value,
                "difference": difference,
                "percent_difference": percentage,
            }
        )
        pairs.append(pair)
        differences.append(difference)
        if percentage is not None:
            percentages.append(percentage)

    def statistics(values: list[float], prefix: str) -> dict[str, object]:
        if not values:
            return {
                f"{prefix}_mean": None,
                f"{prefix}_median": None,
                f"{prefix}_minimum": None,
                f"{prefix}_maximum": None,
                f"{prefix}_p10": None,
                f"{prefix}_p90": None,
            }
        return {
            f"{prefix}_mean": sum(values) / len(values),
            f"{prefix}_median": quantile(values, 0.50),
            f"{prefix}_minimum": min(values),
            f"{prefix}_maximum": max(values),
            f"{prefix}_p10": quantile(values, 0.10),
            f"{prefix}_p90": quantile(values, 0.90),
        }

    return {
        "n": len(differences),
        "percent_n": len(percentages),
        **statistics(differences, "difference"),
        **statistics(percentages, "percent"),
        "pairs": tuple(pairs),
    }
