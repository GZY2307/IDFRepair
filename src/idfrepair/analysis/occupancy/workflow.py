"""把 EnergyPlus 基线输出转换成可编译的受控 occupancy 场景矩阵。"""

from __future__ import annotations

import csv
import math
from pathlib import Path
import re

from idfrepair.analysis.occupancy.extract import extract_people
from idfrepair.analysis.occupancy.models import BaselineProfiles, OccupancyScenario
from idfrepair.analysis.occupancy.scenarios import (
    person_hours,
    redistribute_spatial_bounded,
    scale_volume,
    temporal_profiles,
)
from idfrepair.io.idf import canonical, parse_idf
from idfrepair.knowledge.idd import IDDSchema


_PEOPLE_EIO_LABEL = "people internal gains nominal"
_OCCUPANT_HEADER = re.compile(
    r"^(?P<key>.*):People Occupant Count\s*(?:\[[^]]*\])?\([^()]*\)\s*$",
    re.IGNORECASE,
)
_SCHEDULE_HEADER = re.compile(
    r"^(?P<key>.*):Schedule Value\s*(?:\[[^]]*\])?\([^()]*\)\s*$",
    re.IGNORECASE,
)


def _match_people_name(expanded_name: str, people_names: tuple[str, ...]) -> str:
    key = canonical(expanded_name)
    matches = tuple(
        name
        for name in people_names
        if key == canonical(name) or key.endswith(f" {canonical(name)}")
    )
    if len(matches) != 1:
        raise ValueError(
            f"expanded_people_name_not_unique:{expanded_name}:{len(matches)}"
        )
    return matches[0]


