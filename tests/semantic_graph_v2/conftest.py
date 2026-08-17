"""提供跨 Branch、Loop、Air、OA、Zone 与 Control relation 的小型 fixture。"""

from __future__ import annotations

import pytest

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd


IR_IDD = parse_idd(r"""!IDD_Version 24.1.0
Fan:ConstantVolume,
 A1, \field Name
 A2, \field Availability Schedule Name
 A3, \field Air Inlet Node Name
 A4; \field Air Outlet Node Name
Pipe:Adiabatic,
 A1, \field Name
 A2, \field Inlet Node Name
 A3; \field Outlet Node Name
Branch,
 A1, \field Name
 A2, \field Pressure Drop Curve Name
 A3, \field Component 1 Object Type
     \begin-extensible
 A4, \field Component 1 Name
 A5, \field Component 1 Inlet Node Name
 A6; \field Component 1 Outlet Node Name
     \extensible:4
BranchList,
 A1, \field Name
 A2; \field Branch 1 Name
     \begin-extensible
     \extensible:1
Connector:Splitter,
 A1, \field Name
 A2, \field Inlet Branch Name
 A3; \field Outlet Branch 1 Name
     \begin-extensible
     \extensible:1
Connector:Mixer,
 A1, \field Name
 A2, \field Outlet Branch Name
 A3; \field Inlet Branch 1 Name
     \begin-extensible
     \extensible:1
ConnectorList,
 A1, \field Name
 A2, \field Connector 1 Object Type
 A3, \field Connector 1 Name
 A4, \field Connector 2 Object Type
 A5; \field Connector 2 Name
PlantLoop,
 A1, \field Name
 A2, \field Fluid Type
 A3, \field User Defined Fluid Type
 A4, \field Plant Equipment Operation Scheme Name
 A5, \field Loop Temperature Setpoint Node Name
 N1, \field Maximum Loop Temperature
 N2, \field Minimum Loop Temperature
 N3, \field Maximum Loop Flow Rate
 N4, \field Minimum Loop Flow Rate
 N5, \field Plant Loop Volume
 A6, \field Plant Side Inlet Node Name
 A7, \field Plant Side Outlet Node Name
 A8, \field Plant Side Branch List Name
 A9, \field Plant Side Connector List Name
 A10, \field Demand Side Inlet Node Name
 A11, \field Demand Side Outlet Node Name
 A12, \field Demand Side Branch List Name
 A13; \field Demand Side Connector List Name
AirLoopHVAC:SupplyPath,
 A1, \field Name
 A2, \field Supply Air Path Inlet Node Name
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
AirLoopHVAC:OutdoorAirSystem,
 A1, \field Name
 A2, \field Controller List Name
 A3; \field Outdoor Air Equipment List Name
AirLoopHVAC:OutdoorAirSystem:EquipmentList,
 A1, \field Name
 A2, \field Component 1 Object Type
     \begin-extensible
 A3; \field Component 1 Name
     \extensible:2
OutdoorAir:Mixer,
 A1, \field Name
 A2, \field Mixed Air Node Name
 A3, \field Outdoor Air Stream Node Name
 A4, \field Relief Air Stream Node Name
 A5; \field Return Air Stream Node Name
ZoneHVAC:EquipmentConnections,
 A1, \field Zone Name
 A2, \field Zone Conditioning Equipment List Name
 A3, \field Zone Air Inlet Node or NodeList Name
 A4, \field Zone Air Exhaust Node or NodeList Name
 A5, \field Zone Air Node Name
 A6; \field Zone Return Air Node or NodeList Name
ZoneHVAC:EquipmentList,
 A1, \field Name
 A2, \field Load Distribution Scheme
 A3, \field Zone Equipment 1 Object Type
     \begin-extensible
 A4, \field Zone Equipment 1 Name
 N1, \field Zone Equipment 1 Cooling Sequence
 N2, \field Zone Equipment 1 Heating or No-Load Sequence
 A5, \field Zone Equipment 1 Sequential Cooling Fraction Schedule Name
 A6; \field Zone Equipment 1 Sequential Heating Fraction Schedule Name
     \extensible:6
ZoneHVAC:AirDistributionUnit,
 A1, \field Name
 A2, \field Air Distribution Unit Outlet Node Name
 A3, \field Air Terminal Object Type
 A4; \field Air Terminal Name
ZoneHVAC:PackagedTerminalHeatPump,
 A1, \field Name
 A2, \field Availability Schedule Name
 A3, \field Air Inlet Node Name
 A4; \field Air Outlet Node Name
ZoneHVAC:FourPipeFanCoil,
 A1, \field Name
 A2, \field Availability Schedule Name
 A3, \field Capacity Control Method
 N1, \field Maximum Supply Air Flow Rate
 N2, \field Low Speed Supply Air Flow Ratio
 N3, \field Medium Speed Supply Air Flow Ratio
 N4, \field Maximum Outdoor Air Flow Rate
 A4, \field Outdoor Air Schedule Name
 A5, \field Air Inlet Node Name
 A6; \field Air Outlet Node Name
AirLoopHVAC,
 A1, \field Name
 A2, \field Controller List Name
 A3, \field Availability Manager List Name
 N1, \field Design Supply Air Flow Rate
 A4, \field Branch List Name
 A5, \field Connector List Name
 A6, \field Supply Side Inlet Node Name
 A7, \field Demand Side Outlet Node Name
 A8, \field Demand Side Inlet Node Names
 A9; \field Supply Side Outlet Node Names
AirLoopHVAC:ControllerList,
 A1, \field Name
 A2, \field Controller 1 Object Type
     \begin-extensible
 A3; \field Controller 1 Name
     \extensible:2
Controller:WaterCoil,
 A1, \field Name
 A2, \field Control Variable
 A3, \field Action
 A4, \field Actuator Variable
 A5, \field Sensor Node Name
 A6; \field Actuator Node Name
""")


