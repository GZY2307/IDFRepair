import pytest

from idfrepair.analysis.airport_abm.fixed_sizing import (
    FixedSizingAuditError,
    evaluate_fixed_sizing_audit,
)


def test_apply_sizing_values_contract_requires_every_available_value_to_be_applied() -> None:
    payload = {
        "schema_version": "idfrepair.airport-fixed-sizing-audit.v31",
        "source_unchanged": True,
        "protected_objects_unchanged": True,
        "autosizable_fields_before": 3,
        "autosized_values_available": 3,
        "values_applied": 2,
        "autosizable_fields_unresolved": 0,
        "categories": {
            "Coil": {"before": 3, "available": 3, "applied": 2, "unresolved": 0}
        },
    }

    with pytest.raises(FixedSizingAuditError, match="available sizing values"):
        evaluate_fixed_sizing_audit(payload)


def test_apply_sizing_values_contract_fails_when_source_or_protected_objects_change() -> None:
    payload = {
        "schema_version": "idfrepair.airport-fixed-sizing-audit.v31",
        "source_unchanged": False,
        "protected_objects_unchanged": False,
        "autosizable_fields_before": 1,
        "autosized_values_available": 1,
        "values_applied": 1,
        "autosizable_fields_unresolved": 0,
        "categories": {
            "Pump": {"before": 1, "available": 1, "applied": 1, "unresolved": 0}
        },
    }

    decision = evaluate_fixed_sizing_audit(payload)

    assert decision.status == "FIXED_OPERATION_INCOMPLETE"
    assert decision.reasons == ("source_changed", "protected_objects_changed")
