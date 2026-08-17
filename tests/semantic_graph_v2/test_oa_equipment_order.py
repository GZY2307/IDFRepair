"""OA order closes both the primary and reverse auxiliary traversals."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.runtime import RepairStatus, repair_model
from idfrepair.semantic_graph_v2.scan import scan_ir

from .compound_relation_fixtures import (
    BASE,
    RELATION_IDD,
    prospective_registry,
    relation_model,
)


OA = "V2-OA-EQUIPMENT-PATH-010"


def _swapped(text: str) -> str:
    return text.replace(
        "HeatExchanger:AirToAir:SensibleAndLatent,HX1,"
        "OutdoorAir:Mixer,OA Mixer;",
        "OutdoorAir:Mixer,OA Mixer,"
        "HeatExchanger:AirToAir:SensibleAndLatent,HX1;",
    )


def test_clean_hx_mixer_chain_closes_primary_and_auxiliary() -> None:
    assert OA not in scan_ir(relation_model()).constraint_ids


def test_controller_anchor_fault_does_not_fabricate_list_repair() -> None:
    fault = BASE.replace(
        "Controller:OutdoorAir,OA Controller,OA Relief,OA Return,OA Mixed,OA Source;",
        "Controller:OutdoorAir,OA Controller,OA Relief,OA Return,OA Mixed,BAD Source;",
    )

    assert OA not in scan_ir(relation_model(fault)).constraint_ids


def test_swapped_hx_mixer_order_has_one_complete_reorder() -> None:
    fault = _swapped(BASE)
    result = scan_ir(relation_model(fault))
    violation = next(row for row in result.violations if row.constraint_id == OA)

    assert dict(violation.expected)["compatible_orders"] == "2,1"
    assert dict(violation.expected)["candidate_domain_status"] == "COMPLETE"

    outcome = repair_model(
        fault, RELATION_IDD, registry=prospective_registry(OA),
    )
    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert len(outcome.selected_edits) == 1
    assert len(outcome.selected_edits[0].field_edits) == 4


def test_auxiliary_only_fault_without_list_candidate_abstains() -> None:
    fault = BASE.replace(
        "OutdoorAir:Mixer,OA Mixer,OA Mixed,OA Outside,OA Relief,OA Return;",
        "OutdoorAir:Mixer,OA Mixer,OA Mixed,OA Outside,BAD Relief,OA Return;",
    )
    registry = prospective_registry(OA)
    outcome = repair_model(fault, RELATION_IDD, registry=registry)

    assert OA not in outcome.initial_scan.constraint_ids
    assert outcome.status is RepairStatus.VALID
    assert outcome.selected_edits == ()
