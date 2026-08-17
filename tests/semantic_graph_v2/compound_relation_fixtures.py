"""Source-backed AirPath/OA fixtures for V2.2 topology and candidate tests."""

from __future__ import annotations

from dataclasses import replace

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from idfrepair.semantic_graph_v2 import build_model_ir
from idfrepair.semantic_graph_v2.registry import (
    AdmissionStatus,
    ConstraintRegistry,
    production_registry,
)
from idfrepair.semantic_graph_v2.scan import scan_ir


RELATION_IDD = parse_idd(r"""!IDD_Version 24.1.0
AirLoopHVAC:SupplyPath,
 A1, \field Name
 A2, \field Supply Air Path Inlet Node Name
 A3, \field Component 1 Object Type
     \begin-extensible
 A4; \field Component 1 Name
     \extensible:2
AirLoopHVAC:ReturnPath,
 A1, \field Name
 A2, \field Return Air Path Outlet Node Name
 A3, \field Component 1 Object Type
     \begin-extensible
 A4; \field Component 1 Name
     \extensible:2
AirLoopHVAC:ZoneSplitter,
 A1, \field Name
 A2, \field Inlet Node Name
 A3; \field Outlet 1 Node Name
     \begin-extensible
     \extensible:1
AirLoopHVAC:SupplyPlenum,
 A1, \field Name
 A2, \field Zone Name
 A3, \field Zone Node Name
 A4, \field Inlet Node Name
 A5; \field Outlet 1 Node Name
     \begin-extensible
     \extensible:1
AirLoopHVAC:ZoneMixer,
 A1, \field Name
 A2, \field Outlet Node Name
 A3; \field Inlet 1 Node Name
     \begin-extensible
     \extensible:1
AirLoopHVAC:ReturnPlenum,
 A1, \field Name
 A2, \field Zone Name
 A3, \field Zone Node Name
 A4, \field Outlet Node Name
 A5, \field Induced Air Outlet Node or NodeList Name
 A6; \field Inlet 1 Node Name
     \begin-extensible
     \extensible:1
AirLoopHVAC:OutdoorAirSystem,
 A1, \field Name
 A2, \field Controller List Name
 A3; \field Outdoor Air Equipment List Name
AirLoopHVAC:OutdoorAirSystem:EquipmentList,
 A1, \field Name
 A2, \field Component 1 Object Type
 A3, \field Component 1 Name
 A4, \field Component 2 Object Type
 A5; \field Component 2 Name
AirLoopHVAC:ControllerList,
 A1, \field Name
 A2, \field Controller 1 Object Type
     \begin-extensible
 A3; \field Controller 1 Name
     \extensible:2
Controller:OutdoorAir,
 A1, \field Name
 A2, \field Relief Air Outlet Node Name
 A3, \field Return Air Node Name
 A4, \field Mixed Air Node Name
 A5; \field Actuator Node Name
AirLoopHVAC:DedicatedOutdoorAirSystem,
 A1, \field Name
 A2, \field AirLoopHVAC:OutdoorAirSystem Name
 A3, \field Availability Schedule Name
 A4, \field AirLoopHVAC:Mixer Name
 A5, \field AirLoopHVAC:Splitter Name
 N1, \field Preheat Design Temperature
 N2, \field Preheat Design Humidity Ratio
 N3, \field Precool Design Temperature
 N4, \field Precool Design Humidity Ratio
 N5, \field Number of AirLoopHVAC
 A6; \field AirLoopHVAC 1 Name
     \begin-extensible
     \extensible:1
OutdoorAir:Mixer,
 A1, \field Name
 A2, \field Mixed Air Node Name
 A3, \field Outdoor Air Stream Node Name
 A4, \field Relief Air Stream Node Name
 A5; \field Return Air Stream Node Name
HeatExchanger:AirToAir:SensibleAndLatent,
 A1, \field Name
 A2, \field Availability Schedule Name
 N1, \field Nominal Supply Air Flow Rate
 N2, \field Sensible Effectiveness at 100% Heating Air Flow
 N3, \field Latent Effectiveness at 100% Heating Air Flow
 N4, \field Sensible Effectiveness at 100% Cooling Air Flow
 N5, \field Latent Effectiveness at 100% Cooling Air Flow
 A3, \field Supply Air Inlet Node Name
 A4, \field Supply Air Outlet Node Name
 A5, \field Exhaust Air Inlet Node Name
 A6; \field Exhaust Air Outlet Node Name
HeatExchanger:AirToAir:FlatPlate,
 A1, \field Name
 A2, \field Availability Schedule Name
 A3, \field Flow Arrangement Type
 A4, \field Economizer Lockout
 N1, \field Ratio of Supply to Secondary hA Values
 N2, \field Nominal Supply Air Flow Rate
 N3, \field Nominal Supply Air Inlet Temperature
 N4, \field Nominal Supply Air Outlet Temperature
 N5, \field Nominal Secondary Air Flow Rate
 N6, \field Nominal Secondary Air Inlet Temperature
 N7, \field Nominal Electric Power
 A5, \field Supply Air Inlet Node Name
 A6, \field Supply Air Outlet Node Name
 A7, \field Secondary Air Inlet Node Name
 A8; \field Secondary Air Outlet Node Name
Fan:ConstantVolume,
 A1, \field Name
 A2, \field Availability Schedule Name
 A3, \field Air Inlet Node Name
 A4; \field Air Outlet Node Name
""")


