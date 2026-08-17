"""Small official-field fixture for V2.2 compound-flow projection tests."""

from __future__ import annotations

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from idfrepair.semantic_graph_v2 import build_model_ir


COMPOUND_IDD_22_TEXT = r"""!IDD_Version 22.1.0
Fan:ConstantVolume,
 A1, \field Name
 A2, \field Availability Schedule Name
 A3, \field Air Inlet Node Name
 A4; \field Air Outlet Node Name
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
 N4, \field Sensible Effectiveness at 75% Heating Air Flow
 N5, \field Latent Effectiveness at 75% Heating Air Flow
 N6, \field Sensible Effectiveness at 100% Cooling Air Flow
 N7, \field Latent Effectiveness at 100% Cooling Air Flow
 N8, \field Sensible Effectiveness at 75% Cooling Air Flow
 N9, \field Latent Effectiveness at 75% Cooling Air Flow
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
"""


COMPOUND_IDD_24_TEXT = COMPOUND_IDD_22_TEXT.replace(
    "!IDD_Version 22.1.0",
    "!IDD_Version 24.1.0",
).replace(
    r""" N4, \field Sensible Effectiveness at 75% Heating Air Flow
 N5, \field Latent Effectiveness at 75% Heating Air Flow
 N6, \field Sensible Effectiveness at 100% Cooling Air Flow
 N7, \field Latent Effectiveness at 100% Cooling Air Flow
 N8, \field Sensible Effectiveness at 75% Cooling Air Flow
 N9, \field Latent Effectiveness at 75% Cooling Air Flow
 A3, \field Supply Air Inlet Node Name
 A4, \field Supply Air Outlet Node Name
 A5, \field Exhaust Air Inlet Node Name
 A6; \field Exhaust Air Outlet Node Name""",
    r""" N4, \field Sensible Effectiveness at 100% Cooling Air Flow
 N5, \field Latent Effectiveness at 100% Cooling Air Flow
 A3, \field Supply Air Inlet Node Name
 A4, \field Supply Air Outlet Node Name
 A5, \field Exhaust Air Inlet Node Name
 A6; \field Exhaust Air Outlet Node Name""",
)


COMPOUND_IDF_PREFIX = """Fan:ConstantVolume,Direct Fan,,D In,D Out;
AirLoopHVAC:ZoneSplitter,Splitter 1,S In,S Out 1,S Out 2,S Out 3;
AirLoopHVAC:SupplyPlenum,Supply Plenum,Supply Zone,Supply Zone Node,P In,P Out 1,P Out 2;
AirLoopHVAC:ZoneMixer,Mixer 1,M Out,M In 1,M In 2,M In 3;
AirLoopHVAC:ReturnPlenum,Return Plenum,Return Zone,Return Zone Node,R Out,Induced Nodes,R In 1,R In 2;
OutdoorAir:Mixer,OA Mixer,Mixed Air,Outdoor Air,Relief Air,Return Air;
"""


COMPOUND_IDF_SUFFIX = """\
HeatExchanger:AirToAir:FlatPlate,HX Flat,,CounterFlow,Yes,1,1,20,10,1,20,0,FP Supply In,FP Supply Out,FP Secondary In,FP Secondary Out;
"""


def compound_model(version: str = "24.1.0"):  # type: ignore[no-untyped-def]
    """Build the fixture under an explicitly selected audited IDD version."""

    if version.startswith("22.1"):
        idd_text = COMPOUND_IDD_22_TEXT
        hx = (
            "HeatExchanger:AirToAir:SensibleAndLatent,HX SensLat,,1,0.7,0.6,"
            "0.7,0.6,0.7,0.6,0.7,0.6,HX Supply In,HX Supply Out,"
            "HX Exhaust In,HX Exhaust Out;\n"
        )
    else:
        idd_text = COMPOUND_IDD_24_TEXT
        hx = (
            "HeatExchanger:AirToAir:SensibleAndLatent,HX SensLat,,1,0.7,0.6,"
            "0.7,0.6,HX Supply In,HX Supply Out,HX Exhaust In,HX Exhaust Out;\n"
        )
    idd = parse_idd(idd_text)
    return build_model_ir(
        parse_idf(f"{COMPOUND_IDF_PREFIX}{hx}{COMPOUND_IDF_SUFFIX}"), idd,
    )


def projection_named(model, name: str):  # type: ignore[no-untyped-def]
    """Return the one explicit compound projection for a named object."""

    rows = tuple(
        row for row in model.flow_projections if row.object_ref.raw_name == name
    )
    assert len(rows) == 1
    return rows[0]
