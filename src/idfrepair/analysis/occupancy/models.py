"""定义 occupancy 分析使用的不可变领域记录。

PeopleRecord: 保存一个版本绑定 People 对象及其精确源字段身份。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class PeopleRecord:
    """保存 People 对象的人数、schedule、热增益与源 provenance。"""

    record_id: str
    name: str
    target_name: str
    number_schedule_name: str
    calculation_method: str
    number_of_people: float | None
    people_per_floor_area: float | None
    floor_area_per_person: float | None
    fraction_radiant: float
    sensible_heat_fraction: float | None
    activity_schedule_name: str
    co2_generation_rate: float
    source_object_index: int
    number_schedule_field_index: int
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ZoneServiceMap:
    """保存 People→Zone→HVAC 的 source-backed 关系及显式缺口。"""

    people_to_zones: Mapping[str, tuple[str, ...]]
    zone_to_hvac: Mapping[str, tuple[str, ...]]
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OccupancyScenario:
    """描述一组按 People 名称绑定的单日 occupancy profiles。"""

    name: str
    kind: str
    profiles: Mapping[str, tuple[float, ...]]
    design_people: Mapping[str, float]
    minutes_per_step: float = 15.0
    conserves_passenger_hours: bool = False
    reference_person_hours: float | None = None


@dataclass(frozen=True, slots=True)
class BaselineProfiles:
    """保存由 EnergyPlus 输出反解的 People 组基线及设计人数。"""

    profiles: Mapping[str, tuple[float, ...]]
    design_people: Mapping[str, float]
    group_zone_counts: Mapping[str, int]
    timestamps: tuple[str, ...]
    minutes_per_step: float = 15.0

    @property
    def passenger_hours(self) -> float:
        """按精确 profile、设计人数和时步计算总 passenger-hours。"""

        step_hours = self.minutes_per_step / 60.0
        return sum(
            sum(self.profiles[name]) * float(self.design_people[name]) * step_hours
            for name in self.profiles
        )


@dataclass(frozen=True, slots=True)
class FieldModification:
    """记录一个经 source-span 守卫的 People schedule 字段替换。"""

    object_index: int
    object_type: str
    object_name: str
    field_index: int
    field_name: str
    old_value: str
    new_value: str
    source_start: int
    source_end: int


@dataclass(frozen=True, slots=True)
class CompiledScenario:
    """记录一个确定性派生 IDF/CSV 及其 provenance。"""

    scenario_name: str
    scenario_digest: str
    source_sha256: str
    idf_path: Path
    idf_sha256: str
    schedule_path: Path
    schedule_sha256: str
    passenger_hours: float
    modified_fields: tuple[FieldModification, ...]


@dataclass(frozen=True, slots=True)
class OutputRequest:
    """一个经 RDD 证实存在的 EnergyPlus output request。"""

    variable_name: str
    mechanism: str
    key_value: str = "*"
    frequency: str = "Timestep"


@dataclass(frozen=True, slots=True)
class SimulationRun:
    """保存一次有界 EnergyPlus 进程的身份、状态与输出可用性。"""

    executable: Path
    runtime_version: str
    runtime_sha256: str
    idf_path: Path
    idf_sha256: str
    idd_sha256: str | None
    weather_sha256: str | None
    output_directory: Path
    return_code: int | None
    timed_out: bool
    elapsed_seconds: float
    severe_count: int
    fatal_count: int
    csv_available: bool
    rdd_available: bool
    err_available: bool


@dataclass(frozen=True, slots=True)
class MetricRow:
    """一个 EnergyPlus CSV 时步值或显式 unavailable 机制。"""

    timestamp: str | None
    key_name: str | None
    variable_name: str
    unit: str | None
    frequency: str | None
    mechanism: str
    availability: str
    value: float | None


@dataclass(frozen=True, slots=True)
class ScenarioSummary:
    """一个场景的紧凑、机制分离结果。"""

    scenario_name: str
    kind: str
    run_status: str
    compiled_passenger_hours: float
    reference_passenger_hours: float | None
    conservation_error: float | None
    occupant_hours_from_output: float | None
    occupant_peak: float | None
    occupant_peak_time: str | None
    people_sensible_kwh: float | None
    people_latent_kwh: float | None
    people_radiant_kwh: float | None
    synthetic_heating_kwh: float | None
    synthetic_cooling_kwh: float | None
    synthetic_heating_peak_kw: float | None
    synthetic_heating_peak_time: str | None
    synthetic_cooling_peak_kw: float | None
    synthetic_cooling_peak_time: str | None
    outdoor_air_heating_kwh: float | None
    outdoor_air_cooling_kwh: float | None
    outdoor_air_mass_flow_peak_kg_s: float | None
    facility_hvac_demand_peak_kw: float | None
    zone_temperature_mean_c: float | None
    zone_relative_humidity_mean_pct: float | None
    heating_unmet_zone_hours: float | None
    cooling_unmet_zone_hours: float | None
    mean_zone_occupancy_cv: float | None
    available_variables: tuple[str, ...]
    unavailable_variables: tuple[str, ...]


__all__ = [
    "BaselineProfiles",
    "CompiledScenario",
    "FieldModification",
    "MetricRow",
    "OccupancyScenario",
    "OutputRequest",
    "PeopleRecord",
    "SimulationRun",
    "ScenarioSummary",
    "ZoneServiceMap",
]
