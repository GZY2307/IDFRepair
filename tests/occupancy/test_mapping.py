"""验证 People→Zone→HVAC 语义映射不猜测缺失系统。"""

from __future__ import annotations

from idfrepair.analysis.occupancy.mapping import build_semantic_mapping
from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from tests.occupancy.fixtures import PEOPLE_IDD


MAPPING_IDD = PEOPLE_IDD + r"""
ZoneHVAC:EquipmentConnections,
  A1, \field Zone Name
  A2, \field Zone Conditioning Equipment List Name
  A3, \field Zone Air Inlet Node or NodeList Name
  A4, \field Zone Air Exhaust Node or NodeList Name
  A5, \field Zone Air Node Name
  A6, \field Zone Return Air Node or NodeList Name;

ZoneHVAC:EquipmentList,
  A1, \field Name
  A2, \field Load Distribution Scheme
  A3, \field Zone Equipment 1 Object Type
      \begin-extensible
      \extensible:6
  A4, \field Zone Equipment 1 Name
  N1, \field Zone Equipment Cooling Sequence
  N2, \field Zone Equipment Heating or No-Load Sequence
  A5, \field Zone Equipment Sequential Cooling Fraction Schedule Name
  A6, \field Zone Equipment Sequential Heating Fraction Schedule Name;

ZoneHVAC:IdealLoadsAirSystem,
  A1, \field Name;
"""


def _people(target: str, *, name: str = "Passengers") -> str:
    return f"""People,
  {name},
  {target},
  Passenger Fraction,
  People,
  100,
  ,
  ,
  0.3,
  autocalculate,
  Passenger Activity,
  3.82E-8;
"""


def test_absent_hvac_is_explicit_not_fabricated() -> None:
    """存在 People/Zone 而无 HVAC 时必须给出空关系与明确 issue。"""

    document = parse_idf(
        "Version,24.1;\nZone,Terminal Hall;\n" + _people("Terminal Hall")
    )

    mapping = build_semantic_mapping(document, parse_idd(MAPPING_IDD))

    assert mapping.people_to_zones == {"Passengers": ("Terminal Hall",)}
    assert mapping.zone_to_hvac == {"Terminal Hall": ()}
    assert "zone_without_hvac:Terminal Hall" in mapping.issues


def test_space_target_resolves_to_declared_zone() -> None:
    """People 指向 Space 时复用 Space.Zone Name，不用名称启发式猜 zone。"""

    document = parse_idf(
        "Version,24.1;\n"
        "Zone,Terminal Hall;\n"
        "Space,Gate Lounge,Terminal Hall;\n"
        + _people("Gate Lounge")
    )

    mapping = build_semantic_mapping(document, parse_idd(MAPPING_IDD))

    assert mapping.people_to_zones == {"Passengers": ("Terminal Hall",)}
    assert mapping.zone_to_hvac == {"Terminal Hall": ()}


def test_declared_zone_equipment_relation_is_reused() -> None:
    """Zone service 关系来自 frozen ModelIR 的 EquipmentConnections/List。"""

    document = parse_idf(
        "Version,24.1;\n"
        "Zone,Terminal Hall;\n"
        + _people("Terminal Hall")
        + """
ZoneHVAC:IdealLoadsAirSystem,Terminal Ideal Loads;
ZoneHVAC:EquipmentList,
  Terminal Equipment,
  SequentialLoad,
  ZoneHVAC:IdealLoadsAirSystem,
  Terminal Ideal Loads,
  1,
  1;
ZoneHVAC:EquipmentConnections,
  Terminal Hall,
  Terminal Equipment,
  Terminal Inlet,
  ,
  Terminal Air Node,
  Terminal Return;
"""
    )

    mapping = build_semantic_mapping(document, parse_idd(MAPPING_IDD))

    assert mapping.zone_to_hvac == {
        "Terminal Hall": (
            "ZoneHVAC:IdealLoadsAirSystem / Terminal Ideal Loads",
        )
    }
    assert not any(issue.startswith("zone_without_hvac") for issue in mapping.issues)


def test_zone_list_and_space_list_expansion_preserve_all_members() -> None:
    """ZoneList 与 SpaceList 的成员必须展开，且结果按源顺序去重。"""

    document = parse_idf(
        "Version,24.1;\n"
        "Zone,Check In;\n"
        "Zone,Gate Hall;\n"
        "Space,Gate A,Gate Hall;\n"
        "Space,Gate B,Gate Hall;\n"
        "ZoneList,Public Zones,Check In,Gate Hall;\n"
        "SpaceList,Gate Spaces,Gate A,Gate B;\n"
        + _people("Public Zones", name="Public Passengers")
        + _people("Gate Spaces", name="Gate Passengers")
    )

    mapping = build_semantic_mapping(document, parse_idd(MAPPING_IDD))

    assert mapping.people_to_zones == {
        "Public Passengers": ("Check In", "Gate Hall"),
        "Gate Passengers": ("Gate Hall",),
    }


def test_unresolved_or_polymorphically_ambiguous_target_is_reported() -> None:
    """同名多态对象或不存在的 target 都不能静默选择。"""

    document = parse_idf(
        "Version,24.1;\n"
        "Zone,Shared Name;\n"
        "Space,Shared Name,Shared Name;\n"
        + _people("Shared Name", name="Ambiguous")
        + _people("Missing", name="Unresolved")
    )

    mapping = build_semantic_mapping(document, parse_idd(MAPPING_IDD))

    assert mapping.people_to_zones["Ambiguous"] == ("Shared Name",)
    assert mapping.people_to_zones["Unresolved"] == ()
    assert any(issue.startswith("people_target_ambiguous:Ambiguous") for issue in mapping.issues)
    assert "people_target_unresolved:Unresolved:Missing" in mapping.issues