IR_IDF = """Version,24.1;
Fan:ConstantVolume,Fan A,,A0,A1;
Fan:ConstantVolume,Fan B,,A1,A2;
Branch,Air Branch,,Fan:ConstantVolume,Fan A,A0,A1,Fan:ConstantVolume,Fan B,A1,A2;
Pipe:Adiabatic,SI Pipe,L0,LSplit;
Pipe:Adiabatic,P1 Pipe,LSplit,LMix;
Pipe:Adiabatic,P2 Pipe,LSplit,LMix;
Pipe:Adiabatic,SO Pipe,LMix,LOut;
Branch,SI,,Pipe:Adiabatic,SI Pipe,L0,LSplit;
Branch,P1,,Pipe:Adiabatic,P1 Pipe,LSplit,LMix;
Branch,P2,,Pipe:Adiabatic,P2 Pipe,LSplit,LMix;
Branch,SO,,Pipe:Adiabatic,SO Pipe,LMix,LOut;
BranchList,BL1,SI,P2,P1,SO;
Connector:Splitter,S1,SI,P1,P2;
Connector:Mixer,M1,SO,P2,P1;
ConnectorList,CL1,Connector:Splitter,S1,Connector:Mixer,M1;
PlantLoop,Loop 1,,,,,,,,,,L0,LOut,BL1,CL1,,,,;
AirLoopHVAC:ZoneSplitter,ZS1,Supply Node,Z1 Supply,Z2 Supply;
AirLoopHVAC:SupplyPath,SP1,Supply Node,AirLoopHVAC:ZoneSplitter,ZS1;
OutdoorAir:Mixer,OA Mixer,Mixed Air,Outdoor Air,Relief Air,Return Air;
AirLoopHVAC:OutdoorAirSystem:EquipmentList,OA Equipment,OutdoorAir:Mixer,OA Mixer;
AirLoopHVAC:OutdoorAirSystem,OA System,OA Controllers,OA Equipment;
ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,,Z1 Return,Z1 Supply;
ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,,Z2 Return,Z2 Supply;
ZoneHVAC:EquipmentList,Z1 Equipment,SequentialLoad,ZoneHVAC:PackagedTerminalHeatPump,PTHP 1,1,2,,;
ZoneHVAC:EquipmentList,Wrong Equipment,SequentialLoad,ZoneHVAC:PackagedTerminalHeatPump,PTHP 2,1,1,,;
ZoneHVAC:EquipmentConnections,Z1,Wrong Equipment,Z1 Supply,,Z1 Air,Z1 Return;
Controller:WaterCoil,Water Controller,Temperature,Reverse,Flow,Coil Air Outlet,Coil Water Inlet;
AirLoopHVAC:ControllerList,Main Controllers,Controller:WaterCoil,Water Controller;
AirLoopHVAC,Main Air Loop,Main Controllers,,,BL1,CL1,Supply In,Demand Out,Demand In,Supply Out;
"""


@pytest.fixture
def ir_document():  # type: ignore[no-untyped-def]
    """返回保留 source spans 的跨关系 IDF document。"""

    return parse_idf(IR_IDF)


@pytest.fixture
def ir_idd():  # type: ignore[no-untyped-def]
    """返回与跨关系 fixture 绑定的 IDD。"""

    return IR_IDD
