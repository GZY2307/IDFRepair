"""验证 explicit version-bound port registry 不把任意 node 字段提升为硬证据。"""

from __future__ import annotations

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from idfrepair.semantic_graph_v2.ir import (
    FluidMedium,
    PortApplicability,
    PortRole,
    ZoneSideRole,
)
from idfrepair.semantic_graph_v2.ports import (
    PRODUCTION_PORT_REGISTRY,
    PortRegistry,
    PortRule,
    extract_ports,
)


IDD = parse_idd(r"""!IDD_Version 24.1.0
Fan:Test,
 A1, \field Name
 A2, \field Air Inlet Node Name
 A3, \field Air Outlet Node Name
 A4; \field Control Sensor Node Name
""")


REGISTRY = PortRegistry((
    PortRule(
        rule_id="test.fan.air.inlet.v1",
        versions=("24.1",),
        object_type="Fan:Test",
        field_token="A2",
        field_name="Air Inlet Node Name",
        role=PortRole.INLET,
        medium=FluidMedium.AIR,
        port_group="air",
        zone_side_role=ZoneSideRole.NONE,
    ),
    PortRule(
        rule_id="test.fan.air.outlet.v1",
        versions=("24.1",),
        object_type="Fan:Test",
        field_token="A3",
        field_name="Air Outlet Node Name",
        role=PortRole.OUTLET,
        medium=FluidMedium.AIR,
        port_group="air",
        zone_side_role=ZoneSideRole.NONE,
    ),
))


def test_exact_rules_create_supported_ports_with_lineage() -> None:
    document = parse_idf("Fan:Test,Fan A,Inlet,Outlet,Sensor;\n")
    extraction = extract_ports(document.objects[0], IDD, registry=REGISTRY)

    assert [port.role for port in extraction.ports] == [PortRole.INLET, PortRole.OUTLET]
    assert all(port.medium is FluidMedium.AIR for port in extraction.ports)
    assert all(
        port.applicability is PortApplicability.SUPPORTED_EXACT
        for port in extraction.ports
    )
    assert [port.field_ref.field_index for port in extraction.ports] == [2, 3]
    assert [port.rule_id for port in extraction.ports] == [
        "test.fan.air.inlet.v1", "test.fan.air.outlet.v1",
    ]


def test_unregistered_sensor_node_is_not_promoted_to_port() -> None:
    document = parse_idf("Fan:Test,Fan A,Inlet,Outlet,Sensor;\n")
    extraction = extract_ports(document.objects[0], IDD, registry=REGISTRY)

    assert [field.field_index for field in extraction.unregistered_node_fields] == [4]
    assert all(port.node_name != "Sensor" for port in extraction.ports)


def test_exact_field_identity_mismatch_rejects_rule() -> None:
    changed_idd = parse_idd(r"""!IDD_Version 24.1.0
Fan:Test,
 A1, \field Name
 A2, \field Primary Air Inlet Node Name
 A3; \field Air Outlet Node Name
""")
    document = parse_idf("Fan:Test,Fan A,Inlet,Outlet;\n")
    extraction = extract_ports(document.objects[0], changed_idd, registry=REGISTRY)

    assert [port.field_ref.field_index for port in extraction.ports] == [3]
    assert extraction.issues == ("port_rule_field_identity_mismatch:test.fan.air.inlet.v1",)


def test_version_mismatch_does_not_fallback_to_field_name_heuristic() -> None:
    old_idd = parse_idd(IDD.text.replace("24.1.0", "23.1.0"))
    document = parse_idf("Fan:Test,Fan A,Inlet,Outlet,Sensor;\n")
    extraction = extract_ports(document.objects[0], old_idd, registry=REGISTRY)

    assert extraction.ports == ()
    assert {field.field_index for field in extraction.unregistered_node_fields} == {2, 3, 4}


def test_production_ptac_rules_expose_exact_zone_side_ports() -> None:
    idd = parse_idd(r"""!IDD_Version 24.1.0
ZoneHVAC:PackagedTerminalAirConditioner,
 A1, \field Name
 A2, \field Availability Schedule Name
 A3, \field Air Inlet Node Name
 A4; \field Air Outlet Node Name
""")
    document = parse_idf(
        "ZoneHVAC:PackagedTerminalAirConditioner,PTAC 1,,Zone Return,Zone Supply;"
    )

    extraction = extract_ports(
        document.objects[0], idd, registry=PRODUCTION_PORT_REGISTRY,
    )

    assert [port.field_ref.field_index for port in extraction.ports] == [3, 4]
    assert [port.zone_side_role for port in extraction.ports] == [
        ZoneSideRole.ZONE_RETURN,
        ZoneSideRole.ZONE_INLET,
    ]
