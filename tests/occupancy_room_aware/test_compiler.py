"""验证 room-aware Schedule:File 编译器的覆盖、去重与只写派生边界。"""

from __future__ import annotations

from pathlib import Path

import pytest

from idfrepair.analysis.occupancy_room_aware.compiler import (
    RoomAwareScenario,
    compile_room_scenario,
)
from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from tests.occupancy.fixtures import PEOPLE_IDD


def _two_space_idf() -> str:
    return """Version,24.1;
Zone,Hall Zone;
Zone,Office Zone;
Space,hall-1,Hall Zone;
Space,office-1,Office Zone;
Schedule:Constant,Placeholder Fraction,,1.0;
Schedule:Constant,Activity,,120.0;
People,
  IDFRepair RA People :: hall-1,
  hall-1,
  Placeholder Fraction,
  People,
  10,
  ,
  ,
  0.3,
  autocalculate,
  Activity,
  3.82E-8;
People,
  IDFRepair RA People :: office-1,
  office-1,
  Placeholder Fraction,
  People,
  5,
  ,
  ,
  0.3,
  autocalculate,
  Activity,
  3.82E-8;
"""


def _scenario(*, distinct: bool = False) -> RoomAwareScenario:
    hall = tuple(index / 100.0 for index in range(96))
    office = tuple(reversed(hall)) if distinct else hall
    return RoomAwareScenario(
        scenario_id="fixture_scenario",
        scenario_kind="controlled",
        profiles_by_space={"hall-1": hall, "office-1": office},
        design_people_by_space={"hall-1": 10.0, "office-1": 5.0},
        minutes_per_step=15,
    )


def test_compiler_deduplicates_profiles_and_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "source.idf"
    source.write_text(_two_space_idf(), encoding="utf-8")
    before = source.read_bytes()

    compiled = compile_room_scenario(
        source,
        parse_idd(PEOPLE_IDD),
        _scenario(),
        tmp_path / "derived",
        allowed_root=tmp_path,
    )

    assert source.read_bytes() == before
    assert compiled.unique_profile_count == 1
    assert compiled.people_count == 2
    assert len(compiled.schedule_bindings) == 2
    assert {binding.column_number for binding in compiled.schedule_bindings} == {1}
    rows = compiled.schedule_path.read_text(encoding="ascii").splitlines()
    assert len(rows) == 365 * 96
    assert all(len(row.split(",")) == 1 for row in rows)
    document = parse_idf(compiled.idf_path.read_text(encoding="utf-8"))
    assert len(document.find_objects("Schedule:File")) == 1
    schedules = {
        obj.fields[2].value for obj in document.find_objects("People")
    }
    assert len(schedules) == 1


def test_compiler_has_stable_column_order_and_exact_schedule_fields(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.idf"
    source.write_text(_two_space_idf(), encoding="utf-8")

    one = compile_room_scenario(
        source,
        parse_idd(PEOPLE_IDD),
        _scenario(distinct=True),
        tmp_path / "one",
        allowed_root=tmp_path,
    )
    two = compile_room_scenario(
        source,
        parse_idd(PEOPLE_IDD),
        _scenario(distinct=True),
        tmp_path / "two",
        allowed_root=tmp_path,
    )

    assert one.scenario_digest == two.scenario_digest
    assert one.idf_sha256 == two.idf_sha256
    assert one.schedule_sha256 == two.schedule_sha256
    assert one.unique_profile_count == 2
    assert one.schedule_bindings == two.schedule_bindings
    document = parse_idf(one.idf_path.read_text(encoding="utf-8"))
    schedules = document.find_objects("Schedule:File")
    assert len(schedules) == 2
    assert {obj.fields[3].value for obj in schedules} == {"1", "2"}
    assert all(obj.fields[5].value == "8760" for obj in schedules)
    assert all(obj.fields[8].value == "15" for obj in schedules)
    assert all(obj.fields[2].value == one.schedule_path.name for obj in schedules)


def test_compiler_rejects_unknown_or_missing_people_targets(tmp_path: Path) -> None:
    source = tmp_path / "source.idf"
    source.write_text(_two_space_idf(), encoding="utf-8")
    missing = RoomAwareScenario(
        scenario_id="missing",
        scenario_kind="controlled",
        profiles_by_space={"hall-1": (0.5,) * 96},
        design_people_by_space={"hall-1": 10.0},
    )
    unknown = RoomAwareScenario(
        scenario_id="unknown",
        scenario_kind="controlled",
        profiles_by_space={
            "hall-1": (0.5,) * 96,
            "office-1": (0.5,) * 96,
            "unknown-1": (0.5,) * 96,
        },
        design_people_by_space={
            "hall-1": 10.0,
            "office-1": 5.0,
            "unknown-1": 1.0,
        },
    )

    with pytest.raises(ValueError, match="scenario_space_profile_missing:office-1"):
        compile_room_scenario(
            source,
            parse_idd(PEOPLE_IDD),
            missing,
            tmp_path / "missing",
            allowed_root=tmp_path,
        )
    with pytest.raises(ValueError, match="scenario_space_profile_unknown:unknown-1"):
        compile_room_scenario(
            source,
            parse_idd(PEOPLE_IDD),
            unknown,
            tmp_path / "unknown",
            allowed_root=tmp_path,
        )
    assert not (tmp_path / "missing").exists()
    assert not (tmp_path / "unknown").exists()


def test_compiler_refuses_output_outside_allowed_root(tmp_path: Path) -> None:
    source = tmp_path / "source.idf"
    source.write_text(_two_space_idf(), encoding="utf-8")

    with pytest.raises(ValueError, match="output_outside_allowed_root"):
        compile_room_scenario(
            source,
            parse_idd(PEOPLE_IDD),
            _scenario(),
            tmp_path.parent / "outside",
            allowed_root=tmp_path,
        )

