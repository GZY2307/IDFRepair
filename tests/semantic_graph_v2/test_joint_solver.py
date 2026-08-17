"""验证 bounded exact search 的 joint、ambiguity 与 search-bound 语义。"""

from __future__ import annotations

from dataclasses import replace

from idfrepair.io.idf import parse_idf
from idfrepair.semantic_graph_v2.build_ir import build_model_ir
from idfrepair.semantic_graph_v2.candidates import generate_candidates
from idfrepair.semantic_graph_v2.edits import apply_semantic_edits
from idfrepair.semantic_graph_v2.runtime import RepairStatus, repair_model
from idfrepair.semantic_graph_v2.scan import scan_ir, scan_model
from idfrepair.semantic_graph_v2.solver import (
    ComponentDecisionStatus,
    SolverLimits,
    build_conflict_components,
    solve_components,
)

from .conftest import IR_IDD
from .test_candidates import CLEAN, _connected_zone_double


def _ambiguous_branch(text: str = CLEAN) -> str:
    return text.replace(
        "Fan:ConstantVolume,Fan B,,A1,A2;",
        (
            "Fan:ConstantVolume,Fan B,,A1,A2;\n"
            "Fan:ConstantVolume,Fan A Twin,,A0,A1;"
        ),
    ).replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,",
        "Branch,Air Branch,,Fan:ConstantVolume,Unknown,A0,A1,",
    )


def test_connected_double_requires_two_edits_in_one_unique_component() -> None:
    outcome = repair_model(_connected_zone_double(), IR_IDD)

    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert len(outcome.components) == 1
    assert outcome.decisions[0].status is ComponentDecisionStatus.UNIQUE_REPAIR
    assert len(outcome.selected_edits) == 2
    assert outcome.final_scan.hard_violations == ()


def test_zone_double_uses_ownership_reciprocity_when_member_score_is_zero() -> None:
    text = CLEAN.replace(
        "ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,"
        "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,1,2,,;",
        (
            "ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,"
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,1,2,,;\n"
            "ZoneHVAC:EnergyRecoveryVentilator,Unsupported ERV;\n"
            "ZoneHVAC:EquipmentList,Z3 Equipment,SequentialLoad,"
            "ZoneHVAC:EnergyRecoveryVentilator,Unsupported ERV,1,1,,;"
        ),
    ).replace(
        "ZoneHVAC:EquipmentConnections,Z1,Z1 Equipment,"
        "Z1 Supply,,Z1 Air,Z1 Return;",
        (
            "ZoneHVAC:EquipmentConnections,Z1,Wrong Equipment,"
            "Z1 Supply,,Z1 Air,Z1 Return;\n"
            "ZoneHVAC:EquipmentConnections,Z2,Wrong Equipment,"
            "Z2 Supply,,Z2 Air,Z2 Return;\n"
            "ZoneHVAC:EquipmentConnections,Z3,Z3 Equipment,"
            "Z3 Supply,,Z3 Air,Z3 Return;"
        ),
    )

    outcome = repair_model(text, IR_IDD)
    zone_violations = tuple(
        row for row in outcome.initial_scan.hard_violations
        if row.constraint_id.startswith("V2-ZONE-")
    )

    assert {row.constraint_id for row in zone_violations} == {
        "V2-ZONE-LIST-OWNERSHIP-011",
        "V2-ZONE-TYPED-MEMBER-012",
    }
    assert len(outcome.components) == 1
    assert outcome.decisions[0].status is ComponentDecisionStatus.UNIQUE_REPAIR
    assert outcome.decisions[0].objective == (2, 2)
    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert outcome.final_scan.hard_violations == ()
    assert "ZoneHVAC:EquipmentConnections,Z1,Z1 Equipment," in outcome.output_text
    assert "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,1,2" in outcome.output_text


