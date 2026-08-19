"""Fixed-seed repeated-day schedules for seasonal EnergyPlus comparisons."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .annual_schedule import write_people_manifest
from .source import SourceSpace


class SeasonalScheduleError(ValueError):
    """Raised when a seasonal schedule cannot be compiled without inference."""


@dataclass(frozen=True, slots=True)
class SeasonalScheduleArtifact:
    scenario_id: str
    seed: int
    schedule_path: Path
    manifest_path: Path
    summary_path: Path
    row_count: int


def _daily_series(value: object, identity: str) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SeasonalScheduleError(f"daily series is invalid: {identity}")
    values = tuple(float(item) for item in value)
    if len(values) != 96:
        raise SeasonalScheduleError(f"daily series length is invalid: {identity}")
    if any(not math.isfinite(item) or item < 0 for item in values):
        raise SeasonalScheduleError(f"daily series value is invalid: {identity}")
    return values


def write_repeated_daily_schedule(
    *,
    spaces: Iterable[SourceSpace],
    detail: Mapping[str, object],
    output_dir: str | Path,
) -> SeasonalScheduleArtifact:
    """Repeat one validated 15-minute ABM realization for seasonal runs only."""

    if detail.get("schema_version") != "idfrepair.airport-abm-seed-detail.v3":
        raise SeasonalScheduleError("seed detail schema is invalid")
    if int(detail.get("interval_minutes", 0)) != 15:
        raise SeasonalScheduleError("seasonal schedule requires 15-minute data")
    if len(detail.get("interval_labels", [])) != 96:
        raise SeasonalScheduleError("seasonal interval labels are invalid")
    counts = detail.get("space_counts")
    if not isinstance(counts, Mapping):
        raise SeasonalScheduleError("seasonal Space counts are invalid")
    supported = tuple(
        sorted(
            (space for space in spaces if space.bem_people_supported),
            key=lambda space: space.name,
        )
    )
    profiles: dict[str, tuple[float, ...]] = {}
    for space in supported:
        if space.name not in counts:
            raise SeasonalScheduleError(
                f"seasonal schedule is missing Space data: {space.name}"
            )
        profiles[space.name] = _daily_series(counts[space.name], space.name)

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    schedule_path = root / "occupancy.csv"
    row_count = 0
    with schedule_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(space.name for space in supported)
        for _day_index in range(365):
            for interval_index in range(96):
                writer.writerow(
                    format(
                        profiles[space.name][interval_index]
                        / float(space.source_design_people),
                        ".8g",
                    )
                    for space in supported
                )
                row_count += 1
    if row_count != 365 * 96:
        raise SeasonalScheduleError(f"seasonal row count mismatch: {row_count}")

    manifest_path = write_people_manifest(
        root / "people_manifest.json",
        schedule_path=schedule_path,
        spaces=supported,
        days=365,
        interval_minutes=15,
    )
    scenario_id = str(detail.get("scenario_id", ""))
    seed = int(detail.get("seed", 0))
    source_summary = detail.get("summary", {})
    if not isinstance(source_summary, Mapping):
        source_summary = {}
    summary = {
        "schema_version": "idfrepair.airport-abm-seasonal-schedule.v3",
        "scenario_id": scenario_id,
        "seed": seed,
        "interval_minutes": 15,
        "row_count": row_count,
        "daily_profile_repetitions": 365,
        "seasonal_use_only": True,
        "annual_variability_claim": False,
        "source_supported_space_count": len(supported),
        "daily_public_person_hours": source_summary.get("public_person_hours_bem"),
        "daily_staff_person_hours": source_summary.get("staff_person_hours_bem"),
        "daily_whole_building_peak_occupancy": source_summary.get(
            "whole_building_peak_occupancy"
        ),
        "evidence_status": "CONTROLLED_NOT_MEASURED",
    }
    summary_path = root / "seasonal_schedule_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return SeasonalScheduleArtifact(
        scenario_id=scenario_id,
        seed=seed,
        schedule_path=schedule_path,
        manifest_path=manifest_path,
        summary_path=summary_path,
        row_count=row_count,
    )
