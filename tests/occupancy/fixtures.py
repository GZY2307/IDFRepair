"""提供不依赖私有 OSM 的最小 EnergyPlus occupancy 测试文本。

PEOPLE_IDD: People、Zone、Space 与 schedule 的精确字段定义 fixture。
people_idf(): 生成指定 calculation method 的最小 People 对象。
"""

from __future__ import annotations


PEOPLE_IDD = r"""!IDD_Version 24.1.0
People,
  A1, \field Name
      \required-field
  A2, \field Zone or ZoneList or Space or SpaceList Name
      \required-field
  A3, \field Number of People Schedule Name
      \required-field
  A4, \field Number of People Calculation Method
      \key People
      \key People/Area
      \key Area/Person
      \default People
  N1, \field Number of People
      \minimum 0
  N2, \field People per Floor Area
      \minimum 0
  N3, \field Floor Area per Person
      \minimum 0
  N4, \field Fraction Radiant
      \default 0.3
  N5, \field Sensible Heat Fraction
      \default autocalculate
  A5, \field Activity Level Schedule Name
      \required-field
  N6, \field Carbon Dioxide Generation Rate
      \default 3.82E-8;

Zone,
  A1, \field Name;

Space,
  A1, \field Name
  A2, \field Zone Name
      \type alpha;

ZoneList,
  A1, \field Name
  A2, \field Zone 1 Name
      \begin-extensible
      \extensible:1;

SpaceList,
  A1, \field Name
  A2, \field Space 1 Name
      \begin-extensible
      \extensible:1;
"""


def people_idf(
    method: str,
    *,
    number: str = "",
    people_per_area: str = "",
    area_per_person: str = "",
) -> str:
    """构造一个字段位置与 fixture IDD 对齐的 People 对象。"""

    return f"""Version,24.1;
Zone,Terminal Hall;
People,
  Passengers,
  Terminal Hall,
  Passenger Fraction,
  {method},
  {number},
  {people_per_area},
  {area_per_person},
  0.35,
  autocalculate,
  Passenger Activity,
  4.0E-8;
"""