BASE = """Version,24.1;
AirLoopHVAC:ZoneSplitter,ZS1,S Boundary,S Mid,S Leaf;
AirLoopHVAC:SupplyPlenum,SP1,Supply Zone,Supply Zone Node,S Mid,S Outlet 1,S Outlet 2;
AirLoopHVAC:SupplyPath,Supply Path,S Boundary,AirLoopHVAC:ZoneSplitter,ZS1,AirLoopHVAC:SupplyPlenum,SP1;
AirLoopHVAC:ReturnPlenum,RP1,Return Zone,Return Zone Node,R Mid,Induced Nodes,R Leaf 1,R Leaf 2;
AirLoopHVAC:ZoneMixer,ZM1,R Boundary,R Mid,R Leaf 3;
AirLoopHVAC:ReturnPath,Return Path,R Boundary,AirLoopHVAC:ReturnPlenum,RP1,AirLoopHVAC:ZoneMixer,ZM1;
Controller:OutdoorAir,OA Controller,OA Relief,OA Return,OA Mixed,OA Source;
AirLoopHVAC:ControllerList,OA Controllers,Controller:OutdoorAir,OA Controller;
HeatExchanger:AirToAir:SensibleAndLatent,HX1,,1,0.7,0.6,0.7,0.6,OA Source,OA Outside,OA Relief,OA Exhaust;
OutdoorAir:Mixer,OA Mixer,OA Mixed,OA Outside,OA Relief,OA Return;
AirLoopHVAC:OutdoorAirSystem:EquipmentList,OA Equipment,HeatExchanger:AirToAir:SensibleAndLatent,HX1,OutdoorAir:Mixer,OA Mixer;
AirLoopHVAC:OutdoorAirSystem,OA System,OA Controllers,OA Equipment;
"""


def relation_model(text: str = BASE):  # type: ignore[no-untyped-def]
    return build_model_ir(parse_idf(text), RELATION_IDD)


def prospective_registry(*constraint_ids: str) -> ConstraintRegistry:
    """Promote selected constraints only inside development tests."""

    selected = set(constraint_ids)
    return ConstraintRegistry(tuple(
        replace(
            spec,
            admission_status=AdmissionStatus.ADMIT_SAFE_AUTO,
            candidate_generator_key=spec.evaluator_key,
        ) if spec.constraint_id in selected else spec
        for spec in production_registry().specs
    ))


def prospective_scan(text: str, *constraint_ids: str):  # type: ignore[no-untyped-def]
    model = relation_model(text)
    registry = prospective_registry(*constraint_ids)
    return model, scan_ir(model, registry=registry), registry
