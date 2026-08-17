"""Room/Zone/category-aware EnergyPlus output extraction and run provenance."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from idfrepair.analysis.occupancy.energyplus import prepare_one_day_idf
from idfrepair.analysis.occupancy.models import OutputRequest, SimulationRun
from idfrepair.io.idf import canonical, parse_idf
from idfrepair.knowledge.idd import IDDSchema


RUN_MANIFEST_SCHEMA = "idfrepair.room-aware-run.v2"
RESULT_SCHEMA = "idfrepair.room-aware-results.v1"

OCCUPANT_COUNT = "Zone People Occupant Count"
PEOPLE_SENSIBLE = "Zone People Sensible Heating Energy"
PEOPLE_LATENT = "Zone People Latent Gain Energy"
PEOPLE_RADIANT = "Zone People Radiant Heating Energy"
HEATING_ENERGY = "Zone Ideal Loads Supply Air Total Heating Energy"
COOLING_ENERGY = "Zone Ideal Loads Supply Air Total Cooling Energy"
HEATING_RATE = "Zone Ideal Loads Supply Air Total Heating Rate"
COOLING_RATE = "Zone Ideal Loads Supply Air Total Cooling Rate"
OA_HEATING_ENERGY = "Zone Ideal Loads Outdoor Air Total Heating Energy"
OA_COOLING_ENERGY = "Zone Ideal Loads Outdoor Air Total Cooling Energy"
OA_MASS_FLOW = "Zone Ideal Loads Outdoor Air Mass Flow Rate"
TEMPERATURE = "Zone Air Temperature"
MEAN_TEMPERATURE = "Zone Mean Air Temperature"
RELATIVE_HUMIDITY = "Zone Air Relative Humidity"
HEATING_UNMET = "Zone Heating Setpoint Not Met Time"
COOLING_UNMET = "Zone Cooling Setpoint Not Met Time"

SEASONAL_OUTPUT_VARIABLES = (
    OCCUPANT_COUNT,
    PEOPLE_SENSIBLE,
    PEOPLE_LATENT,
    PEOPLE_RADIANT,
    HEATING_ENERGY,
    COOLING_ENERGY,
    HEATING_RATE,
    COOLING_RATE,
    OA_HEATING_ENERGY,
    OA_COOLING_ENERGY,
    OA_MASS_FLOW,
    TEMPERATURE,
    RELATIVE_HUMIDITY,
    HEATING_UNMET,
    COOLING_UNMET,
)

ANNUAL_OUTPUT_VARIABLES = (
    OCCUPANT_COUNT,
    PEOPLE_SENSIBLE,
    PEOPLE_LATENT,
    PEOPLE_RADIANT,
    HEATING_ENERGY,
    COOLING_ENERGY,
    HEATING_RATE,
    COOLING_RATE,
)

_ENERGY_TO_FIELD = {
    PEOPLE_SENSIBLE: "people_sensible_kwh",
    PEOPLE_LATENT: "people_latent_kwh",
    PEOPLE_RADIANT: "people_radiant_kwh",
    HEATING_ENERGY: "heating_kwh",
    COOLING_ENERGY: "cooling_kwh",
    OA_HEATING_ENERGY: "oa_heating_kwh",
    OA_COOLING_ENERGY: "oa_cooling_kwh",
}
_UNMET_TO_FIELD = {
    HEATING_UNMET: "heating_unmet_zone_hours",
    COOLING_UNMET: "cooling_unmet_zone_hours",
}
_HEADER = re.compile(
    r"^(?P<body>.*?)(?:\s+\[(?P<unit>[^]]*)\])?"
    r"\((?P<frequency>[^()]*)\)\s*$"
)


@dataclass(frozen=True, slots=True)
class SpaceResultBinding:
    """Source-backed one-Space/one-Zone result identity."""

    space_name: str
    zone_name: str
    category: str
    floor_area_m2: float
    design_people: float


@dataclass(frozen=True, slots=True)
class RoomMetricSummary:
    """Compact additive and synchronized-peak metrics for one result grouping."""

    scenario_id: str
    period_id: str
    grouping: str
    category: str | None
    space_name: str | None
    zone_name: str | None
    space_count: int
    floor_area_m2: float
    design_people: float
    person_hours: float | None
    occupant_peak: float | None
    occupant_peak_time: str | None
    occupant_density_peak_per_m2: float | None
    people_sensible_kwh: float | None
    people_latent_kwh: float | None
    people_radiant_kwh: float | None
    heating_kwh: float | None
    cooling_kwh: float | None
    heating_peak_kw: float | None
    heating_peak_time: str | None
    cooling_peak_kw: float | None
    cooling_peak_time: str | None
    oa_heating_kwh: float | None
    oa_cooling_kwh: float | None
    oa_mass_flow_peak_kg_s: float | None
    oa_mass_flow_peak_time: str | None
    temperature_area_weighted_mean_c: float | None
    rh_area_weighted_mean_pct: float | None
    heating_unmet_zone_hours: float | None
    cooling_unmet_zone_hours: float | None
    available_variables: tuple[str, ...]
    unavailable_variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExtractedRoomResults:
    """One EnergyPlus CSV reconciled to zones, categories, and building."""

    scenario_id: str
    period_id: str
    timestamps: tuple[str, ...]
    zones: tuple[RoomMetricSummary, ...]
    categories: tuple[RoomMetricSummary, ...]
    whole_building: RoomMetricSummary
    occupancy_by_space: Mapping[str, tuple[float, ...]]

    def records(self) -> tuple[dict[str, Any], ...]:
        rows = (*self.zones, *self.categories, self.whole_building)
        result: list[dict[str, Any]] = []
        for row in rows:
            record = asdict(row)
            record["available_variables"] = "|".join(row.available_variables)
            record["unavailable_variables"] = "|".join(row.unavailable_variables)
            result.append(record)
        return tuple(result)


@dataclass(slots=True)
class _Accumulator:
    bindings: tuple[SpaceResultBinding, ...]
    energy_j: dict[str, float]
    unmet_h: dict[str, float]
    person_hours: float
    occupant_peak: float | None
    occupant_peak_time: str | None
    heating_peak_w: float | None
    heating_peak_time: str | None
    cooling_peak_w: float | None
    cooling_peak_time: str | None
    oa_peak_kg_s: float | None
    oa_peak_time: str | None
    temperature_area_sum: float
    temperature_area_weight: float
    rh_area_sum: float
    rh_area_weight: float

    @classmethod
    def create(cls, bindings: Sequence[SpaceResultBinding]) -> _Accumulator:
        return cls(
            bindings=tuple(bindings),
            energy_j=defaultdict(float),
            unmet_h=defaultdict(float),
            person_hours=0.0,
            occupant_peak=None,
            occupant_peak_time=None,
            heating_peak_w=None,
            heating_peak_time=None,
            cooling_peak_w=None,
            cooling_peak_time=None,
            oa_peak_kg_s=None,
            oa_peak_time=None,
            temperature_area_sum=0.0,
            temperature_area_weight=0.0,
            rh_area_sum=0.0,
            rh_area_weight=0.0,
        )

    @property
    def floor_area(self) -> float:
        return math.fsum(row.floor_area_m2 for row in self.bindings)

    @property
    def design_people(self) -> float:
        return math.fsum(row.design_people for row in self.bindings)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _contract_sha256(minutes_per_output_step: float, variables: Sequence[str]) -> str:
    payload = {
        "expected_variables": list(variables),
        "minutes_per_output_step": float(minutes_per_output_step),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def expected_run_identity(
    *,
    scenario_id: str,
    period_id: str,
    executable_path: Path,
    idd_path: Path,
    weather_path: Path,
    source_osm_path: Path,
    prepared_idf_path: Path,
    schedule_path: Path | None,
    minutes_per_output_step: float,
    expected_variables: Sequence[str],
) -> dict[str, Any]:
    """Hash every simulation input and the downstream extraction contract."""

    if not scenario_id.strip() or not period_id.strip():
        raise ValueError("result_identity_missing")
    if not math.isfinite(minutes_per_output_step) or minutes_per_output_step <= 0.0:
        raise ValueError("result_timestep_invalid")
    variables = tuple(
        dict.fromkeys(value.strip() for value in expected_variables if value.strip())
    )
    if not variables:
        raise ValueError("result_expected_variables_empty")
    required = {
        "runtime": Path(executable_path),
        "idd": Path(idd_path),
        "weather": Path(weather_path),
        "source_osm": Path(source_osm_path),
        "prepared_idf": Path(prepared_idf_path),
    }
    if schedule_path is not None:
        required["schedule"] = Path(schedule_path)
    for label, path in required.items():
        if not path.is_file():
            raise ValueError(f"result_identity_{label}_not_found")
    return {
        "scenario_id": scenario_id,
        "period_id": period_id,
        "runtime_sha256": _sha256(required["runtime"]),
        "idd_sha256": _sha256(required["idd"]),
        "weather_sha256": _sha256(required["weather"]),
        "source_osm_sha256": _sha256(required["source_osm"]),
        "prepared_idf_sha256": _sha256(required["prepared_idf"]),
        "schedule_filename": (
            required["schedule"].name if "schedule" in required else None
        ),
        "schedule_sha256": (
            _sha256(required["schedule"]) if "schedule" in required else None
        ),
        "minutes_per_output_step": float(minutes_per_output_step),
        "expected_variables": list(variables),
        "extraction_contract_sha256": _contract_sha256(
            minutes_per_output_step, variables
        ),
    }


def _result_file_record(path: Path) -> dict[str, Any]:
    return {"bytes": path.stat().st_size, "sha256": _sha256(path)}


def _validate_result_file_records(
    output_directory: Path,
    records: Mapping[str, Any],
) -> None:
    required = {"eplusout.csv", "eplusout.err", "eplusout.rdd"}
    if set(records) != required:
        raise ValueError("result_manifest_result_file_set_mismatch")
    for name in sorted(required):
        record = records.get(name)
        if not isinstance(record, Mapping):
            raise ValueError(f"result_manifest_file_record_invalid:{name}")
        path = output_directory / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"result_manifest_file_missing:{name}")
        if record.get("bytes") != path.stat().st_size:
            raise ValueError(f"result_manifest_file_size_mismatch:{name}")
        if record.get("sha256") != _sha256(path):
            raise ValueError(f"result_manifest_file_hash_mismatch:{name}")


def validate_run_manifest(
    manifest_path: Path,
    *,
    expected_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed unless a PASS manifest and all declared bytes are exact."""

    path = Path(manifest_path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("result_manifest_not_found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("result_manifest_invalid_json") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != RUN_MANIFEST_SCHEMA:
        raise ValueError("result_manifest_schema_invalid")
    identity = payload.get("input_identity")
    if not isinstance(identity, dict):
        raise ValueError("result_manifest_input_identity_missing")
    if expected_identity is not None and identity != dict(expected_identity):
        raise ValueError("result_manifest_input_identity_mismatch")
    variables = identity.get("expected_variables")
    minutes = identity.get("minutes_per_output_step")
    if not isinstance(variables, list) or not variables:
        raise ValueError("result_manifest_extraction_contract_invalid")
    try:
        expected_contract = _contract_sha256(float(minutes), tuple(map(str, variables)))
    except (TypeError, ValueError) as exc:
        raise ValueError("result_manifest_extraction_contract_invalid") from exc
    if identity.get("extraction_contract_sha256") != expected_contract:
        raise ValueError("result_manifest_extraction_contract_hash_mismatch")
    if not (
        payload.get("status") == "PASS"
        and payload.get("return_code") == 0
        and payload.get("timed_out") is False
        and payload.get("severe_count") == 0
        and payload.get("fatal_count") == 0
        and payload.get("csv_available") is True
        and payload.get("rdd_available") is True
        and payload.get("err_available") is True
    ):
        raise ValueError("result_manifest_run_not_clean_pass")
    records = payload.get("result_files")
    if not isinstance(records, Mapping):
        raise ValueError("result_manifest_result_files_missing")
    _validate_result_file_records(path.parent, records)
    return payload


def migrate_v1_run_manifest(
    manifest_path: Path,
    *,
    expected_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Upgrade an exact legacy PASS cache without rerunning EnergyPlus."""

    path = Path(manifest_path)
    try:
        legacy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("result_manifest_invalid_json") from exc
    if not isinstance(legacy, dict) or legacy.get("schema_version") != "idfrepair.room-aware-run.v1":
        raise ValueError("result_manifest_legacy_schema_invalid")
    legacy_fields = {
        "scenario_id": "scenario_id",
        "period_id": "period_id",
        "runtime_sha256": "runtime_sha256",
        "idd_sha256": "idd_sha256",
        "weather_sha256": "weather_sha256",
        "source_osm_sha256": "source_osm_sha256",
        "derived_idf_sha256": "prepared_idf_sha256",
        "schedule_sha256": "schedule_sha256",
    }
    for legacy_name, current_name in legacy_fields.items():
        if legacy.get(legacy_name) != expected_identity.get(current_name):
            raise ValueError(f"result_manifest_legacy_identity_mismatch:{legacy_name}")
    if not (
        legacy.get("status") == "PASS"
        and legacy.get("return_code") == 0
        and legacy.get("timed_out") is False
        and legacy.get("severe_count") == 0
        and legacy.get("fatal_count") == 0
        and legacy.get("csv_available") is True
        and legacy.get("rdd_available") is True
        and legacy.get("err_available") is True
    ):
        raise ValueError("result_manifest_legacy_run_not_clean_pass")
    output = path.parent
    result_files = {
        name: _result_file_record(output / name)
        for name in ("eplusout.csv", "eplusout.err", "eplusout.rdd")
        if (output / name).is_file() and not (output / name).is_symlink()
    }
    _validate_result_file_records(output, result_files)
    payload = {
        **legacy,
        "schema_version": RUN_MANIFEST_SCHEMA,
        "input_identity": dict(expected_identity),
        "result_files": result_files,
        "migration": {
            "from_schema": "idfrepair.room-aware-run.v1",
            "basis": "all_legacy_input_hashes_equal_current_identity",
        },
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return validate_run_manifest(path, expected_identity=expected_identity)


def _within(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    allowed = root.resolve()
    return resolved == allowed or allowed in resolved.parents


def validate_bindings(
    bindings: Sequence[SpaceResultBinding],
) -> tuple[SpaceResultBinding, ...]:
    """Require exact nonempty one-Space/one-Zone identities and valid capacities."""

    rows = tuple(bindings)
    if not rows:
        raise ValueError("result_bindings_empty")
    spaces: dict[str, str] = {}
    zones: dict[str, str] = {}
    for row in rows:
        if not row.space_name.strip() or not row.zone_name.strip() or not row.category.strip():
            raise ValueError("result_binding_identity_missing")
        space_key = canonical(row.space_name)
        zone_key = canonical(row.zone_name)
        if space_key in spaces:
            raise ValueError(f"result_space_identity_duplicate:{row.space_name}")
        if zone_key in zones:
            raise ValueError(f"result_zone_identity_duplicate:{row.zone_name}")
        if (
            not math.isfinite(row.floor_area_m2)
            or row.floor_area_m2 <= 0.0
            or not math.isfinite(row.design_people)
            or row.design_people < 0.0
        ):
            raise ValueError(f"result_binding_capacity_invalid:{row.space_name}")
        spaces[space_key] = row.space_name
        zones[zone_key] = row.zone_name
    return rows


def bindings_from_audit(
    audit: Mapping[str, Any],
    *,
    design_people_by_space: Mapping[str, float] | None = None,
) -> tuple[SpaceResultBinding, ...]:
    """Build exact result bindings with an optional scenario design capacity."""

    overrides: dict[str, float] = {}
    for name, value in (design_people_by_space or {}).items():
        key = canonical(name)
        if key in overrides:
            raise ValueError(f"result_design_people_space_duplicate:{name}")
        overrides[key] = float(value)
    source_keys = {canonical(row["source_space_name"]) for row in audit.get("spaces", [])}
    if overrides and set(overrides) != source_keys:
        raise ValueError("result_design_people_space_mismatch")

    rows = []
    for source in audit.get("spaces", []):
        zone = source.get("thermal_zone")
        if not zone:
            raise ValueError(f"result_audit_space_zone_missing:{source.get('source_space_name')}")
        rows.append(
            SpaceResultBinding(
                space_name=str(source["source_space_name"]),
                zone_name=str(zone),
                category=str(source["room_category"]),
                floor_area_m2=float(source["floor_area_m2"]),
                design_people=overrides.get(
                    canonical(source["source_space_name"]),
                    float(source.get("design_people") or 0.0),
                ),
            )
        )
    return validate_bindings(rows)


def ideal_loads_key_to_zone(idf_path: Path) -> dict[str, str]:
    """Resolve IdealLoads output keys through explicit IDF equipment relations."""

    path = Path(idf_path)
    if not path.is_file():
        raise ValueError("result_mapping_idf_not_found")
    document = parse_idf(path.read_text(encoding="utf-8"))
    ideal_names = {
        canonical(obj.fields[0].value): obj.fields[0].value
        for obj in document.find_objects("ZoneHVAC:IdealLoadsAirSystem")
        if obj.fields and obj.fields[0].value.strip()
    }
    equipment_by_list: dict[str, tuple[str, ...]] = {}
    list_display: dict[str, str] = {}
    for obj in document.find_objects("ZoneHVAC:EquipmentList"):
        if len(obj.fields) < 4:
            continue
        list_name = obj.fields[0].value
        names: list[str] = []
        for index in range(2, len(obj.fields) - 1):
            if canonical(obj.fields[index].value) != canonical(
                "ZoneHVAC:IdealLoadsAirSystem"
            ):
                continue
            equipment_name = obj.fields[index + 1].value
            if canonical(equipment_name) not in ideal_names:
                raise ValueError(
                    f"result_ideal_loads_object_missing:{equipment_name}"
                )
            names.append(ideal_names[canonical(equipment_name)])
        equipment_by_list[canonical(list_name)] = tuple(names)
        list_display[canonical(list_name)] = list_name
    result: dict[str, str] = {}
    canonical_equipment: dict[str, str] = {}
    for obj in document.find_objects("ZoneHVAC:EquipmentConnections"):
        if len(obj.fields) < 2:
            raise ValueError("result_equipment_connection_fields_missing")
        zone_name = obj.fields[0].value
        list_name = obj.fields[1].value
        list_key = canonical(list_name)
        if list_key not in equipment_by_list:
            raise ValueError(f"result_equipment_list_missing:{list_name}")
        for equipment_name in equipment_by_list[list_key]:
            equipment_key = canonical(equipment_name)
            if equipment_key in canonical_equipment:
                raise ValueError(
                    f"result_ideal_loads_zone_duplicate:{equipment_name}"
                )
            canonical_equipment[equipment_key] = equipment_name
            result[equipment_name] = zone_name
    if ideal_names and len(result) != len(ideal_names):
        missing = sorted(set(ideal_names) - set(canonical_equipment))
        raise ValueError("result_ideal_loads_zone_unmapped:" + "|".join(missing))
    return result


def _parse_header(
    raw: str,
    expected: Sequence[str],
) -> tuple[str, str, str | None, str] | None:
    match = _HEADER.match(raw.strip())
    if match is None:
        return None
    body = match.group("body").strip()
    body_key = canonical(body)
    for variable in sorted(expected, key=len, reverse=True):
        suffix = canonical(":" + variable)
        if body_key.endswith(suffix):
            key_length = len(body) - len(":" + variable)
            key_name = body[:key_length].strip()
            unit = (match.group("unit") or "").strip() or None
            return key_name, variable, unit, match.group("frequency").strip()
    return None


def _set_peak(
    accumulator: _Accumulator,
    *,
    field: str,
    time_field: str,
    value: float,
    timestamp: str,
) -> None:
    current = getattr(accumulator, field)
    if current is None or value > current:
        setattr(accumulator, field, value)
        setattr(accumulator, time_field, timestamp)


def _update_accumulator(
    accumulator: _Accumulator,
    values: Mapping[str, Mapping[str, float]],
    timestamp: str,
    step_hours: float,
    temperature_variable: str | None,
) -> None:
    occupant_count = 0.0
    heating_rate = 0.0
    cooling_rate = 0.0
    oa_flow = 0.0
    occupant_available = OCCUPANT_COUNT in next(iter(values.values()), {})
    heating_rate_available = HEATING_RATE in next(iter(values.values()), {})
    cooling_rate_available = COOLING_RATE in next(iter(values.values()), {})
    oa_available = OA_MASS_FLOW in next(iter(values.values()), {})
    by_zone = {canonical(row.zone_name): row for row in accumulator.bindings}
    for zone_key, binding in by_zone.items():
        zone_values = values[zone_key]
        if occupant_available:
            occupant_count += zone_values[OCCUPANT_COUNT]
        if heating_rate_available:
            heating_rate += zone_values[HEATING_RATE]
        if cooling_rate_available:
            cooling_rate += zone_values[COOLING_RATE]
        if oa_available:
            oa_flow += zone_values[OA_MASS_FLOW]
        for variable in _ENERGY_TO_FIELD:
            if variable in zone_values:
                accumulator.energy_j[variable] += zone_values[variable]
        for variable in _UNMET_TO_FIELD:
            if variable in zone_values:
                accumulator.unmet_h[variable] += zone_values[variable]
        if temperature_variable and temperature_variable in zone_values:
            accumulator.temperature_area_sum += (
                zone_values[temperature_variable] * binding.floor_area_m2
            )
            accumulator.temperature_area_weight += binding.floor_area_m2
        if RELATIVE_HUMIDITY in zone_values:
            accumulator.rh_area_sum += (
                zone_values[RELATIVE_HUMIDITY] * binding.floor_area_m2
            )
            accumulator.rh_area_weight += binding.floor_area_m2
    if occupant_available:
        accumulator.person_hours += occupant_count * step_hours
        _set_peak(
            accumulator,
            field="occupant_peak",
            time_field="occupant_peak_time",
            value=occupant_count,
            timestamp=timestamp,
        )
    if heating_rate_available:
        _set_peak(
            accumulator,
            field="heating_peak_w",
            time_field="heating_peak_time",
            value=heating_rate,
            timestamp=timestamp,
        )
    if cooling_rate_available:
        _set_peak(
            accumulator,
            field="cooling_peak_w",
            time_field="cooling_peak_time",
            value=cooling_rate,
            timestamp=timestamp,
        )
    if oa_available:
        _set_peak(
            accumulator,
            field="oa_peak_kg_s",
            time_field="oa_peak_time",
            value=oa_flow,
            timestamp=timestamp,
        )


def _summary(
    accumulator: _Accumulator,
    *,
    scenario_id: str,
    period_id: str,
    grouping: str,
    category: str | None,
    available: tuple[str, ...],
    unavailable: tuple[str, ...],
) -> RoomMetricSummary:
    binding = accumulator.bindings[0] if grouping == "zone" else None
    area = accumulator.floor_area

    def energy(variable: str) -> float | None:
        if variable not in available:
            return None
        return accumulator.energy_j[variable] / 3_600_000.0

    def unmet(variable: str) -> float | None:
        if variable not in available:
            return None
        return accumulator.unmet_h[variable]

    return RoomMetricSummary(
        scenario_id=scenario_id,
        period_id=period_id,
        grouping=grouping,
        category=category,
        space_name=binding.space_name if binding else None,
        zone_name=binding.zone_name if binding else None,
        space_count=len(accumulator.bindings),
        floor_area_m2=area,
        design_people=accumulator.design_people,
        person_hours=(accumulator.person_hours if OCCUPANT_COUNT in available else None),
        occupant_peak=accumulator.occupant_peak,
        occupant_peak_time=accumulator.occupant_peak_time,
        occupant_density_peak_per_m2=(
            accumulator.occupant_peak / area
            if accumulator.occupant_peak is not None and area > 0.0
            else None
        ),
        people_sensible_kwh=energy(PEOPLE_SENSIBLE),
        people_latent_kwh=energy(PEOPLE_LATENT),
        people_radiant_kwh=energy(PEOPLE_RADIANT),
        heating_kwh=energy(HEATING_ENERGY),
        cooling_kwh=energy(COOLING_ENERGY),
        heating_peak_kw=(
            accumulator.heating_peak_w / 1000.0
            if accumulator.heating_peak_w is not None
            else None
        ),
        heating_peak_time=accumulator.heating_peak_time,
        cooling_peak_kw=(
            accumulator.cooling_peak_w / 1000.0
            if accumulator.cooling_peak_w is not None
            else None
        ),
        cooling_peak_time=accumulator.cooling_peak_time,
        oa_heating_kwh=energy(OA_HEATING_ENERGY),
        oa_cooling_kwh=energy(OA_COOLING_ENERGY),
        oa_mass_flow_peak_kg_s=accumulator.oa_peak_kg_s,
        oa_mass_flow_peak_time=accumulator.oa_peak_time,
        temperature_area_weighted_mean_c=(
            accumulator.temperature_area_sum / accumulator.temperature_area_weight
            if accumulator.temperature_area_weight > 0.0
            else None
        ),
        rh_area_weighted_mean_pct=(
            accumulator.rh_area_sum / accumulator.rh_area_weight
            if accumulator.rh_area_weight > 0.0
            else None
        ),
        heating_unmet_zone_hours=unmet(HEATING_UNMET),
        cooling_unmet_zone_hours=unmet(COOLING_UNMET),
        available_variables=available,
        unavailable_variables=unavailable,
    )


def extract_room_results(
    csv_path: Path,
    bindings: Sequence[SpaceResultBinding],
    *,
    scenario_id: str,
    period_id: str,
    expected_variables: Sequence[str] = SEASONAL_OUTPUT_VARIABLES,
    minutes_per_step: float = 15.0,
    capture_occupancy: bool = False,
    key_to_zone: Mapping[str, str] | None = None,
) -> ExtractedRoomResults:
    """Stream a wide EnergyPlus CSV and reconcile Zone→category→building metrics."""

    path = Path(csv_path)
    if not path.is_file():
        raise ValueError("result_csv_not_found")
    if not scenario_id.strip() or not period_id.strip():
        raise ValueError("result_identity_missing")
    if not math.isfinite(minutes_per_step) or minutes_per_step <= 0.0:
        raise ValueError("result_timestep_invalid")
    rows = validate_bindings(bindings)
    expected = tuple(dict.fromkeys(value.strip() for value in expected_variables if value.strip()))
    if not expected:
        raise ValueError("result_expected_variables_empty")
    binding_by_zone = {canonical(row.zone_name): row for row in rows}
    aliases: dict[str, str] = {}
    for key_name, zone_name in (key_to_zone or {}).items():
        key = canonical(key_name)
        zone_key = canonical(zone_name)
        if zone_key not in binding_by_zone:
            raise ValueError(f"result_alias_zone_unmapped:{zone_name}")
        if key in aliases and aliases[key] != zone_key:
            raise ValueError(f"result_alias_identity_duplicate:{key_name}")
        aliases[key] = zone_key

    categories: dict[str, tuple[SpaceResultBinding, ...]] = {}
    for category in sorted({row.category for row in rows}):
        categories[category] = tuple(row for row in rows if row.category == category)
    zone_accumulators = {
        canonical(row.zone_name): _Accumulator.create((row,)) for row in rows
    }
    category_accumulators = {
        category: _Accumulator.create(items) for category, items in categories.items()
    }
    whole_accumulator = _Accumulator.create(rows)
    occupancy = {row.space_name: [] for row in rows} if capture_occupancy else {}
    timestamps: list[str] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("result_csv_empty") from exc
        columns: dict[int, tuple[str, str]] = {}
        variable_zones: dict[str, set[str]] = defaultdict(set)
        for index, raw in enumerate(header[1:], start=1):
            parsed = _parse_header(raw, expected)
            if parsed is None:
                continue
            key_name, variable, _unit, _frequency = parsed
            zone_key = canonical(key_name)
            if zone_key not in binding_by_zone:
                zone_key = aliases.get(zone_key, "")
            if zone_key not in binding_by_zone:
                raise ValueError(f"result_header_zone_unmapped:{key_name}")
            identity = (zone_key, canonical(variable))
            if any(
                previous_zone == identity[0] and canonical(previous_variable) == identity[1]
                for previous_zone, previous_variable in columns.values()
            ):
                raise ValueError(f"result_header_variable_duplicate:{key_name}:{variable}")
            columns[index] = (zone_key, variable)
            variable_zones[variable].add(zone_key)
        found = tuple(variable for variable in expected if variable in variable_zones)
        unavailable = tuple(variable for variable in expected if variable not in variable_zones)
        expected_zone_keys = set(binding_by_zone)
        for variable, zone_keys in variable_zones.items():
            if zone_keys != expected_zone_keys:
                missing = sorted(expected_zone_keys - zone_keys)
                raise ValueError(
                    f"result_variable_zone_coverage_incomplete:{variable}:{'|'.join(missing)}"
                )
        if not columns:
            raise ValueError("result_expected_columns_missing")
        temperature_variable = (
            TEMPERATURE
            if TEMPERATURE in found
            else MEAN_TEMPERATURE if MEAN_TEMPERATURE in found else None
        )
        for record in reader:
            if not record:
                continue
            timestamp = record[0].strip()
            if not timestamp:
                raise ValueError("result_timestamp_missing")
            raw_values = []
            for index in columns:
                raw_values.append(record[index].strip() if index < len(record) else "")
            if not any(raw_values):
                continue
            if any(not value for value in raw_values):
                raise ValueError(f"result_row_partial_reporting:{timestamp}")
            values: dict[str, dict[str, float]] = {
                zone_key: {} for zone_key in binding_by_zone
            }
            for index, (zone_key, variable) in columns.items():
                try:
                    value = float(record[index])
                except ValueError as exc:
                    raise ValueError(
                        f"result_value_invalid:{timestamp}:{binding_by_zone[zone_key].zone_name}:{variable}"
                    ) from exc
                if not math.isfinite(value):
                    raise ValueError(
                        f"result_value_nonfinite:{timestamp}:{binding_by_zone[zone_key].zone_name}:{variable}"
                    )
                values[zone_key][variable] = value
            timestamps.append(timestamp)
            for zone_key, accumulator in zone_accumulators.items():
                _update_accumulator(
                    accumulator,
                    {zone_key: values[zone_key]},
                    timestamp,
                    minutes_per_step / 60.0,
                    temperature_variable,
                )
                if capture_occupancy and OCCUPANT_COUNT in found:
                    binding = binding_by_zone[zone_key]
                    occupancy[binding.space_name].append(values[zone_key][OCCUPANT_COUNT])
            for category, accumulator in category_accumulators.items():
                selected = {
                    canonical(binding.zone_name): values[canonical(binding.zone_name)]
                    for binding in categories[category]
                }
                _update_accumulator(
                    accumulator,
                    selected,
                    timestamp,
                    minutes_per_step / 60.0,
                    temperature_variable,
                )
            _update_accumulator(
                whole_accumulator,
                values,
                timestamp,
                minutes_per_step / 60.0,
                temperature_variable,
            )

    if not timestamps:
        raise ValueError("result_csv_has_no_data_rows")
    available = tuple(found)
    zone_results = tuple(
        _summary(
            zone_accumulators[canonical(binding.zone_name)],
            scenario_id=scenario_id,
            period_id=period_id,
            grouping="zone",
            category=binding.category,
            available=available,
            unavailable=unavailable,
        )
        for binding in sorted(rows, key=lambda item: canonical(item.space_name))
    )
    category_results = tuple(
        _summary(
            category_accumulators[category],
            scenario_id=scenario_id,
            period_id=period_id,
            grouping="category",
            category=category,
            available=available,
            unavailable=unavailable,
        )
        for category in sorted(category_accumulators)
    )
    whole = _summary(
        whole_accumulator,
        scenario_id=scenario_id,
        period_id=period_id,
        grouping="whole_building",
        category=None,
        available=available,
        unavailable=unavailable,
    )
    additive = (
        "floor_area_m2",
        "design_people",
        "person_hours",
        "people_sensible_kwh",
        "people_latent_kwh",
        "people_radiant_kwh",
        "heating_kwh",
        "cooling_kwh",
        "oa_heating_kwh",
        "oa_cooling_kwh",
        "heating_unmet_zone_hours",
        "cooling_unmet_zone_hours",
    )
    for field in additive:
        expected_value = getattr(whole, field)
        category_values = [getattr(row, field) for row in category_results]
        if expected_value is None:
            if any(value is not None for value in category_values):
                raise ValueError(f"result_reconciliation_availability_mismatch:{field}")
            continue
        actual = math.fsum(float(value or 0.0) for value in category_values)
        if not math.isclose(actual, float(expected_value), rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(f"result_category_reconciliation_failed:{field}")
    return ExtractedRoomResults(
        scenario_id=scenario_id,
        period_id=period_id,
        timestamps=tuple(timestamps),
        zones=zone_results,
        categories=category_results,
        whole_building=whole,
        occupancy_by_space={name: tuple(values) for name, values in occupancy.items()},
    )


def build_run_manifest(
    run: SimulationRun,
    *,
    scenario_id: str,
    period_id: str,
    source_osm_path: Path,
    schedule_path: Path | None,
    idd_path: Path,
    weather_path: Path,
    derived_root: Path,
    minutes_per_output_step: float,
    expected_variables: Sequence[str],
) -> Path:
    """Write a v2 manifest bound to exact inputs, outputs and extraction contract."""

    root = Path(derived_root)
    schedule = Path(schedule_path) if schedule_path is not None else None
    source = Path(source_osm_path)
    guarded = (Path(run.idf_path), Path(run.output_directory)) + (
        (schedule,) if schedule is not None else ()
    )
    for path in guarded:
        if not _within(path, root):
            raise ValueError(f"result_path_outside_derived_root:{path}")
    required_paths = ((source, "source_osm"),) + (
        ((schedule, "schedule"),) if schedule is not None else ()
    )
    for path, label in required_paths:
        assert path is not None
        if not path.is_file():
            raise ValueError(f"result_manifest_{label}_not_found")
    identity = expected_run_identity(
        scenario_id=scenario_id,
        period_id=period_id,
        executable_path=run.executable,
        idd_path=idd_path,
        weather_path=weather_path,
        source_osm_path=source,
        prepared_idf_path=run.idf_path,
        schedule_path=schedule,
        minutes_per_output_step=minutes_per_output_step,
        expected_variables=expected_variables,
    )
    run_hashes = {
        "runtime_sha256": run.runtime_sha256,
        "idd_sha256": run.idd_sha256,
        "weather_sha256": run.weather_sha256,
        "prepared_idf_sha256": run.idf_sha256,
    }
    for field, value in run_hashes.items():
        if identity[field] != value:
            raise ValueError(f"result_manifest_runner_hash_mismatch:{field}")
    status = (
        "PASS"
        if run.return_code == 0
        and not run.timed_out
        and run.severe_count == 0
        and run.fatal_count == 0
        and run.csv_available
        else "FAIL"
    )
    payload = {
        "schema_version": RUN_MANIFEST_SCHEMA,
        "scenario_id": scenario_id,
        "period_id": period_id,
        "status": status,
        "runtime_version": run.runtime_version,
        "runtime_sha256": run.runtime_sha256,
        "idd_sha256": run.idd_sha256,
        "weather_sha256": run.weather_sha256,
        "source_osm_sha256": _sha256(source),
        "derived_idf_sha256": run.idf_sha256,
        "schedule_sha256": _sha256(schedule) if schedule is not None else None,
        "schedule_provenance": (
            "external_schedule_file" if schedule is not None else "source_embedded"
        ),
        "return_code": run.return_code,
        "timed_out": run.timed_out,
        "elapsed_seconds": run.elapsed_seconds,
        "severe_count": run.severe_count,
        "fatal_count": run.fatal_count,
        "csv_available": run.csv_available,
        "rdd_available": run.rdd_available,
        "err_available": run.err_available,
        "input_identity": identity,
    }
    output = Path(run.output_directory)
    output.mkdir(parents=True, exist_ok=True)
    result_files = {
        name: _result_file_record(output / name)
        for name in ("eplusout.csv", "eplusout.err", "eplusout.rdd")
        if (output / name).is_file() and not (output / name).is_symlink()
    }
    payload["result_files"] = result_files
    destination = output / "run_manifest.json"
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if status == "PASS":
        validate_run_manifest(destination, expected_identity=identity)
    return destination


def _patch_run_period_fields(
    destination: Path,
    idd: IDDSchema,
    replacements_by_name: Mapping[str, str],
) -> Path:
    text = destination.read_text(encoding="utf-8")
    document = parse_idf(text)
    run_periods = document.find_objects("RunPeriod")
    definition = idd.get("RunPeriod")
    if len(run_periods) != 1 or definition is None:
        raise ValueError("room_run_period_not_unique")
    positions: dict[str, int] = {}
    for field_name in replacements_by_name:
        matches = tuple(
            field.index
            for field in definition.fields
            if canonical(field.name) == canonical(field_name)
        )
        if len(matches) != 1:
            raise ValueError(f"room_run_period_idd_field_not_unique:{field_name}")
        positions[field_name] = matches[0]
    replacements: list[tuple[int, int, str]] = []
    run_period = run_periods[0]
    for field_name, value in replacements_by_name.items():
        position = positions[field_name]
        if not 1 <= position <= len(run_period.fields):
            raise ValueError(f"room_run_period_field_missing:{field_name}")
        field = run_period.fields[position - 1]
        if text[field.start : field.end] != field.value:
            raise ValueError(f"room_run_period_span_mismatch:{field_name}")
        replacements.append((field.start, field.end, value))
    for start, end, value in sorted(replacements, reverse=True):
        text = text[:start] + value + text[end:]
    destination.write_text(text, encoding="utf-8")
    return destination


def prepare_controlled_day_idf(
    source_path: Path,
    idd: IDDSchema,
    destination_path: Path,
    *,
    output_requests: Sequence[OutputRequest],
    month: int,
    day: int,
    day_of_week: str,
    resolution_minutes: int = 15,
) -> Path:
    """Prepare a day whose explicit weekday cannot be overridden by a source year."""

    destination = prepare_one_day_idf(
        Path(source_path),
        idd,
        Path(destination_path),
        output_requests=output_requests,
        month=month,
        day=day,
        day_of_week=day_of_week,
        resolution_minutes=resolution_minutes,
    )
    return _patch_run_period_fields(
        destination,
        idd,
        {"Begin Year": "", "End Year": ""},
    )


def prepare_annual_idf(
    source_path: Path,
    idd: IDDSchema,
    destination_path: Path,
    *,
    output_requests: Sequence[OutputRequest],
    resolution_minutes: int = 15,
) -> Path:
    """Prepare a 1 Jan–31 Dec weather run without mutating the source IDF."""

    source = Path(source_path)
    destination_path = Path(destination_path)
    source_text = source.read_text(encoding="utf-8")
    source_document = parse_idf(source_text)
    cleaned_text = source_text
    for obj in reversed(source_document.find_objects("Output:Variable")):
        cleaned_text = cleaned_text[: obj.start] + cleaned_text[obj.end :]
    cleaned_source = destination_path.with_name(
        f"{destination_path.stem}.annual-base.idf"
    )
    cleaned_source.parent.mkdir(parents=True, exist_ok=True)
    cleaned_source.write_text(cleaned_text, encoding="utf-8")
    destination = prepare_one_day_idf(
        cleaned_source,
        idd,
        destination_path,
        output_requests=output_requests,
        month=1,
        day=1,
        resolution_minutes=resolution_minutes,
    )
    return _patch_run_period_fields(
        destination,
        idd,
        {"End Month": "12", "End Day of Month": "31"},
    )


__all__ = [
    "ANNUAL_OUTPUT_VARIABLES",
    "RESULT_SCHEMA",
    "RUN_MANIFEST_SCHEMA",
    "SEASONAL_OUTPUT_VARIABLES",
    "ExtractedRoomResults",
    "RoomMetricSummary",
    "SpaceResultBinding",
    "bindings_from_audit",
    "build_run_manifest",
    "expected_run_identity",
    "extract_room_results",
    "ideal_loads_key_to_zone",
    "prepare_annual_idf",
    "prepare_controlled_day_idf",
    "migrate_v1_run_manifest",
    "validate_run_manifest",
    "validate_bindings",
]