def extract_baseline_profiles(
    idf_path: Path,
    idd: IDDSchema,
    eio_path: Path,
    csv_path: Path,
    *,
    expected_steps: int = 96,
    minutes_per_step: float = 15.0,
) -> BaselineProfiles:
    """从 exact EIO/CSV 反解每个 People 组的设计人数与 schedule multiplier。"""

    idf_path = Path(idf_path)
    eio_path = Path(eio_path)
    csv_path = Path(csv_path)
    for path, label in (
        (idf_path, "baseline_idf"),
        (eio_path, "baseline_eio"),
        (csv_path, "baseline_csv"),
    ):
        if not path.is_file():
            raise ValueError(f"{label}_not_found")
    if expected_steps <= 0:
        raise ValueError("baseline_expected_steps_must_be_positive")
    if not math.isfinite(minutes_per_step) or minutes_per_step <= 0.0:
        raise ValueError("baseline_minutes_per_step_invalid")

    document = parse_idf(idf_path.read_text(encoding="utf-8"))
    people_records = extract_people(document, idd)
    people_names = tuple(row.name for row in people_records)
    if not people_names:
        raise ValueError("baseline_has_no_people")
    schedule_by_people = {
        row.name: row.number_schedule_name for row in people_records
    }
    if any(not value for value in schedule_by_people.values()):
        raise ValueError("baseline_people_schedule_missing")

    reported_design_people = {name: 0.0 for name in people_names}
    group_zone_counts = {name: 0 for name in people_names}
    with eio_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.reader(handle):
            if not row or canonical(row[0]) != _PEOPLE_EIO_LABEL:
                continue
            if len(row) <= 6:
                raise ValueError("people_eio_record_too_short")
            name = _match_people_name(row[1].strip(), people_names)
            try:
                design = float(row[6])
            except ValueError as exc:
                raise ValueError(f"people_eio_design_invalid:{name}") from exc
            if not math.isfinite(design) or design < 0.0:
                raise ValueError(f"people_eio_design_invalid:{name}")
            reported_design_people[name] += design
            group_zone_counts[name] += 1
    for name in people_names:
        if group_zone_counts[name] <= 0 or reported_design_people[name] <= 0.0:
            raise ValueError(f"people_eio_group_missing:{name}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("baseline_csv_empty") from exc
        columns = {name: [] for name in people_names}
        schedule_names = {
            canonical(value): value for value in schedule_by_people.values()
        }
        schedule_columns: dict[str, int] = {}
        for index, raw_header in enumerate(header[1:], start=1):
            match = _OCCUPANT_HEADER.match(raw_header.strip())
            if match is not None:
                name = _match_people_name(match.group("key").strip(), people_names)
                columns[name].append(index)
                continue
            schedule_match = _SCHEDULE_HEADER.match(raw_header.strip())
            if schedule_match is None:
                continue
            schedule_key = canonical(schedule_match.group("key"))
            if schedule_key not in schedule_names:
                continue
            if schedule_key in schedule_columns:
                raise ValueError(
                    f"baseline_schedule_output_not_unique:{schedule_names[schedule_key]}"
                )
            schedule_columns[schedule_key] = index
        for name in people_names:
            if not columns[name]:
                raise ValueError(f"baseline_people_output_missing:{name}")
            schedule_name = schedule_by_people[name]
            if canonical(schedule_name) not in schedule_columns:
                raise ValueError(f"baseline_schedule_output_missing:{schedule_name}")

        timestamps: list[str] = []
        occupant_counts = {name: [] for name in people_names}
        schedule_values = {key: [] for key in schedule_columns}
        for row in reader:
            if not row:
                continue
            timestamps.append(row[0].strip())
            for name in people_names:
                values: list[float] = []
                for index in columns[name]:
                    if index >= len(row):
                        raise ValueError(f"baseline_csv_row_short:{name}")
                    try:
                        value = float(row[index])
                    except ValueError as exc:
                        raise ValueError(f"baseline_people_output_invalid:{name}") from exc
                    if not math.isfinite(value) or value < 0.0:
                        raise ValueError(f"baseline_people_output_invalid:{name}")
                    values.append(value)
                occupant_counts[name].append(math.fsum(values))
            for schedule_key, index in schedule_columns.items():
                if index >= len(row):
                    raise ValueError(
                        f"baseline_csv_schedule_row_short:{schedule_names[schedule_key]}"
                    )
                try:
                    schedule_value = float(row[index])
                except ValueError as exc:
                    raise ValueError(
                        f"baseline_schedule_output_invalid:{schedule_names[schedule_key]}"
                    ) from exc
                if not math.isfinite(schedule_value) or schedule_value < 0.0:
                    raise ValueError(
                        f"baseline_schedule_output_invalid:{schedule_names[schedule_key]}"
                    )
                schedule_values[schedule_key].append(schedule_value)
    if len(timestamps) != expected_steps:
        raise ValueError(
            f"baseline_step_count_mismatch:{len(timestamps)}:{expected_steps}"
        )
    design_people: dict[str, float] = {}
    profiles: dict[str, tuple[float, ...]] = {}
    for name in people_names:
        schedule_key = canonical(schedule_by_people[name])
        profile = tuple(schedule_values[schedule_key])
        ratios = [
            count / schedule
            for count, schedule in zip(occupant_counts[name], profile)
            if schedule > 1e-12
        ]
        if not ratios:
            raise ValueError(f"baseline_schedule_never_positive:{schedule_by_people[name]}")
        ordered = sorted(ratios)
        design = ordered[len(ordered) // 2]
        tolerance = max(1e-6, abs(design) * 1e-7)
        if max(abs(value - design) for value in ratios) > tolerance:
            raise ValueError(f"baseline_design_ratio_inconsistent:{name}")
        design_people[name] = design
        profiles[name] = profile
    return BaselineProfiles(
        profiles=profiles,
        design_people=design_people,
        group_zone_counts=group_zone_counts,
        timestamps=tuple(timestamps),
        minutes_per_step=minutes_per_step,
    )


def _spatial_profiles(
    counts: dict[str, tuple[float, ...]],
    design_people: dict[str, float],
    weights: dict[str, float],
    *,
    max_multiplier: float,
) -> dict[str, tuple[float, ...]]:
    capacities = {
        name: design_people[name] * max_multiplier for name in design_people
    }
    redistributed = redistribute_spatial_bounded(counts, weights, capacities)
    return {
        name: tuple(value / design_people[name] for value in redistributed[name])
        for name in design_people
    }


def build_controlled_scenarios(
    baseline: BaselineProfiles,
) -> tuple[OccupancyScenario, ...]:
    """生成冻结协议的 4+2+8+5 个场景，且不猜测 terminal function。"""

    names = tuple(baseline.profiles)
    if not names or set(names) != set(baseline.design_people):
        raise ValueError("baseline_profile_design_names_mismatch")
    lengths = {len(baseline.profiles[name]) for name in names}
    if lengths != {96}:
        raise ValueError("baseline_profiles_must_have_96_steps")
    design = {name: float(baseline.design_people[name]) for name in names}
    if any(not math.isfinite(value) or value <= 0.0 for value in design.values()):
        raise ValueError("baseline_design_people_invalid")
    reference = baseline.passenger_hours
    if not math.isfinite(reference) or reference <= 0.0:
        raise ValueError("baseline_passenger_hours_invalid")

    temporal_names = (
        "morning_peak",
        "midday_peak",
        "evening_peak",
        "double_peak",
    )
    temporal_by_name: dict[str, dict[str, tuple[float, ...]]] = {
        name: {} for name in temporal_names
    }
    for people_name in names:
        profile = baseline.profiles[people_name]
        group_hours = person_hours(
            profile,
            design[people_name],
            minutes_per_step=baseline.minutes_per_step,
        )
        if group_hours == 0.0:
            for scenario_name in temporal_by_name:
                temporal_by_name[scenario_name][people_name] = (0.0,) * 96
            continue
        generated = temporal_profiles(profile)
        for scenario_name in temporal_by_name:
            temporal_by_name[scenario_name][people_name] = generated[scenario_name]

    scenarios: list[OccupancyScenario] = []
    for scenario_name, profiles in temporal_by_name.items():
        scenarios.append(
            OccupancyScenario(
                name=scenario_name,
                kind="temporal_redistribution",
                profiles=profiles,
                design_people=design,
                minutes_per_step=baseline.minutes_per_step,
                conserves_passenger_hours=True,
                reference_person_hours=reference,
            )
        )

    baseline_counts = {
        name: tuple(value * design[name] for value in baseline.profiles[name])
        for name in names
    }
    ranked = sorted(names, key=lambda name: (-design[name], canonical(name)))
    top_two = set(ranked[:2])
    distributed_weights = {name: design[name] for name in names}
    concentrated_weights = {
        name: design[name] * (4.0 if name in top_two else 0.25) for name in names
    }
    spatial_vectors = {
        "spatial_concentrated": concentrated_weights,
        "spatial_distributed": distributed_weights,
    }
    for scenario_name, weights in spatial_vectors.items():
        profiles = _spatial_profiles(
            baseline_counts,
            design,
            weights,
            max_multiplier=1.0,
        )
        scenarios.append(
            OccupancyScenario(
                name=scenario_name,
                kind="spatial_redistribution",
                profiles=profiles,
                design_people=design,
                minutes_per_step=baseline.minutes_per_step,
                conserves_passenger_hours=True,
                reference_person_hours=reference,
            )
        )

    for temporal_name, temporal_group_profiles in temporal_by_name.items():
        temporal_counts = {
            name: tuple(value * design[name] for value in temporal_group_profiles[name])
            for name in names
        }
        admitted_peak_multiplier = max(
            1.0,
            max(max(profile) for profile in temporal_group_profiles.values()),
        )
        for spatial_name, weights in spatial_vectors.items():
            profiles = _spatial_profiles(
                temporal_counts,
                design,
                weights,
                max_multiplier=admitted_peak_multiplier,
            )
            scenarios.append(
                OccupancyScenario(
                    name=f"{temporal_name}__{spatial_name}",
                    kind="spatiotemporal_redistribution",
                    profiles=profiles,
                    design_people=design,
                    minutes_per_step=baseline.minutes_per_step,
                    conserves_passenger_hours=True,
                    reference_person_hours=reference,
                )
            )

    for factor in (0.50, 0.75, 1.00, 1.25, 1.50):
        profiles = {
            name: scale_volume(baseline.profiles[name], factor) for name in names
        }
        scenarios.append(
            OccupancyScenario(
                name=f"volume_{factor:.2f}".replace(".", "_"),
                kind="volume_sensitivity",
                profiles=profiles,
                design_people=design,
                minutes_per_step=baseline.minutes_per_step,
                conserves_passenger_hours=factor == 1.0,
                reference_person_hours=reference if factor == 1.0 else None,
            )
        )
    return tuple(scenarios)


__all__ = ["build_controlled_scenarios", "extract_baseline_profiles"]
