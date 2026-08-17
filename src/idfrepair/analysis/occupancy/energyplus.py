"""EnergyPlus output discovery、受限执行与机制可用性提取。"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
import re
import subprocess
import time
from collections.abc import Iterable, Sequence

from idfrepair.analysis.occupancy.models import (
    MetricRow,
    OutputRequest,
    SimulationRun,
    ZoneServiceMap,
)
from idfrepair.io.idf import canonical
from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import IDDObject, IDDSchema


_OUTPUT_CATALOG: tuple[tuple[str, str], ...] = (
    ("Schedule Value", "schedule"),
    ("People Occupant Count", "occupancy"),
    ("People Total Heating Energy", "people_heat_gain"),
    ("People Sensible Heating Energy", "people_heat_gain"),
    ("People Convective Heating Energy", "people_heat_gain"),
    ("People Radiant Heating Energy", "people_heat_gain"),
    ("People Latent Gain Energy", "people_heat_gain"),
    ("Zone People Occupant Count", "occupancy"),
    ("Zone People Total Heating Energy", "people_heat_gain"),
    ("Zone People Sensible Heating Energy", "people_heat_gain"),
    ("Zone People Radiant Heating Energy", "people_heat_gain"),
    ("Zone People Latent Gain Energy", "people_heat_gain"),
    ("Zone Mean Air Temperature", "zone_state"),
    ("Zone Air Relative Humidity", "zone_state"),
    ("Zone Air System Sensible Heating Energy", "zone_load"),
    ("Zone Air System Sensible Cooling Energy", "zone_load"),
    ("Zone Air System Sensible Heating Rate", "zone_load"),
    ("Zone Air System Sensible Cooling Rate", "zone_load"),
    (
        "Zone Predicted Sensible Load to Heating Setpoint Heat Transfer Rate",
        "zone_load",
    ),
    (
        "Zone Predicted Sensible Load to Cooling Setpoint Heat Transfer Rate",
        "zone_load",
    ),
    ("Zone Ideal Loads Supply Air Total Heating Energy", "ideal_loads"),
    ("Zone Ideal Loads Supply Air Total Cooling Energy", "ideal_loads"),
    ("Zone Ideal Loads Supply Air Total Heating Rate", "ideal_loads"),
    ("Zone Ideal Loads Supply Air Total Cooling Rate", "ideal_loads"),
    ("Zone Ideal Loads Zone Total Heating Energy", "ideal_loads"),
    ("Zone Ideal Loads Zone Total Cooling Energy", "ideal_loads"),
    ("Zone Ideal Loads Zone Total Heating Rate", "ideal_loads"),
    ("Zone Ideal Loads Zone Total Cooling Rate", "ideal_loads"),
    ("Zone Ideal Loads Outdoor Air Total Heating Energy", "outdoor_air"),
    ("Zone Ideal Loads Outdoor Air Total Cooling Energy", "outdoor_air"),
    ("Zone Ideal Loads Outdoor Air Total Heating Rate", "outdoor_air"),
    ("Zone Ideal Loads Outdoor Air Total Cooling Rate", "outdoor_air"),
    ("Zone Ideal Loads Outdoor Air Mass Flow Rate", "outdoor_air"),
    ("Fan Electricity Energy", "fan"),
    ("Pump Electricity Energy", "pump"),
    ("Facility Total HVAC Electricity Demand Rate", "facility_hvac"),
    ("Facility Total Electricity Demand Rate", "facility_energy"),
    ("Air System Outdoor Air Mass Flow Rate", "outdoor_air"),
    (
        "Zone Mechanical Ventilation Standard Density Volume Flow Rate",
        "ventilation",
    ),
    ("Zone Ventilation Standard Density Volume Flow Rate", "ventilation"),
    ("Zone Air CO2 Concentration", "co2"),
    ("Zone Heating Setpoint Not Met Time", "unmet_hours"),
    ("Zone Cooling Setpoint Not Met Time", "unmet_hours"),
)
_MECHANISM_BY_VARIABLE = {
    canonical(name): mechanism for name, mechanism in _OUTPUT_CATALOG
}
_RDD_LINE = re.compile(r"^\s*Output:Variable\s*,", re.IGNORECASE)
_CSV_COLUMN = re.compile(
    r"^(?P<key>.*):(?P<variable>.*?)\s*"
    r"(?:\[(?P<unit>.*?)\])?\((?P<frequency>[^()]*)\)\s*$"
)
_SEVERE = re.compile(r"\*\*\s*Severe\s*\*\*", re.IGNORECASE)
_FATAL = re.compile(r"\*\*\s*Fatal\s*\*\*", re.IGNORECASE)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_output_variables(rdd_text: str) -> frozenset[str]:
    """从 EnergyPlus RDD 的 ``Output:Variable`` 行提取精确变量名。"""

    names: set[str] = set()
    for raw_line in rdd_text.splitlines():
        visible = raw_line.split("!", 1)[0].strip()
        if not _RDD_LINE.match(visible):
            continue
        fields = [field.strip() for field in visible.rstrip(";").split(",")]
        if len(fields) >= 3 and fields[2]:
            names.add(fields[2])
    return frozenset(names)


def select_output_requests(available: Iterable[str]) -> tuple[OutputRequest, ...]:
    """只选择 exact RDD 中存在的 catalog 变量，保持机制顺序稳定。"""

    actual_by_key = {canonical(name): name for name in available if name.strip()}
    requests: list[OutputRequest] = []
    for variable_name, mechanism in _OUTPUT_CATALOG:
        actual = actual_by_key.get(canonical(variable_name))
        if actual is not None:
            requests.append(
                OutputRequest(variable_name=actual, mechanism=mechanism)
            )
    return tuple(requests)


def render_output_requests(requests: Sequence[OutputRequest]) -> str:
    """确定性渲染 EnergyPlus ``Output:Variable`` 对象。"""

    lines = [
        f"Output:Variable,{request.key_value},{request.variable_name},{request.frequency};"
        for request in requests
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def _idd_position(definition: IDDObject, field_name: str) -> int:
    key = canonical(field_name)
    matches = tuple(
        field.index for field in definition.fields if canonical(field.name) == key
    )
    if len(matches) != 1:
        raise ValueError(f"idd_field_not_unique:{definition.name}:{field_name}")
    return matches[0]


def prepare_one_day_idf(
    source_path: Path,
    idd: IDDSchema,
    destination_path: Path,
    *,
    output_requests: Sequence[OutputRequest] = (),
    month: int = 1,
    day: int = 15,
    day_of_week: str | None = None,
    resolution_minutes: int = 15,
) -> Path:
    """从年度 IDF 生成一个 IDD-bound、只写派生件的一日 smoke IDF。"""

    source_path = Path(source_path)
    destination_path = Path(destination_path)
    if not source_path.is_file():
        raise ValueError("one_day_source_idf_not_found")
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("one_day_destination_must_not_equal_source")
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        raise ValueError("one_day_date_invalid")
    valid_days = {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
    if day_of_week is not None and canonical(day_of_week) not in valid_days:
        raise ValueError("one_day_day_of_week_invalid")
    if resolution_minutes <= 0 or 60 % resolution_minutes:
        raise ValueError("resolution_minutes_must_divide_hour")
    source_text = source_path.read_text(encoding="utf-8")
    document = parse_idf(source_text)
    definitions: dict[str, IDDObject] = {}
    for object_type in ("Timestep", "SimulationControl", "RunPeriod"):
        definition = idd.get(object_type)
        if definition is None:
            raise ValueError(f"one_day_object_missing_from_idd:{object_type}")
        definitions[object_type] = definition
    timesteps = document.find_objects("Timestep")
    controls = document.find_objects("SimulationControl")
    run_periods = document.find_objects("RunPeriod")
    if len(timesteps) != 1 or len(controls) != 1 or len(run_periods) != 1:
        raise ValueError("one_day_required_object_not_unique")

    replacements: list[tuple[int, int, str]] = []

    def replace(object_type: str, field_name: str, new_value: str) -> None:
        obj = {
            "Timestep": timesteps[0],
            "SimulationControl": controls[0],
            "RunPeriod": run_periods[0],
        }[object_type]
        position = _idd_position(definitions[object_type], field_name)
        if not 1 <= position <= len(obj.fields):
            raise ValueError(f"one_day_field_missing:{object_type}:{field_name}")
        field = obj.fields[position - 1]
        if source_text[field.start : field.end] != field.value:
            raise ValueError(f"one_day_source_span_mismatch:{object_type}:{field_name}")
        if field.value != new_value:
            replacements.append((field.start, field.end, new_value))

    replace("Timestep", "Number of Timesteps per Hour", str(60 // resolution_minutes))
    replace("SimulationControl", "Do Zone Sizing Calculation", "No")
    replace("SimulationControl", "Run Simulation for Sizing Periods", "No")
    replace("SimulationControl", "Run Simulation for Weather File Run Periods", "Yes")
    replace("RunPeriod", "Begin Month", str(month))
    replace("RunPeriod", "Begin Day of Month", str(day))
    replace("RunPeriod", "End Month", str(month))
    replace("RunPeriod", "End Day of Month", str(day))
    if day_of_week is not None:
        replace("RunPeriod", "Day of Week for Start Day", day_of_week.strip().title())
    derived = source_text
    for start, end, new_value in sorted(replacements, reverse=True):
        derived = derived[:start] + new_value + derived[end:]

    existing_variables = {
        canonical(obj.fields[1].value)
        for obj in document.find_objects("Output:Variable")
        if len(obj.fields) >= 2
    }
    missing_requests = tuple(
        request
        for request in output_requests
        if canonical(request.variable_name) not in existing_variables
    )
    additions = render_output_requests(missing_requests).rstrip()
    if not document.find_objects("Output:VariableDictionary"):
        additions = (additions + "\n" if additions else "") + (
            "Output:VariableDictionary,IDF,Unsorted;"
        )
    if additions:
        derived = derived.rstrip() + "\n\n" + additions + "\n"
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(derived, encoding="utf-8")
    return destination_path


def _runtime_version(executable: Path) -> str:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    text = (result.stdout or result.stderr).strip()
    if not text:
        return "unavailable"
    return text.splitlines()[0].split(", YMD=", 1)[0]


def run_energyplus(
    *,
    executable: Path,
    idf_path: Path,
    output_directory: Path,
    idd_path: Path | None = None,
    weather_path: Path | None = None,
    timeout_seconds: int = 1800,
) -> SimulationRun:
    """在新派生目录中有界运行 EnergyPlus，并记录失败而非隐藏它。"""

    executable = Path(executable).resolve()
    idf_path = Path(idf_path).resolve()
    output_directory = Path(output_directory).resolve()
    idd_path = Path(idd_path).resolve() if idd_path is not None else None
    weather_path = Path(weather_path).resolve() if weather_path is not None else None
    if not executable.is_file():
        raise ValueError("energyplus_executable_not_found")
    if not idf_path.is_file():
        raise ValueError("energyplus_idf_not_found")
    if idd_path is not None and not idd_path.is_file():
        raise ValueError("energyplus_idd_not_found")
    if weather_path is not None and not weather_path.is_file():
        raise ValueError("energyplus_weather_not_found")
    if output_directory == idf_path or output_directory == executable:
        raise ValueError("energyplus_output_must_be_derived_directory")
    if output_directory.exists() and any(output_directory.iterdir()):
        raise ValueError("energyplus_output_directory_must_be_empty")
    output_directory.mkdir(parents=True, exist_ok=True)

    command = [str(executable), "-d", str(output_directory), "-r"]
    if weather_path is not None:
        command.extend(["-w", str(weather_path)])
    command.append(str(idf_path))
    started = time.monotonic()
    return_code: int | None
    timed_out = False
    stdout = ""
    stderr = ""
    try:
        result = subprocess.run(
            command,
            cwd=idf_path.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired as exc:
        return_code = None
        timed_out = True
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    elapsed = time.monotonic() - started
    (output_directory / "runner.stdout.log").write_text(stdout, encoding="utf-8")
    (output_directory / "runner.stderr.log").write_text(stderr, encoding="utf-8")

    err_path = output_directory / "eplusout.err"
    err_text = err_path.read_text(encoding="utf-8", errors="replace") if err_path.is_file() else ""
    return SimulationRun(
        executable=executable,
        runtime_version=_runtime_version(executable),
        runtime_sha256=_file_sha256(executable),
        idf_path=idf_path,
        idf_sha256=_file_sha256(idf_path),
        idd_sha256=_file_sha256(idd_path) if idd_path is not None else None,
        weather_sha256=(
            _file_sha256(weather_path) if weather_path is not None else None
        ),
        output_directory=output_directory,
        return_code=return_code,
        timed_out=timed_out,
        elapsed_seconds=elapsed,
        severe_count=len(_SEVERE.findall(err_text)),
        fatal_count=len(_FATAL.findall(err_text)),
        csv_available=(output_directory / "eplusout.csv").is_file(),
        rdd_available=(output_directory / "eplusout.rdd").is_file(),
        err_available=err_path.is_file(),
    )


def _allowed_keys(mapping: ZoneServiceMap) -> set[str]:
    names = set(mapping.people_to_zones)
    names.update(zone for zones in mapping.people_to_zones.values() for zone in zones)
    for equipment in mapping.zone_to_hvac.values():
        for value in equipment:
            names.add(value.split(" / ", 1)[-1])
    names.update({"*", "environment", "facility"})
    return {canonical(name) for name in names}


def _key_is_allowed(key_name: str, mapping: ZoneServiceMap, allowed: set[str]) -> bool:
    """接受原始 key，也接受 EnergyPlus 展开后 ``Zone + People`` 的 key。"""

    key = canonical(key_name)
    if key in allowed:
        return True
    return any(
        key.endswith(f" {canonical(people_name)}")
        for people_name in mapping.people_to_zones
        if canonical(people_name)
    )


def extract_metrics(
    csv_path: Path,
    mapping: ZoneServiceMap,
    *,
    expected_variable_names: Sequence[str] | None = None,
) -> tuple[MetricRow, ...]:
    """提取映射内 CSV 时步，并为完全缺失的预期变量添加 unavailable 行。"""

    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise ValueError("energyplus_csv_not_found")
    expected = tuple(
        expected_variable_names
        if expected_variable_names is not None
        else (name for name, _mechanism in _OUTPUT_CATALOG)
    )
    expected_by_key = {canonical(name): name for name in expected}
    allowed_keys = _allowed_keys(mapping)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("energyplus_csv_empty") from exc
        columns: dict[int, tuple[str, str, str | None, str | None]] = {}
        found_variables: set[str] = set()
        for index, raw in enumerate(header[1:], start=1):
            match = _CSV_COLUMN.match(raw.strip())
            if match is None:
                continue
            key_name = match.group("key").strip()
            variable_name = match.group("variable").strip()
            variable_key = canonical(variable_name)
            if variable_key not in expected_by_key:
                continue
            if allowed_keys and not _key_is_allowed(key_name, mapping, allowed_keys):
                continue
            unit = (match.group("unit") or "").strip() or None
            frequency = (match.group("frequency") or "").strip() or None
            columns[index] = (key_name, expected_by_key[variable_key], unit, frequency)
            found_variables.add(variable_key)

        rows: list[MetricRow] = []
        for record in reader:
            if not record:
                continue
            timestamp = record[0].strip() if record else ""
            for index, (key_name, variable_name, unit, frequency) in columns.items():
                raw_value = record[index].strip() if index < len(record) else ""
                try:
                    value = float(raw_value)
                except ValueError:
                    value = None
                valid = value is not None and math.isfinite(value)
                rows.append(
                    MetricRow(
                        timestamp=timestamp or None,
                        key_name=key_name,
                        variable_name=variable_name,
                        unit=unit,
                        frequency=frequency,
                        mechanism=_MECHANISM_BY_VARIABLE.get(
                            canonical(variable_name), "other"
                        ),
                        availability="available" if valid else "invalid",
                        value=value if valid else None,
                    )
                )
    for variable_name in expected:
        if canonical(variable_name) in found_variables:
            continue
        rows.append(
            MetricRow(
                timestamp=None,
                key_name=None,
                variable_name=variable_name,
                unit=None,
                frequency=None,
                mechanism=_MECHANISM_BY_VARIABLE.get(
                    canonical(variable_name), "other"
                ),
                availability="unavailable",
                value=None,
            )
        )
    return tuple(rows)


__all__ = [
    "discover_output_variables",
    "extract_metrics",
    "prepare_one_day_idf",
    "render_output_requests",
    "run_energyplus",
    "select_output_requests",
]
