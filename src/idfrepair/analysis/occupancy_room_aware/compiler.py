"""People-only manifest 与 room-aware Schedule:File 编译器。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from idfrepair.analysis.occupancy.extract import extract_people
from idfrepair.analysis.occupancy_room_aware.evidence import (
    parameter_evidence_records,
)
from idfrepair.io.idf import canonical, parse_idf
from idfrepair.knowledge.idd import IDDSchema


PEOPLE_MANIFEST_SCHEMA = "idfrepair.room-aware-people-manifest.v1"
COMPILE_MANIFEST_SCHEMA = "idfrepair.room-aware-compiled-scenario.v1"
STEPS_PER_DAY = 96


@dataclass(frozen=True, slots=True)
class RoomAwareScenario:
    """按 source Space 绑定的一个 15 分钟受控场景。"""

    scenario_id: str
    scenario_kind: str
    profiles_by_space: Mapping[str, tuple[float, ...]]
    design_people_by_space: Mapping[str, float]
    minutes_per_step: int = 15
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ScheduleBinding:
    """People→去重 profile column 的精确绑定。"""

    space_name: str
    people_name: str
    profile_digest: str
    schedule_name: str
    column_number: int


@dataclass(frozen=True, slots=True)
class CompiledRoomScenario:
    """一个确定性 IDF/Schedule:File 派生件及其身份。"""

    scenario_id: str
    scenario_kind: str
    scenario_digest: str
    source_sha256: str
    idf_path: Path
    idf_sha256: str
    schedule_path: Path
    schedule_sha256: str
    manifest_path: Path
    manifest_sha256: str
    people_count: int
    unique_profile_count: int
    daily_person_hours: float
    schedule_bindings: tuple[ScheduleBinding, ...]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _ensure_within(path: Path, root: Path) -> None:
    resolved = path.resolve()
    allowed = root.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise ValueError(f"output_outside_allowed_root:{resolved}")


def build_people_manifest(
    audit: Mapping[str, Any],
    *,
    scenario_id: str,
) -> dict[str, Any]:
    """把审计事实和 density evidence 合成逐 Space People-only manifest。"""

    source_sha = str(audit.get("source_sha256_after", ""))
    if len(source_sha) != 64:
        raise ValueError("audit_source_sha256_invalid")
    if not scenario_id.strip():
        raise ValueError("manifest_scenario_id_missing")
    density_evidence = {
        row.category: row
        for row in parameter_evidence_records()
        if row.parameter == "design_density_m2_per_person"
    }
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for row in audit.get("spaces", []):
        name = str(row.get("source_space_name", ""))
        if not name or canonical(name) in names:
            raise ValueError(f"audit_space_identity_invalid:{name}")
        names.add(canonical(name))
        category = str(row.get("room_category", ""))
        if category not in density_evidence:
            raise ValueError(f"density_evidence_missing:{category}")
        sources = row.get("people_sources", [])
        if not isinstance(sources, list) or len(sources) != 1:
            raise ValueError(f"effective_people_source_not_unique:{name}")
        source = sources[0]
        definition = source.get("definition", {})
        source_people = float(row.get("design_people") or 0.0)
        area = float(row.get("floor_area_m2") or 0.0)
        conflict = row.get("metadata_status") == "SOURCE_METADATA_CONFLICT"
        evidence = density_evidence[category]
        if conflict:
            target_people = source_people
            evidence_id = "SOURCE_METADATA_CONFLICT_PRESERVE"
        elif evidence.value is None:
            target_people = source_people
            evidence_id = evidence.parameter_id
        else:
            if area < 0:
                raise ValueError(f"space_floor_area_invalid:{name}")
            target_people = area / evidence.value
            evidence_id = evidence.parameter_id
        result.append(
            {
                "source_space_name": name,
                "room_category": category,
                "target_design_people": target_people,
                "source_design_people": source_people,
                "metadata_status": row.get("metadata_status"),
                "preserve_source_people_parameters": conflict,
                "fraction_radiant": definition.get("fraction_radiant"),
                "sensible_heat_fraction": definition.get("sensible_heat_fraction"),
                "co2_generation_rate_m3_s_person": definition.get(
                    "co2_generation_rate_m3_s_person"
                ),
                "activity_schedule": source.get("activity_schedule"),
                "source_count_schedule": source.get("count_schedule"),
                "source_people_definition": definition.get("name"),
                "count_evidence_id": evidence_id,
            }
        )
    return {
        "schema_version": PEOPLE_MANIFEST_SCHEMA,
        "scenario_id": scenario_id,
        "source_alias": "Terminal Model A",
        "source_sha256": source_sha,
        "space_count": len(result),
        "spaces": result,
    }


def _profile_digest(profile: Sequence[float]) -> str:
    encoded = json.dumps(
        [f"{float(value):.12f}" for value in profile],
        separators=(",", ":"),
    ).encode("ascii")
    return _sha256(encoded)


def _scenario_digest(scenario: RoomAwareScenario) -> str:
    payload = {
        "scenario_id": scenario.scenario_id,
        "scenario_kind": scenario.scenario_kind,
        "minutes_per_step": scenario.minutes_per_step,
        "profiles": {
            name: [f"{float(value):.12f}" for value in scenario.profiles_by_space[name]]
            for name in sorted(scenario.profiles_by_space, key=canonical)
        },
        "design_people": {
            name: f"{float(scenario.design_people_by_space[name]):.12f}"
            for name in sorted(scenario.design_people_by_space, key=canonical)
        },
        "metadata": scenario.metadata or {},
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256(encoded)


def _schedule_object(
    schedule_name: str,
    csv_name: str,
    column_number: int,
    minutes_per_step: int,
) -> str:
    return (
        "Schedule:File,\n"
        f"  {schedule_name},\n"
        "  ,\n"
        f"  {csv_name},\n"
        f"  {column_number},\n"
        "  0,\n"
        "  8760,\n"
        "  Comma,\n"
        "  No,\n"
        f"  {minutes_per_step};"
    )


def _output_object(variable_name: str) -> str:
    return (
        "Output:Variable,\n"
        "  *,\n"
        f"  {variable_name},\n"
        "  Timestep;"
    )


def compile_room_scenario(
    source_path: Path,
    idd: IDDSchema,
    scenario: RoomAwareScenario,
    output_directory: Path,
    *,
    allowed_root: Path,
    output_variables: Sequence[str] = (),
) -> CompiledRoomScenario:
    """替换逐 Space People schedule，并按唯一 profile 写全年 CSV。"""

    source = Path(source_path)
    destination = Path(output_directory)
    _ensure_within(destination, Path(allowed_root))
    if not source.is_file():
        raise ValueError(f"source_idf_not_found:{source}")
    if source.resolve() == destination.resolve():
        raise ValueError("output_directory_must_not_equal_source")
    if not scenario.scenario_id.strip() or not scenario.scenario_kind.strip():
        raise ValueError("scenario_identity_missing")
    if scenario.minutes_per_step != 15:
        raise ValueError("room_aware_schedule_requires_15_minutes")

    source_bytes = source.read_bytes()
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("source_idf_must_be_utf8") from exc
    document = parse_idf(source_text)
    people = extract_people(document, idd)
    if not people:
        raise ValueError("source_idf_has_no_people")
    space_names = tuple(record.target_name for record in people)
    if len({canonical(name) for name in space_names}) != len(space_names):
        raise ValueError("people_space_target_not_unique")
    if len({canonical(record.name) for record in people}) != len(people):
        raise ValueError("people_name_not_unique")

    profiles = {
        canonical(name): tuple(float(value) for value in values)
        for name, values in scenario.profiles_by_space.items()
    }
    designs = {
        canonical(name): float(value)
        for name, value in scenario.design_people_by_space.items()
    }
    if len(profiles) != len(scenario.profiles_by_space):
        raise ValueError("scenario_space_profile_name_collision")
    if len(designs) != len(scenario.design_people_by_space):
        raise ValueError("scenario_space_design_name_collision")
    expected = {canonical(name): name for name in space_names}
    for key, display in expected.items():
        if key not in profiles:
            raise ValueError(f"scenario_space_profile_missing:{display}")
        if key not in designs:
            raise ValueError(f"scenario_space_design_missing:{display}")
    extra = sorted(set(profiles) - set(expected))
    if extra:
        original_names = {
            canonical(name): name for name in scenario.profiles_by_space
        }
        raise ValueError(
            "scenario_space_profile_unknown:"
            + "|".join(original_names[key] for key in extra)
        )
    extra_design = sorted(set(designs) - set(expected))
    if extra_design:
        raise ValueError("scenario_space_design_unknown:" + "|".join(extra_design))

    normalized: dict[str, tuple[float, ...]] = {}
    for key, values in profiles.items():
        if len(values) != STEPS_PER_DAY:
            raise ValueError(f"scenario_profile_length_invalid:{expected[key]}")
        rounded = tuple(float(f"{value:.12f}") for value in values)
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in rounded):
            raise ValueError(f"scenario_profile_value_invalid:{expected[key]}")
        if not math.isfinite(designs[key]) or designs[key] < 0:
            raise ValueError(f"scenario_design_people_invalid:{expected[key]}")
        normalized[key] = rounded

    unique_profiles: dict[str, tuple[float, ...]] = {}
    digest_by_space: dict[str, str] = {}
    for key, profile in normalized.items():
        digest = _profile_digest(profile)
        if digest in unique_profiles and unique_profiles[digest] != profile:
            raise ValueError("profile_digest_collision")
        unique_profiles[digest] = profile
        digest_by_space[key] = digest
    ordered_digests = tuple(sorted(unique_profiles))
    column_by_digest = {
        digest: index for index, digest in enumerate(ordered_digests, start=1)
    }
    schedule_by_digest = {
        digest: f"IDFRepair_RA_{digest[:16]}" for digest in ordered_digests
    }
    scenario_digest = _scenario_digest(scenario)
    csv_name = f"room-aware-{scenario_digest[:16]}.csv"
    idf_name = f"room-aware-{scenario_digest[:16]}.idf"

    replacements: list[tuple[int, int, str]] = []
    bindings: list[ScheduleBinding] = []
    for record in people:
        key = canonical(record.target_name)
        if canonical(record.calculation_method) != canonical("People"):
            raise ValueError(f"people_not_explicit_count:{record.name}")
        actual_design = record.number_of_people
        if actual_design is None or not math.isclose(
            actual_design, designs[key], rel_tol=1e-8, abs_tol=1e-8
        ):
            raise ValueError(f"people_design_count_mismatch:{record.name}")
        obj = document.objects[record.source_object_index]
        position = record.number_schedule_field_index
        if canonical(obj.object_type) != "people" or canonical(obj.name) != canonical(
            record.name
        ):
            raise ValueError(f"people_object_identity_mismatch:{record.name}")
        if not 1 <= position <= len(obj.fields):
            raise ValueError(f"people_schedule_field_missing:{record.name}")
        field = obj.fields[position - 1]
        if source_text[field.start : field.end] != field.value:
            raise ValueError(f"people_schedule_span_mismatch:{record.name}")
        digest = digest_by_space[key]
        schedule_name = schedule_by_digest[digest]
        replacements.append((field.start, field.end, schedule_name))
        bindings.append(
            ScheduleBinding(
                space_name=record.target_name,
                people_name=record.name,
                profile_digest=digest,
                schedule_name=schedule_name,
                column_number=column_by_digest[digest],
            )
        )

    derived_text = source_text
    for start, end, value in sorted(replacements, reverse=True):
        derived_text = derived_text[:start] + value + derived_text[end:]
    schedule_objects = [
        _schedule_object(
            schedule_by_digest[digest],
            csv_name,
            column_by_digest[digest],
            scenario.minutes_per_step,
        )
        for digest in ordered_digests
    ]
    requested_variables = tuple(
        dict.fromkeys(name.strip() for name in output_variables if name.strip())
    )
    output_objects = [_output_object(name) for name in requested_variables]
    additions = schedule_objects + output_objects
    if additions:
        derived_text = derived_text.rstrip() + "\n\n" + "\n\n".join(additions) + "\n"

    csv_lines = []
    for index in range(365 * STEPS_PER_DAY):
        csv_lines.append(
            ",".join(
                f"{unique_profiles[digest][index % STEPS_PER_DAY]:.12f}"
                for digest in ordered_digests
            )
        )
    csv_bytes = ("\n".join(csv_lines) + "\n").encode("ascii")
    idf_bytes = derived_text.encode("utf-8")
    daily_person_hours = math.fsum(
        sum(normalized[key]) * designs[key] * scenario.minutes_per_step / 60.0
        for key in sorted(expected)
    )
    manifest_payload = {
        "schema_version": COMPILE_MANIFEST_SCHEMA,
        "scenario_id": scenario.scenario_id,
        "scenario_kind": scenario.scenario_kind,
        "scenario_digest": scenario_digest,
        "source_sha256": _sha256(source_bytes),
        "idf_sha256": _sha256(idf_bytes),
        "schedule_sha256": _sha256(csv_bytes),
        "people_count": len(people),
        "unique_profile_count": len(ordered_digests),
        "minutes_per_step": scenario.minutes_per_step,
        "schedule_rows": 365 * STEPS_PER_DAY,
        "daily_person_hours": daily_person_hours,
        "output_variables": list(requested_variables),
        "schedule_bindings": [asdict(binding) for binding in bindings],
        "metadata": scenario.metadata or {},
    }
    manifest_bytes = (
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    destination.mkdir(parents=True, exist_ok=True)
    idf_path = destination / idf_name
    schedule_path = destination / csv_name
    manifest_path = destination / "compile_manifest.json"
    idf_path.write_bytes(idf_bytes)
    schedule_path.write_bytes(csv_bytes)
    manifest_path.write_bytes(manifest_bytes)
    return CompiledRoomScenario(
        scenario_id=scenario.scenario_id,
        scenario_kind=scenario.scenario_kind,
        scenario_digest=scenario_digest,
        source_sha256=_sha256(source_bytes),
        idf_path=idf_path,
        idf_sha256=_sha256(idf_bytes),
        schedule_path=schedule_path,
        schedule_sha256=_sha256(csv_bytes),
        manifest_path=manifest_path,
        manifest_sha256=_sha256(manifest_bytes),
        people_count=len(people),
        unique_profile_count=len(ordered_digests),
        daily_person_hours=daily_person_hours,
        schedule_bindings=tuple(bindings),
    )


__all__ = [
    "COMPILE_MANIFEST_SCHEMA",
    "PEOPLE_MANIFEST_SCHEMA",
    "CompiledRoomScenario",
    "RoomAwareScenario",
    "ScheduleBinding",
    "build_people_manifest",
    "compile_room_scenario",
]
