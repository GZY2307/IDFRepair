"""依据精确 EnergyPlus IDD 提取 People 语义与设计人数。

extract_people(): 按 IDD 字段名读取全部 People 对象。
design_people(): 根据官方 calculation method 与面积计算设计人数。
"""

from __future__ import annotations

from idfrepair.analysis.occupancy.models import PeopleRecord
from idfrepair.io.idf import IDFDocument, IDFObject, canonical
from idfrepair.knowledge.idd import IDDObject, IDDSchema


_PEOPLE_FIELDS = {
    "name": "Name",
    "target": "Zone or ZoneList or Space or SpaceList Name",
    "number_schedule": "Number of People Schedule Name",
    "calculation_method": "Number of People Calculation Method",
    "number": "Number of People",
    "people_per_area": "People per Floor Area",
    "area_per_person": "Floor Area per Person",
    "fraction_radiant": "Fraction Radiant",
    "sensible_fraction": "Sensible Heat Fraction",
    "activity_schedule": "Activity Level Schedule Name",
    "co2_rate": "Carbon Dioxide Generation Rate",
}


def _positions(definition: IDDObject) -> dict[str, int]:
    """把所需语义字段名解析为当前 IDD 中的精确 1-based 位置。"""

    by_name = {canonical(field.name): field.index for field in definition.fields}
    values: dict[str, int] = {}
    for key, name in _PEOPLE_FIELDS.items():
        position = by_name.get(canonical(name))
        if position is None:
            raise ValueError(f"people_idd_field_missing:{name}")
        values[key] = position
    return values


def _value(obj: IDFObject, position: int) -> str:
    """返回指定 People 字段的去空白值；缺失尾字段视为空输入。"""

    if not 1 <= position <= len(obj.fields):
        return ""
    return obj.fields[position - 1].value.strip()


def _default(definition: IDDObject, position: int, fallback: str) -> str:
    """读取 IDD 默认值，并在 IDD 未声明时使用显式标准 fallback。"""

    field = definition.field_at(position)
    if field is None or field.default is None:
        return fallback
    return field.default


def _optional_float(value: str, *, label: str) -> float | None:
    """解析可选有限数值，并为非法文本返回明确错误。"""

    if not value:
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"invalid_people_numeric:{label}") from exc
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"non_finite_people_numeric:{label}")
    return number


def _float_or_default(
    value: str,
    *,
    definition: IDDObject,
    position: int,
    fallback: float,
    label: str,
) -> float:
    """解析数值；空字段按当前 IDD 默认值补全。"""

    raw = value or _default(definition, position, str(fallback))
    parsed = _optional_float(raw, label=label)
    if parsed is None:
        return fallback
    return parsed


def extract_people(document: IDFDocument, idd: IDDSchema) -> tuple[PeopleRecord, ...]:
    """从一个 IDF/IDD snapshot 提取带源位置的 People 记录。"""

    definition = idd.get("People")
    if definition is None:
        raise ValueError("people_object_missing_from_idd")
    positions = _positions(definition)
    records: list[PeopleRecord] = []
    for obj in document.find_objects("People"):
        method = _value(obj, positions["calculation_method"]) or _default(
            definition, positions["calculation_method"], "People"
        )
        sensible_raw = _value(obj, positions["sensible_fraction"]) or _default(
            definition, positions["sensible_fraction"], "autocalculate"
        )
        sensible = (
            None
            if canonical(sensible_raw) == "autocalculate"
            else _optional_float(sensible_raw, label="sensible_heat_fraction")
        )
        name = _value(obj, positions["name"])
        issues = []
        if not name:
            issues.append("people_name_missing")
        target = _value(obj, positions["target"])
        if not target:
            issues.append("people_target_missing")
        number_schedule = _value(obj, positions["number_schedule"])
        if not number_schedule:
            issues.append("people_number_schedule_missing")
        activity_schedule = _value(obj, positions["activity_schedule"])
        if not activity_schedule:
            issues.append("people_activity_schedule_missing")
        records.append(
            PeopleRecord(
                record_id=f"people:{obj.index}:{canonical(name)}",
                name=name,
                target_name=target,
                number_schedule_name=number_schedule,
                calculation_method=method,
                number_of_people=_optional_float(
                    _value(obj, positions["number"]), label="number_of_people"
                ),
                people_per_floor_area=_optional_float(
                    _value(obj, positions["people_per_area"]),
                    label="people_per_floor_area",
                ),
                floor_area_per_person=_optional_float(
                    _value(obj, positions["area_per_person"]),
                    label="floor_area_per_person",
                ),
                fraction_radiant=_float_or_default(
                    _value(obj, positions["fraction_radiant"]),
                    definition=definition,
                    position=positions["fraction_radiant"],
                    fallback=0.3,
                    label="fraction_radiant",
                ),
                sensible_heat_fraction=sensible,
                activity_schedule_name=activity_schedule,
                co2_generation_rate=_float_or_default(
                    _value(obj, positions["co2_rate"]),
                    definition=definition,
                    position=positions["co2_rate"],
                    fallback=3.82e-8,
                    label="co2_generation_rate",
                ),
                source_object_index=obj.index,
                number_schedule_field_index=positions["number_schedule"],
                issues=tuple(issues),
            )
        )
    return tuple(records)


def design_people(record: PeopleRecord, floor_area_m2: float) -> float:
    """按 EnergyPlus People calculation method 计算最大设计人数。"""

    if floor_area_m2 < 0:
        raise ValueError("floor_area_must_be_nonnegative")
    method = canonical(record.calculation_method)
    if method == "people":
        if record.number_of_people is None or record.number_of_people < 0:
            raise ValueError("number_of_people_must_be_nonnegative")
        return record.number_of_people
    if method == "people/area":
        if record.people_per_floor_area is None or record.people_per_floor_area < 0:
            raise ValueError("people_per_floor_area_must_be_nonnegative")
        return record.people_per_floor_area * floor_area_m2
    if method == "area/person":
        if record.floor_area_per_person is None or record.floor_area_per_person <= 0:
            raise ValueError("floor_area_per_person_must_be_positive")
        return floor_area_m2 / record.floor_area_per_person
    raise ValueError(f"unsupported_people_calculation_method:{record.calculation_method}")


__all__ = ["design_people", "extract_people"]
