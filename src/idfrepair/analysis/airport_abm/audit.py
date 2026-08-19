"""Fail-closed baseline admission for the Airport Occupancy V3 workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


_EXPECTED_COUNTS = {
    "spaces": 304,
    "thermal_zones": 304,
    "air_loops": 14,
    "plant_loops": 2,
    "fan_coils": 75,
    "zone_exhaust_fans": 27,
    "heat_recovery_units": 7,
    "ideal_loads": 0,
    "doors": 98,
    "physical_reciprocal_door_pairs": 49,
    "unique_space_door_connections": 48,
}
_REQUIRED_RUNS = ("summer_design", "winter_design", "beijing_jan01_07")


@dataclass(frozen=True, slots=True)
class BaselineGateResult:
    status: str
    block_code: str | None
    violations: tuple[str, ...]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def validate_baseline_audit(audit: Mapping[str, Any]) -> BaselineGateResult:
    """Validate the exact inventory and independent simulation gates."""

    violations: list[str] = []
    if audit.get("schema_version") != "idfrepair.airport-abm-baseline-audit.v3":
        violations.append("schema_version")
    if audit.get("source_unchanged") is not True:
        violations.append("source_unchanged")
    if audit.get("draft_validity_errors") != 0:
        violations.append("draft_validity_errors")
    if audit.get("forward_translation_errors") != 0:
        violations.append("forward_translation_errors")

    counts = _mapping(audit.get("counts"))
    for name, expected in _EXPECTED_COUNTS.items():
        if counts.get(name) != expected:
            violations.append(f"counts.{name}")

    ventilation = _mapping(audit.get("mechanical_ventilation_controllers"))
    if ventilation.get("count") != 14:
        violations.append("mechanical_ventilation_controllers.count")
    if ventilation.get("demand_controlled_ventilation_enabled") != 0:
        violations.append(
            "mechanical_ventilation_controllers."
            "demand_controlled_ventilation_enabled"
        )

    runs = _mapping(audit.get("energyplus_runs"))
    for run_name in _REQUIRED_RUNS:
        if run_name not in runs:
            violations.append(f"energyplus_runs.{run_name}.missing")
            continue
        run = _mapping(runs.get(run_name))
        if run.get("severe") != 0:
            violations.append(f"energyplus_runs.{run_name}.severe")
        if run.get("fatal") != 0:
            violations.append(f"energyplus_runs.{run_name}.fatal")
        if run.get("completed") is not True:
            violations.append(f"energyplus_runs.{run_name}.completed")

    if violations:
        return BaselineGateResult(
            status="BLOCKED",
            block_code="OCCUPANCY_V3_BLOCKED_BASE_MODEL",
            violations=tuple(violations),
        )
    return BaselineGateResult(status="PASS", block_code=None, violations=())
