"""Fixed-HVAC sizing and protected-object gates for Airport ABM V3.1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class FixedSizingAuditError(ValueError):
    """Raised when an applySizingValues audit is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class FixedSizingDecision:
    status: str
    unresolved_critical_fields: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProtectedObjectDecision:
    status: str
    reasons: tuple[str, ...]


CRITICAL_CATEGORIES = frozenset(
    {
        "Fan",
        "Coil",
        "VAV terminal",
        "AirLoop",
        "PlantLoop",
        "Pump",
        "FourPipeFanCoil",
        "OutdoorAir",
        "HeatExchanger",
        "Air terminal",
        "Other critical HVAC",
    }
)


def _count(payload: Mapping[str, object], name: str) -> int:
    try:
        value = int(payload[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise FixedSizingAuditError(f"fixed-sizing count is missing: {name}") from exc
    if value < 0:
        raise FixedSizingAuditError(f"fixed-sizing count is negative: {name}")
    return value


def evaluate_fixed_sizing_audit(
    payload: Mapping[str, object],
) -> FixedSizingDecision:
    if payload.get("schema_version") != "idfrepair.airport-fixed-sizing-audit.v31":
        raise FixedSizingAuditError("fixed-sizing audit schema is invalid")
    before = _count(payload, "autosizable_fields_before")
    available = _count(payload, "autosized_values_available")
    applied = _count(payload, "values_applied")
    unresolved = _count(payload, "autosizable_fields_unresolved")
    if available != applied:
        raise FixedSizingAuditError(
            "not all available sizing values were applied"
        )
    if before != applied + unresolved:
        raise FixedSizingAuditError(
            "autosizable field reconciliation is inconsistent"
        )
    categories = payload.get("categories")
    if not isinstance(categories, Mapping) or not categories:
        raise FixedSizingAuditError("fixed-sizing categories are missing")
    category_totals = {name: 0 for name in ("before", "available", "applied", "unresolved")}
    unresolved_critical = 0
    for category, raw in categories.items():
        if not isinstance(raw, Mapping):
            raise FixedSizingAuditError(f"fixed-sizing category is invalid: {category}")
        values = {name: _count(raw, name) for name in category_totals}
        if values["available"] != values["applied"]:
            raise FixedSizingAuditError(
                f"not all available sizing values were applied: {category}"
            )
        if values["before"] != values["applied"] + values["unresolved"]:
            raise FixedSizingAuditError(
                f"fixed-sizing category does not reconcile: {category}"
            )
        for name, value in values.items():
            category_totals[name] += value
        if str(category) in CRITICAL_CATEGORIES:
            unresolved_critical += values["unresolved"]
    if category_totals != {
        "before": before,
        "available": available,
        "applied": applied,
        "unresolved": unresolved,
    }:
        raise FixedSizingAuditError("fixed-sizing category totals do not reconcile")
    reasons = []
    if not bool(payload.get("source_unchanged")):
        reasons.append("source_changed")
    if not bool(payload.get("protected_objects_unchanged")):
        reasons.append("protected_objects_changed")
    if unresolved_critical:
        reasons.append("critical_autosized_fields_unresolved")
    return FixedSizingDecision(
        status=(
            "FIXED_OPERATION_COMPARISON_VALID"
            if not reasons
            else "FIXED_OPERATION_INCOMPLETE"
        ),
        unresolved_critical_fields=unresolved_critical,
        reasons=tuple(reasons),
    )


def evaluate_people_only_derivative(
    *,
    source_unchanged: bool,
    people_schedule_only: bool,
    protected_inventory_equal: bool,
    common_operation_controls_equal: bool,
    dcv_equal: bool,
    ideal_loads_added: int,
) -> ProtectedObjectDecision:
    if ideal_loads_added < 0:
        raise ValueError("IdealLoads delta must not be negative")
    reasons = []
    if not source_unchanged:
        reasons.append("source_changed")
    if not people_schedule_only:
        reasons.append("non_people_object_changed")
    if not protected_inventory_equal:
        reasons.append("protected_inventory_changed")
    if not common_operation_controls_equal:
        reasons.append("operation_controls_differ")
    if not dcv_equal:
        reasons.append("dcv_changed")
    if ideal_loads_added:
        reasons.append("ideal_loads_added")
    return ProtectedObjectDecision(
        status=(
            "PASS_PEOPLE_SCHEDULE_ONLY"
            if not reasons
            else "FAIL_PROTECTED_OBJECT_DIFF"
        ),
        reasons=tuple(reasons),
    )
