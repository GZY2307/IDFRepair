"""把受控 occupancy profile 编译为只写派生件的 IDF/CSV。

编译器按 IDD 字段名定位 People schedule，并在替换前验证 object/field/span
身份。源 IDF 永不写入；派生文件名与内容只由输入内容和场景决定。
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from idfrepair.analysis.occupancy.extract import extract_people
from idfrepair.analysis.occupancy.models import (
    CompiledScenario,
    FieldModification,
    OccupancyScenario,
)
from idfrepair.analysis.occupancy.scenarios import person_hours
from idfrepair.io.idf import canonical, parse_idf
from idfrepair.knowledge.idd import IDDSchema


_PEOPLE_SCHEDULE_FIELD = "Number of People Schedule Name"
_STEPS_PER_DAY = 96


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _scenario_digest(scenario: OccupancyScenario) -> str:
    """构造不依赖输出路径或 dict 插入顺序的场景 digest。"""

    payload = {
        "name": scenario.name,
        "kind": scenario.kind,
        "minutes_per_step": f"{scenario.minutes_per_step:.12f}",
        "conserves_passenger_hours": scenario.conserves_passenger_hours,
        "reference_person_hours": (
            None
            if scenario.reference_person_hours is None
            else f"{scenario.reference_person_hours:.12f}"
        ),
        "profiles": {
            name: [f"{float(value):.12f}" for value in scenario.profiles[name]]
            for name in sorted(scenario.profiles, key=canonical)
        },
        "design_people": {
            name: f"{float(scenario.design_people[name]):.12f}"
            for name in sorted(scenario.design_people, key=canonical)
        },
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256(encoded)


def _validate_scenario(
    scenario: OccupancyScenario,
    people_names: tuple[str, ...],
) -> tuple[tuple[float, ...], ...]:
    """验证精确 People coverage、96 点 profiles 与守恒声明。"""

    if not scenario.name.strip():
        raise ValueError("scenario_name_missing")
    if not scenario.kind.strip():
        raise ValueError("scenario_kind_missing")
    if not math.isfinite(scenario.minutes_per_step) or scenario.minutes_per_step <= 0:
        raise ValueError("scenario_minutes_per_step_must_be_positive")

    profile_by_key = {canonical(name): values for name, values in scenario.profiles.items()}
    design_by_key = {
        canonical(name): float(value) for name, value in scenario.design_people.items()
    }
    if len(profile_by_key) != len(scenario.profiles):
        raise ValueError("scenario_profile_name_collision")
    if len(design_by_key) != len(scenario.design_people):
        raise ValueError("scenario_design_people_name_collision")

    ordered: list[tuple[float, ...]] = []
    total_person_hours = 0.0
    for name in people_names:
        key = canonical(name)
        if key not in profile_by_key:
            raise ValueError(f"scenario_profile_missing:{name}")
        if key not in design_by_key:
            raise ValueError(f"scenario_design_people_missing:{name}")
        values = tuple(float(value) for value in profile_by_key[key])
        if len(values) != _STEPS_PER_DAY:
            raise ValueError(f"scenario_profile_must_have_96_steps:{name}")
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError(f"scenario_profile_invalid:{name}")
        ordered.append(values)
        total_person_hours += person_hours(
            values,
            design_by_key[key],
            minutes_per_step=scenario.minutes_per_step,
        )

    supplied_keys = set(profile_by_key)
    expected_keys = {canonical(name) for name in people_names}
    extra = sorted(supplied_keys - expected_keys)
    if extra:
        raise ValueError(f"scenario_profile_unknown:{'|'.join(extra)}")
    if scenario.conserves_passenger_hours:
        reference = scenario.reference_person_hours
        if reference is None or not math.isfinite(reference) or reference < 0.0:
            raise ValueError("scenario_reference_person_hours_invalid")
        if not math.isclose(
            total_person_hours,
            reference,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "passenger_hours_conservation_failed:"
                f"{total_person_hours:.12f}:{reference:.12f}"
            )
    return tuple(ordered)


def _schedule_object(
    *,
    schedule_name: str,
    csv_name: str,
    column: int,
    minutes_per_step: float,
) -> str:
    """渲染一个使用相对 CSV 路径的 EnergyPlus Schedule:File。"""

    minutes = int(minutes_per_step)
    if float(minutes) != minutes_per_step:
        raise ValueError("schedule_file_requires_integer_minutes_per_step")
    return (
        "Schedule:File,\n"
        f"  {schedule_name},\n"
        "  ,\n"
        f"  {csv_name},\n"
        f"  {column},\n"
        "  0,\n"
        "  8760,\n"
        "  Comma,\n"
        "  No,\n"
        f"  {minutes};"
    )


def compile_scenario(
    source_path: Path,
    idd: IDDSchema,
    scenario: OccupancyScenario,
    output_directory: Path,
) -> CompiledScenario:
    """编译场景到派生目录，并返回 hashes、守恒量与精确修改 provenance。"""

    source = Path(source_path)
    destination = Path(output_directory)
    if not source.is_file():
        raise ValueError(f"source_idf_not_found:{source}")
    if source.resolve() == destination.resolve():
        raise ValueError("output_directory_must_not_equal_source")
    source_bytes = source.read_bytes()
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("source_idf_must_be_utf8") from exc
    document = parse_idf(source_text)
    records = extract_people(document, idd)
    if not records:
        raise ValueError("source_idf_has_no_people")
    people_names = tuple(record.name for record in records)
    if len({canonical(name) for name in people_names}) != len(people_names):
        raise ValueError("source_people_names_not_unique")

    validated_profiles = _validate_scenario(scenario, people_names)
    # Schedule CSV is the executable evidence, so all reported conservation
    # metrics are calculated from the exact 12-decimal values written to it.
    profiles = tuple(
        tuple(float(f"{value:.12f}") for value in profile)
        for profile in validated_profiles
    )
    design_lookup = {
        canonical(name): float(value)
        for name, value in scenario.design_people.items()
    }
    emitted_person_hours = math.fsum(
        person_hours(
            profile,
            design_lookup[canonical(name)],
            minutes_per_step=scenario.minutes_per_step,
        )
        for name, profile in zip(people_names, profiles)
    )
    if scenario.conserves_passenger_hours and not math.isclose(
        emitted_person_hours,
        float(scenario.reference_person_hours),
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise ValueError("emitted_passenger_hours_conservation_failed")
    digest = _scenario_digest(scenario)
    csv_name = f"occupancy-{digest[:16]}.csv"
    idf_name = f"occupancy-{digest[:16]}.idf"
    schedule_names = tuple(
        f"IDFRepair_OCC_{digest[:12]}_{ordinal:03d}"
        for ordinal in range(1, len(records) + 1)
    )

    replacements: list[tuple[int, int, str]] = []
    modifications: list[FieldModification] = []
    for record, new_schedule in zip(records, schedule_names):
        if not record.name or not record.number_schedule_name:
            raise ValueError(f"people_schedule_provenance_incomplete:{record.record_id}")
        if not 0 <= record.source_object_index < len(document.objects):
            raise ValueError(f"people_object_index_invalid:{record.record_id}")
        obj = document.objects[record.source_object_index]
        if canonical(obj.object_type) != "people" or canonical(obj.name) != canonical(record.name):
            raise ValueError(f"people_object_identity_mismatch:{record.record_id}")
        position = record.number_schedule_field_index
        if not 1 <= position <= len(obj.fields):
            raise ValueError(f"people_schedule_field_missing:{record.record_id}")
        field = obj.fields[position - 1]
        visible = source_text[field.start : field.end]
        if visible != field.value or field.value.strip() != record.number_schedule_name:
            raise ValueError(f"people_schedule_span_mismatch:{record.record_id}")
        replacements.append((field.start, field.end, new_schedule))
        modifications.append(
            FieldModification(
                object_index=obj.index,
                object_type=obj.object_type,
                object_name=obj.name,
                field_index=position,
                field_name=_PEOPLE_SCHEDULE_FIELD,
                old_value=record.number_schedule_name,
                new_value=new_schedule,
                source_start=field.start,
                source_end=field.end,
            )
        )

    derived_text = source_text
    for start, end, new_value in sorted(replacements, reverse=True):
        derived_text = derived_text[:start] + new_value + derived_text[end:]
    objects = tuple(
        _schedule_object(
            schedule_name=name,
            csv_name=csv_name,
            column=column,
            minutes_per_step=scenario.minutes_per_step,
        )
        for column, name in enumerate(schedule_names, start=1)
    )
    derived_text = derived_text.rstrip() + "\n\n" + "\n\n".join(objects) + "\n"
    csv_text = "\n".join(
        ",".join(
            f"{profile[index % _STEPS_PER_DAY]:.12f}" for profile in profiles
        )
        for index in range(365 * _STEPS_PER_DAY)
    ) + "\n"
    derived_bytes = derived_text.encode("utf-8")
    csv_bytes = csv_text.encode("ascii")

    destination.mkdir(parents=True, exist_ok=True)
    idf_path = destination / idf_name
    schedule_path = destination / csv_name
    idf_path.write_bytes(derived_bytes)
    schedule_path.write_bytes(csv_bytes)
    return CompiledScenario(
        scenario_name=scenario.name,
        scenario_digest=digest,
        source_sha256=_sha256(source_bytes),
        idf_path=idf_path,
        idf_sha256=_sha256(derived_bytes),
        schedule_path=schedule_path,
        schedule_sha256=_sha256(csv_bytes),
        passenger_hours=emitted_person_hours,
        modified_fields=tuple(modifications),
    )


__all__ = ["compile_scenario"]
