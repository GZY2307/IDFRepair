"""OA typed/order domains are exhaustive within the audited component frontier."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.candidates import (
    CandidateDomainStatus,
    generate_candidates,
)
from idfrepair.semantic_graph_v2.runtime import RepairStatus, repair_model
from idfrepair.semantic_graph_v2.scan import scan_ir

from .compound_relation_fixtures import (
    BASE,
    RELATION_IDD,
    prospective_registry,
    prospective_scan,
    relation_model,
)


OA = "V2-OA-EQUIPMENT-PATH-010"


def _missing_hx(text: str) -> str:
    return text.replace(
        "HeatExchanger:AirToAir:SensibleAndLatent,HX1,OutdoorAir:Mixer,OA Mixer;",
        "HeatExchanger:AirToAir:SensibleAndLatent,Missing,OutdoorAir:Mixer,OA Mixer;",
    )


def test_unique_oa_typed_member_candidate_repairs_both_traversals() -> None:
    fault = _missing_hx(BASE)
    outcome = repair_model(
        fault, RELATION_IDD, registry=prospective_registry(OA),
    )

    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert len(outcome.selected_edits) == 1
    assert outcome.selected_edits[0].field_edits[-1].new_value == "HX1"


def test_two_equal_oa_typed_alternatives_abstain() -> None:
    fault = _missing_hx(BASE) + (
        "HeatExchanger:AirToAir:SensibleAndLatent,HX Twin,,1,0.7,0.6,0.7,"
        "0.6,OA Source,OA Outside,OA Relief,OA Exhaust;\n"
    )
    registry = prospective_registry(OA)
    outcome = repair_model(fault, RELATION_IDD, registry=registry)

    assert outcome.status is RepairStatus.NEEDS_INPUT
    assert outcome.selected_edits == ()
    assert outcome.decisions[0].alternative_count == 2


def test_oa_candidate_set_marks_supported_domain_complete() -> None:
    model, scan, _ = prospective_scan(_missing_hx(BASE), OA)
    violation = next(row for row in scan.hard_violations if row.constraint_id == OA)
    domain = generate_candidates(model, scan).for_violation(violation.violation_id)

    assert domain is not None
    assert domain.status is CandidateDomainStatus.COMPLETE
    assert len(domain.candidates) == 1


def test_unsupported_or_incomplete_oa_scope_is_not_a_hard_fault() -> None:
    unsupported = BASE.replace(
        "HeatExchanger:AirToAir:SensibleAndLatent,HX1,OutdoorAir:Mixer,OA Mixer;",
        "Fan:ConstantVolume,Other Fan,OutdoorAir:Mixer,OA Mixer;",
    ) + "Fan:ConstantVolume,Other Fan,,OA Source,OA Outside;\n"
    incomplete = BASE.replace(
        "OutdoorAir:Mixer,OA Mixer,OA Mixed,OA Outside,OA Relief,OA Return;",
        "OutdoorAir:Mixer,OA Mixer,OA Mixed,OA Outside,,OA Return;",
    )

    for text in (unsupported, incomplete):
        result = scan_ir(
            relation_model(text), registry=prospective_registry(OA),
        )
        assert not any(row.constraint_id == OA for row in result.hard_violations)


def test_flatplate_projection_does_not_imply_oa_safe_auto_admission() -> None:
    text = BASE.replace(
        "HeatExchanger:AirToAir:SensibleAndLatent,HX1,OutdoorAir:Mixer,OA Mixer;",
        "HeatExchanger:AirToAir:FlatPlate,FP1,OutdoorAir:Mixer,OA Mixer;",
    ) + (
        "HeatExchanger:AirToAir:FlatPlate,FP1,,CounterFlow,Yes,1,1,20,10,"
        "1,20,0,OA Source,OA Outside,OA Relief,OA Exhaust;\n"
    )

    model = relation_model(text)
    flat_plate = next(
        obj for obj in model.objects if obj.raw_name == "FP1"
    )
    result = scan_ir(model, registry=prospective_registry(OA))

    assert model.projections_for(flat_plate.object_id)[0].complete is True
    assert not any(row.constraint_id == OA for row in result.hard_violations)
