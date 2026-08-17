"""ReturnPath scanning closes merge/plenum topology toward the path boundary."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.runtime import RepairStatus, repair_model
from idfrepair.semantic_graph_v2.scan import scan_ir

from .compound_relation_fixtures import (
    BASE,
    RELATION_IDD,
    prospective_registry,
    relation_model,
)


AIR = "V2-AIRPATH-TYPED-MEMBER-009"


def test_returnpath_plenum_and_mixer_close_independent_of_declaration_order() -> None:
    reordered = BASE.replace(
        "AirLoopHVAC:ReturnPlenum,RP1,AirLoopHVAC:ZoneMixer,ZM1;",
        "AirLoopHVAC:ZoneMixer,ZM1,AirLoopHVAC:ReturnPlenum,RP1;",
    )

    assert AIR not in scan_ir(relation_model()).constraint_ids
    assert AIR not in scan_ir(relation_model(reordered)).constraint_ids


def test_returnpath_wrong_type_and_name_has_one_topology_replacement() -> None:
    fault = BASE.replace(
        "AirLoopHVAC:ReturnPlenum,RP1,AirLoopHVAC:ZoneMixer,ZM1;",
        "AirLoopHVAC:ZoneMixer,Missing,AirLoopHVAC:ZoneMixer,ZM1;",
    )
    registry = prospective_registry(AIR)

    outcome = repair_model(fault, RELATION_IDD, registry=registry)

    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert len(outcome.selected_edits) == 1
    assert len(outcome.selected_edits[0].field_edits) == 2
    assert "AirLoopHVAC:ReturnPlenum,RP1" in outcome.output_text
