"""Unsupported and incomplete compound scopes cannot become hard faults."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.scan import scan_ir

from .compound_relation_fixtures import (
    BASE,
    prospective_registry,
    relation_model,
)


AIR = "V2-AIRPATH-TYPED-MEMBER-009"
OA = "V2-OA-EQUIPMENT-PATH-010"


def test_unsupported_airpath_and_partial_oa_projection_abstain() -> None:
    unsupported_air = BASE.replace(
        "AirLoopHVAC:ZoneSplitter,ZS1,AirLoopHVAC:SupplyPlenum,SP1;",
        "Fan:ConstantVolume,Other Fan,AirLoopHVAC:SupplyPlenum,SP1;",
    )
    partial_oa = BASE.replace(
        "OutdoorAir:Mixer,OA Mixer,OA Mixed,OA Outside,OA Relief,OA Return;",
        "OutdoorAir:Mixer,OA Mixer,OA Mixed,OA Outside,,OA Return;",
    )

    air_scan = scan_ir(relation_model(unsupported_air), registry=prospective_registry(AIR))
    oa_scan = scan_ir(relation_model(partial_oa), registry=prospective_registry(OA))

    assert not any(row.constraint_id == AIR for row in air_scan.hard_violations)
    assert not any(row.constraint_id == OA for row in oa_scan.hard_violations)
