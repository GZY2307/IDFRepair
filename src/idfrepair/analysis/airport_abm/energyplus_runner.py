"""Bounded, marker-cached EnergyPlus execution for Airport ABM V3.1."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Mapping

from .energyplus_coupling import (
    OutputContractError,
    aggregate_output_statistics,
    list_environment_periods,
)
from .v31 import SEASONAL_SEEDS, TIMING_SCENARIOS


_WARNING_SUMMARY = re.compile(r"(\d+) Warning;\s*(\d+) Severe Errors", re.I)
_SEVERE = re.compile(r"\*\*\s*Severe\s*\*\*", re.I)
_FATAL = re.compile(r"\*\*\s*Fatal\s*\*\*", re.I)
_ELAPSED = re.compile(
    r"Elapsed Time=(\d+)hr\s+(\d+)min\s+([\d.]+)sec", re.I
)
_UNMET_NAMES = (
    "Facility Heating Setpoint Not Met While Occupied Time",
    "Facility Cooling Setpoint Not Met While Occupied Time",
)


@dataclass(frozen=True, slots=True)
class EnergyPlusErrorSummary:
    warning_count: int
    severe_count: int
    fatal_count: int
    completed_successfully: bool
    elapsed_seconds: float | None


@dataclass(frozen=True, slots=True)
class EnergyPlusCase:
    scenario_id: str
    seed: int | None
    run_kind: str
    input_path: Path
    output_dir: Path
    expected_periods: tuple[str, ...]


def parse_energyplus_error_summary(text: str) -> EnergyPlusErrorSummary:
    summaries = _WARNING_SUMMARY.findall(text)
    terminal = summaries[-1] if summaries else None
    warnings = int(terminal[0]) if terminal else 0
    severe = int(terminal[1]) if terminal else len(_SEVERE.findall(text))
    fatal = len(_FATAL.findall(text))
    elapsed_matches = _ELAPSED.findall(text)
    elapsed = None
    if elapsed_matches:
        hours, minutes, seconds = elapsed_matches[-1]
        elapsed = int(hours) * 3600.0 + int(minutes) * 60.0 + float(seconds)
    return EnergyPlusErrorSummary(
        warning_count=warnings,
        severe_count=severe,
        fatal_count=fatal,
        completed_successfully="EnergyPlus Completed Successfully" in text,
        elapsed_seconds=elapsed,
    )


def seasonal_case_registry(energy_root: str | Path) -> tuple[EnergyPlusCase, ...]:
    root = Path(energy_root)
    cases = [
        EnergyPlusCase(
            scenario_id="SOURCE_STATIC",
            seed=None,
            run_kind="design_days",
            input_path=root / "static_source/design-days.idf",
            output_dir=root / "static_source/design-days",
            expected_periods=("summer", "winter"),
        ),
        EnergyPlusCase(
            scenario_id="SOURCE_STATIC",
            seed=None,
            run_kind="shoulder",
            input_path=root / "static_source/shoulder.idf",
            output_dir=root / "static_source/shoulder",
            expected_periods=("shoulder",),
        ),
    ]
    for scenario in TIMING_SCENARIOS:
        for seed in SEASONAL_SEEDS:
            parent = root / "seasonal" / scenario / f"seed-{seed}"
            cases.extend(
                [
                    EnergyPlusCase(
                        scenario_id=scenario,
                        seed=seed,
                        run_kind="design_days",
                        input_path=parent / "design-days.idf",
                        output_dir=parent / "design-days",
                        expected_periods=("summer", "winter"),
                    ),
                    EnergyPlusCase(
                        scenario_id=scenario,
                        seed=seed,
                        run_kind="shoulder",
                        input_path=parent / "shoulder.idf",
                        output_dir=parent / "shoulder",
                        expected_periods=("shoulder",),
                    ),
                ]
            )
    return tuple(cases)


def _period_id(run_kind: str, environment_name: str) -> str:
    lowered = environment_name.casefold()
    if "summer" in lowered:
        return "summer"
    if "winter" in lowered:
        return "winter"
    return run_kind


def _sum_statistic(
    statistics: Mapping[str, Mapping[str, Mapping[str, object]]], name: str
) -> float:
    rows = statistics.get(name)
    if not rows:
        raise OutputContractError(f"required EnergyPlus output missing: {name}")
    return sum(float(row["sum"]) for row in rows.values())


def _period_records(sql_path: Path, run_kind: str) -> list[dict[str, object]]:
    output = []
    for environment_index, environment_name in list_environment_periods(sql_path).items():
        period = _period_id(run_kind, environment_name)
        statistics = aggregate_output_statistics(
            sql_path, _UNMET_NAMES, environment_period_index=environment_index
        )
        heating = _sum_statistic(statistics, _UNMET_NAMES[0])
        cooling = _sum_statistic(statistics, _UNMET_NAMES[1])
        output.append(
            {
                "period_id": period,
                "environment_name": environment_name,
                "heating_unmet_occupied_hours": heating,
                "cooling_unmet_occupied_hours": cooling,
                "occupied_unmet_hours": heating + cooling,
            }
        )
    return output


def _marker_matches(case: EnergyPlusCase, marker: Mapping[str, object]) -> bool:
    try:
        stat = case.input_path.stat()
        return (
            marker.get("schema_version")
            == "idfrepair.airport-v31-energyplus-completion.v1"
            and marker.get("scenario_id") == case.scenario_id
            and marker.get("seed") == case.seed
            and marker.get("run_kind") == case.run_kind
            and marker.get("parser_version") == 3
            and int(marker.get("input_size_bytes", -1)) == stat.st_size
            and int(marker.get("input_modified_ns", -1)) == stat.st_mtime_ns
            and marker.get("passed") is True
            and (case.output_dir / "eplusout.sql").is_file()
            and (case.output_dir / "eplusout.err").is_file()
        )
    except (OSError, TypeError, ValueError):
        return False


def _inspect_outputs(
    case: EnergyPlusCase,
    *,
    return_code: int,
    wall_seconds: float,
) -> dict[str, object]:
    error_path = case.output_dir / "eplusout.err"
    sql_path = case.output_dir / "eplusout.sql"
    text = (
        error_path.read_text(encoding="utf-8", errors="replace")
        if error_path.is_file()
        else ""
    )
    summary = parse_energyplus_error_summary(text)
    passed = (
        return_code == 0
        and summary.completed_successfully
        and summary.severe_count == 0
        and summary.fatal_count == 0
    )
    periods: list[dict[str, object]] = []
    output_contract_error = None
    if passed and sql_path.is_file():
        try:
            periods = _period_records(sql_path, case.run_kind)
        except OutputContractError as exc:
            output_contract_error = str(exc)
    actual_periods = tuple(row["period_id"] for row in periods)
    period_contract_passed = sorted(actual_periods) == sorted(case.expected_periods)
    stat = case.input_path.stat()
    return {
        "schema_version": "idfrepair.airport-v31-energyplus-completion.v1",
        "parser_version": 3,
        "scenario_id": case.scenario_id,
        "seed": case.seed,
        "run_kind": case.run_kind,
        "expected_periods": list(case.expected_periods),
        "input_size_bytes": stat.st_size,
        "input_modified_ns": stat.st_mtime_ns,
        "return_code": return_code,
        "warning_count": summary.warning_count,
        "severe_count": summary.severe_count,
        "fatal_count": summary.fatal_count,
        "wall_seconds": (
            wall_seconds
            if wall_seconds > 0
            else float(summary.elapsed_seconds or 0.0)
        ),
        "passed": passed,
        "period_contract_passed": period_contract_passed,
        "output_contract_error": output_contract_error,
        "periods": periods,
    }


def run_energyplus_case(
    case: EnergyPlusCase,
    *,
    energyplus: str | Path,
    epw: str | Path,
    timeout_seconds: int,
) -> dict[str, object]:
    if not case.input_path.is_file():
        raise FileNotFoundError(case.input_path)
    case.output_dir.mkdir(parents=True, exist_ok=True)
    marker_path = case.output_dir / ".v31-completion.json"
    if marker_path.is_file():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            marker = {}
        if _marker_matches(case, marker):
            return {**marker, "execution_status": "CACHED"}

    error_path = case.output_dir / "eplusout.err"
    sql_path = case.output_dir / "eplusout.sql"
    if (
        error_path.is_file()
        and sql_path.is_file()
        and min(error_path.stat().st_mtime_ns, sql_path.stat().st_mtime_ns)
        >= case.input_path.stat().st_mtime_ns
    ):
        existing = _inspect_outputs(case, return_code=0, wall_seconds=0.0)
        if existing["passed"] and existing["period_contract_passed"]:
            marker_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
            return {**existing, "execution_status": "CACHED_EXISTING"}

    command = [str(energyplus)]
    if case.run_kind == "shoulder":
        command.extend(["-w", str(epw)])
    command.extend(["-d", str(case.output_dir), str(case.input_path)])
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return_code = result.returncode
        process_text = result.stdout + result.stderr
    except subprocess.TimeoutExpired as exc:
        return_code = -9
        process_text = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(process_text, bytes):
            process_text = process_text.decode("utf-8", errors="replace")
    wall_seconds = time.monotonic() - started
    (case.output_dir / "process.log").write_text(
        process_text, encoding="utf-8", errors="replace"
    )
    record = _inspect_outputs(
        case, return_code=return_code, wall_seconds=wall_seconds
    )
    marker_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return {**record, "execution_status": "RAN"}
