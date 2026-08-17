"""验证 People 对象的版本绑定提取与设计人数计算。

test_design_people_uses_declared_method(): 验证三种官方 calculation method。
test_extract_people_preserves_semantic_fields(): 验证 schedule、热增益与 CO₂ 字段。
test_design_people_rejects_zero_area_per_person(): 验证无效除数不会被猜测。
"""

from __future__ import annotations

import pytest

from idfrepair.analysis.occupancy.extract import design_people, extract_people
from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from tests.occupancy.fixtures import PEOPLE_IDD, people_idf


@pytest.mark.parametrize(
    ("method", "number", "people_per_area", "area_per_person", "expected"),
    [
        ("People", "40", "", "", 40.0),
        ("People/Area", "", "0.2", "", 20.0),
        ("Area/Person", "", "", "5", 20.0),
    ],
)
def test_design_people_uses_declared_method(
    method: str,
    number: str,
    people_per_area: str,
    area_per_person: str,
    expected: float,
) -> None:
    """三种官方人数计算方式必须以同一 100 m² 面积得到预期人数。"""

    records = extract_people(
        parse_idf(
            people_idf(
                method,
                number=number,
                people_per_area=people_per_area,
                area_per_person=area_per_person,
            )
        ),
        parse_idd(PEOPLE_IDD),
    )

    assert len(records) == 1
    assert design_people(records[0], floor_area_m2=100.0) == expected


def test_extract_people_preserves_semantic_fields() -> None:
    """提取结果必须保留人数、activity、radiant、sensible 与 CO₂ 语义。"""

    record = extract_people(
        parse_idf(people_idf("People", number="40")),
        parse_idd(PEOPLE_IDD),
    )[0]

    assert record.name == "Passengers"
    assert record.target_name == "Terminal Hall"
    assert record.number_schedule_name == "Passenger Fraction"
    assert record.activity_schedule_name == "Passenger Activity"
    assert record.fraction_radiant == 0.35
    assert record.sensible_heat_fraction is None
    assert record.co2_generation_rate == 4.0e-8
    assert record.source_object_index == 2


def test_design_people_rejects_zero_area_per_person() -> None:
    """Area/Person 为零时不得除零或生成虚构人数。"""

    record = extract_people(
        parse_idf(people_idf("Area/Person", area_per_person="0")),
        parse_idd(PEOPLE_IDD),
    )[0]

    with pytest.raises(ValueError, match="floor_area_per_person_must_be_positive"):
        design_people(record, floor_area_m2=100.0)
