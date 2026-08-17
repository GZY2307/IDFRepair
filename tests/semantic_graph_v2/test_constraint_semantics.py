"""锁定已证伪 invariant 与 zone 显式端口证据边界。"""

from __future__ import annotations

from dataclasses import replace
import inspect

from idfrepair.io.idf import parse_idf
from idfrepair.semantic_graph_v2.build_ir import build_model_ir
from idfrepair.semantic_graph_v2.scan import scan_ir, scan_model

from .conftest import IR_IDD, IR_IDF


def test_priority_inequality_and_parallel_middle_order_are_not_violations() -> None:
    valid = IR_IDF.replace(
        "ZoneHVAC:EquipmentConnections,Z1,Wrong Equipment,",
        "ZoneHVAC:EquipmentConnections,Z1,Z1 Equipment,",
    )
    result = scan_model(parse_idf(valid), IR_IDD)

    assert "V2-ZONE-PRIORITY-EQUALITY-901" not in result.constraint_ids
    assert "V2-PARALLEL-MIDDLE-ORDER-903" not in result.constraint_ids


def test_zone_list_and_member_faults_share_explicit_latent_factor() -> None:
    connected = IR_IDF.replace(
        "ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,,Z2 Return,Z2 Supply;",
        (
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,,Z2 Return,Z2 Supply;\n"
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1B,,Z1 Return,Z1 Supply;"
        ),
    ).replace(
        "ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,"
        "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,1,2,,;",
        (
            "ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,"
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,1,2,,,"
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,2,1,,;"
        ),
    )
    result = scan_model(parse_idf(connected), IR_IDD)
    zone = tuple(
        row for row in result.hard_violations
        if row.constraint_id in {
            "V2-ZONE-LIST-OWNERSHIP-011",
            "V2-ZONE-TYPED-MEMBER-012",
        }
    )

    assert {row.constraint_id for row in zone} == {
        "V2-ZONE-LIST-OWNERSHIP-011",
        "V2-ZONE-TYPED-MEMBER-012",
    }
    assert len({factor for row in zone for factor in row.latent_factors}) == 1


def test_zone_hard_evaluators_skip_an_incomplete_global_evidence_domain() -> None:
    connected = IR_IDF.replace(
        "ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,,Z2 Return,Z2 Supply;",
        (
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,,Z2 Return,Z2 Supply;\n"
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1B,,Z1 Return,Z1 Supply;"
        ),
    ).replace(
        "ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,"
        "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,1,2,,;",
        (
            "ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,"
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,1,2,,,"
            "ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,2,1,,;"
        ),
    )
    model = build_model_ir(parse_idf(connected), IR_IDD)
    incomplete = replace(
        model,
        zone_relations=tuple(
            replace(relation, evidence_complete=False)
            for relation in model.zone_relations
        ),
    )

    result = scan_ir(incomplete)

    assert not {
        "V2-ZONE-LIST-OWNERSHIP-011",
        "V2-ZONE-TYPED-MEMBER-012",
    } & set(result.constraint_ids)


def test_zone_typed_member_abstains_when_declared_list_ports_are_incomplete() -> None:
    text = IR_IDF.replace(
        "ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,"
        "ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,1,2,,;",
        (
            "ZoneHVAC:EnergyRecoveryVentilator,Unsupported ERV;\n"
            "ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,"
            "ZoneHVAC:EnergyRecoveryVentilator,Unsupported ERV,1,2,,;"
        ),
    ).replace(
        "ZoneHVAC:EquipmentConnections,Z1,Wrong Equipment,"
        "Z1 Supply,,Z1 Air,Z1 Return;",
        (
            "ZoneHVAC:EquipmentConnections,Z1,Z1 Equipment,"
            "Z1 Supply,,Z1 Air,Z1 Return;\n"
            "ZoneHVAC:EquipmentConnections,Z2,Wrong Equipment,"
            "Z2 Supply,,Z2 Air,Z2 Return;"
        ),
    )

    result = scan_model(parse_idf(text), IR_IDD)

    assert "V2-ZONE-TYPED-MEMBER-012" not in result.constraint_ids


def test_scanner_public_boundary_has_no_target_hints() -> None:
    parameters = inspect.signature(scan_model).parameters

    assert not {"family", "locator", "clean", "oracle", "record"} & set(parameters)
