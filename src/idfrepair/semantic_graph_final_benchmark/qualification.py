"""在不调用 V2 inference 的前提下资格化 sealed sources。

schema_issues(): 执行 target IDD 基础结构验证。
make_transition_fn(): 构造官方 22.1→24.1 copy-transition 执行器。
make_smoke_fn(): 构造 EnergyPlus design-day smoke 执行器。
qualify_sources(): 保留每个 sealed source 的成功或失败资格化结果。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import time
from types import SimpleNamespace
from typing import Callable, Mapping, Sequence

from idfrepair.config import EngineConfig
from idfrepair.diagnostics.err_parser import diagnostic_counts, parse_err
from idfrepair.domain.enums import RepairMode
from idfrepair.domain.models import RepairSession
from idfrepair.io.idf import canonical, parse_idf, text_sha256
from idfrepair.io.workspace import SessionWorkspace
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.runtime.discovery import RuntimeSpec, normalize_version
from idfrepair.runtime.energyplus import preprocessing_requirements
from idfrepair.runtime.transition import TransitionStep, migrate_copy

from .seals import sha256_file


TransitionFn = Callable[[Mapping[str, str], Path, Path], dict[str, object]]
SmokeFn = Callable[[Mapping[str, str], Path, Path, Path], dict[str, object]]


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def schema_issues(
    text: str, idd: IDDSchema, expected_version: str,
) -> list[str]:
    document = parse_idf(text)
    issues = list(document.issues)
    if normalize_version(document.version) != normalize_version(expected_version):
        issues.append(
            f"target_version_mismatch:{document.version}:{expected_version}"
        )
    if normalize_version(idd.version) != normalize_version(expected_version):
        issues.append(f"idd_version_mismatch:{idd.version}:{expected_version}")
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None:
            if canonical(obj.object_type) != "version":
                issues.append(f"unknown_object_type:{obj.index}:{obj.object_type}")
            continue
        if len(obj.fields) < definition.minimum_fields:
            issues.append(f"too_few_fields:{obj.index}")
        maximum = definition.maximum_fields
        if maximum is not None and len(obj.fields) > maximum:
            issues.append(f"too_many_fields:{obj.index}")
        for field in definition.fields:
            if field.required and (
                field.index > len(obj.fields)
                or not obj.fields[field.index - 1].value.strip()
            ):
                issues.append(f"required_field_empty:{obj.index}:{field.index}")
    return issues


def make_transition_fn(
    *,
    project_root: Path,
    runtime: RuntimeSpec,
    transitions: Sequence[TransitionStep],
    timeout_seconds: int,
) -> TransitionFn:
    def transition(
        row: Mapping[str, str], source: Path, destination: Path,
    ) -> dict[str, object]:
        source_text = source.read_text(encoding="utf-8-sig", errors="replace")
        source_version = normalize_version(parse_idf(source_text).version)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_version == normalize_version(runtime.version):
            if destination.is_file() and destination.read_text(
                encoding="utf-8-sig", errors="replace",
            ) != source_text:
                raise RuntimeError("qualified_artifact_content_mismatch")
            if not destination.is_file():
                destination.write_text(source_text, encoding="utf-8")
            return {
                "status": "PASSED",
                "step_count": 0,
                "artifact": destination,
            }
        workspace = SessionWorkspace(destination.parent / "transition-workspace")
        upload = workspace.safe_path("uploads/input.idf")
        upload.parent.mkdir(parents=True, exist_ok=True)
        if upload.is_file() and upload.read_text(
            encoding="utf-8-sig", errors="replace",
        ) != source_text:
            raise RuntimeError("transition_workspace_input_mismatch")
        if not upload.is_file():
            upload.write_text(source_text, encoding="utf-8")
        session = RepairSession.create(
            mode=RepairMode.ANALYZE_ONLY,
            input_name=source.name,
            input_sha256=text_sha256(source_text),
        )
        weather_value = str(row.get("weather_path", ""))
        weather = _resolve(project_root, weather_value) if weather_value else None
        record = SimpleNamespace(
            session=session,
            workspace=workspace,
            input_text=source_text,
            config=EngineConfig(
                mode=RepairMode.ANALYZE_ONLY,
                timeout_seconds=timeout_seconds,
            ),
            weather=weather,
            dependencies=[],
        )
        report = migrate_copy(
            record,
            runtime,
            transitions=transitions,
            run_energyplus=False,
        )
        migrated = Path(str(report["artifact_path"]))
        if destination.is_file():
            if destination.read_bytes() != migrated.read_bytes():
                raise RuntimeError("qualified_artifact_content_mismatch")
        else:
            shutil.copy2(migrated, destination)
        return {
            "status": "PASSED",
            "step_count": int(report["transition_step_count"]),
            "artifact": destination,
            "report": str(report["report_path"]),
        }
    return transition


def make_smoke_fn(
    *, runtime: RuntimeSpec, timeout_seconds: int,
) -> SmokeFn:
    def smoke(
        row: Mapping[str, str], artifact: Path, weather: Path, run_root: Path,
    ) -> dict[str, object]:
        del row
        output = run_root / "output"
        output.mkdir(parents=True, exist_ok=True)
        cached_err = output / "eplusout.err"
        cached_end = output / "eplusout.end"
        if cached_err.is_file() and cached_end.is_file():
            diagnostics = cached_err.read_text(encoding="utf-8", errors="replace")
            counts = diagnostic_counts(parse_err(diagnostics))
            passed = counts["severe"] == 0 and counts["fatal"] == 0
            return {
                "status": "PASSED" if passed else "FAILED_ENERGYPLUS",
                "returncode": 0 if passed else 1,
                "severe_count": counts["severe"],
                "fatal_count": counts["fatal"],
                "warning_count": counts["warning"],
                "wall_seconds": 0.0,
                "cached": True,
            }
        text = artifact.read_text(encoding="utf-8-sig", errors="replace")
        command = [
            str(runtime.executable),
            "-i", str(runtime.idd_path),
            "-d", str(output),
            "-D",
        ]
        if preprocessing_requirements(text):
            command.append("-x")
        command.extend(("-r", "-w", str(weather), str(artifact)))
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=run_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "TIMEOUT",
                "returncode": None,
                "severe_count": 0,
                "fatal_count": 0,
                "warning_count": 0,
                "wall_seconds": time.monotonic() - started,
                "cached": False,
            }
        diagnostics = (
            cached_err.read_text(encoding="utf-8", errors="replace")
            if cached_err.is_file() else ""
        )
        counts = diagnostic_counts(parse_err(diagnostics))
        passed = (
            completed.returncode == 0
            and counts["severe"] == 0
            and counts["fatal"] == 0
        )
        return {
            "status": "PASSED" if passed else "FAILED_ENERGYPLUS",
            "returncode": completed.returncode,
            "severe_count": counts["severe"],
            "fatal_count": counts["fatal"],
            "warning_count": counts["warning"],
            "wall_seconds": time.monotonic() - started,
            "cached": False,
            "diagnostic_tail": "" if passed else diagnostics[-2000:],
        }
    return smoke


def qualify_sources(
    rows: Sequence[Mapping[str, str]],
    *,
    project_root: Path,
    output_root: Path,
    target_idd: IDDSchema,
    target_version: str,
    transition_fn: TransitionFn,
    smoke_fn: SmokeFn,
    max_workers: int = 4,
) -> list[dict[str, object]]:
    if max_workers < 1:
        raise ValueError("qualification_max_workers_must_be_positive")

    def qualify(row: Mapping[str, str]) -> dict[str, object]:
        outcome: dict[str, object] = dict(row)
        outcome.update({
            "qualification_status": "PROCESS_FAILURE",
            "file_status": "NOT_RUN",
            "weather_qualification_status": "NOT_RUN",
            "parse_status": "NOT_RUN",
            "transition_status": "NOT_RUN",
            "transition_step_count": "",
            "schema_status": "NOT_RUN",
            "schema_issue_count": "",
            "smoke_status": "NOT_RUN",
            "smoke_returncode": "",
            "smoke_severe_count": "",
            "smoke_fatal_count": "",
            "smoke_warning_count": "",
            "smoke_wall_seconds": "",
            "qualified_artifact": "",
            "qualified_sha256": "",
            "error": "",
        })
        source_id = str(row.get("sealed_source_id", ""))
        member_root = output_root / source_id
        destination = member_root / "qualified.idf"
        try:
            source = _resolve(project_root, str(row.get("source_path", "")))
            weather = _resolve(project_root, str(row.get("weather_path", "")))
            if not source.is_file():
                outcome["file_status"] = "MISSING"
                outcome["qualification_status"] = "FAILED_FILE_MISSING"
                return outcome
            outcome["file_status"] = "PASSED"
            if not weather.is_file():
                outcome["weather_qualification_status"] = "MISSING"
                outcome["qualification_status"] = "FAILED_WEATHER_MISSING"
                return outcome
            outcome["weather_qualification_status"] = "PASSED"
            source_text = source.read_text(
                encoding="utf-8-sig", errors="replace",
            )
            document = parse_idf(source_text)
            if document.issues:
                outcome["parse_status"] = "FAILED"
                outcome["qualification_status"] = "FAILED_PARSE"
                outcome["error"] = "|".join(document.issues[:20])
                return outcome
            outcome["parse_status"] = "PASSED"
            try:
                transition = transition_fn(row, source, destination)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                timed_out = "timed_out" in error.casefold() or "timeout" in error.casefold()
                outcome["transition_status"] = "TIMEOUT" if timed_out else "FAILED"
                outcome["qualification_status"] = (
                    "TIMEOUT" if timed_out else "FAILED_TRANSITION"
                )
                outcome["error"] = error
                return outcome
            outcome["transition_status"] = transition.get("status", "PASSED")
            outcome["transition_step_count"] = transition.get("step_count", "")
            artifact = Path(str(transition.get("artifact", destination)))
            text = artifact.read_text(encoding="utf-8-sig", errors="replace")
            issues = schema_issues(text, target_idd, target_version)
            outcome["schema_issue_count"] = len(issues)
            if issues:
                outcome["schema_status"] = "FAILED"
                outcome["qualification_status"] = "FAILED_SCHEMA"
                outcome["error"] = "|".join(issues[:20])
                return outcome
            outcome["schema_status"] = "PASSED"
            smoke = smoke_fn(row, artifact, weather, member_root / "smoke")
            outcome["smoke_status"] = smoke.get("status", "PROCESS_FAILURE")
            outcome["smoke_returncode"] = smoke.get("returncode", "")
            outcome["smoke_severe_count"] = smoke.get("severe_count", "")
            outcome["smoke_fatal_count"] = smoke.get("fatal_count", "")
            outcome["smoke_warning_count"] = smoke.get("warning_count", "")
            outcome["smoke_wall_seconds"] = smoke.get("wall_seconds", "")
            outcome["qualified_artifact"] = _relative(project_root, artifact)
            outcome["qualified_sha256"] = sha256_file(artifact)
            outcome["qualification_status"] = str(smoke.get("status", "PROCESS_FAILURE"))
            if outcome["qualification_status"] != "PASSED":
                outcome["error"] = str(
                    smoke.get("diagnostic_tail", smoke.get("status", "smoke_failed"))
                )
        except Exception as exc:
            outcome["qualification_status"] = "PROCESS_FAILURE"
            outcome["error"] = f"{type(exc).__name__}: {exc}"
        return outcome

    if max_workers == 1:
        return [qualify(row) for row in rows]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(qualify, rows))


__all__ = [
    "make_smoke_fn",
    "make_transition_fn",
    "qualify_sources",
    "schema_issues",
]
