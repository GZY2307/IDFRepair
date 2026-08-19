"""EnergyPlus dictionary discovery and SQLite extraction for Airport ABM V3."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import math
from pathlib import Path
import re
import sqlite3
from typing import Iterable

from idfrepair.io.idf import canonical, parse_idf
from idfrepair.knowledge.idd import IDDSchema

from .source import SourceSpace


class OutputContractError(ValueError):
    """Raised when EnergyPlus does not expose a pre-registered output."""


ANNUAL_VARIABLES = frozenset(
    {
        "Facility Total HVAC Electricity Demand Rate",
        "Facility Heating Setpoint Not Met While Occupied Time",
        "Facility Cooling Setpoint Not Met While Occupied Time",
        "Air System Outdoor Air Mass Flow Rate",
        "Air System Fan Electricity Energy",
        "Air System Total Heating Energy",
        "Air System Total Cooling Energy",
    }
)


def _idd_field_position(idd: IDDSchema, object_type: str, field_name: str) -> int:
    definition = idd.get(object_type)
    if definition is None:
        raise OutputContractError(f"EnergyPlus definition missing: {object_type}")
    positions = tuple(
        field.index
        for field in definition.fields
        if canonical(field.name) == canonical(field_name)
    )
    if len(positions) != 1:
        raise OutputContractError(
            f"EnergyPlus field is not unique: {object_type}:{field_name}"
        )
    return positions[0]


def prepare_weather_run_idf(
    source_path: str | Path,
    destination_path: str | Path,
    *,
    idd: IDDSchema,
    begin_month: int,
    begin_day: int,
    begin_year: int,
    end_month: int,
    end_day: int,
    end_year: int,
    day_of_week: str,
    variables: Iterable[str],
    meters: Iterable[str],
    reporting_frequency: str = "Timestep",
    resolution_minutes: int = 15,
    fixed_sizing_operation: bool = False,
) -> Path:
    """Prepare a source-immutable weather-period derivative with a strict output set."""

    source = Path(source_path)
    destination = Path(destination_path)
    if not source.is_file():
        raise OutputContractError(f"source IDF not found: {source}")
    if source.resolve() == destination.resolve():
        raise OutputContractError("weather-period IDF must not replace its source")
    if resolution_minutes <= 0 or 60 % resolution_minutes:
        raise OutputContractError("resolution must divide one hour")
    frequency = reporting_frequency.strip().title()
    if frequency not in {"Timestep", "Hourly", "Daily", "Runperiod"}:
        raise OutputContractError("unsupported reporting frequency")
    if frequency == "Runperiod":
        frequency = "RunPeriod"
    try:
        begin = date(begin_year, begin_month, begin_day)
        end = date(end_year, end_month, end_day)
    except ValueError as exc:
        raise OutputContractError("weather-period date is invalid") from exc
    if end < begin:
        raise OutputContractError("weather-period end precedes begin")
    weekdays = {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
    if day_of_week.strip().casefold() not in weekdays:
        raise OutputContractError("weather-period weekday is invalid")

    source_bytes = source.read_bytes()
    text = source_bytes.decode("utf-8")
    document = parse_idf(text)
    if document.issues:
        raise OutputContractError("source IDF cannot be prepared safely")
    timesteps = document.find_objects("Timestep")
    controls = document.find_objects("SimulationControl")
    periods = document.find_objects("RunPeriod")
    if len(timesteps) != 1 or len(controls) != 1 or len(periods) != 1:
        raise OutputContractError("weather-period control objects are not unique")

    objects = {
        "Timestep": timesteps[0],
        "SimulationControl": controls[0],
        "RunPeriod": periods[0],
    }
    edits: list[tuple[int, int, str]] = []

    def replace(object_type: str, field_name: str, value: str) -> None:
        position = _idd_field_position(idd, object_type, field_name)
        obj = objects[object_type]
        if not 1 <= position <= len(obj.fields):
            raise OutputContractError(
                f"weather-period field missing: {object_type}:{field_name}"
            )
        field = obj.fields[position - 1]
        if text[field.start : field.end] != field.value:
            raise OutputContractError(
                f"weather-period source span mismatch: {object_type}:{field_name}"
            )
        if field.value != value:
            edits.append((field.start, field.end, value))

    replace("Timestep", "Number of Timesteps per Hour", str(60 // resolution_minutes))
    sizing_value = "No" if fixed_sizing_operation else "Yes"
    replace("SimulationControl", "Do Zone Sizing Calculation", sizing_value)
    replace("SimulationControl", "Do System Sizing Calculation", sizing_value)
    replace("SimulationControl", "Do Plant Sizing Calculation", sizing_value)
    replace("SimulationControl", "Run Simulation for Sizing Periods", "No")
    replace("SimulationControl", "Run Simulation for Weather File Run Periods", "Yes")
    replace("RunPeriod", "Begin Month", str(begin_month))
    replace("RunPeriod", "Begin Day of Month", str(begin_day))
    replace("RunPeriod", "Begin Year", str(begin_year))
    replace("RunPeriod", "End Month", str(end_month))
    replace("RunPeriod", "End Day of Month", str(end_day))
    replace("RunPeriod", "End Year", str(end_year))
    replace("RunPeriod", "Day of Week for Start Day", day_of_week.strip().title())

    for object_type in ("Output:Variable", "Output:Meter"):
        edits.extend((obj.start, obj.end, "") for obj in document.find_objects(object_type))
    derived = text
    for start, finish, value in sorted(edits, reverse=True):
        derived = derived[:start] + value + derived[finish:]
    output_rows = [
        f"Output:Variable,*,{name},{frequency};"
        for name in sorted({name.strip() for name in variables if name.strip()})
    ]
    output_rows.extend(
        f"Output:Meter,{name},{frequency};"
        for name in sorted({name.strip() for name in meters if name.strip()})
    )
    if not output_rows:
        raise OutputContractError("weather-period output contract is empty")
    derived = derived.rstrip() + "\n\n" + "\n".join(output_rows) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(derived, encoding="utf-8")
    if source.read_bytes() != source_bytes:
        raise OutputContractError("source IDF changed during weather-period preparation")
    return destination


def prepare_design_day_run_idf(
    source_path: str | Path,
    destination_path: str | Path,
    *,
    idd: IDDSchema,
    variables: Iterable[str],
    meters: Iterable[str],
    reporting_frequency: str = "Timestep",
    resolution_minutes: int = 15,
    fixed_sizing_operation: bool = False,
) -> Path:
    """Prepare a source-immutable design-period derivative.

    Fixed operation keeps the source design-day environments but disables new
    zone, system, and plant sizing calculations.  This is deliberately separate
    from weather-period preparation so no RunPeriod or EPW assumption is added.
    """

    source = Path(source_path)
    destination = Path(destination_path)
    if not source.is_file():
        raise OutputContractError(f"source IDF not found: {source}")
    if source.resolve() == destination.resolve():
        raise OutputContractError("design-day IDF must not replace its source")
    if resolution_minutes <= 0 or 60 % resolution_minutes:
        raise OutputContractError("resolution must divide one hour")
    frequency = reporting_frequency.strip().title()
    if frequency not in {"Timestep", "Hourly", "Daily", "Runperiod"}:
        raise OutputContractError("unsupported reporting frequency")
    if frequency == "Runperiod":
        frequency = "RunPeriod"

    source_bytes = source.read_bytes()
    text = source_bytes.decode("utf-8")
    document = parse_idf(text)
    if document.issues:
        raise OutputContractError("source IDF cannot be prepared safely")
    timesteps = document.find_objects("Timestep")
    controls = document.find_objects("SimulationControl")
    design_days = document.find_objects("SizingPeriod:DesignDay")
    if len(timesteps) != 1 or len(controls) != 1 or not design_days:
        raise OutputContractError("design-period control objects are incomplete")

    objects = {"Timestep": timesteps[0], "SimulationControl": controls[0]}
    edits: list[tuple[int, int, str]] = []

    def replace(object_type: str, field_name: str, value: str) -> None:
        position = _idd_field_position(idd, object_type, field_name)
        obj = objects[object_type]
        if not 1 <= position <= len(obj.fields):
            raise OutputContractError(
                f"design-period field missing: {object_type}:{field_name}"
            )
        field = obj.fields[position - 1]
        if text[field.start : field.end] != field.value:
            raise OutputContractError(
                f"design-period source span mismatch: {object_type}:{field_name}"
            )
        if field.value != value:
            edits.append((field.start, field.end, value))

    replace("Timestep", "Number of Timesteps per Hour", str(60 // resolution_minutes))
    sizing_value = "No" if fixed_sizing_operation else "Yes"
    replace("SimulationControl", "Do Zone Sizing Calculation", sizing_value)
    replace("SimulationControl", "Do System Sizing Calculation", sizing_value)
    replace("SimulationControl", "Do Plant Sizing Calculation", sizing_value)
    replace("SimulationControl", "Run Simulation for Sizing Periods", "Yes")
    replace("SimulationControl", "Run Simulation for Weather File Run Periods", "No")

    for object_type in ("Output:Variable", "Output:Meter"):
        edits.extend(
            (obj.start, obj.end, "") for obj in document.find_objects(object_type)
        )
    derived = text
    for start, finish, value in sorted(edits, reverse=True):
        derived = derived[:start] + value + derived[finish:]
    output_rows = [
        f"Output:Variable,*,{name},{frequency};"
        for name in sorted({name.strip() for name in variables if name.strip()})
    ]
    output_rows.extend(
        f"Output:Meter,{name},{frequency};"
        for name in sorted({name.strip() for name in meters if name.strip()})
    )
    if not output_rows:
        raise OutputContractError("design-period output contract is empty")
    derived = derived.rstrip() + "\n\n" + "\n".join(output_rows) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(derived, encoding="utf-8")
    if source.read_bytes() != source_bytes:
        raise OutputContractError("source IDF changed during design-period preparation")
    return destination


def instrument_idf(
    source_path: str | Path,
    destination_path: str | Path,
    *,
    variables: Iterable[str],
    meters: Iterable[str],
) -> Path:
    """Append missing timestep requests to a derivative IDF only."""

    source = Path(source_path)
    destination = Path(destination_path)
    if not source.is_file():
        raise OutputContractError(f"source IDF not found: {source}")
    if source.resolve() == destination.resolve():
        raise OutputContractError("instrumented IDF must not replace its source")
    source_bytes = source.read_bytes()
    text = source_bytes.decode("utf-8")
    document = parse_idf(text)
    if document.issues:
        raise OutputContractError("source IDF cannot be instrumented safely")
    existing_variables = {
        (canonical(row.fields[1].value), canonical(row.fields[2].value))
        for row in document.find_objects("Output:Variable")
        if len(row.fields) >= 3
    }
    existing_meters = {
        (canonical(row.fields[0].value), canonical(row.fields[1].value))
        for row in document.find_objects("Output:Meter")
        if len(row.fields) >= 2
    }
    additions = [
        f"Output:Variable,*,{name},Timestep;"
        for name in sorted(set(variables))
        if (canonical(name), "timestep") not in existing_variables
    ]
    additions.extend(
        f"Output:Meter,{name},Timestep;"
        for name in sorted(set(meters))
        if (canonical(name), "timestep") not in existing_meters
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        text.rstrip() + ("\n\n" + "\n".join(additions) if additions else "") + "\n",
        encoding="utf-8",
    )
    if source.read_bytes() != source_bytes:
        raise OutputContractError("source IDF changed during instrumentation")
    return destination


@dataclass(frozen=True, slots=True)
class DiscoveredDictionary:
    variables: dict[str, str]
    meters: dict[str, str]


@dataclass(frozen=True, slots=True)
class SeriesRecord:
    key: str
    name: str
    units: str
    reporting_frequency: str
    year: int
    month: int
    day: int
    hour: int
    minute: int
    interval_minutes: int
    environment_period_index: int
    value: float


_VARIABLE = re.compile(
    r"^Output:Variable,[^,]*,(?P<name>[^,]+),(?P<frequency>[^;]+);.*?\[(?P<units>[^]]*)\]",
    re.IGNORECASE,
)
_METER = re.compile(
    r"^Output:Meter,(?P<name>[^,]+),(?P<frequency>[^;]+);.*?\[(?P<units>[^]]*)\]",
    re.IGNORECASE,
)


def discover_dictionary(rdd_text: str, mdd_text: str) -> DiscoveredDictionary:
    variables: dict[str, str] = {}
    meters: dict[str, str] = {}
    for line in rdd_text.splitlines():
        match = _VARIABLE.search(line.strip())
        if match:
            variables.setdefault(match.group("name").strip(), match.group("units").strip())
    for line in mdd_text.splitlines():
        match = _METER.search(line.strip())
        if match:
            meters.setdefault(match.group("name").strip(), match.group("units").strip())
    return DiscoveredDictionary(variables=variables, meters=meters)


def validate_dictionary(
    discovered: DiscoveredDictionary,
    *,
    required_variables: Iterable[str],
    required_meters: Iterable[str],
) -> None:
    missing_variables = sorted(set(required_variables).difference(discovered.variables))
    missing_meters = sorted(set(required_meters).difference(discovered.meters))
    if missing_variables or missing_meters:
        parts = []
        if missing_variables:
            parts.append("variables=" + ",".join(missing_variables))
        if missing_meters:
            parts.append("meters=" + ",".join(missing_meters))
        raise OutputContractError("required EnergyPlus output missing: " + "; ".join(parts))


def extract_series(
    sql_path: str | Path,
    name: str,
    *,
    key: str | None = None,
    reporting_frequency: str = "Timestep",
    environment_period_index: int | None = None,
) -> tuple[SeriesRecord, ...]:
    path = Path(sql_path)
    if not path.is_file():
        raise OutputContractError(f"EnergyPlus SQLite not found: {path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        timestep_request = reporting_frequency.strip().casefold() == "timestep"
        frequency_clause = (
            "lower(d.ReportingFrequency) in ('timestep', 'zone timestep')"
            if timestep_request
            else "lower(d.ReportingFrequency) = lower(?)"
        )
        query = f"""
            select
              d.KeyValue,
              d.Name,
              d.Units,
              d.ReportingFrequency,
              t.Year,
              t.Month,
              t.Day,
              t.Hour,
              t.Minute,
              t.Interval,
              t.EnvironmentPeriodIndex,
              r.Value
            from ReportDataDictionary d
            join ReportData r
              on r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex
            join Time t on t.TimeIndex = r.TimeIndex
            where d.Name = ?
              and {frequency_clause}
              and t.WarmupFlag = 0
        """
        parameters: list[object] = [name]
        if not timestep_request:
            parameters.append(reporting_frequency)
        if key is not None:
            query += " and d.KeyValue = ?"
            parameters.append(key)
        if environment_period_index is not None:
            if environment_period_index <= 0:
                raise OutputContractError("environment period index must be positive")
            query += " and t.EnvironmentPeriodIndex = ?"
            parameters.append(environment_period_index)
        query += " order by t.TimeIndex, d.KeyValue"
        rows = connection.execute(query, parameters).fetchall()
    except sqlite3.DatabaseError as exc:
        raise OutputContractError(f"invalid EnergyPlus SQLite: {path}") from exc
    finally:
        connection.close()
    if not rows:
        suffix = f" key={key}" if key is not None else ""
        raise OutputContractError(
            f"EnergyPlus output not found: {name}{suffix} frequency={reporting_frequency}"
        )
    return tuple(
        SeriesRecord(
            key=row[0] or "",
            name=row[1],
            units=row[2] or "",
            reporting_frequency=row[3],
            year=int(row[4] or 0),
            month=int(row[5] or 0),
            day=int(row[6] or 0),
            hour=int(row[7] or 0),
            minute=int(row[8] or 0),
            interval_minutes=int(row[9] or 0),
            environment_period_index=int(row[10] or 0),
            value=float(row[11]),
        )
        for row in rows
    )


_VIEWER_HEATING = "Zone Air System Sensible Heating Energy"
_VIEWER_COOLING = "Zone Air System Sensible Cooling Energy"


def extract_viewer_energy_by_space(
    sql_path: str | Path,
    *,
    spaces: Iterable[SourceSpace],
    environment_period_index: int,
) -> dict[str, dict[str, tuple[float, ...]]]:
    """Extract complete 96-step zone loads for one explicit environment period."""

    space_rows = tuple(spaces)
    if environment_period_index <= 0:
        raise OutputContractError("environment period index must be positive")
    zone_to_space: dict[str, SourceSpace] = {}
    for space in space_rows:
        key = space.thermal_zone.strip().casefold()
        if not key or key in zone_to_space:
            raise OutputContractError("Space-to-Zone mapping is not a bijection")
        zone_to_space[key] = space

    by_variable: dict[str, dict[str, list[SeriesRecord]]] = {}
    for variable in (_VIEWER_HEATING, _VIEWER_COOLING):
        grouped: dict[str, list[SeriesRecord]] = defaultdict(list)
        for record in extract_series(
            sql_path,
            variable,
            reporting_frequency="Timestep",
            environment_period_index=environment_period_index,
        ):
            grouped[record.key.strip().casefold()].append(record)
        if set(grouped) != set(zone_to_space):
            raise OutputContractError(
                f"viewer zone coverage mismatch: {variable}:"
                f"expected={len(zone_to_space)} actual={len(grouped)}"
            )
        by_variable[variable] = grouped

    reference_times: tuple[tuple[object, ...], ...] | None = None
    output: dict[str, dict[str, tuple[float, ...]]] = {}
    for zone_key, space in sorted(zone_to_space.items()):
        space_energy: dict[str, tuple[float, ...]] = {}
        for variable, field in (
            (_VIEWER_HEATING, "heating_kw"),
            (_VIEWER_COOLING, "cooling_kw"),
        ):
            records = by_variable[variable][zone_key]
            if len(records) != 96:
                raise OutputContractError(
                    f"viewer energy series must contain 96 records: {space.name}:{variable}"
                )
            signatures = tuple(
                (
                    row.year,
                    row.month,
                    row.day,
                    row.hour,
                    row.minute,
                    row.interval_minutes,
                    row.environment_period_index,
                    row.reporting_frequency.casefold(),
                )
                for row in records
            )
            if len(set(signatures)) != 96:
                raise OutputContractError(
                    f"viewer energy timestamps are duplicated: {space.name}:{variable}"
                )
            if any(
                row.units != "J"
                or row.interval_minutes != 15
                or not math.isfinite(row.value)
                or row.value < 0
                for row in records
            ):
                raise OutputContractError(
                    f"viewer energy requires finite non-negative 15-minute joules: "
                    f"{space.name}:{variable}"
                )
            if reference_times is None:
                reference_times = signatures
            elif signatures != reference_times:
                raise OutputContractError("viewer energy timestamps do not align")
            space_energy[field] = tuple(row.value / 900_000.0 for row in records)
        output[space.name] = space_energy
    return output


def list_environment_periods(sql_path: str | Path) -> dict[int, str]:
    path = Path(sql_path)
    if not path.is_file():
        raise OutputContractError(f"EnergyPlus SQLite not found: {path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "select EnvironmentPeriodIndex, EnvironmentName "
            "from EnvironmentPeriods order by EnvironmentPeriodIndex"
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise OutputContractError(f"invalid EnergyPlus SQLite: {path}") from exc
    finally:
        connection.close()
    return {int(index): str(name) for index, name in rows}


def aggregate_output_statistics(
    sql_path: str | Path,
    names: Iterable[str],
    *,
    environment_period_index: int | None = None,
) -> dict[str, dict[str, dict[str, float | int | str]]]:
    """Aggregate several timestep outputs in one read-only SQLite scan."""

    path = Path(sql_path)
    requested = tuple(sorted({name.strip() for name in names if name.strip()}))
    if not path.is_file():
        raise OutputContractError(f"EnergyPlus SQLite not found: {path}")
    if not requested:
        return {}
    if environment_period_index is not None and environment_period_index <= 0:
        raise OutputContractError("environment period index must be positive")
    placeholders = ",".join("?" for _name in requested)
    query = f"""
        select
          d.Name,
          d.KeyValue,
          d.Units,
          count(*),
          sum(r.Value),
          min(r.Value),
          avg(r.Value),
          max(r.Value),
          max(
            case
              when d.Units = 'J' and t.Interval > 0
              then r.Value / (t.Interval * 60.0 * 1000.0)
              else 0.0
            end
          )
        from ReportDataDictionary d
        join ReportData r
          on r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex
        join Time t on t.TimeIndex = r.TimeIndex
        where d.Name in ({placeholders})
          and lower(d.ReportingFrequency) in ('timestep', 'zone timestep')
          and t.WarmupFlag = 0
    """
    parameters: list[object] = list(requested)
    if environment_period_index is not None:
        query += " and t.EnvironmentPeriodIndex = ?"
        parameters.append(environment_period_index)
    query += " group by d.Name, d.KeyValue, d.Units order by d.Name, d.KeyValue"
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute(query, parameters).fetchall()
    except sqlite3.DatabaseError as exc:
        raise OutputContractError(f"invalid EnergyPlus SQLite: {path}") from exc
    finally:
        connection.close()
    output: dict[str, dict[str, dict[str, float | int | str]]] = defaultdict(dict)
    for name, key, units, count, total, minimum, mean, maximum, interval_peak_kw in rows:
        output[str(name)][str(key or "")] = {
            "units": str(units or ""),
            "count": int(count),
            "sum": float(total),
            "minimum": float(minimum),
            "mean": float(mean),
            "maximum": float(maximum),
            "interval_peak_kw": float(interval_peak_kw),
        }
    return {name: dict(by_key) for name, by_key in output.items()}


def _values(
    sql_path: str | Path,
    name: str,
    environment_period_index: int | None,
) -> tuple[SeriesRecord, ...]:
    return extract_series(
        sql_path,
        name,
        reporting_frequency="Timestep",
        environment_period_index=environment_period_index,
    )


def _optional_values(
    sql_path: str | Path,
    name: str,
    environment_period_index: int | None,
) -> tuple[SeriesRecord, ...]:
    try:
        return _values(sql_path, name, environment_period_index)
    except OutputContractError:
        return ()


def _energy_kwh(records: Iterable[SeriesRecord]) -> float:
    records = tuple(records)
    if any(record.units != "J" for record in records):
        raise OutputContractError("energy output unit must be J")
    return sum(record.value for record in records) / 3_600_000.0


def _peak_kw(records: Iterable[SeriesRecord]) -> float:
    records = tuple(records)
    if any(record.units != "W" for record in records):
        raise OutputContractError("rate output unit must be W")
    return max((record.value for record in records), default=0.0) / 1000.0


def energy_kwh_by_key(
    sql_path: str | Path,
    name: str,
    *,
    environment_period_index: int | None = None,
) -> dict[str, float]:
    """Sum one timestep energy output by its exact EnergyPlus key."""

    grouped: dict[str, list[SeriesRecord]] = defaultdict(list)
    for record in _values(sql_path, name, environment_period_index):
        grouped[record.key].append(record)
    return {key: _energy_kwh(records) for key, records in sorted(grouped.items())}


def interval_peak_kw_by_key(
    sql_path: str | Path,
    name: str,
    *,
    environment_period_index: int | None = None,
) -> dict[str, float]:
    """Convert an interval energy series to peak mean power for each exact key."""

    grouped: dict[str, list[SeriesRecord]] = defaultdict(list)
    for record in _values(sql_path, name, environment_period_index):
        if record.units != "J" or record.interval_minutes <= 0:
            raise OutputContractError(
                "interval peak requires joules and a positive interval"
            )
        grouped[record.key].append(record)
    return {
        key: max(
            record.value / (record.interval_minutes * 60.0 * 1000.0)
            for record in records
        )
        for key, records in sorted(grouped.items())
    }


def value_statistics_by_key(
    sql_path: str | Path,
    name: str,
    *,
    environment_period_index: int | None = None,
) -> dict[str, dict[str, float]]:
    """Return minimum, arithmetic mean, and maximum for each exact output key."""

    grouped: dict[str, list[SeriesRecord]] = defaultdict(list)
    for record in _values(sql_path, name, environment_period_index):
        grouped[record.key].append(record)
    return {
        key: {
            "minimum": min(record.value for record in records),
            "mean": sum(record.value for record in records) / len(records),
            "maximum": max(record.value for record in records),
        }
        for key, records in sorted(grouped.items())
    }


def summarize_energyplus(
    sql_path: str | Path,
    *,
    environment_period_index: int | None = None,
) -> dict[str, object]:
    facility = _values(sql_path, "Electricity:Facility", environment_period_index)
    fans = _values(sql_path, "Fans:Electricity", environment_period_index)
    pumps = _values(sql_path, "Pumps:Electricity", environment_period_index)
    cooling = _values(sql_path, "DistrictCooling:Facility", environment_period_index)
    heating = _values(sql_path, "DistrictHeating:Facility", environment_period_index)
    demand = _values(
        sql_path, "Facility Total HVAC Electricity Demand Rate", environment_period_index
    )
    cooling_unmet = _optional_values(
        sql_path,
        "Facility Cooling Setpoint Not Met While Occupied Time",
        environment_period_index,
    )
    heating_unmet = _optional_values(
        sql_path,
        "Facility Heating Setpoint Not Met While Occupied Time",
        environment_period_index,
    )

    loop_fan_records = _optional_values(
        sql_path, "Air System Fan Electricity Energy", environment_period_index
    )
    loop_oa_records = _optional_values(
        sql_path, "Air System Outdoor Air Mass Flow Rate", environment_period_index
    )
    fan_by_loop: dict[str, list[SeriesRecord]] = defaultdict(list)
    oa_by_loop: dict[str, list[SeriesRecord]] = defaultdict(list)
    for record in loop_fan_records:
        fan_by_loop[record.key].append(record)
    for record in loop_oa_records:
        oa_by_loop[record.key].append(record)
    air_loops: dict[str, dict[str, float]] = {}
    for loop in sorted(set(fan_by_loop) | set(oa_by_loop)):
        oa = oa_by_loop.get(loop, [])
        if oa and any(record.units != "kg/s" for record in oa):
            raise OutputContractError("AirLoop outdoor-air unit must be kg/s")
        air_loops[loop] = {
            "fan_electricity_kwh": _energy_kwh(fan_by_loop.get(loop, [])),
            "outdoor_air_mass_flow_peak_kg_s": max(
                (record.value for record in oa), default=0.0
            ),
            "outdoor_air_mass_flow_mean_kg_s": (
                sum(record.value for record in oa) / len(oa) if oa else 0.0
            ),
        }

    return {
        "facility_electricity_kwh": _energy_kwh(facility),
        "fan_electricity_kwh": _energy_kwh(fans),
        "pump_electricity_kwh": _energy_kwh(pumps),
        "district_cooling_kwh_boundary": _energy_kwh(cooling),
        "district_heating_kwh_boundary": _energy_kwh(heating),
        "peak_hvac_electric_kw": _peak_kw(demand),
        "cooling_unmet_occupied_hours": sum(
            record.value for record in cooling_unmet
        ),
        "heating_unmet_occupied_hours": sum(
            record.value for record in heating_unmet
        ),
        "air_loops": air_loops,
    }


REQUIRED_VARIABLES = frozenset(
    {
        "Space People Occupant Count",
        "Space People Total Heating Energy",
        "Zone People Sensible Heating Energy",
        "Zone People Latent Gain Energy",
        "Zone People Radiant Heating Energy",
        "Zone Air System Sensible Heating Energy",
        "Zone Air System Sensible Cooling Energy",
        "Zone Air Temperature",
        "Zone Air Relative Humidity",
        "Zone Air Terminal Outdoor Air Volume Flow Rate",
        "Facility Total HVAC Electricity Demand Rate",
        "Facility Heating Setpoint Not Met While Occupied Time",
        "Facility Cooling Setpoint Not Met While Occupied Time",
        "Air System Outdoor Air Mass Flow Rate",
        "Air System Fan Electricity Energy",
        "Air System Total Heating Energy",
        "Air System Total Cooling Energy",
        "Fan Electricity Energy",
        "Fan Coil Fan Electricity Energy",
        "Pump Electricity Energy",
    }
)
REQUIRED_METERS = frozenset(
    {
        "Electricity:Facility",
        "Fans:Electricity",
        "Pumps:Electricity",
        "DistrictCooling:Facility",
        "DistrictHeating:Facility",
    }
)