PARTIAL_ZONE_DOUBLE = """Version,24.1;
ZoneHVAC:AirDistributionUnit,Z1 ADU,Z1 Supply,Terminal:Test,Z1 Terminal;
ZoneHVAC:FourPipeFanCoil,Z1 Fan Coil,,CyclingFan,Autosize,,,,,Z1 Return,Z1 Supply;
ZoneHVAC:FourPipeFanCoil,Z2 Fan Coil,,CyclingFan,Autosize,,,,,Z2 Return,Z2 Supply;
ZoneHVAC:PackagedTerminalHeatPump,Banquet PTHP,,Banquet Return,Banquet Supply;
ZoneHVAC:EquipmentList,Room 1 Equipment,SequentialLoad,
  ZoneHVAC:AirDistributionUnit,Z1 ADU,1,1,,,
  ZoneHVAC:FourPipeFanCoil,Z2 Fan Coil,2,2;
ZoneHVAC:EquipmentList,Room 2 Equipment,SequentialLoad,
  ZoneHVAC:FourPipeFanCoil,Z2 Fan Coil,1,1,,;
ZoneHVAC:EquipmentList,Banquet Equipment,SequentialLoad,
  ZoneHVAC:PackagedTerminalHeatPump,Banquet PTHP,1,1,,;
ZoneHVAC:EquipmentConnections,Room 1,Banquet Equipment,Z1 Supply,,Z1 Air,Z1 Return;
ZoneHVAC:EquipmentConnections,Room 2,Room 2 Equipment,Z2 Supply,,Z2 Air,Z2 Return;
ZoneHVAC:EquipmentConnections,Banquet,Banquet Equipment,
  Banquet Supply,,Banquet Air,Banquet Return;
"""


def test_zone_double_keeps_partial_extensible_member_and_avoids_duplicate_equipment() -> None:
    text = PARTIAL_ZONE_DOUBLE

    outcome = repair_model(text, IR_IDD)
    zone_violations = tuple(
        row for row in outcome.initial_scan.hard_violations
        if row.constraint_id.startswith("V2-ZONE-")
    )

    assert [row.constraint_id for row in zone_violations] == [
        "V2-ZONE-LIST-OWNERSHIP-011",
        "V2-ZONE-TYPED-MEMBER-012",
    ]
    assert len(outcome.components) == 1
    assert outcome.decisions[0].status is ComponentDecisionStatus.UNIQUE_REPAIR
    assert outcome.decisions[0].objective == (2, 2)
    assert len(outcome.selected_edits) == 2
    for edit in outcome.selected_edits:
        residual = scan_model(
            parse_idf(apply_semantic_edits(text, (edit,))), IR_IDD,
        )
        assert any(
            row.constraint_id.startswith("V2-ZONE-")
            for row in residual.hard_violations
        )
    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert outcome.final_scan.hard_violations == ()
    repaired = parse_idf(outcome.output_text)
    member_names = tuple(
        equipment_list.fields[index - 1].value
        for equipment_list in repaired.find_objects("ZoneHVAC:EquipmentList")
        for index in range(4, len(equipment_list.fields) + 1, 6)
    )
    assert member_names.count("Z1 Fan Coil") == 1
    assert member_names.count("Z2 Fan Coil") == 1


def test_zone_double_treats_resolved_non_port_sibling_as_neutral_evidence() -> None:
    text = PARTIAL_ZONE_DOUBLE.replace(
        "ZoneHVAC:AirDistributionUnit,Z1 ADU,Z1 Supply,Terminal:Test,Z1 Terminal;",
        "ZoneHVAC:EnergyRecoveryVentilator,Z1 ERV;",
    ).replace(
        "ZoneHVAC:AirDistributionUnit,Z1 ADU,1,1,,,",
        "ZoneHVAC:EnergyRecoveryVentilator,Z1 ERV,1,1,,,",
    )

    outcome = repair_model(text, IR_IDD)
    zone_violations = tuple(
        row for row in outcome.initial_scan.hard_violations
        if row.constraint_id.startswith("V2-ZONE-")
    )

    assert [row.constraint_id for row in zone_violations] == [
        "V2-ZONE-LIST-OWNERSHIP-011",
        "V2-ZONE-TYPED-MEMBER-012",
    ]
    assert len(outcome.components) == 1
    assert outcome.decisions[0].objective == (2, 2)
    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert outcome.final_scan.hard_violations == ()


