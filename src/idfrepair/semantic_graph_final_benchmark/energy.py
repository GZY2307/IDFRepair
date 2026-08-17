"""提供哈希缓存的 EnergyPlus design-day 与 annual validation。

prepare_energy_text(): 构造不改变模拟语义的年度 reporting copy。
run_energyplus_cached(): 依据 artifact/runtime/weather identity 复用模拟证据。
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Literal

from idfrepair.diagnostics.err_parser import diagnostic_counts, parse_err
from idfrepair.runtime.discovery import RuntimeSpec
from idfrepair.runtime.energyplus import preprocessing_requirements
from tools.analysis.energy_buildings_posthoc import (
    add_analysis_reporting,
    parse_abups_html_text,
    qualify_energy_model,
)

from .artifacts import write_json
from .seals import json_identity, sha256_file


Mode = Literal["design_day", "annual"]


def energy_case_identity(
    *,
    artifact_sha256: str,
    analysis_text_sha256: str,
    runtime: RuntimeSpec,
    mode: Mode,
    weather_sha256: str | None,
) -> dict[str, object]:
    return {
        "artifact_sha256": artifact_sha256,
        "analysis_text_sha256": analysis_text_sha256,
        "energyplus_executable_sha256": sha256_file(runtime.executable),
        "idd_sha256": sha256_file(runtime.idd_path),
        "mode": mode,
        "weather_sha256": weather_sha256,
    }


def prepare_energy_text(text: str, mode: Mode) -> tuple[str, list[str], dict[str, object]]:
    if mode == "design_day":
        return text, [], {"eligible": True, "reason": "design_day"}
    qualification = qualify_energy_model(text)
    if not qualification["eligible"]:
        return text, [], qualification
    analysis, additions = add_analysis_reporting(text)
    return analysis, additions, qualification


def run_energyplus_cached(
    *,
    artifact: Path,
    runtime: RuntimeSpec,
    cache_root: Path,
    mode: Mode,
    weather: Path | None,
    timeout_seconds: int,
) -> dict[str, object]:
    source_text = artifact.read_text(encoding="utf-8-sig", errors="replace")
    analysis_text, additions, qualification = prepare_energy_text(source_text, mode)
    source_sha = sha256_file(artifact)
    analysis_sha = __import__("hashlib").sha256(
        analysis_text.encode("utf-8")
    ).hexdigest()
    weather_sha = sha256_file(weather) if weather is not None and weather.is_file() else None
    identity = energy_case_identity(
        artifact_sha256=source_sha,
        analysis_text_sha256=analysis_sha,
        runtime=runtime,
        mode=mode,
        weather_sha256=weather_sha,
    )
    key = json_identity(identity)
    final_root = cache_root / key
    result_path = final_root / "result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("cache_key") != key:
            raise ValueError(f"energy_cache_identity_mismatch:{key}")
        result["cache_reused"] = True
        return result
    if mode == "annual" and not qualification["eligible"]:
        result = {
            "schema_version": "idfrepair.semantic-graph-formal-energy-case.v1",
            "cache_key": key,
            "cache_reused": False,
            "mode": mode,
            "attempted": False,
            "passed": False,
            "status": "INELIGIBLE",
            "qualification": qualification,
            "artifact_sha256": source_sha,
            "analysis_text_sha256": analysis_sha,
            "reporting_additions": additions,
            "metrics": None,
        }
        final_root.mkdir(parents=True, exist_ok=False)
        write_json(result_path, result)
        return result
    if mode == "annual" and (weather is None or not weather.is_file()):
        result = {
            "schema_version": "idfrepair.semantic-graph-formal-energy-case.v1",
            "cache_key": key,
            "cache_reused": False,
            "mode": mode,
            "attempted": False,
            "passed": False,
            "status": "WEATHER_MISSING",
            "qualification": qualification,
            "artifact_sha256": source_sha,
            "analysis_text_sha256": analysis_sha,
            "reporting_additions": additions,
            "metrics": None,
        }
        final_root.mkdir(parents=True, exist_ok=False)
        write_json(result_path, result)
        return result

    cache_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{key}-", dir=cache_root))
    input_path = staging / "analysis.idf"
    input_path.write_text(analysis_text, encoding="utf-8")
    output = staging / "output"
    output.mkdir()
    command = [
        str(runtime.executable),
        "--idd", str(runtime.idd_path),
        "--output-directory", str(output),
    ]
    if preprocessing_requirements(analysis_text):
        command.append("--expandobjects")
    if mode == "design_day":
        command.append("--design-day")
    else:
        command.extend(("--annual", "--weather", str(weather)))
    command.append(str(input_path))
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=staging,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        returncode = completed.returncode
        timed_out = False
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        returncode = None
        timed_out = True
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
    err = output / "eplusout.err"
    diagnostics = err.read_text(encoding="utf-8", errors="replace") if err.is_file() else ""
    counts = diagnostic_counts(parse_err(diagnostics))
    passed = bool(
        not timed_out
        and returncode == 0
        and counts["severe"] == 0
        and counts["fatal"] == 0
    )
    metrics = None
    report_error = ""
    html = output / "eplustbl.htm"
    if mode == "annual" and passed:
        if html.is_file():
            try:
                metrics = parse_abups_html_text(
                    html.read_text(encoding="utf-8", errors="replace")
                )
            except (KeyError, ValueError) as exc:
                report_error = f"{type(exc).__name__}: {exc}"
        else:
            report_error = "annual_html_missing"
    final_output = final_root / "output"
    result = {
        "schema_version": "idfrepair.semantic-graph-formal-energy-case.v1",
        "cache_key": key,
        "cache_reused": False,
        "mode": mode,
        "attempted": True,
        "passed": passed,
        "status": (
            "PASSED" if passed else "TIMEOUT" if timed_out else "FAILED"
        ),
        "returncode": returncode,
        "timed_out": timed_out,
        "severe_count": counts["severe"],
        "fatal_count": counts["fatal"],
        "warning_count": counts["warning"],
        "wall_seconds": time.monotonic() - started,
        "artifact_sha256": source_sha,
        "analysis_text_sha256": analysis_sha,
        "artifact_identity_reused": source_sha == analysis_sha,
        "reporting_additions": additions,
        "qualification": qualification,
        "metrics": metrics,
        "report_error": report_error,
        "output_directory": str(final_output),
        "command": command,
        "runtime_identity": runtime.identity,
        "stdout_sha256": __import__("hashlib").sha256(stdout).hexdigest(),
        "stderr_sha256": __import__("hashlib").sha256(stderr).hexdigest(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (staging / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        os.replace(staging, final_root)
    except OSError:
        if not result_path.is_file():
            raise
        shutil.rmtree(staging)
        cached = json.loads(result_path.read_text(encoding="utf-8"))
        cached["cache_reused"] = True
        return cached
    return result


__all__ = [
    "energy_case_identity",
    "prepare_energy_text",
    "run_energyplus_cached",
]
