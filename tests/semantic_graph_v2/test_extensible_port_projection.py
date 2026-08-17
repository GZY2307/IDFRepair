"""TDD contract for IDD-bound extensible port extraction."""

from __future__ import annotations

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from idfrepair.semantic_graph_v2.ir import FluidMedium, PortApplicability, PortRole
from idfrepair.semantic_graph_v2.ports import (
    ExtensiblePortRule,
    PRODUCTION_PORT_REGISTRY,
    PortRegistry,
    extract_ports,
)


def _registry() -> PortRegistry:
    return PortRegistry(
        (),
        (
            ExtensiblePortRule(
                rule_id="test.splitter.outlets.e24_1.v1",
                versions=("24.1",),
                object_type="AirLoopHVAC:ZoneSplitter",
                begin_field_token="A3",
                begin_field_name="Outlet 1 Node Name",
                group_width=1,
                role=PortRole.OUTLET,
                medium=FluidMedium.AIR,
                port_group="distribution",
            ),
        ),
    )


def _idd(version: str = "24.1.0", width: int = 1):  # type: ignore[no-untyped-def]
    return parse_idd(rf"""!IDD_Version {version}
AirLoopHVAC:ZoneSplitter,
 A1, \field Name
 A2, \field Inlet Node Name
 A3; \field Outlet 1 Node Name
     \begin-extensible
     \extensible:{width}
""")


def test_extensible_rule_extracts_every_declared_group_without_field_enumeration() -> None:
    obj = parse_idf(
        "AirLoopHVAC:ZoneSplitter,S1,In,Out 1,Out 2,Out 3,Out 4;"
    ).objects[0]

    extraction = extract_ports(obj, _idd(), registry=_registry())

    assert [port.node_name for port in extraction.ports] == [
        "Out 1", "Out 2", "Out 3", "Out 4",
    ]
    assert [port.field_ref.field_index for port in extraction.ports] == [3, 4, 5, 6]
    assert all(
        port.applicability is PortApplicability.SUPPORTED_MULTI_PORT
        for port in extraction.ports
    )
    assert [field.field_index for field in extraction.unregistered_node_fields] == [2]


def test_extensible_rule_rejects_version_or_group_identity_mismatch() -> None:
    obj = parse_idf("AirLoopHVAC:ZoneSplitter,S1,In,Out 1,Out 2;").objects[0]

    wrong_version = extract_ports(obj, _idd("23.1.0"), registry=_registry())
    wrong_width = extract_ports(obj, _idd(width=2), registry=_registry())

    assert wrong_version.ports == ()
    assert [field.field_index for field in wrong_version.unregistered_node_fields] == [
        2, 3, 4,
    ]
    assert wrong_width.ports == ()
    assert wrong_width.issues == (
        "extensible_port_rule_group_mismatch:test.splitter.outlets.e24_1.v1",
    )


def test_extensible_lineage_uses_begin_template_beyond_preexpanded_tail() -> None:
    preexpanded = parse_idd(r"""!IDD_Version 24.1.0
AirLoopHVAC:ZoneSplitter,
 A1, \field Name
 A2, \field Inlet Node Name
 A3, \field Outlet 1 Node Name
     \begin-extensible
 A4, \field Outlet 2 Node Name
 A5; \field Outlet 3 Node Name
     \extensible:1
""")
    obj = parse_idf(
        "AirLoopHVAC:ZoneSplitter,S1,In,O1,O2,O3,O4,O5;"
    ).objects[0]

    extraction = extract_ports(obj, preexpanded, registry=_registry())

    assert [port.node_name for port in extraction.ports] == ["O1", "O2", "O3", "O4", "O5"]
    assert extraction.ports[-1].field_ref.extensible_ordinal == 5
    assert extraction.ports[-1].field_ref.field_token == "A3"
    assert extraction.ports[-1].field_ref.field_name == "Outlet 1 Node Name"


def test_blank_extensible_member_is_an_explicit_incompleteness_issue() -> None:
    obj = parse_idf(
        "AirLoopHVAC:ZoneSplitter,S1,In,O1,,O3;"
    ).objects[0]

    extraction = extract_ports(obj, _idd(), registry=_registry())

    assert [port.node_name for port in extraction.ports] == ["O1", "O3"]
    assert extraction.issues == (
        "extensible_port_blank_member:test.splitter.outlets.e24_1.v1:4",
    )


def test_wrong_begin_field_name_is_not_accepted_by_token_alone() -> None:
    changed = parse_idd(r"""!IDD_Version 24.1.0
AirLoopHVAC:ZoneSplitter,
 A1, \field Name
 A2, \field Inlet Node Name
 A3; \field Discharge Node Name
     \begin-extensible
     \extensible:1
""")
    obj = parse_idf("AirLoopHVAC:ZoneSplitter,S1,In,O1;").objects[0]

    extraction = extract_ports(obj, changed, registry=_registry())

    assert extraction.ports == ()
    assert extraction.issues == (
        "extensible_port_rule_field_identity_mismatch:"
        "test.splitter.outlets.e24_1.v1",
    )


def test_production_compound_atomic_rules_are_single_version_records() -> None:
    compound_types = (
        "AirLoopHVAC:ZoneSplitter",
        "AirLoopHVAC:SupplyPlenum",
        "AirLoopHVAC:ZoneMixer",
        "AirLoopHVAC:ReturnPlenum",
        "OutdoorAir:Mixer",
        "HeatExchanger:AirToAir:SensibleAndLatent",
        "HeatExchanger:AirToAir:FlatPlate",
    )

    for version in ("22.1", "24.1"):
        for object_type in compound_types:
            fixed = PRODUCTION_PORT_REGISTRY.rules_for(object_type, version)
            repeated = PRODUCTION_PORT_REGISTRY.extensible_rules_for(
                object_type, version,
            )
            assert fixed or repeated
            assert all(rule.versions == (version,) for rule in (*fixed, *repeated))