def test_zone_double_without_any_exact_port_witness_is_not_auto_repaired() -> None:
    text = PARTIAL_ZONE_DOUBLE.replace(
        "ZoneHVAC:AirDistributionUnit,Z1 ADU,Z1 Supply,Terminal:Test,Z1 Terminal;",
        "ZoneHVAC:EnergyRecoveryVentilator,Z1 ERV;",
    ).replace(
        "ZoneHVAC:FourPipeFanCoil,Z1 Fan Coil,,CyclingFan,Autosize,,,,,Z1 Return,Z1 Supply;",
        "ZoneHVAC:EnergyRecoveryVentilator,Z1 Fan Coil;",
    ).replace(
        "ZoneHVAC:FourPipeFanCoil,Z2 Fan Coil,,CyclingFan,Autosize,,,,,Z2 Return,Z2 Supply;",
        "ZoneHVAC:EnergyRecoveryVentilator,Z2 Fan Coil;",
    ).replace(
        "ZoneHVAC:PackagedTerminalHeatPump,Banquet PTHP,,Banquet Return,Banquet Supply;",
        "ZoneHVAC:EnergyRecoveryVentilator,Banquet PTHP;",
    ).replace(
        "ZoneHVAC:AirDistributionUnit,Z1 ADU",
        "ZoneHVAC:EnergyRecoveryVentilator,Z1 ERV",
    ).replace(
        "ZoneHVAC:FourPipeFanCoil", "ZoneHVAC:EnergyRecoveryVentilator",
    ).replace(
        "ZoneHVAC:PackagedTerminalHeatPump", "ZoneHVAC:EnergyRecoveryVentilator",
    )

    outcome = repair_model(text, IR_IDD)

    assert outcome.selected_edits == ()
    assert outcome.output_text == text
    assert not any(
        row.constraint_id.startswith("V2-ZONE-")
        for row in outcome.initial_scan.hard_violations
    )


def test_connected_loop_double_uses_connector_reads_and_two_edit_closure() -> None:
    text = CLEAN.replace(
        "Connector:Splitter,S1,SI,P1,P2;",
        "Connector:Splitter,S1,SI,Air Branch,P2;",
    ).replace(
        "BranchList,BL1,SI,P2,P1,SO;",
        "BranchList,BL1,Air Branch,P2,P1,SO;",
    )
    outcome = repair_model(text, IR_IDD)

    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert len(outcome.components) == 1
    assert {
        row.constraint_id for row in outcome.initial_scan.hard_violations
    } == {
        "V2-LOOP-PARALLEL-SET-004",
        "V2-LOOP-BRANCHLIST-SET-005",
        "V2-LOOP-BRANCHLIST-BOUNDARY-006",
    }
    assert len(outcome.selected_edits) == 2
    assert outcome.decisions[0].objective == (2, 2)
    assert outcome.final_scan.hard_violations == ()


def test_identical_field_effects_from_two_domains_are_one_semantic_alternative() -> None:
    text = CLEAN.replace(
        "Connector:Splitter,S1,SI,P1,P2;",
        "Connector:Splitter,S1,SI,SO,P2;",
    ).replace(
        "BranchList,BL1,SI,P2,P1,SO;",
        "BranchList,BL1,Air Branch,P2,P1,SO;",
    )

    outcome = repair_model(text, IR_IDD)

    assert len(outcome.components) == 1
    assert outcome.decisions[0].status is ComponentDecisionStatus.UNIQUE_REPAIR
    assert outcome.decisions[0].alternative_count == 1
    assert outcome.decisions[0].objective == (2, 2)
    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert outcome.final_scan.hard_violations == ()


def test_wrong_existing_connector_member_uses_reciprocal_pair_for_one_edit_closure() -> None:
    text = CLEAN.replace(
        "ConnectorList,CL1,Connector:Splitter,S1,Connector:Mixer,M1;",
        "ConnectorList,CL1,Connector:Splitter,S2,Connector:Mixer,M1;",
    ) + "\nConnector:Splitter,S2,Other Inlet,Q1,Q2;\n"

    outcome = repair_model(text, IR_IDD)

    assert any(
        row.constraint_id == "V2-CONNECTOR-TYPED-MEMBER-008"
        for row in outcome.initial_scan.hard_violations
    )
    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert outcome.decisions[0].objective == (1, 1)
    assert len(outcome.selected_edits) == 1
    assert outcome.final_scan.hard_violations == ()


