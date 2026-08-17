"""验证基线 profile 解析与完整受控场景矩阵。"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

from idfrepair.analysis.occupancy.models import BaselineProfiles
from idfrepair.analysis.occupancy.scenarios import person_hours
from idfrepair.analysis.occupancy.workflow import (
    build_controlled_scenarios,
    extract_baseline_profiles,
)
from idfrepair.knowledge.idd import parse_idd
from tests.occupancy.fixtures import PEOPLE_IDD


def _two_people_idf() -> str:
    return """Version,24.1;
Zone,Zone A;
Zone,Zone B;
People,Group A,Zone A,Schedule A,People,100,,,0.3,autocalculate,Activity A,3.82E-8;
People,Group B,Zone B,Schedule B,People,50,,,0.3,autocalculate,Activity B,3.82E-8;
"""


def test_extract_baseline_profiles_uses_schedule_value_ratio_not_rounded_eio_design(
    tmp_path: Path,
) -> None:
    """设计人数由 exact schedule/occupant 比值恢复，不采用 EIO 截断值。"""

    idf = tmp_path / "model.idf"
    idf.write_text(_two_people_idf(), encoding="utf-8")
    eio = tmp_path / "eplusout.eio"
    eio.write_text(
        " People Internal Gains Nominal, ZONE A GROUP A,SCHEDULE A,ZONE A,100,99.9,99.9,1,1,0.3,0.7,AutoCalculate,ACTIVITY A,No,3.82E-8,0,100\n"
        " People Internal Gains Nominal, ZONE B GROUP B,SCHEDULE B,ZONE B,50,49.8,49.8,1,1,0.3,0.7,AutoCalculate,ACTIVITY B,No,3.82E-8,0,50\n",
        encoding="utf-8",
    )
    output = tmp_path / "eplusout.csv"
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "Date/Time",
                "ZONE A GROUP A:People Occupant Count [](TimeStep)",
                "ZONE B GROUP B:People Occupant Count [](TimeStep)",
                "SCHEDULE A:Schedule Value [](TimeStep)",
                "SCHEDULE B:Schedule Value [](TimeStep)",
            ]
        )
        for step in range(96):
            writer.writerow([f"01/18 {step:02d}", "25", "10", "0.25", "0.2"])

    baseline = extract_baseline_profiles(
        idf,
        parse_idd(PEOPLE_IDD),
        eio,
        output,
        expected_steps=96,
    )

    assert baseline.design_people == {"Group A": 100.0, "Group B": 50.0}
    assert baseline.group_zone_counts == {"Group A": 1, "Group B": 1}
    assert baseline.profiles["Group A"] == pytest.approx((0.25,) * 96)
    assert baseline.profiles["Group B"] == pytest.approx((0.2,) * 96)
    assert baseline.passenger_hours == pytest.approx(840.0)


def test_controlled_suite_is_deterministic_complete_and_conserved() -> None:
    """四时序、两空间、八组合及五 volume controls 均有明确边界。"""

    baseline = BaselineProfiles(
        profiles={
            "Group A": tuple(0.2 + 0.4 * (20 <= step < 60) for step in range(96)),
            "Group B": tuple(0.1 + 0.3 * (44 <= step < 84) for step in range(96)),
            "Group C": tuple(0.05 + 0.15 * (68 <= step < 88) for step in range(96)),
        },
        design_people={"Group A": 100.0, "Group B": 50.0, "Group C": 25.0},
        group_zone_counts={"Group A": 4, "Group B": 2, "Group C": 1},
        timestamps=tuple(f"t{step:02d}" for step in range(96)),
        minutes_per_step=15.0,
    )

    first = build_controlled_scenarios(baseline)
    second = build_controlled_scenarios(baseline)

    assert first == second
    assert len(first) == 19
    assert {row.kind for row in first} == {
        "temporal_redistribution",
        "spatial_redistribution",
        "spatiotemporal_redistribution",
        "volume_sensitivity",
    }
    assert sum(row.kind == "temporal_redistribution" for row in first) == 4
    assert sum(row.kind == "spatial_redistribution" for row in first) == 2
    assert sum(row.kind == "spatiotemporal_redistribution" for row in first) == 8
    assert sum(row.kind == "volume_sensitivity" for row in first) == 5

    reference = baseline.passenger_hours
    for scenario in first:
        total = math.fsum(
            person_hours(scenario.profiles[name], scenario.design_people[name])
            for name in scenario.profiles
        )
        if scenario.kind == "volume_sensitivity":
            factor = float(scenario.name.removeprefix("volume_").replace("_", "."))
            assert total == pytest.approx(reference * factor, rel=1e-9)
            assert scenario.conserves_passenger_hours is (factor == 1.0)
        else:
            assert total == pytest.approx(reference, rel=1e-9)
            assert scenario.conserves_passenger_hours is True
            assert scenario.reference_person_hours == pytest.approx(reference)

    baseline_counts = tuple(
        sum(
            baseline.profiles[name][step] * baseline.design_people[name]
            for name in baseline.profiles
        )
        for step in range(96)
    )
    for scenario in first:
        if scenario.kind != "spatial_redistribution":
            continue
        redistributed = tuple(
            sum(
                scenario.profiles[name][step] * scenario.design_people[name]
                for name in scenario.profiles
            )
            for step in range(96)
        )
        assert redistributed == pytest.approx(baseline_counts, rel=0, abs=1e-9)
        assert max(max(profile) for profile in scenario.profiles.values()) <= 1.0 + 1e-12
