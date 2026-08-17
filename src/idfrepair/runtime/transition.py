"""Discover and run official EnergyPlus Transition executables on copied IDFs.

This module is intentionally separate from IDFRepair's candidate-based migration
provider.  It never rewrites a Version object itself: every intermediate IDF must
be produced by an installed ``Transition-V…-to-V…`` executable and identify the
expected next version before the chain may continue.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Iterable, TYPE_CHECKING

from idfrepair.domain.errors import RuntimeProcessError, SessionStateError
from idfrepair.io.assets import sha256_file
from idfrepair.io.idf import canonical, parse_idf
from idfrepair.io.workspace import SessionWorkspace
from idfrepair.knowledge.idd import parse_idd
from idfrepair.runtime.discovery import RuntimeSpec, normalize_version
from idfrepair.runtime.energyplus import EnergyPlusRunner

if TYPE_CHECKING:
    from idfrepair.api.sessions import SessionRecord


_TRANSITION_NAME = re.compile(
    r"^Transition-V(?P<source>\d+(?:-\d+)+)-to-V(?P<target>\d+(?:-\d+)+)(?:\.exe)?$",
    re.IGNORECASE,
)
_MIGRATION_ID = re.compile(r"^migration-[0-9a-f]{20}$")
_REPORT_LIMIT = 12_000
_ISSUE_LIMIT = 100


@dataclass(frozen=True, slots=True)
class TransitionStep:
    """One official, adjacent EnergyPlus version transition."""

    source_version: str
    target_version: str
    executable: Path
    runtime_home: Path


ProcessRunner = Callable[..., subprocess.CompletedProcess[Any]]


def _version_key(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in normalize_version(value).split("."))
    except ValueError:
        return ()


def _filename_version(value: str) -> str:
    return normalize_version(value.replace("-", "."))


def _bounded_text(value: object, limit: int = _REPORT_LIMIT) -> str:
    """Return bounded process text suitable for a JSON report."""

    text = str(value or "")
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n[truncated {omitted} characters]"


def _updater_version_token(value: str) -> str:
    parts = normalize_version(value).split(".")
    while len(parts) < 3:
        parts.append("0")
    return "-".join(parts)


def _stage_transition_assets(step: TransitionStep, destination: Path) -> dict[str, str]:
    """Copy the official read-only assets needed by one step into isolation."""

    source_root = step.executable.parent
    try:
        available = {
            path.name.casefold(): path
            for path in source_root.iterdir()
            if path.is_file()
        }
    except OSError as exc:
        raise RuntimeProcessError("transition_support_assets_unavailable") from exc
    source_token = _updater_version_token(step.source_version)
    target_token = _updater_version_token(step.target_version)
    required_names = (
        f"V{source_token}-Energy+.idd",
        f"V{target_token}-Energy+.idd",
    )
    optional_names = (
        "Energy+.ini",
        f"Report Variables {source_token} to {target_token}.csv",
    )
    destination.mkdir()
    staged: dict[str, str] = {}
    for name in (*required_names, *optional_names):
        source = available.get(name.casefold())
        if source is None:
            if name in required_names:
                raise RuntimeProcessError(f"transition_support_asset_missing:{name}")
            continue
        target = destination / name
        shutil.copy2(source, target)
        staged[target.name] = sha256_file(target)
    return staged


def _changed_tool_artifacts(
    directory: Path,
    staged: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file():
            continue
        identity = sha256_file(path)
        if staged.get(path.name) == identity:
            continue
        rows.append({"name": path.name, "size": path.stat().st_size, "sha256": identity})
        if len(rows) >= 20:
            break
    return rows


def discover_transitions(runtimes: Iterable[RuntimeSpec]) -> tuple[TransitionStep, ...]:
    """Discover official Transition binaries within validated runtime homes.

    When multiple installations provide the same edge, the newest host runtime
    wins.  This normally selects the latest updater directory, which contains the
    most complete set of adjacent IDDs.
    """

    found: dict[tuple[str, str], TransitionStep] = {}
    ordered = sorted(
        runtimes,
        key=lambda row: (_version_key(row.version), str(row.home).casefold()),
    )
    for runtime in ordered:
        updater = runtime.home / "PreProcess" / "IDFVersionUpdater"
        if not updater.is_dir():
            continue
        try:
            children = sorted(updater.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            continue
        for executable in children:
            match = _TRANSITION_NAME.fullmatch(executable.name)
            if (
                match is None
                or not executable.is_file()
                or (os.name != "nt" and not os.access(executable, os.X_OK))
            ):
                continue
            source = _filename_version(match.group("source"))
            target = _filename_version(match.group("target"))
            if not source or not target or _version_key(target) <= _version_key(source):
                continue
            required_assets = (
                updater / f"V{_updater_version_token(source)}-Energy+.idd",
                updater / f"V{_updater_version_token(target)}-Energy+.idd",
            )
            if not all(path.is_file() for path in required_assets):
                continue
            found[(source, target)] = TransitionStep(
                source_version=source,
                target_version=target,
                executable=executable.resolve(),
                runtime_home=runtime.home.resolve(),
            )
    return tuple(
        found[key]
        for key in sorted(found, key=lambda edge: (_version_key(edge[0]), _version_key(edge[1])))
    )


def transition_chain(
    source_version: str,
    target_version: str,
    transitions: Iterable[TransitionStep],
) -> tuple[TransitionStep, ...]:
    """Return a complete upgrade chain, or an empty tuple when none is proven."""

    source = normalize_version(source_version)
    target = normalize_version(target_version)
    if not source or not target or source == target or _version_key(target) <= _version_key(source):
        return ()
    by_source: dict[str, list[TransitionStep]] = {}
    for step in transitions:
        if _version_key(step.target_version) <= _version_key(step.source_version):
            continue
        by_source.setdefault(normalize_version(step.source_version), []).append(step)
    for rows in by_source.values():
        rows.sort(key=lambda row: (_version_key(row.target_version), str(row.executable)))

    queue: deque[tuple[str, tuple[TransitionStep, ...]]] = deque([(source, ())])
    visited = {source}
    while queue:
        current, chain = queue.popleft()
        for step in by_source.get(current, ()):
            next_version = normalize_version(step.target_version)
            if _version_key(next_version) > _version_key(target):
                continue
            next_chain = (*chain, step)
            if next_version == target:
                return next_chain
            if next_version not in visited:
                visited.add(next_version)
                queue.append((next_version, next_chain))
    return ()


def _target_idd_validation(text: str, runtime: RuntimeSpec) -> dict[str, Any]:
    document = parse_idf(text)
    schema = parse_idd(runtime.idd_path.read_text(encoding="utf-8", errors="replace"))
    issues: list[dict[str, Any]] = []
    issue_count = 0

    def add(code: str, obj: Any | None = None, **details: Any) -> None:
        nonlocal issue_count
        issue_count += 1
        if len(issues) >= _ISSUE_LIMIT:
            return
        row: dict[str, Any] = {"code": code}
        if obj is not None:
            row.update({
                "object_index": obj.index,
                "object_type": obj.object_type,
                "object_name": obj.name or None,
            })
        row.update(details)
        issues.append(row)

    if normalize_version(document.version) != normalize_version(runtime.version):
        add(
            "target_version_mismatch",
            actual=normalize_version(document.version),
            expected=normalize_version(runtime.version),
        )
    for parser_issue in document.issues:
        add(str(parser_issue))
    for obj in document.objects:
        definition = schema.get(obj.object_type)
        if definition is None:
            add("unknown_object_type", obj)
            continue
        if len(obj.fields) < definition.minimum_fields:
            add(
                "too_few_fields", obj,
                actual=len(obj.fields), expected_minimum=definition.minimum_fields,
            )
        maximum = definition.maximum_fields
        if maximum is not None and len(obj.fields) > maximum:
            add("too_many_fields", obj, actual=len(obj.fields), expected_maximum=maximum)
        for field in definition.fields:
            if field.required and (
                field.index > len(obj.fields) or not obj.fields[field.index - 1].value.strip()
            ):
                add(
                    "required_field_empty", obj,
                    field_index=field.index, field_name=field.name,
                )
    return {
        "valid": issue_count == 0,
        "issue_count": issue_count,
        "issues": issues,
        "issues_truncated": issue_count > len(issues),
        "checked_object_count": len(document.objects),
        "target_idd_version": normalize_version(schema.version),
        "target_idd_sha256": schema.sha256,
    }


def _changed_object_summary(before: str, after: str) -> dict[str, Any]:
    def inventory(text: str) -> tuple[Counter[str], dict[str, Counter[tuple[str, ...]]]]:
        counts: Counter[str] = Counter()
        signatures: dict[str, Counter[tuple[str, ...]]] = {}
        for obj in parse_idf(text).objects:
            object_type = obj.object_type.strip()
            key = canonical(object_type)
            counts[object_type] += 1
            signatures.setdefault(key, Counter())[tuple(field.value for field in obj.fields)] += 1
        return counts, signatures

    before_counts, before_signatures = inventory(before)
    after_counts, after_signatures = inventory(after)
    changed_keys = sorted(
        set(before_signatures) | set(after_signatures),
        key=str.casefold,
    )
    changed_keys = [
        key for key in changed_keys
        if before_signatures.get(key, Counter()) != after_signatures.get(key, Counter())
    ]
    count_changes = []
    count_names = sorted(set(before_counts) | set(after_counts), key=str.casefold)
    for name in count_names:
        old = before_counts[name]
        new = after_counts[name]
        if old != new:
            count_changes.append({"object_type": name, "before": old, "after": new})
    return {
        "source_object_count": sum(before_counts.values()),
        "target_object_count": sum(after_counts.values()),
        "changed_type_count": len(changed_keys),
        "changed_types": changed_keys[:_ISSUE_LIMIT],
        "changed_types_truncated": len(changed_keys) > _ISSUE_LIMIT,
        "count_changes": count_changes[:_ISSUE_LIMIT],
        "count_changes_truncated": len(count_changes) > _ISSUE_LIMIT,
    }


def _transition_output(path: Path, expected_version: str) -> tuple[Path, str] | None:
    candidates = (
        path,
        path.with_suffix(".idfnew"),
        path.parent / f"{path.name}new",
    )
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        try:
            text = candidate.read_text(encoding="utf-8-sig")
            actual = normalize_version(parse_idf(text).version)
        except (OSError, UnicodeError, ValueError):
            continue
        if actual == normalize_version(expected_version):
            return candidate, text
    return None


def _energyplus_validation(
    record: SessionRecord,
    runtime: RuntimeSpec,
    text: str,
    workspace_root: Path,
) -> dict[str, Any]:
    workspace_root.mkdir(parents=True, exist_ok=True)
    runner = EnergyPlusRunner(
        runtime,
        workspace=SessionWorkspace(workspace_root),
        weather=record.weather,
        dependencies=record.dependencies,
        timeout_seconds=min(int(record.config.timeout_seconds), 300),
    )
    result = runner.run(text, 1)
    return {
        "status": "PASSED" if result.passed else "FAILED",
        "passed": result.passed,
        "returncode": result.returncode,
        "severe_count": result.severe_count,
        "fatal_count": result.fatal_count,
        "warning_count": result.warning_count,
        "process_failure": result.process_failure,
        "timed_out": result.timed_out,
        "diagnostics": _bounded_text(result.diagnostics),
        "wall_seconds": result.wall_seconds,
    }


def migrate_copy(
    record: SessionRecord,
    target_runtime: RuntimeSpec,
    *,
    transitions: Iterable[TransitionStep] | None = None,
    runner: ProcessRunner = subprocess.run,
    run_energyplus: bool = False,
) -> dict[str, Any]:
    """Create, validate, and retain an upgraded copy of one session input."""

    original_path = record.workspace.safe_path("uploads/input.idf")
    original_bytes = original_path.read_bytes()
    try:
        original_text = original_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SessionStateError("migration_input_must_be_utf8") from exc
    source_version = normalize_version(parse_idf(original_text).version)
    target_version = normalize_version(target_runtime.version)
    available = tuple(transitions) if transitions is not None else discover_transitions((target_runtime,))
    chain = transition_chain(source_version, target_version, available)
    if not chain:
        raise SessionStateError(f"official_transition_chain_unavailable:{source_version}:{target_version}")
    if any(not step.executable.is_file() for step in chain):
        raise RuntimeProcessError("transition_executable_unavailable")

    identity = {
        "input_sha256": sha256(original_bytes).hexdigest(),
        "target_version": target_version,
        "target_idd_sha256": sha256_file(target_runtime.idd_path),
        "steps": [
            {
                "source": step.source_version,
                "target": step.target_version,
                "executable_sha256": sha256_file(step.executable),
            }
            for step in chain
        ],
        "run_energyplus": bool(run_energyplus),
    }
    migration_id = "migration-" + sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    migration_root = record.workspace.safe_path("migrations")
    destination = record.workspace.safe_path(f"migrations/{migration_id}")
    report_path = destination / "migration-report.json"
    if report_path.is_file():
        return dict(json.loads(report_path.read_text(encoding="utf-8")))
    if destination.exists():
        raise SessionStateError("migration_artifact_incomplete")
    migration_root.mkdir(parents=True, exist_ok=True)
    build = Path(tempfile.mkdtemp(prefix=f".{migration_id}-", dir=migration_root))
    try:
        current_bytes = original_bytes
        current_text = original_text
        step_reports: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, step in enumerate(chain, start=1):
            step_root = build / f"step-{index:02d}"
            step_root.mkdir()
            step_input = step_root / "input.idf"
            step_input.write_bytes(current_bytes)
            tool_root = step_root / "tool-assets"
            staged_assets = _stage_transition_assets(step, tool_root)
            command = [str(step.executable), str(step_input)]
            try:
                completed = runner(
                    command,
                    cwd=tool_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=120,
                    check=False,
                    text=True,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeProcessError("transition_process_timed_out") from exc
            except OSError as exc:
                raise RuntimeProcessError(f"transition_process_failed:{exc}") from exc
            stdout = _bounded_text(completed.stdout)
            stderr = _bounded_text(completed.stderr)
            if completed.returncode != 0:
                raise RuntimeProcessError(
                    f"transition_process_failed:{step.source_version}:{step.target_version}:"
                    f"{completed.returncode}:{stderr}"
                )
            produced = _transition_output(step_input, step.target_version)
            if produced is None:
                raise RuntimeProcessError(
                    f"transition_output_version_mismatch:{step.source_version}:{step.target_version}"
                )
            output_path, current_text = produced
            current_bytes = output_path.read_bytes()
            tool_artifacts = _changed_tool_artifacts(tool_root, staged_assets)
            shutil.rmtree(tool_root)
            side_artifacts = []
            for artifact in sorted(step_root.iterdir(), key=lambda path: path.name.casefold()):
                if not artifact.is_file() or artifact == output_path:
                    continue
                side_artifacts.append({
                    "name": artifact.name,
                    "size": artifact.stat().st_size,
                    "sha256": sha256_file(artifact),
                })
                if len(side_artifacts) >= 20:
                    break
            step_reports.append({
                "index": index,
                "source_version": step.source_version,
                "target_version": step.target_version,
                "executable_name": step.executable.name,
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "output_sha256": sha256(current_bytes).hexdigest(),
                "side_artifacts": side_artifacts,
                "tool_workspace_artifacts": tool_artifacts,
            })
            for stream in (stdout, stderr):
                for line in stream.splitlines():
                    if line.strip() and len(warnings) < _ISSUE_LIMIT:
                        warnings.append(line.strip())

        artifact_in_build = build / "migrated.idf"
        artifact_in_build.write_bytes(current_bytes)
        final_artifact = destination / "migrated.idf"
        validation = _target_idd_validation(current_text, target_runtime)
        energyplus_validation = (
            _energyplus_validation(
                record, target_runtime, current_text, build / "energyplus-validation",
            )
            if run_energyplus
            else {"status": "NOT_RUN", "passed": None}
        )
        if original_path.read_bytes() != original_bytes:
            raise SessionStateError("migration_original_changed")
        report: dict[str, Any] = {
            "schema_version": "idfrepair.transition-copy.v1",
            "migration_id": migration_id,
            "source_name": record.session.input_name,
            "source_version": source_version,
            "target_version": target_version,
            "transition_step_count": len(chain),
            "steps": step_reports,
            "warnings": warnings,
            "warnings_truncated": len(warnings) >= _ISSUE_LIMIT,
            "original_preserved": True,
            "creates_copy": True,
            "original_sha256": sha256(original_bytes).hexdigest(),
            "migrated_sha256": sha256(current_bytes).hexdigest(),
            "artifact_path": str(final_artifact),
            "report_path": str(destination / "migration-report.json"),
            "target_idd_validation": validation,
            "changed_object_summary": _changed_object_summary(original_text, current_text),
            "energyplus_validation": energyplus_validation,
        }
        (build / "migration-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(build, destination)
        return report
    finally:
        if build.exists():
            shutil.rmtree(build, ignore_errors=True)


def migration_report(record: SessionRecord, migration_id: str) -> dict[str, Any]:
    """Read one bounded migration report from its session workspace."""

    if _MIGRATION_ID.fullmatch(migration_id) is None:
        raise SessionStateError("migration_id_invalid")
    path = record.workspace.safe_path(f"migrations/{migration_id}/migration-report.json")
    if not path.is_file():
        raise KeyError(migration_id)
    return dict(json.loads(path.read_text(encoding="utf-8")))


def migration_artifact(record: SessionRecord, migration_id: str) -> Path:
    """Resolve one completed migrated copy without trusting report paths."""

    report = migration_report(record, migration_id)
    path = record.workspace.safe_path(f"migrations/{migration_id}/migrated.idf")
    if not path.is_file() or sha256_file(path) != report.get("migrated_sha256"):
        raise SessionStateError("migration_artifact_identity_mismatch")
    return path


__all__ = [
    "TransitionStep", "discover_transitions", "migrate_copy", "migration_artifact",
    "migration_report", "transition_chain",
]
