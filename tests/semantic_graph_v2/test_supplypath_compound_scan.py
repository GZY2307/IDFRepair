"""SupplyPath scanning uses the member-induced split graph, not a linear pair."""

from __future__ import annotations

from idfrepair.io.idf import parse_idf
from idfrepair.semantic_graph_v2.runtime import RepairStatus, repair_model
from idfrepair.semantic_graph_v2.scan import scan_ir

from .compound_relation_fixtures import (
    BASE,
    RELATION_IDD,
    prospective_registry,
    relation_model,
)


AIR = "V2-AIRPATH-TYPED-MEMBER-009"


def test_supplypath_clean_parallel_leaves_and_declaration_order_are_valid() -> None:
    reordered = BASE.replace(
        "AirLoopHVAC:ZoneSplitter,ZS1,AirLoopHVAC:SupplyPlenum,SP1;",
        "AirLoopHVAC:SupplyPlenum,SP1,AirLoopHVAC:ZoneSplitter,ZS1;",
    )

    assert AIR not in scan_ir(relation_model()).constraint_ids
    assert AIR not in scan_ir(relation_model(reordered)).constraint_ids


def test_supplypath_wrong_name_is_detected_by_whole_split_topology() -> None:
    fault = BASE.replace(
        "AirLoopHVAC:ZoneSplitter,ZS1,AirLoopHVAC:SupplyPlenum,SP1;",
        "AirLoopHVAC:ZoneSplitter,Missing,AirLoopHVAC:SupplyPlenum,SP1;",
    )
    result = scan_ir(relation_model(fault))
    violation = next(row for row in result.violations if row.constraint_id == AIR)

    assert dict(violation.expected)["compatible_replacements"] == "1@object:1"
    assert dict(violation.expected)["candidate_domain_status"] == "COMPLETE"
    assert violation.hard is True


def test_prospective_unique_supplypath_repair_closes_globally() -> None:
    fault = BASE.replace(
        "AirLoopHVAC:ZoneSplitter,ZS1,AirLoopHVAC:SupplyPlenum,SP1;",
        "AirLoopHVAC:SupplyPlenum,Missing,AirLoopHVAC:SupplyPlenum,SP1;",
    )
    registry = prospective_registry(AIR)

    outcome = repair_model(fault, RELATION_IDD, registry=registry)

    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert len(outcome.selected_edits) == 1
    assert len(outcome.selected_edits[0].field_edits) == 2
    assert AIR not in outcome.final_scan.constraint_ids
    assert "AirLoopHVAC:ZoneSplitter,ZS1" in outcome.output_text
