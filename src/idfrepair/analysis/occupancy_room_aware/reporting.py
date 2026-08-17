"""Fail-closed helpers for compact room-aware result reports."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import csv
import math
from pathlib import Path
from typing import Any


_IDENTITY_FIELDS = ("period_id", "category", "space_name", "zone_name")
PAPER_READY = "OCCUPANCY_CASE_PAPER_READY"
DEMO_ONLY = "OCCUPANCY_CASE_DEMO_ONLY"
NOT_ADMISSIBLE = "OCCUPANCY_CASE_NOT_ADMISSIBLE"
_MATCHED_NON_VOLUME_SCENARIOS = {
    "public_morning",
    "public_midday",
    "public_evening",
    "public_perimeter",
    "public_core",
    "entrance_2_lead",
    "entrance_3_lead",
}
_LOCAL_SCOPES = {"seasonal_category", "seasonal_zone", "annual_category"}
_ADMISSION_THRESHOLDS = {
    "heating_peak_kw": {"minimum_baseline": 50.0, "minimum_absolute_delta": 20.0, "minimum_relative_delta_pct": 10.0},
    "cooling_peak_kw": {"minimum_baseline": 50.0, "minimum_absolute_delta": 20.0, "minimum_relative_delta_pct": 10.0},
    "heating_kwh": {"minimum_baseline": 100.0, "minimum_absolute_delta": 100.0, "minimum_relative_delta_pct": 10.0},
    "cooling_kwh": {"minimum_baseline": 100.0, "minimum_absolute_delta": 100.0, "minimum_relative_delta_pct": 10.0},
}


def _number(row: dict[str, Any], field: str) -> float:
    raw = row.get(field)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"report_numeric_value_invalid:{field}:{raw}") from exc
    if not math.isfinite(value):
        raise ValueError(f"report_numeric_value_nonfinite:{field}:{raw}")
    return value


def _identity(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "") for field in _IDENTITY_FIELDS)


def assert_same_person_hours(
    rows: Iterable[dict[str, Any]],
    *,
    scenario_ids: Sequence[str],
    baseline_id: str = "baseline_r",
    tolerance: float = 1e-6,
) -> None:
    """Require matched person-hours for each retained grouping."""

    records = list(rows)
    baselines = {
        _identity(row): _number(row, "person_hours")
        for row in records
        if row.get("scenario_id") == baseline_id
    }
    if not baselines:
        raise ValueError("report_baseline_missing")
    selected = set(scenario_ids)
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for row in records:
        scenario_id = str(row.get("scenario_id") or "")
        if scenario_id not in selected:
            continue
        identity = _identity(row)
        if identity not in baselines:
            raise ValueError(f"report_baseline_group_missing:{scenario_id}:{identity}")
        actual = _number(row, "person_hours")
        expected = baselines[identity]
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
            raise ValueError(
                "report_person_hours_not_conserved:"
                f"{scenario_id}:{identity}:{actual}:{expected}"
            )
        seen.add((scenario_id, identity))
    expected_pairs = {(scenario, identity) for scenario in selected for identity in baselines}
    if seen != expected_pairs:
        raise ValueError("report_counterfactual_group_coverage_mismatch")


def ranked_effects(
    rows: Iterable[dict[str, Any]],
    *,
    scenario_ids: Sequence[str],
    metrics: Sequence[str],
    baseline_id: str = "baseline_r",
    minimum_baseline: float = 1e-9,
) -> list[dict[str, Any]]:
    """Return absolute-percent-ranked effects relative to a matched baseline."""

    records = list(rows)
    baselines = {
        _identity(row): row
        for row in records
        if row.get("scenario_id") == baseline_id
    }
    if not baselines:
        raise ValueError("report_baseline_missing")
    selected = set(scenario_ids)
    effects: list[dict[str, Any]] = []
    for row in records:
        scenario_id = str(row.get("scenario_id") or "")
        if scenario_id not in selected:
            continue
        identity = _identity(row)
        baseline = baselines.get(identity)
        if baseline is None:
            raise ValueError(f"report_baseline_group_missing:{scenario_id}:{identity}")
        for metric in metrics:
            reference = _number(baseline, metric)
            if abs(reference) < minimum_baseline:
                continue
            value = _number(row, metric)
            delta = value - reference
            effects.append(
                {
                    "scenario_id": scenario_id,
                    "period_id": identity[0],
                    "category": identity[1],
                    "space_name": identity[2],
                    "zone_name": identity[3],
                    "metric": metric,
                    "baseline": reference,
                    "value": value,
                    "delta": delta,
                    "delta_pct": delta / reference * 100.0,
                }
            )
    effects.sort(
        key=lambda row: (
            -abs(float(row["delta_pct"])),
            str(row["period_id"]),
            str(row["scenario_id"]),
            str(row["metric"]),
            str(row["category"]),
            str(row["space_name"]),
        )
    )
    return effects


def evaluate_paper_admission(
    effects: Sequence[dict[str, Any]] | None,
    *,
    evidence_valid: bool,
) -> dict[str, Any]:
    """Return a three-state, evidence-driven manuscript admission decision."""

    if not evidence_valid or effects is None:
        return {
            "status": NOT_ADMISSIBLE,
            "reason": "required_evidence_missing_or_invalid",
            "qualifying_effects": [],
            "thresholds": _ADMISSION_THRESHOLDS,
        }
    required = {
        "analysis_scope",
        "scenario_id",
        "period_id",
        "metric",
        "baseline",
        "delta",
        "delta_pct",
    }
    qualifying: list[dict[str, Any]] = []
    for index, effect in enumerate(effects):
        if not isinstance(effect, dict) or not required.issubset(effect):
            return {
                "status": NOT_ADMISSIBLE,
                "reason": f"effect_record_invalid:{index}",
                "qualifying_effects": [],
                "thresholds": _ADMISSION_THRESHOLDS,
            }
        try:
            baseline = float(effect["baseline"])
            delta = float(effect["delta"])
            delta_pct = float(effect["delta_pct"])
        except (TypeError, ValueError):
            return {
                "status": NOT_ADMISSIBLE,
                "reason": f"effect_numeric_invalid:{index}",
                "qualifying_effects": [],
                "thresholds": _ADMISSION_THRESHOLDS,
            }
        if not all(math.isfinite(value) for value in (baseline, delta, delta_pct)):
            return {
                "status": NOT_ADMISSIBLE,
                "reason": f"effect_numeric_nonfinite:{index}",
                "qualifying_effects": [],
                "thresholds": _ADMISSION_THRESHOLDS,
            }
        metric = str(effect["metric"])
        threshold = _ADMISSION_THRESHOLDS.get(metric)
        if (
            threshold is None
            or str(effect["scenario_id"]) not in _MATCHED_NON_VOLUME_SCENARIOS
            or str(effect["analysis_scope"]) not in _LOCAL_SCOPES
        ):
            continue
        if (
            abs(baseline) >= threshold["minimum_baseline"]
            and abs(delta) >= threshold["minimum_absolute_delta"]
            and abs(delta_pct) >= threshold["minimum_relative_delta_pct"]
        ):
            qualifying.append(dict(effect))
    qualifying.sort(
        key=lambda row: (
            -abs(float(row["delta_pct"])),
            -abs(float(row["delta"])),
            str(row["scenario_id"]),
        )
    )
    if not qualifying:
        return {
            "status": DEMO_ONLY,
            "reason": "no_non_volume_local_effect_passed_absolute_and_relative_thresholds",
            "qualifying_effects": [],
            "thresholds": _ADMISSION_THRESHOLDS,
        }
    return {
        "status": PAPER_READY,
        "reason": "localized_same_person_hours_effect_passed_predeclared_thresholds",
        "qualifying_effects": qualifying,
        "thresholds": _ADMISSION_THRESHOLDS,
    }


def _read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"report_table_header_missing:{path}")
        return list(reader.fieldnames), list(reader)


def combine_result_tables(
    seasonal_path: Path,
    annual_path: Path,
    destination: Path,
) -> int:
    """Combine compact seasonal and annual tables with an explicit scope field."""

    seasonal_fields, seasonal = _read_table(seasonal_path)
    annual_fields, annual = _read_table(annual_path)
    if seasonal_fields != annual_fields:
        raise ValueError("report_table_schema_mismatch")
    fieldnames = ["simulation_scope", *seasonal_fields]
    rows = [
        {"simulation_scope": scope, **row}
        for scope, source in (("seasonal", seasonal), ("annual", annual))
        for row in source
    ]
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


__all__ = [
    "DEMO_ONLY",
    "NOT_ADMISSIBLE",
    "PAPER_READY",
    "assert_same_person_hours",
    "combine_result_tables",
    "evaluate_paper_admission",
    "ranked_effects",
]
