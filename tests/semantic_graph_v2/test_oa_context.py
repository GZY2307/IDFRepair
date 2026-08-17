"""OutdoorAirSystem normal/DOAS ownership remains explicit in the IR."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.ir import OutdoorAirSystemContext
from idfrepair.semantic_graph_v2.scan import scan_ir

from .compound_relation_fixtures import BASE, relation_model


def test_normal_oa_context_retains_controller_node_anchor() -> None:
    path = relation_model().equipment_paths[0]

    assert path.context is OutdoorAirSystemContext.NORMAL
    assert path.controller_list_ref is not None
    assert path.controller_list_ref.raw_name == "OA Controllers"
    assert path.outdoor_air_controller_ref is not None
    assert path.outdoor_air_controller_ref.raw_name == "OA Controller"
    assert [field.raw_value for field in path.controller_node_fields] == [
        "OA Relief", "OA Return", "OA Mixed", "OA Source",
    ]
    assert path.reference_shape_complete is True


def test_doas_without_mixer_is_context_not_missing_mixer_violation() -> None:
    text = BASE.replace(
        "AirLoopHVAC:OutdoorAirSystem:EquipmentList,OA Equipment,"
        "HeatExchanger:AirToAir:SensibleAndLatent,HX1,OutdoorAir:Mixer,OA Mixer;",
        "AirLoopHVAC:OutdoorAirSystem:EquipmentList,OA Equipment,"
        "HeatExchanger:AirToAir:SensibleAndLatent,HX1;",
    ) + (
        "AirLoopHVAC:DedicatedOutdoorAirSystem,DOAS 1,OA System,,DOAS Mixer,"
        "DOAS Splitter,-10,0.001,30,0.01,1,Main Air Loop;\n"
    )
    model = relation_model(text)
    path = model.equipment_paths[0]
    result = scan_ir(model)

    assert path.context is OutdoorAirSystemContext.DEDICATED
    assert path.context_owner_refs[0].raw_name == "DOAS 1"
    assert "V2-OA-EQUIPMENT-PATH-010" not in result.constraint_ids
