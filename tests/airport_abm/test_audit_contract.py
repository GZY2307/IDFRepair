from __future__ import annotations

import importlib


def _valid_audit() -> dict[str, object]:
    return {
        "schema_version": "idfrepair.airport-abm-baseline-audit.v3",
        "source_unchanged": True,
        "draft_validity_errors": 0,
        "forward_translation_errors": 0,
        "counts": {
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
        },
        "mechanical_ventilation_controllers": {
            "count": 14,
            "demand_controlled_ventilation_enabled": 0,
        },
        "energyplus_runs": {
            "summer_design": {"severe": 0, "fatal": 0, "completed": True},
            "winter_design": {"severe": 0, "fatal": 0, "completed": True},
            "beijing_jan01_07": {"severe": 0, "fatal": 0, "completed": True},
        },
    }


def test_baseline_gate_accepts_only_the_exact_valid_inventory() -> None:
    module = importlib.import_module("idfrepair.analysis.airport_abm.audit")

    result = module.validate_baseline_audit(_valid_audit())

    assert result.status == "PASS"
    assert result.block_code is None
    assert result.violations == ()


def test_baseline_gate_reports_all_failures_and_blocks_abm() -> None:
    module = importlib.import_module("idfrepair.analysis.airport_abm.audit")
    audit = _valid_audit()
    audit["source_unchanged"] = False
    audit["draft_validity_errors"] = 2
    audit["counts"]["air_loops"] = 13  # type: ignore[index]
    audit["counts"]["ideal_loads"] = 1  # type: ignore[index]
    audit["mechanical_ventilation_controllers"][  # type: ignore[index]
        "demand_controlled_ventilation_enabled"
    ] = 1
    audit["energyplus_runs"]["winter_design"]["severe"] = 1  # type: ignore[index]

    result = module.validate_baseline_audit(audit)

    assert result.status == "BLOCKED"
    assert result.block_code == "OCCUPANCY_V3_BLOCKED_BASE_MODEL"
    assert result.violations == (
        "source_unchanged",
        "draft_validity_errors",
        "counts.air_loops",
        "counts.ideal_loads",
        "mechanical_ventilation_controllers.demand_controlled_ventilation_enabled",
        "energyplus_runs.winter_design.severe",
    )


def test_baseline_gate_rejects_a_missing_required_run_instead_of_defaulting() -> None:
    module = importlib.import_module("idfrepair.analysis.airport_abm.audit")
    audit = _valid_audit()
    del audit["energyplus_runs"]["beijing_jan01_07"]  # type: ignore[index]

    result = module.validate_baseline_audit(audit)

    assert result.status == "BLOCKED"
    assert result.violations == ("energyplus_runs.beijing_jan01_07.missing",)
