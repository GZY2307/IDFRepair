"""验证派生 occupancy IDF/CSV 编译器的守恒、可复现与源只读约束。"""

from __future__ import annotations

from pathlib import Path

import pytest

from idfrepair.analysis.occupancy.compiler import compile_scenario
from idfrepair.analysis.occupancy.models import OccupancyScenario
from idfrepair.analysis.occupancy.scenarios import person_hours, temporal_profiles
from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from tests.occupancy.fixtures import PEOPLE_IDD, people_idf


def _scenario(name: str = "morning_peak") -> OccupancyScenario:
    baseline = (0.5,) * 96
    profile = temporal_profiles(baseline)[name]
    return OccupancyScenario(
        name=name,
        kind="temporal_redistribution",
        profiles={"Passengers": profile},
        design_people={"Passengers": 40.0},
        minutes_per_step=15.0,
        conserves_passenger_hours=True,
        reference_person_hours=person_hours(baseline, 40.0),
    )


def test_compile_scenario_never_changes_source_and_is_deterministic(
    tmp_path: Path,
) -> None:
    """两个不同输出目录必须产生相同 bytes/hash，且 source byte 不变。"""

    source = tmp_path / "source.idf"
    source.write_text(people_idf("People", number="40"), encoding="utf-8")
    before = source.read_bytes()

    one = compile_scenario(source, parse_idd(PEOPLE_IDD), _scenario(), tmp_path / "one")
    two = compile_scenario(source, parse_idd(PEOPLE_IDD), _scenario(), tmp_path / "two")

    assert source.read_bytes() == before
    assert one.idf_sha256 == two.idf_sha256
    assert one.schedule_sha256 == two.schedule_sha256
    assert one.idf_path.read_bytes() == two.idf_path.read_bytes()
    assert one.schedule_path.read_bytes() == two.schedule_path.read_bytes()
    assert one.passenger_hours == pytest.approx(two.passenger_hours, rel=0, abs=1e-9)


def test_compiler_replaces_only_people_schedule_field_and_appends_schedule_file(
    tmp_path: Path,
) -> None:
    """编译器只替换 People schedule 引用，并追加 source-backed Schedule:File。"""

    source = tmp_path / "source.idf"
    source.write_text(people_idf("People", number="40"), encoding="utf-8")
    original = parse_idf(source.read_text(encoding="utf-8"))

    compiled = compile_scenario(
        source, parse_idd(PEOPLE_IDD), _scenario(), tmp_path / "derived"
    )
    derived = parse_idf(compiled.idf_path.read_text(encoding="utf-8"))

    old_people = original.find_objects("People")[0]
    new_people = derived.find_objects("People")[0]
    assert len(compiled.modified_fields) == 1
    assert compiled.modified_fields[0].field_name == "Number of People Schedule Name"
    assert new_people.fields[2].value == compiled.modified_fields[0].new_value
    assert tuple(field.value for field in new_people.fields[:2]) == tuple(
        field.value for field in old_people.fields[:2]
    )
    schedules = derived.find_objects("Schedule:File")
    assert len(schedules) == 1
    assert schedules[0].fields[0].value == new_people.fields[2].value
    assert schedules[0].fields[2].value == compiled.schedule_path.name
    assert schedules[0].fields[3].value == "1"
    assert schedules[0].fields[5].value == "8760"
    assert schedules[0].fields[8].value == "15"


def test_schedule_csv_has_96_rows_per_day_for_full_year_and_conserves_daily_hours(
    tmp_path: Path,
) -> None:
    """23.1 Schedule:File 写 365×96 行，日 profile 重复且每日守恒。"""

    source = tmp_path / "source.idf"
    source.write_text(people_idf("People", number="40"), encoding="utf-8")
    scenario = _scenario("evening_peak")

    compiled = compile_scenario(
        source, parse_idd(PEOPLE_IDD), scenario, tmp_path / "derived"
    )

    rows = compiled.schedule_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 365 * 96
    assert all(len(row.split(".")) == 2 and len(row.split(".")[1]) == 12 for row in rows)
    assert rows[:96] == rows[-96:]
    emitted_person_hours = sum(float(row) for row in rows[:96]) * 40.0 * 0.25
    assert compiled.passenger_hours == pytest.approx(
        emitted_person_hours, rel=0, abs=1e-12
    )
    assert compiled.passenger_hours == pytest.approx(
        scenario.reference_person_hours, rel=1e-9
    )


def test_compiler_rejects_missing_or_nonconserved_profiles(tmp_path: Path) -> None:
    """缺少 People profile 或伪称守恒的场景必须在写派生件前失败。"""

    source = tmp_path / "source.idf"
    source.write_text(people_idf("People", number="40"), encoding="utf-8")
    missing = OccupancyScenario(
        name="missing",
        kind="temporal_redistribution",
        profiles={},
        design_people={},
        reference_person_hours=0.0,
    )
    false_claim = OccupancyScenario(
        name="false",
        kind="temporal_redistribution",
        profiles={"Passengers": (1.0,) * 96},
        design_people={"Passengers": 40.0},
        conserves_passenger_hours=True,
        reference_person_hours=1.0,
    )

    with pytest.raises(ValueError, match="scenario_profile_missing:Passengers"):
        compile_scenario(source, parse_idd(PEOPLE_IDD), missing, tmp_path / "missing")
    with pytest.raises(ValueError, match="passenger_hours_conservation_failed"):
        compile_scenario(source, parse_idd(PEOPLE_IDD), false_claim, tmp_path / "false")
    assert not (tmp_path / "missing").exists()
    assert not (tmp_path / "false").exists()