def test_single_member_inlet_and_outlet_faults_close_as_one_joint_component() -> None:
    text = CLEAN.replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,"
        "Fan:ConstantVolume,Fan B,A1,A2;",
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,BAD INLET,BAD OUTLET;",
    )

    outcome = repair_model(text, IR_IDD)
    endpoint_violations = tuple(
        row for row in outcome.initial_scan.hard_violations
        if row.constraint_id == "V2-BRANCH-ENDPOINT-002"
    )

    assert len(endpoint_violations) == 2
    assert len({
        factor for row in endpoint_violations for factor in row.latent_factors
    }) == 1
    assert len(outcome.components) == 1
    assert outcome.decisions[0].status is ComponentDecisionStatus.UNIQUE_REPAIR
    assert outcome.decisions[0].objective == (2, 2)
    assert outcome.status is RepairStatus.REPAIRED_COMPLETE
    assert outcome.final_scan.hard_violations == ()


def test_equal_optimum_semantic_interpretations_abstain_without_modification() -> None:
    text = _ambiguous_branch()
    outcome = repair_model(text, IR_IDD)

    assert outcome.status is RepairStatus.NEEDS_INPUT
    assert outcome.output_text == text
    assert outcome.selected_edits == ()
    assert outcome.decisions[0].status is ComponentDecisionStatus.AMBIGUOUS
    assert outcome.decisions[0].alternative_count == 2


def test_bound_exceeded_is_search_exhausted_not_first_found() -> None:
    text = _ambiguous_branch()
    outcome = repair_model(
        text,
        IR_IDD,
        limits=SolverLimits(max_candidate_edits=1),
    )

    assert outcome.status is RepairStatus.SEARCH_EXHAUSTED
    assert outcome.output_text == text
    assert outcome.selected_edits == ()
    assert outcome.decisions[0].status is ComponentDecisionStatus.SEARCH_EXHAUSTED


def test_incomplete_objective_level_is_not_sampled_for_uniqueness() -> None:
    outcome = repair_model(
        _ambiguous_branch(),
        IR_IDD,
        limits=SolverLimits(max_evaluated_sets=1),
    )

    assert outcome.status is RepairStatus.SEARCH_EXHAUSTED
    assert outcome.selected_edits == ()
    assert outcome.decisions[0].evaluated_sets == 0
    assert outcome.decisions[0].search_exhausted is True


def test_search_rejects_candidate_with_stale_relation_precondition() -> None:
    text = CLEAN.replace(
        "Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,",
        "Branch,Air Branch,,Fan:ConstantVolume,Unknown,A0,A1,",
    )
    model = build_model_ir(parse_idf(text), IR_IDD)
    initial = scan_ir(model)
    generation = generate_candidates(model, initial)
    violation = next(
        row for row in initial.hard_violations
        if row.constraint_id == "V2-BRANCH-TYPED-IDENTITY-001"
    )
    domain = generation.for_violation(violation.violation_id)
    assert domain is not None and len(domain.candidates) == 1
    original = domain.candidates[0]
    stale = replace(
        original,
        relation_preconditions=tuple(
            replace(row, expected_document_sha256="stale-snapshot")
            for row in original.relation_preconditions
        ),
    )
    stale_generation = replace(
        generation,
        candidate_sets=tuple(
            replace(row, candidates=(stale,))
            if row.violation_id == violation.violation_id else row
            for row in generation.candidate_sets
        ),
    )

    components = build_conflict_components(
        initial.hard_violations,
        stale_generation,
    )
    decisions = solve_components(text, IR_IDD, initial, components)

    assert len(decisions) == 1
    assert decisions[0].status is ComponentDecisionStatus.NEEDS_INPUT
    assert decisions[0].selected_edits == ()
