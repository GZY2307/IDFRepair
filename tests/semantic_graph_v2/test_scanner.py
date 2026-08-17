"""验证 whole-model scanner 无需 family/locator 即发现跨 relation faults。"""

from __future__ import annotations

from idfrepair.io.idf import parse_idf
from idfrepair.semantic_graph_v2.scan import scan_model

from .conftest import IR_IDD, IR_IDF


CLEAN = IR_IDF.replace(
    "ZoneHVAC:EquipmentConnections,Z1,Wrong Equipment,",
    "ZoneHVAC:EquipmentConnections,Z1,Z1 Equipment,",
)


def _constraint_ids(text: str) -> set[str]:
    return set(scan_model(parse_idf(text), IR_IDD).constraint_ids)


def test_clean_cross_relation_fixture_has_no_hard_violations() -> None:
    result = scan_model(parse_idf(CLEAN), IR_IDD)

    assert result.hard_violations == ()


def test_applicability_does_not_claim_constraints_without_any_scope() -> None:
    result = scan_model(parse_idf("Version,24.1;"), IR_IDD)

    assert result.applicability
    assert all(not row.applied for row in result.applicability)
    assert {row.reason for row in result.applicability} == {"no_applicable_scope"}


def test_unsupported_oa_port_scope_is_reported_not_applied() -> None:
    result = scan_model(parse_idf(CLEAN), IR_IDD)
    applicability = next(
        row for row in result.applicability
        if row.constraint_id == "V2-OA-EQUIPMENT-PATH-010"
    )

    assert applicability.applied is False
    assert applicability.reason == "incomplete_compound_flow_scope"


def test_scanner_finds_branch_identity_and_symmetric_endpoint_faults() -> None:
    wrong_identity = CLEAN.replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,",
        "Branch,Air Branch,,Fan:ConstantVolume,Fan B,A0,A1,",
    )
    wrong_inlet = CLEAN.replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,",
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,BAD,A1,",
    )
    wrong_outlet = CLEAN.replace(
        "Fan:ConstantVolume,Fan A,A0,A1,",
        "Fan:ConstantVolume,Fan A,A0,BAD,",
        1,
    )

    assert "V2-BRANCH-TYPED-IDENTITY-001" in _constraint_ids(wrong_identity)
    assert "V2-BRANCH-ENDPOINT-002" in _constraint_ids(wrong_inlet)
    assert "V2-BRANCH-ENDPOINT-002" in _constraint_ids(wrong_outlet)


def test_scanner_finds_loop_parallel_set_branchlist_and_boundary_faults() -> None:
    mixer_fault = CLEAN.replace(
        "Connector:Mixer,M1,SO,P2,P1;",
        "Connector:Mixer,M1,SO,P2,SI;",
    )
    list_member_fault = CLEAN.replace(
        "BranchList,BL1,SI,P2,P1,SO;",
        "BranchList,BL1,SI,P2,Air Branch,SO;",
    )
    list_boundary_fault = CLEAN.replace(
        "BranchList,BL1,SI,P2,P1,SO;",
        "BranchList,BL1,P2,SI,P1,SO;",
    )

    assert "V2-LOOP-PARALLEL-SET-004" in _constraint_ids(mixer_fault)
    assert "V2-LOOP-BRANCHLIST-SET-005" in _constraint_ids(list_member_fault)
    assert "V2-LOOP-BRANCHLIST-BOUNDARY-006" in _constraint_ids(list_boundary_fault)


def test_scanner_finds_loop_and_connector_ownership_faults() -> None:
    loop_fault = CLEAN.replace(
        "L0,LOut,BL1,CL1,",
        "L0,LOut,Missing Branches,CL1,",
    )
    connector_fault = CLEAN.replace(
        "ConnectorList,CL1,Connector:Splitter,S1,Connector:Mixer,M1;",
        "ConnectorList,CL1,Connector:Splitter,Missing,Connector:Mixer,M1;",
    )
    wrong_existing_connector = CLEAN.replace(
        "ConnectorList,CL1,Connector:Splitter,S1,Connector:Mixer,M1;",
        "ConnectorList,CL1,Connector:Splitter,S2,Connector:Mixer,M1;",
    ) + "\nConnector:Splitter,S2,Other Inlet,Q1,Q2;\n"

    assert "V2-LOOP-SIDE-OWNERSHIP-007" in _constraint_ids(loop_fault)
    assert "V2-CONNECTOR-TYPED-MEMBER-008" in _constraint_ids(connector_fault)
    assert "V2-CONNECTOR-TYPED-MEMBER-008" in _constraint_ids(
        wrong_existing_connector
    )


def test_scanner_finds_air_fault_and_abstains_from_pair_only_oa_scope() -> None:
    air_fault = CLEAN.replace(
        "AirLoopHVAC:SupplyPath,SP1,Supply Node,AirLoopHVAC:ZoneSplitter,ZS1;",
        "AirLoopHVAC:SupplyPath,SP1,Supply Node,AirLoopHVAC:ZoneSplitter,Missing;",
    )
    oa_clean = CLEAN.replace(
        "AirLoopHVAC:OutdoorAirSystem:EquipmentList,OA Equipment,OutdoorAir:Mixer,OA Mixer;",
        (
            "Fan:ConstantVolume,OA Fan 1,,OA In,OA Mid;\n"
            "Fan:ConstantVolume,OA Fan 2,,OA Mid,OA Out;\n"
            "AirLoopHVAC:OutdoorAirSystem:EquipmentList,OA Equipment,"
            "Fan:ConstantVolume,OA Fan 1,Fan:ConstantVolume,OA Fan 2;"
        ),
    )
    oa_fault = oa_clean.replace(
        "Fan:ConstantVolume,OA Fan 1,Fan:ConstantVolume,OA Fan 2;",
        "Fan:ConstantVolume,OA Fan 2,Fan:ConstantVolume,OA Fan 1;",
    )

    assert "V2-AIRPATH-TYPED-MEMBER-009" in _constraint_ids(air_fault)
    assert "V2-OA-EQUIPMENT-PATH-010" not in _constraint_ids(oa_fault)


def test_scanner_retains_stable_field_provenance() -> None:
    fault = CLEAN.replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,",
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,BAD,A1,",
    )
    first = scan_model(parse_idf(fault), IR_IDD)
    second = scan_model(parse_idf(fault), IR_IDD)
    violation = next(
        row for row in first.violations
        if row.constraint_id == "V2-BRANCH-ENDPOINT-002"
        and any(field.raw_value == "BAD" for field in row.field_refs)
    )

    assert violation.violation_id in {row.violation_id for row in second.violations}
    assert any(field.object_type == "Branch" for field in violation.field_refs)
    assert all(field.start < field.end for field in violation.field_refs)
