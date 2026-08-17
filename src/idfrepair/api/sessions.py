'''
使用 SQLite 和隔离工作区管理可重启恢复的本地修复会话。

SessionManager.create(): 创建并持久化上传、配置和会话元数据。
SessionManager.execute(): 运行统一引擎并保存轮次、尝试、问题和报告。
SessionManager.resume(): 从持久状态重新执行未完成会话。
SessionManager.cancel(): 回滚并标记会话取消。
'''

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import threading
from typing import Any, Iterable, Iterator, Mapping
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from idfrepair.api.messages import error_message, status_message
from idfrepair.api.presentation import session_display_metadata
from idfrepair.api.schemas import ModelPreflightReport
from idfrepair.api.create_intent import (
    MAX_CREATE_INTENT_SCAN,
    SessionCreateIntent,
    create_recovery_leaf,
    publish_create_intent,
    read_create_intent,
    read_create_intent_at,
    recovery_session_id,
    remove_create_intent,
    remove_create_intent_at,
)
from idfrepair.api.atomic_rename import rename_noreplace
from idfrepair.api.weather_storage import (
    WeatherBlob,
    publish_weather_blob,
    validate_upload_display_leaf,
    validate_weather_upload,
    verify_weather_blob,
)
from idfrepair.api.workbench import (
    field_context as build_field_context,
    object_context as build_object_context,
    source_context as build_source_context,
)
from idfrepair.audit.model import audit_model
from idfrepair.capabilities.release_profile import (
    EXPECTED_SUPPORT_REGISTRY_SHA256,
    RELEASE_PROFILE_ID,
)
from idfrepair.capabilities.reporting import component_statuses, support_coverage_summary
from idfrepair.candidates.base import CandidateContext
from idfrepair.cli import select_input_runtime
from idfrepair.config import EngineConfig
from idfrepair.domain.enums import (
    OperationKind, Provenance, QuestionType, RepairMode, RepairStatus, RiskLevel,
)
from idfrepair.domain.errors import SessionStateError
from idfrepair.domain.models import (
    CandidateEvidence, CandidateScore, RepairCandidate, RepairOperation,
    PendingRepairState, RepairOutcome, RepairSession, UserAnswer, UserQuestion,
    pending_repair_state_is_valid, to_primitive, utc_now,
)
from idfrepair.engine.orchestrator import UnifiedEngine
from idfrepair.experimental.geometry import preview_geometry_lab
from idfrepair.interaction.answers import answer_to_candidate
from idfrepair.io.assets import sha256_file
from idfrepair.io.idf import parse_idf, text_sha256
from idfrepair.io.workspace import SessionWorkspace
from idfrepair.knowledge.idd import parse_idd
from idfrepair.knowledge.object_graph import build_object_graph
from idfrepair.knowledge.rdd import parse_rdd
from idfrepair.memory.database import MemoryDatabase
from idfrepair.memory.learning import save_validated_rule, template_fingerprint
from idfrepair.memory.models import RepairRule, RuleScope
from idfrepair.memory.repository import RuleRepository
from idfrepair.osm.artifacts import (
    bounded_osm_failure_reason as _bounded_osm_failure_reason,
    json_artifact as _json_artifact,
    publish_osm_artifacts as _publish_osm_artifacts,
    read_osm_artifact as _read_osm_artifact,
)
from idfrepair.osm.protocol import OSMWorkflowReport
from idfrepair.osm.bridge import _valid_writeback_report, _validated_inventory
from idfrepair.osm.verification import _forward_report_evidence
from idfrepair.osm.workflow import (
    OSMChildVerificationFailed,
    OSMExecutionAuthority,
    OSMVerifiedEvidence,
    build_failed_osm_workflow_report,
    build_verified_osm_workflow_report,
    execute_osm_writeback_verification,
    prepare_osm_execution,
    validate_osm_simulation,
)
from idfrepair.preflight.model import target_issue_remains
from idfrepair.project.readiness import (
    blocking_readiness_checks,
    inspect_readiness,
    normalize_project_path,
)
from idfrepair.preflight.model import apply_model_preflight, build_model_preflight
from idfrepair.reporting.session_report import build_session_report, write_session_report
from idfrepair.runtime.cache import EnergyPlusCache
from idfrepair.runtime.energyplus import EnergyPlusRunner
from idfrepair.runtime.energyplus import dependency_run_path, weather_asset_ready
from idfrepair.validation.terminal_safety import repaired_artifact_allowed


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UTF8_BOM = b"\xef\xbb\xbf"
_OSM_VERIFIED_LEAVES = (
    "osm-writeback.json", "repaired.osm", "osm-post-derived.idf",
    "osm-source-preflight.json", "osm-source-forward.json", "osm-patch.json",
    "osm-execution-preflight.json", "osm-execution-patch.json",
    "osm-patcher-report.json", "osm-source-audit.json", "osm-child-audit.json",
    "osm-post-forward.json", "osm-post-preflight.json", "source.osm",
)


def _atomic_replace_file(path: Path, content: bytes) -> None:
    """Publish one complete private file by same-directory atomic replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}-{uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        remaining = memoryview(content)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("private_checkpoint_short_write")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
        parent_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _read_workspace_file_nofollow(
    workspace: SessionWorkspace,
    relative: str,
    *,
    required: bool = True,
    max_bytes: int = MAX_UPLOAD_BYTES,
    error_token: str = "settings_inherited_asset_invalid",
) -> bytes | None:
    """Read one regular workspace leaf without following any path component."""

    parts = relative.split("/")
    if (
        not parts
        or any(not part or part in {".", ".."} for part in parts)
        or relative.startswith("/")
    ):
        raise SessionStateError(error_token)
    descriptors: list[int] = []
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptors.append(os.open(
            workspace.root,
            flags | os.O_DIRECTORY,
        ))
        for part in parts[:-1]:
            descriptors.append(os.open(
                part,
                flags | os.O_DIRECTORY,
                dir_fd=descriptors[-1],
            ))
        file_descriptor = os.open(
            parts[-1], flags, dir_fd=descriptors[-1],
        )
        descriptors.append(file_descriptor)
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
            raise SessionStateError(error_token)
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(file_descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise SessionStateError(error_token)
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_descriptor, 1):
            raise SessionStateError(error_token)
        return b"".join(chunks)
    except FileNotFoundError as exc:
        if not required:
            return None
        raise SessionStateError(error_token) from exc
    except SessionStateError:
        raise
    except (OSError, ValueError) as exc:
        raise SessionStateError(error_token) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _normalized_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


_REPAIR_FAMILIES = frozenset({
    "ems", "external_dependency", "extra_field", "geometry", "hvac_reference",
    "output_variable", "reference", "reference_schedule", "schema", "syntax",
    "version_migration",
})
_WEATHER_UNSET = object()
_WEATHER_COLUMNS = (
    "weather_path",
    "weather_sha256",
    "weather_size_bytes",
    "weather_original_name",
    "weather_readiness_json",
)
@dataclass(slots=True)
class _SessionLockEntry:
    """Stable per-session mutation lock with deletion and cleanup state."""

    lock: Any = field(default_factory=threading.RLock)
    users: int = 0
    tombstone: bool = False
    osm_writeback_in_progress: bool = False


def _write_result_artifact(record: SessionRecord, text: str) -> None:
    payload = text.encode("utf-8")
    if record.interaction_context.get("input_had_utf8_bom") is True:
        payload = UTF8_BOM + payload
    record.workspace.safe_path("result.idf").write_bytes(payload)


def capture_preprocessing_artifact(
    workspace: SessionWorkspace,
    results: Iterable[Any],
    *,
    output_sha256: str,
) -> dict[str, Any]:
    """Copy the expanded form matching the final IDF into a stable session artifact."""
    rows = tuple(results)
    object_types = sorted({
        str(object_type)
        for row in rows
        for object_type in getattr(row, "preprocessing_object_types", ())
    }, key=str.casefold)
    source = next((
        Path(str(row.expanded_input_path))
        for row in reversed(rows)
        if getattr(row, "input_sha256", None) == output_sha256
        and getattr(row, "expanded_input_path", None)
        and Path(str(row.expanded_input_path)).is_file()
    ), None)
    destination = workspace.safe_path("artifacts/expanded.expidf")
    if source is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
    available = destination.is_file()
    return {
        "required": any(bool(getattr(row, "preprocessing_required", False)) for row in rows),
        "used": any(bool(getattr(row, "preprocessing_used", False)) for row in rows),
        "object_types": object_types,
        "artifact_available": available,
        "artifact_name": "expanded.expidf" if available else None,
        "artifact_sha256": sha256_file(destination) if available else None,
        "main_idf_preserves_templates": True,
    }


@dataclass(slots=True)
class SessionRecord:
    '''封装一个会话的运行对象和全部可持久恢复状态。'''

    session: RepairSession
    workspace: SessionWorkspace
    input_text: str
    config: EngineConfig
    energyplus_path: Path | None
    energyplus_version: str | None
    weather: Path | None = None
    weather_sha256: str | None = None
    weather_size_bytes: int | None = None
    weather_original_name: str | None = None
    weather_readiness: dict[str, Any] | None = None
    dependencies: list[Path] = field(default_factory=list)
    approved_candidate_ids: list[str] = field(default_factory=list)
    runtime_identity: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] | None = None
    lifecycle_status: str = "CREATED"
    archived: bool = False
    selected_rule_set_id: str = "default"
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    persisted_outcome: dict[str, Any] | None = None
    extra_candidates: list[RepairCandidate] = field(default_factory=list)
    interaction_context: dict[str, Any] = field(default_factory=dict)


def _config(value: Mapping[str, Any]) -> EngineConfig:
    '''从持久 JSON 恢复经过同一边界验证的 EngineConfig。'''
    return EngineConfig(
        mode=RepairMode(str(value.get("mode", RepairMode.SAFE_AUTO.value))),
        max_rounds=int(value.get("max_rounds", 6)),
        max_candidates_per_root=int(value.get("max_candidates_per_root", 3)),
        max_total_energyplus_runs=int(value.get("max_total_energyplus_runs", 20)),
        max_backtracks=int(value.get("max_backtracks", 1)),
        max_wall_time=float(value.get("max_wall_time", 600.0)),
        max_model_tool_calls=int(value.get("max_model_tool_calls", 12)),
        maximum_automatic_risk=RiskLevel(str(value.get("maximum_automatic_risk", RiskLevel.LOW.value))),
        minimum_automatic_confidence=float(value.get("minimum_automatic_confidence", 0.85)),
        model=str(value.get("model", "none")),
        model_base_path=(str(value["model_base_path"]) if value.get("model_base_path") else None),
        model_adapter_path=(str(value["model_adapter_path"]) if value.get("model_adapter_path") else None),
        model_runtime_python=(
            str(value["model_runtime_python"]) if value.get("model_runtime_python") else None
        ),
        timeout_seconds=int(value.get("timeout_seconds", 120)),
    )


def _question(value: Mapping[str, Any]) -> UserQuestion:
    '''从 JSON 恢复统一问题协议。'''
    return UserQuestion(
        question_id=str(value["question_id"]),
        question_type=QuestionType(str(value["question_type"])),
        root_id=str(value["root_id"]),
        prompt=str(value["prompt"]),
        choices=tuple(dict(row) for row in value.get("choices", ())),
        required=bool(value.get("required", True)),
        metadata=dict(value.get("metadata", {})),
    )


def _answer(value: Mapping[str, Any]) -> UserAnswer:
    '''从 JSON 恢复用户回答及时间身份。'''
    return UserAnswer(
        question_id=str(value["question_id"]),
        value=value.get("value"),
        answered_at=str(value.get("answered_at") or utc_now()),
    )


def _line_number(text: str, offset: int) -> int:
    """Return a one-based line number for LF, CRLF, or legacy CR text."""
    prefix = text[:max(0, offset)]
    return 1 + prefix.count("\n") + prefix.count("\r") - prefix.count("\r\n")


def _optional_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _question_display_rows(record: SessionRecord) -> list[dict[str, Any]]:
    """Add read-only source context without changing the persisted question contract."""
    rows = [dict(row) for row in to_primitive(record.session.pending_questions)]
    if not rows:
        return rows
    persisted_text = (record.persisted_outcome or {}).get("output_text")
    source_text = persisted_text if isinstance(persisted_text, str) else record.input_text
    try:
        document = parse_idf(source_text)
    except Exception:
        return rows

    roots = {
        str(root.get("root_id")): root
        for root in (record.persisted_outcome or {}).get("initial_diagnostics", ())
        if isinstance(root, Mapping) and root.get("root_id")
    }

    def target_from(value: Mapping[str, Any]) -> dict[str, Any] | None:
        object_index = _optional_index(value.get("object_index"))
        field_index = _optional_index(value.get("field_index"))
        target = {
            "object_type": value.get("object_type"),
            "object_name": value.get("object_name"),
            "object_index": object_index,
            "field_index": field_index,
            "field_name": value.get("field_name"),
        }
        if not any(item is not None and item != "" for item in target.values()):
            return None
        return target

    def resolve_target(target: Mapping[str, Any]) -> tuple[dict[str, Any], Any | None]:
        object_index = _optional_index(target.get("object_index"))
        obj = document.objects[object_index] if (
            object_index is not None and 0 <= object_index < len(document.objects)
        ) else None
        if obj is None and target.get("object_type"):
            matches = document.find_objects(
                str(target["object_type"]),
                str(target["object_name"]) if target.get("object_name") else None,
            )
            obj = matches[0] if len(matches) == 1 else None
        resolved = dict(target)
        if obj is not None:
            resolved.update({
                "object_type": obj.object_type,
                "object_name": obj.name or None,
                "object_index": obj.index,
            })
            field_index = _optional_index(resolved.get("field_index"))
            if field_index is not None and 1 <= field_index <= len(obj.fields):
                resolved["line"] = _line_number(source_text, obj.fields[field_index - 1].start)
        return resolved, obj

    def object_context(obj: Any) -> dict[str, Any]:
        start = obj.start
        while start < obj.end and source_text[start].isspace():
            start += 1
        line_end = source_text.find("\n", obj.end)
        if line_end < 0:
            line_end = len(source_text)
        snippet = source_text[start:line_end].rstrip("\r")
        truncated = len(snippet) > 12_000
        if truncated:
            snippet = f"{snippet[:6000]}\n! … IDFRepair context truncated …\n{snippet[-6000:]}"
        return {
            "object_type": obj.object_type,
            "object_name": obj.name or None,
            "object_index": obj.index,
            "line_start": _line_number(source_text, start),
            "line_end": _line_number(source_text, max(start, obj.end - 1)),
            "snippet": snippet,
            "truncated": truncated,
        }

    for row in rows:
        metadata = dict(row.get("metadata") or {})
        proposed_changes: list[dict[str, Any]] = []
        targets: list[dict[str, Any]] = []
        metadata_target = target_from(metadata)
        if metadata_target:
            targets.append(metadata_target)
        for choice in row.get("choices") or ():
            if not isinstance(choice, Mapping):
                continue
            choice_value = choice.get("value")
            if isinstance(choice_value, Mapping):
                choice_target = target_from(choice_value)
                if choice_target:
                    targets.append(choice_target)
            for operation in choice.get("operations") or ():
                if not isinstance(operation, Mapping):
                    continue
                operation_target = target_from(operation)
                if operation_target:
                    targets.append(operation_target)
                proposed_changes.append({
                    "candidate_id": choice.get("candidate_id"),
                    "provider": choice.get("provider"),
                    "kind": operation.get("kind"),
                    **(operation_target or {}),
                    "old_value": operation.get("old_value"),
                    "new_value": operation.get("new_value"),
                    "vertices": operation.get("vertices") or (),
                    "object_text": operation.get("object_text"),
                })
        root = roots.get(str(row.get("root_id")))
        if root:
            root_metadata = dict(root.get("metadata") or {})
            metadata["diagnostic_context"] = {
                "family": root.get("family"),
                "severity": root.get("severity"),
                "message": root.get("message"),
            }
            owner_bindings = root_metadata.get("owner_bindings")
            if isinstance(owner_bindings, (list, tuple)) and len(owner_bindings) == 1:
                binding = owner_bindings[0]
                if isinstance(binding, (list, tuple)) and len(binding) >= 4:
                    owner_target = target_from({
                        "object_index": binding[0],
                        "field_index": binding[1],
                        "object_type": binding[2],
                        "field_name": binding[3],
                    })
                    if owner_target:
                        targets.append(owner_target)
            elif root.get("object_type"):
                root_target = target_from({**root_metadata, **dict(root)})
                if root_target:
                    targets.append(root_target)

        resolved_targets: list[dict[str, Any]] = []
        contexts: list[dict[str, Any]] = []
        context_indices: set[int] = set()
        for target in targets:
            resolved, obj = resolve_target(target)
            resolved_targets.append(resolved)
            if obj is not None and obj.index not in context_indices and len(contexts) < 5:
                contexts.append(object_context(obj))
                context_indices.add(obj.index)
        if resolved_targets:
            metadata["target"] = resolved_targets[0]
            metadata["targets"] = resolved_targets
        if contexts:
            metadata["idf_contexts"] = contexts
        if proposed_changes:
            metadata["proposed_changes"] = proposed_changes
        row["metadata"] = metadata
    return rows


def _candidate(value: Mapping[str, Any]) -> RepairCandidate:
    '''从持久 JSON 恢复用户提供且仍需统一验证的有限候选。'''
    operations = tuple(RepairOperation(
        kind=OperationKind(str(row["kind"])),
        object_type=row.get("object_type"),
        object_name=row.get("object_name"),
        object_index=row.get("object_index"),
        field_index=row.get("field_index"),
        field_name=row.get("field_name"),
        old_value=row.get("old_value"),
        new_value=row.get("new_value"),
        vertices=tuple(tuple(float(item) for item in point) for point in row.get("vertices", ())),
        object_text=row.get("object_text"),
        metadata=dict(row.get("metadata", {})),
    ) for row in value.get("operations", ()))
    evidence = tuple(CandidateEvidence(
        kind=str(row["kind"]),
        source=str(row["source"]),
        strength=float(row["strength"]),
        details=dict(row.get("details", {})),
    ) for row in value.get("evidence", ()))
    score_value = value.get("score")
    score = CandidateScore(
        total=float(score_value["total"]),
        components={str(key): float(item) for key, item in score_value.get("components", {}).items()},
    ) if isinstance(score_value, Mapping) else None
    return RepairCandidate(
        candidate_id=str(value["candidate_id"]),
        provider=str(value["provider"]),
        root_id=str(value["root_id"]),
        family=str(value["family"]),
        operations=operations,
        evidence=evidence,
        risk=RiskLevel(str(value["risk"])),
        confidence=float(value["confidence"]),
        input_sha256=str(value["input_sha256"]),
        idd_sha256=str(value["idd_sha256"]),
        version=str(value["version"]),
        requires_user_confirmation=bool(value.get("requires_user_confirmation", False)),
        rollback_supported=bool(value.get("rollback_supported", True)),
        provenance=Provenance(str(value.get("provenance", Provenance.USER_SUPPLIED.value))),
        score=score,
        metadata=dict(value.get("metadata", {})),
    )


class SessionManager:
    '''以 SQLite 为事实来源，并用内存缓存当前进程已读取的会话。'''

    def __init__(
        self,
        root: Path | None = None,
        *,
        rule_repository: RuleRepository | None = None,
        osm_bridge: object | None = None,
    ) -> None:
        self.root = (root or Path(tempfile.gettempdir()) / "idfrepair-sessions").expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "sessions.sqlite3"
        self.rule_repository = rule_repository or RuleRepository(
            MemoryDatabase(self.root / "repair_memory.sqlite3")
        )
        self.osm_bridge = osm_bridge
        self._records: dict[str, SessionRecord] = {}
        self._osm_workflow_cache: dict[
            str, tuple[tuple[tuple[str, str], ...], dict[str, Any]]
        ] = {}
        self._lock = threading.RLock()
        self._session_locks: dict[str, _SessionLockEntry] = {}
        self._create_intent_invalid: set[str] = set()
        self._create_recovery_quarantined: set[str] = set()
        self._create_commit_unknown: set[str] = set()
        self._parent_lineage_invalid: set[str] = set()
        self._parent_lineage_commit_unknown: set[str] = set()
        self._create_intent_scan_incomplete = False
        self._create_intent_storage_invalid = False
        self._initialize()
        self._reconcile_session_create_intents()
        self._reconcile_parent_lineage()
        self._reconcile_osm_writeback_commits()

    @contextmanager
    def _session_guard(
        self,
        session_id: str,
        *,
        mode: str = "read",
    ) -> Iterator[_SessionLockEntry]:
        """Acquire a stable session lock and safely reclaim unused identities."""

        if mode not in {"read", "mutation", "workflow", "delete"}:
            raise ValueError("session_guard_mode_invalid")
        with self._lock:
            entry = self._session_locks.setdefault(session_id, _SessionLockEntry())
            if mode == "mutation" and entry.osm_writeback_in_progress:
                raise SessionStateError("osm_child_writeback_in_progress")
            entry.users += 1
            if mode == "workflow":
                if entry.osm_writeback_in_progress:
                    entry.users -= 1
                    raise SessionStateError("osm_child_writeback_in_progress")
                entry.osm_writeback_in_progress = True
            if mode == "delete":
                entry.tombstone = True
        try:
            with entry.lock:
                if entry.tombstone and mode != "delete":
                    raise SessionStateError("session_deletion_pending")
                try:
                    yield entry
                finally:
                    if mode == "workflow":
                        with self._lock:
                            entry.osm_writeback_in_progress = False
        finally:
            with self._lock:
                entry.users -= 1
                if entry.users == 0 and (
                    entry.tombstone or session_id not in self._records
                ):
                    if self._session_locks.get(session_id) is entry:
                        self._session_locks.pop(session_id, None)

    def _connect(self) -> sqlite3.Connection:
        '''创建启用外键、WAL 和忙等待的会话数据库连接。'''
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        '''建立持久会话表；已有 schema 和记录保持不变。'''
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    workspace_path TEXT NOT NULL,
                    input_name TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT,
                    lifecycle_status TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    energyplus_path TEXT,
                    energyplus_version TEXT,
                    weather_path TEXT,
                    weather_sha256 TEXT,
                    weather_size_bytes INTEGER,
                    weather_original_name TEXT,
                    weather_readiness_json TEXT,
                    dependencies_json TEXT NOT NULL,
                    approved_candidate_ids_json TEXT NOT NULL,
                    runtime_identity_json TEXT NOT NULL,
                    pending_questions_json TEXT NOT NULL,
                    answers_json TEXT NOT NULL,
                    selected_rule_set_id TEXT NOT NULL,
                    model_calls_json TEXT NOT NULL,
                    outcome_json TEXT,
                    report_json TEXT,
                    extra_candidates_json TEXT NOT NULL DEFAULT '[]',
                    interaction_context_json TEXT NOT NULL DEFAULT '{}'
                )
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
            if "extra_candidates_json" not in columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN extra_candidates_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "interaction_context_json" not in columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN interaction_context_json TEXT NOT NULL DEFAULT '{}'"
                )
            for column, kind in (
                ("weather_sha256", "TEXT"),
                ("weather_size_bytes", "INTEGER"),
                ("weather_original_name", "TEXT"),
                ("weather_readiness_json", "TEXT"),
            ):
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE sessions ADD COLUMN {column} {kind}"
                    )
            connection.execute(
                "UPDATE sessions SET lifecycle_status = 'RECOVERABLE' WHERE lifecycle_status = 'RUNNING'"
            )

    @staticmethod
    def _preallocated_session_id(value: str) -> bool:
        return len(value) == 32 and all(character in "0123456789abcdef" for character in value)

    def _create_preallocated_workspace(self, session_id: str) -> SessionWorkspace:
        """Create one direct UUID workspace without following an existing node."""

        if not self._preallocated_session_id(session_id):
            raise SessionStateError("session_identity_invalid")
        root = self.root / "workspaces"
        root.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(root, flags)
        try:
            os.mkdir(session_id, 0o700, dir_fd=descriptor)
            child = os.open(session_id, flags, dir_fd=descriptor)
            os.close(child)
            os.fsync(descriptor)
        except OSError as exc:
            raise SessionStateError("session_workspace_create_failed") from exc
        finally:
            os.close(descriptor)
        return SessionWorkspace(root / session_id)

    @staticmethod
    def _create_intent_input_matches(
        workspace: Path | int, intent: SessionCreateIntent,
    ) -> bool:
        held: list[int] = []
        input_descriptor = -1
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            held.append(
                os.dup(workspace) if type(workspace) is int else os.open(workspace, flags)
            )
            held.append(os.open("uploads", flags, dir_fd=held[-1]))
            leaf_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            input_descriptor = os.open("input.idf", leaf_flags, dir_fd=held[-1])
            node = os.fstat(input_descriptor)
            if not stat.S_ISREG(node.st_mode) or node.st_size > MAX_UPLOAD_BYTES:
                return False
            content = os.read(input_descriptor, node.st_size + 1)
            return (
                len(content) == node.st_size
                and text_sha256(content.decode("utf-8-sig")) == intent.input_sha256
            )
        except (OSError, UnicodeError):
            return False
        finally:
            if input_descriptor >= 0:
                os.close(input_descriptor)
            for descriptor in reversed(held):
                os.close(descriptor)

    def _quarantine_create_intent_workspace(
        self,
        workspaces_descriptor: int,
        child_descriptor: int,
        session_id: str,
    ) -> str | None:
        """Stage a public name, then quarantine only the held child inode."""

        held = os.fstat(child_descriptor)
        staged_leaf = create_recovery_leaf(session_id)
        try:
            rename_noreplace(
                workspaces_descriptor, session_id,
                workspaces_descriptor, staged_leaf,
            )
            os.fsync(workspaces_descriptor)
            staged_descriptor = os.open(
                staged_leaf,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=workspaces_descriptor,
            )
        except (OSError, SessionStateError):
            return None
        try:
            staged = os.fstat(staged_descriptor)
            if (staged.st_dev, staged.st_ino) != (held.st_dev, held.st_ino):
                try:
                    rename_noreplace(
                        workspaces_descriptor, staged_leaf,
                        workspaces_descriptor, session_id,
                    )
                    os.fsync(workspaces_descriptor)
                except (OSError, SessionStateError):
                    pass
                return None
            self._create_recovery_quarantined.add(session_id)
        finally:
            os.close(staged_descriptor)
        return staged_leaf

    def _complete_create_intent_recovery(
        self, session_id: str, child_descriptor: int,
    ) -> None:
        """Load one exact committed row and retire its create intent."""

        try:
            record = self._load(session_id)
            remove_create_intent_at(child_descriptor)
        except (SessionStateError, OSError):
            self._create_intent_invalid.add(session_id)
            return
        if record.interaction_context.pop(
            "session_create_intent_cleanup_pending", None,
        ) is not None:
            self._persist(record)
        self._records[session_id] = record

    def _create_intent_row_matches(
        self,
        session_id: str,
        row: Mapping[str, Any],
        intent: SessionCreateIntent,
        child_descriptor: int,
    ) -> bool:
        """Bind one marker and held input to its exact durable identity."""

        workspace = self.root / "workspaces" / session_id
        return (
            row["workspace_path"] == str(workspace)
            and row["input_name"] == intent.input_name
            and row["input_sha256"] == intent.input_sha256
            and self._create_intent_input_matches(child_descriptor, intent)
        )

    def _reconcile_staged_create_intent(
        self, workspaces_descriptor: int, staged_leaf: str, session_id: str,
    ) -> None:
        """Restore an exact committed stage or retain it as quarantine."""

        child_descriptor = -1
        try:
            child_descriptor = os.open(
                staged_leaf,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=workspaces_descriptor,
            )
            intent = read_create_intent_at(
                child_descriptor, expected_session_id=session_id,
            )
        except (OSError, SessionStateError):
            try:
                self._durable_session_row(session_id)
            except KeyError:
                self._create_recovery_quarantined.add(session_id)
            else:
                self._create_intent_invalid.add(session_id)
            if child_descriptor >= 0:
                os.close(child_descriptor)
            return
        try:
            row = self._durable_session_row(session_id)
        except KeyError:
            self._create_recovery_quarantined.add(session_id)
            os.close(child_descriptor)
            return
        if not self._create_intent_row_matches(
            session_id, row, intent, child_descriptor,
        ):
            self._create_intent_invalid.add(session_id)
            os.close(child_descriptor)
            return
        restored = False
        public_descriptor = -1
        try:
            rename_noreplace(
                workspaces_descriptor, staged_leaf,
                workspaces_descriptor, session_id,
            )
            restored = True
            public_descriptor = os.open(
                session_id,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=workspaces_descriptor,
            )
            public = os.fstat(public_descriptor)
            staged = os.fstat(child_descriptor)
            if (public.st_dev, public.st_ino) != (staged.st_dev, staged.st_ino):
                raise SessionStateError("session_create_intent_invalid")
            os.fsync(workspaces_descriptor)
        except (OSError, SessionStateError):
            if restored:
                try:
                    rename_noreplace(
                        workspaces_descriptor, session_id,
                        workspaces_descriptor, staged_leaf,
                    )
                    os.fsync(workspaces_descriptor)
                except (OSError, SessionStateError):
                    pass
            self._create_intent_invalid.add(session_id)
            os.close(child_descriptor)
            if public_descriptor >= 0:
                os.close(public_descriptor)
            return
        os.close(public_descriptor)
        self._complete_create_intent_recovery(session_id, child_descriptor)
        os.close(child_descriptor)

    def _reconcile_public_create_intent(
        self, workspaces_descriptor: int, session_id: str,
    ) -> None:
        """Reconcile one direct UUID workspace while holding its descriptor."""

        child_descriptor = -1
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            child_descriptor = os.open(
                session_id, flags, dir_fd=workspaces_descriptor,
            )
            intent = read_create_intent_at(
                child_descriptor, expected_session_id=session_id,
            )
        except FileNotFoundError:
            if child_descriptor >= 0:
                os.close(child_descriptor)
            return
        except (OSError, SessionStateError):
            if child_descriptor >= 0:
                os.close(child_descriptor)
            try:
                self._durable_session_row(session_id)
            except KeyError:
                pass
            else:
                self._create_intent_invalid.add(session_id)
            return
        try:
            row = self._durable_session_row(session_id)
        except KeyError:
            if (
                self._create_intent_input_matches(child_descriptor, intent)
                and self._quarantine_create_intent_workspace(
                    workspaces_descriptor, child_descriptor, session_id,
                ) is None
            ):
                self._create_intent_invalid.add(session_id)
            os.close(child_descriptor)
            return
        if not self._create_intent_row_matches(
            session_id, row, intent, child_descriptor,
        ):
            self._create_intent_invalid.add(session_id)
            os.close(child_descriptor)
            return
        self._complete_create_intent_recovery(session_id, child_descriptor)
        os.close(child_descriptor)

    def _reconcile_session_create_intents(self) -> None:
        """Classify only bounded, direct, marker-owned preallocated workspaces."""

        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        root_descriptor = workspaces_descriptor = -1
        try:
            root_descriptor = os.open(self.root, flags)
            workspaces_descriptor = os.open(
                "workspaces", flags, dir_fd=root_descriptor,
            )
        except FileNotFoundError:
            return
        except OSError:
            self._create_intent_storage_invalid = True
            return
        try:
            public_candidates: list[str] = []
            staged_candidates: dict[str, list[str]] = {}
            with os.scandir(workspaces_descriptor) as entries:
                for index, entry in enumerate(entries):
                    if index == MAX_CREATE_INTENT_SCAN:
                        self._create_intent_scan_incomplete = True
                        break
                    if self._preallocated_session_id(entry.name):
                        public_candidates.append(entry.name)
                    else:
                        session_id = recovery_session_id(entry.name)
                        if session_id is not None:
                            staged_candidates.setdefault(session_id, []).append(
                                entry.name
                            )

            staged_session_ids = set(staged_candidates)
            for session_id, leaves in staged_candidates.items():
                if len(leaves) != 1:
                    try:
                        self._durable_session_row(session_id)
                    except KeyError:
                        self._create_recovery_quarantined.add(session_id)
                    else:
                        self._create_intent_invalid.add(session_id)
                    continue
                self._reconcile_staged_create_intent(
                    workspaces_descriptor, leaves[0], session_id,
                )
            for session_id in public_candidates:
                if session_id not in staged_session_ids:
                    self._reconcile_public_create_intent(
                        workspaces_descriptor, session_id,
                    )
        finally:
            if workspaces_descriptor >= 0:
                os.close(workspaces_descriptor)
            if root_descriptor >= 0:
                os.close(root_descriptor)

    @staticmethod
    def _record_database_identity(record: SessionRecord) -> dict[str, Any]:
        """Serialize the exact row inserted for a newly created session."""

        session = record.session
        return {
            "session_id": session.session_id,
            "workspace_path": str(record.workspace.root),
            "input_name": session.input_name,
            "input_sha256": session.input_sha256,
            "mode": session.mode.value,
            "status": session.status.value if session.status else None,
            "lifecycle_status": record.lifecycle_status,
            "archived": int(record.archived),
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "config_json": json.dumps(record.config.to_dict(), sort_keys=True),
            "energyplus_path": str(record.energyplus_path) if record.energyplus_path else None,
            "energyplus_version": record.energyplus_version,
            "weather_path": str(record.weather) if record.weather else None,
            "weather_sha256": record.weather_sha256,
            "weather_size_bytes": record.weather_size_bytes,
            "weather_original_name": record.weather_original_name,
            "weather_readiness_json": (
                json.dumps(record.weather_readiness, ensure_ascii=False, sort_keys=True)
                if record.weather_readiness is not None else None
            ),
            "dependencies_json": json.dumps([str(path) for path in record.dependencies]),
            "approved_candidate_ids_json": json.dumps(record.approved_candidate_ids),
            "runtime_identity_json": json.dumps(to_primitive(record.runtime_identity), sort_keys=True),
            "pending_questions_json": json.dumps(
                to_primitive(session.pending_questions), ensure_ascii=False, sort_keys=True,
            ),
            "answers_json": json.dumps(
                to_primitive(session.answers), ensure_ascii=False, sort_keys=True,
            ),
            "selected_rule_set_id": record.selected_rule_set_id,
            "model_calls_json": json.dumps(
                to_primitive(record.model_calls), ensure_ascii=False, sort_keys=True,
            ),
            "outcome_json": (
                json.dumps(record.persisted_outcome, ensure_ascii=False, sort_keys=True)
                if record.persisted_outcome else None
            ),
            "report_json": (
                json.dumps(record.report, ensure_ascii=False, sort_keys=True)
                if record.report else None
            ),
            "extra_candidates_json": json.dumps(
                to_primitive(record.extra_candidates), ensure_ascii=False, sort_keys=True,
            ),
            "interaction_context_json": json.dumps(
                to_primitive(record.interaction_context), ensure_ascii=False, sort_keys=True,
            ),
        }

    @staticmethod
    def _row_matches_identity(
        row: Mapping[str, Any], expected: Mapping[str, Any],
    ) -> bool:
        return all(row[field] == value for field, value in expected.items())

    def _parent_lineage_commit_state(
        self,
        session_id: str,
        *,
        old: Mapping[str, Any],
        new: Mapping[str, Any],
    ) -> str:
        """Classify a lost parent commit acknowledgement with one exact retry."""

        for _attempt in range(2):
            try:
                row = self._durable_session_row(session_id)
            except Exception:
                continue
            if self._row_matches_identity(row, new):
                return "NEW"
            if self._row_matches_identity(row, old):
                return "OLD"
            return "THIRD"
        return "UNKNOWN"

    def _reconcile_parent_lineage(self) -> None:
        """Fail closed when durable parent and child lineage disagree."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT session_id,interaction_context_json FROM sessions"
            ).fetchall()
        contexts: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                value = json.loads(row["interaction_context_json"])
            except (TypeError, ValueError):
                continue
            if type(value) is dict:
                contexts[str(row["session_id"])] = value
        for parent_id, parent_context in contexts.items():
            child_id = parent_context.get("preflight_child_session_id")
            if type(child_id) is not str:
                continue
            child_context = contexts.get(child_id)
            if (
                child_context is None
                or child_context.get("preflight_parent_session_id") != parent_id
            ):
                self._parent_lineage_invalid.add(parent_id)
                if child_context is not None:
                    self._parent_lineage_invalid.add(child_id)

    def _reconcile_osm_writeback_commits(self) -> None:
        """Resolve durable OSM transitions from the marker-last publication."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT session_id,interaction_context_json FROM sessions"
            ).fetchall()
        for row in rows:
            try:
                context = json.loads(row["interaction_context_json"])
            except (TypeError, ValueError):
                continue
            if (
                type(context) is not dict
                or context.get("source_type") != "OSM"
                or context.get("osm_writeback_commit_state") != "COMMITTING"
            ):
                continue
            session_id = str(row["session_id"])
            record: SessionRecord | None = None
            try:
                record = self._load(session_id)
                marker = self._osm_writeback_report_for_locked_record(record)
            except SessionStateError as exc:
                if str(exc) == "osm_writeback_report_not_available":
                    continue
                if record is None:
                    continue
                record.interaction_context.update({
                    "osm_writeback_status": "OSM_WRITEBACK_FAILED",
                    "osm_writeback_commit_state": "FAILED",
                    "osm_repaired_available": False,
                    "osm_writeback_failure_reason": (
                        "osm_artifact_reconciliation_failed"
                    ),
                })
            else:
                if marker["status"] == "VERIFIED":
                    record.interaction_context.update({
                        "osm_writeback_status": marker["osm_writeback_status"],
                        "osm_writeback_commit_state": "COMMITTED",
                        "osm_repaired_available": True,
                    })
                else:
                    record.interaction_context.update({
                        "osm_writeback_status": "OSM_WRITEBACK_FAILED",
                        "osm_writeback_commit_state": "FAILED",
                        "osm_repaired_available": False,
                    })
            record.session.updated_at = utc_now()
            self._records[session_id] = record
            try:
                self._persist(record)
            except Exception:
                pass

    def _persist(self, record: SessionRecord) -> None:
        '''原子写入会话的完整可恢复快照。'''
        values = tuple(self._record_database_identity(record).values())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""
                INSERT INTO sessions (
                    session_id,workspace_path,input_name,input_sha256,mode,status,
                    lifecycle_status,archived,created_at,updated_at,config_json,
                    energyplus_path,energyplus_version,weather_path,weather_sha256,
                    weather_size_bytes,weather_original_name,weather_readiness_json,dependencies_json,
                    approved_candidate_ids_json,runtime_identity_json,pending_questions_json,
                    answers_json,selected_rule_set_id,model_calls_json,outcome_json,report_json,
                    extra_candidates_json,interaction_context_json
                ) VALUES (
                    ?,?,?,?,?,
                    ?,?,?,?,?,
                    ?,?,?,?,?,
                    ?,?,?,?,?,
                    ?,?,?,?,?,
                    ?,?,?,?
                ) ON CONFLICT(session_id) DO UPDATE SET
                    workspace_path=excluded.workspace_path,
                    input_name=excluded.input_name,
                    input_sha256=excluded.input_sha256,
                    mode=excluded.mode,
                    status=excluded.status,
                    lifecycle_status=excluded.lifecycle_status,
                    archived=excluded.archived,
                    updated_at=excluded.updated_at,
                    config_json=excluded.config_json,
                    energyplus_path=excluded.energyplus_path,
                    energyplus_version=excluded.energyplus_version,
                    dependencies_json=excluded.dependencies_json,
                    approved_candidate_ids_json=excluded.approved_candidate_ids_json,
                    runtime_identity_json=excluded.runtime_identity_json,
                    pending_questions_json=excluded.pending_questions_json,
                    answers_json=excluded.answers_json,
                    selected_rule_set_id=excluded.selected_rule_set_id,
                    model_calls_json=excluded.model_calls_json,
                    outcome_json=excluded.outcome_json,
                    report_json=excluded.report_json,
                    extra_candidates_json=excluded.extra_candidates_json,
                    interaction_context_json=excluded.interaction_context_json
            """, values)
            connection.commit()

    def _durable_session_row(self, session_id: str) -> sqlite3.Row:
        """Read one complete SQLite row without consulting workspace garbage."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return row

    @staticmethod
    def _weather_db_state_from_row(row: sqlite3.Row | None) -> dict[str, Any]:
        """Project one row onto the durable fields used by weather publication."""

        if row is None:
            return {}
        fields = (
            "session_id",
            "updated_at",
            "lifecycle_status",
            "status",
            "archived",
            "outcome_json",
            "report_json",
            *_WEATHER_COLUMNS,
        )
        return {field: row[field] for field in fields}

    def _read_weather_db_state(self, session_id: str) -> Mapping[str, Any]:
        """Read only the SQLite fields that determine durable weather state."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT session_id,updated_at,lifecycle_status,status,archived,
                       outcome_json,report_json,weather_path,weather_sha256,
                       weather_size_bytes,weather_original_name,weather_readiness_json
                FROM sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return self._weather_db_state_from_row(row)

    @staticmethod
    def _durable_weather_kind(state: Mapping[str, Any]) -> str:
        """Classify weather-column presence without consulting filesystem state."""

        present = tuple(state.get(field) is not None for field in _WEATHER_COLUMNS)
        if not any(present):
            return "ABSENT"
        if present == (True, False, False, False, False):
            return "LEGACY"
        if all(present):
            return "ATTACHED"
        return "INVALID"

    @staticmethod
    def _attachment_row_is_eligible(
        state: Mapping[str, Any],
        *,
        observed_updated_at: str | None = None,
    ) -> bool:
        """Return whether a durable row is the exact pristine attachment source."""

        return bool(state) and (
            state.get("lifecycle_status") == "CREATED"
            and state.get("status") is None
            and state.get("outcome_json") is None
            and state.get("report_json") is None
            and state.get("archived") == 0
            and (
                observed_updated_at is None
                or state.get("updated_at") == observed_updated_at
            )
        )

    @staticmethod
    def _weather_readiness_json(readiness: Mapping[str, Any]) -> str:
        return json.dumps(dict(readiness), ensure_ascii=False, sort_keys=True)

    @classmethod
    def _weather_candidate_matches(
        cls,
        state: Mapping[str, Any],
        *,
        blob: WeatherBlob,
        original_name: str,
        readiness: Mapping[str, Any],
        attached_at: str,
    ) -> bool:
        """Match the exact row this attachment attempted to commit."""

        return cls._attachment_row_is_eligible(state) and (
            state.get("updated_at") == attached_at
            and state.get("weather_path") == str(blob.path)
            and state.get("weather_sha256") == blob.sha256
            and state.get("weather_size_bytes") == blob.size_bytes
            and state.get("weather_original_name") == original_name
            and state.get("weather_readiness_json")
            == cls._weather_readiness_json(readiness)
        )

    def _compare_and_set_weather(
        self,
        session_id: str,
        *,
        observed_updated_at: str,
        blob: WeatherBlob,
        original_name: str,
        readiness: Mapping[str, Any],
        attached_at: str,
    ) -> str:
        """Publish one complete identity only from the exact pristine SQLite row."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT session_id,updated_at,lifecycle_status,status,archived,
                       outcome_json,report_json,weather_path,weather_sha256,
                       weather_size_bytes,weather_original_name,weather_readiness_json
                FROM sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            state = self._weather_db_state_from_row(row)
            if not state:
                connection.rollback()
                return "ABSENT"
            weather_kind = self._durable_weather_kind(state)
            if weather_kind in {"LEGACY", "ATTACHED"}:
                connection.rollback()
                return "ALREADY_ATTACHED"
            if (
                weather_kind != "ABSENT"
                or not self._attachment_row_is_eligible(
                    state,
                    observed_updated_at=observed_updated_at,
                )
            ):
                connection.rollback()
                return "CONFLICT"
            cursor = connection.execute(
                """
                UPDATE sessions SET weather_path = ?, weather_sha256 = ?,
                    weather_size_bytes = ?, weather_original_name = ?,
                    weather_readiness_json = ?, updated_at = ?
                WHERE session_id = ? AND updated_at = ?
                  AND lifecycle_status = 'CREATED' AND status IS NULL
                  AND archived = 0 AND outcome_json IS NULL AND report_json IS NULL
                  AND weather_path IS NULL AND weather_sha256 IS NULL
                  AND weather_size_bytes IS NULL AND weather_original_name IS NULL
                  AND weather_readiness_json IS NULL
                """,
                (
                    str(blob.path),
                    blob.sha256,
                    blob.size_bytes,
                    original_name,
                    self._weather_readiness_json(readiness),
                    attached_at,
                    session_id,
                    observed_updated_at,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return "CONFLICT"
            connection.commit()
        return "COMMITTED"

    def _load(self, session_id: str) -> SessionRecord:
        '''从 SQLite 和工作区文件恢复一个会话运行对象。'''
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        workspace_path = self._trusted_workspace_path(row)
        workspace = SessionWorkspace(workspace_path)
        weather, weather_sha256, weather_size_bytes, weather_original_name, weather_readiness = (
            self._loaded_weather_identity(row, workspace_path)
        )
        input_path = workspace.safe_path("uploads/input.idf")
        if not input_path.is_file():
            raise SessionStateError("persisted_session_input_missing")
        input_bytes = input_path.read_bytes()
        input_text = input_bytes.decode("utf-8-sig")
        answers = [_answer(value) for value in json.loads(row["answers_json"])]
        questions = [_question(value) for value in json.loads(row["pending_questions_json"])]
        status = RepairStatus(row["status"]) if row["status"] else None
        outcome_payload = json.loads(row["outcome_json"]) if row["outcome_json"] else None
        outcome = None
        if outcome_payload is not None and status is not None:
            output_path = workspace.safe_path("result.idf")
            output_text = output_path.read_bytes().decode("utf-8-sig") if output_path.is_file() else input_text
            outcome = RepairOutcome(
                status=status,
                input_sha256=str(outcome_payload.get("input_sha256", row["input_sha256"])),
                output_sha256=text_sha256(output_text),
                output_text=output_text,
                questions=questions,
                answers=answers,
                backtracks=int(outcome_payload.get("backtracks", 0)),
                energyplus_runs=int(outcome_payload.get("energyplus_runs", 0)),
                rollback_reason=outcome_payload.get("rollback_reason"),
                limitations=list(outcome_payload.get("limitations", ())),
                initial_energyplus_diagnostics=str(
                    outcome_payload.get("initial_energyplus_diagnostics", "")
                ),
                terminal_safety_admitted=(
                    outcome_payload.get("terminal_safety_admitted") is True
                ),
                terminal_safety_disposition=str(
                    outcome_payload.get(
                        "terminal_safety_disposition",
                        "NOT_EVALUATED",
                    )
                ),
            )
        session = RepairSession(
            session_id=row["session_id"],
            mode=RepairMode(row["mode"]),
            input_name=row["input_name"],
            input_sha256=row["input_sha256"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=status,
            outcome=outcome,
            pending_questions=questions,
            answers=answers,
            metadata={"lifecycle_status": row["lifecycle_status"]},
        )
        interaction_context = dict(json.loads(row["interaction_context_json"]))
        interaction_context.setdefault("input_had_utf8_bom", input_bytes.startswith(UTF8_BOM))
        return SessionRecord(
            session=session,
            workspace=workspace,
            input_text=input_text,
            config=_config(json.loads(row["config_json"])),
            energyplus_path=Path(row["energyplus_path"]) if row["energyplus_path"] else None,
            energyplus_version=row["energyplus_version"],
            weather=weather,
            weather_sha256=weather_sha256,
            weather_size_bytes=weather_size_bytes,
            weather_original_name=weather_original_name,
            weather_readiness=weather_readiness,
            dependencies=[Path(value) for value in json.loads(row["dependencies_json"])],
            approved_candidate_ids=list(json.loads(row["approved_candidate_ids_json"])),
            runtime_identity=dict(json.loads(row["runtime_identity_json"])),
            report=(dict(json.loads(row["report_json"])) if row["report_json"] else None),
            lifecycle_status=row["lifecycle_status"],
            archived=bool(row["archived"]),
            selected_rule_set_id=row["selected_rule_set_id"],
            model_calls=list(json.loads(row["model_calls_json"])),
            persisted_outcome=outcome_payload,
            extra_candidates=[
                _candidate(value) for value in json.loads(row["extra_candidates_json"])
            ],
            interaction_context=interaction_context,
        )

    def _trusted_workspace_path(self, row: sqlite3.Row) -> Path:
        """Return one unique canonical workspace bound to this manager root."""

        raw_value = row["workspace_path"]
        if type(raw_value) is not str:
            raise SessionStateError("session_storage_row_invalid")
        workspace = Path(raw_value)
        workspaces_root = self.root / "workspaces"
        try:
            workspaces_node = workspaces_root.lstat()
            workspace_node = workspace.lstat()
            canonical_workspaces_root = workspaces_root.resolve(strict=True)
            canonical_workspace = workspace.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SessionStateError("session_storage_row_invalid") from exc
        if (
            canonical_workspaces_root != workspaces_root
            or not stat.S_ISDIR(workspaces_node.st_mode)
            or not workspace.is_absolute()
            or Path(os.path.abspath(workspace)) != workspace
            or canonical_workspace != workspace
            or workspace.parent != workspaces_root
            or not stat.S_ISDIR(workspace_node.st_mode)
        ):
            raise SessionStateError("session_storage_row_invalid")
        with self._connect() as connection:
            owners = connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE workspace_path = ?",
                (raw_value,),
            ).fetchone()[0]
        if owners != 1:
            raise SessionStateError("session_storage_row_invalid")
        return workspace

    @staticmethod
    def _loaded_weather_identity(
        row: sqlite3.Row,
        workspace_path: Path,
    ) -> tuple[Path | None, str | None, int | None, str | None, dict[str, Any] | None]:
        """Classify and verify one SQLite-authoritative weather identity."""

        raw_path = row["weather_path"]
        raw_sha256 = row["weather_sha256"]
        raw_size = row["weather_size_bytes"]
        raw_original_name = row["weather_original_name"]
        raw_readiness = row["weather_readiness_json"]
        present = tuple(
            value is not None
            for value in (
                raw_path,
                raw_sha256,
                raw_size,
                raw_original_name,
                raw_readiness,
            )
        )
        if not any(present):
            return None, None, None, None, None
        if present == (True, False, False, False, False):
            if type(raw_path) is not str:
                raise SessionStateError("weather_asset_state_invalid")
            return Path(raw_path), None, None, None, None
        if not all(present):
            raise SessionStateError("weather_asset_state_invalid")
        if (
            type(raw_path) is not str
            or type(raw_sha256) is not str
            or len(raw_sha256) != 64
            or any(character not in "0123456789abcdef" for character in raw_sha256)
            or type(raw_size) is not int
            or raw_size < 0
            or type(raw_original_name) is not str
            or type(raw_readiness) is not str
        ):
            raise SessionStateError("weather_asset_state_invalid")
        try:
            validate_weather_upload(
                raw_original_name,
                b"",
                max_bytes=MAX_UPLOAD_BYTES,
            )
            decoded_readiness = json.loads(raw_readiness)
        except (TypeError, ValueError) as exc:
            raise SessionStateError("weather_asset_state_invalid") from exc
        if not isinstance(decoded_readiness, Mapping):
            raise SessionStateError("weather_asset_state_invalid")
        expected_path = (
            workspace_path
            / "uploads"
            / "weather"
            / "blobs"
            / f"{raw_sha256}.epw"
        )
        if raw_path != str(expected_path):
            raise SessionStateError("weather_asset_state_invalid")
        try:
            verified_path = verify_weather_blob(
                workspace_path,
                raw_sha256,
                raw_size,
            )
        except ValueError as exc:
            raise SessionStateError("weather_blob_integrity_error") from exc
        return (
            verified_path,
            raw_sha256,
            raw_size,
            raw_original_name,
            dict(decoded_readiness),
        )

    def create(
        self,
        *,
        input_name: str,
        input_bytes: bytes,
        config: EngineConfig,
        energyplus_path: Path | None = None,
        energyplus_version: str | None = None,
        weather: tuple[str, bytes] | None = None,
        dependencies: Iterable[tuple[str, bytes]] = (),
        selected_rule_set_id: str = "default",
        project_id: str | None = None,
        batch_id: str | None = None,
        _session_id: str | None = None,
        _initial_interaction_context: Mapping[str, Any] | None = None,
        _workspace_holder: list[SessionWorkspace] | None = None,
        _record_holder: list[SessionRecord] | None = None,
        _staged_files: Mapping[str, bytes] | None = None,
    ) -> SessionRecord:
        '''验证上传并持久化一个隔离会话。'''
        if self._create_intent_storage_invalid:
            raise SessionStateError("session_create_intent_storage_invalid")
        if self._create_intent_scan_incomplete:
            raise SessionStateError("session_create_intent_scan_incomplete")
        if (
            _session_id is not None
            and _session_id in self._create_recovery_quarantined
        ):
            raise SessionStateError("session_create_recovery_quarantined")
        if len(input_bytes) > MAX_UPLOAD_BYTES:
            raise SessionStateError("input_upload_too_large")
        try:
            text = input_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SessionStateError("input_must_be_utf8") from exc
        parse_idf(text)
        safe_name = Path(input_name).name
        if not safe_name.casefold().endswith(".idf"):
            raise SessionStateError("input_extension_must_be_idf")
        validated_weather = None
        if weather is not None:
            weather_name, weather_content = weather
            weather_name = self._validated_upload_name(
                "weather", weather_name, weather_content,
            )
            if Path(weather_name).suffix.casefold() == ".epw":
                weather_name = self._validated_weather_upload_name(
                    weather_name, weather_content,
                )
            validated_weather = (weather_name, weather_content)
        workspace = (
            self._create_preallocated_workspace(_session_id)
            if _session_id is not None
            else SessionWorkspace.create(self.root / "workspaces")
        )
        if _workspace_holder is not None:
            _workspace_holder.append(workspace)
        session = RepairSession.create(mode=config.mode, input_name=safe_name, input_sha256=text_sha256(text))
        if _session_id is not None:
            session.session_id = _session_id
            publish_create_intent(
                workspace.root,
                SessionCreateIntent(session.session_id, safe_name, session.input_sha256),
            )
        input_path = workspace.safe_path("uploads/input.idf")
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(input_bytes)
        dependency_paths = [
            self._store_upload(workspace, "dependencies", name, content)
            for name, content in dependencies
        ]
        record = SessionRecord(
            session=session,
            workspace=workspace,
            input_text=text,
            config=config,
            energyplus_path=energyplus_path,
            energyplus_version=energyplus_version,
            dependencies=dependency_paths,
            selected_rule_set_id=selected_rule_set_id,
            interaction_context={
                "project_id": project_id or selected_rule_set_id,
                "input_had_utf8_bom": input_bytes.startswith(UTF8_BOM),
                **({"batch_id": batch_id} if batch_id else {}),
                **dict(_initial_interaction_context or {}),
            },
        )
        if _record_holder is not None:
            _record_holder.append(record)
        if validated_weather is not None:
            weather_name, weather_content = validated_weather
            if Path(weather_name).suffix.casefold() == ".epw":
                blob = self._publish_weather_blob(workspace.root, weather_content)
                record.weather = blob.path
                record.weather_sha256 = blob.sha256
                record.weather_size_bytes = blob.size_bytes
                record.weather_original_name = weather_name
                record.weather_readiness = self._readiness_for_record(
                    record,
                    weather=blob.path,
                )
            else:
                record.weather = self._store_upload(
                    workspace,
                    "weather",
                    weather_name,
                    weather_content,
                )
        if _staged_files:
            try:
                for relative, content in _staged_files.items():
                    normalized = normalize_project_path(relative)
                    if not (
                        normalized.startswith("artifacts/")
                        or normalized == "uploads/source.osm"
                    ):
                        raise SessionStateError("settings_inherited_asset_invalid")
                    destination = workspace.safe_path(normalized)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
            except Exception as staging_error:
                if _session_id is not None:
                    try:
                        self._recover_failed_create(record)
                    except Exception:
                        raise SessionStateError(
                            "session_create_cleanup_failed"
                        ) from staging_error
                raise
        with self._lock:
            self._records[session.session_id] = record
            try:
                self._persist(record)
            except Exception as insert_error:
                try:
                    durable_row = self._durable_session_row(session.session_id)
                except KeyError:
                    try:
                        self._recover_failed_create(record)
                    except Exception:
                        raise SessionStateError(
                            "session_create_cleanup_failed"
                        ) from insert_error
                    raise insert_error from None
                except Exception:
                    self._records.pop(session.session_id, None)
                    raise SessionStateError(
                        "weather_commit_state_unknown"
                    ) from insert_error
                expected = self._record_database_identity(record)
                if all(durable_row[field] == value for field, value in expected.items()):
                    self._records[session.session_id] = record
                    try:
                        remove_create_intent(workspace.root)
                    except SessionStateError:
                        record.interaction_context[
                            "session_create_intent_cleanup_pending"
                        ] = True
                        self._persist(record)
                    return record
                self._records.pop(session.session_id, None)
                try:
                    self._load(session.session_id)
                except SessionStateError as state_error:
                    raise SessionStateError(str(state_error)) from insert_error
                raise SessionStateError(
                    "weather_attachment_conflict"
                ) from insert_error
        if _session_id is not None:
            try:
                remove_create_intent(workspace.root)
            except SessionStateError:
                record.interaction_context[
                    "session_create_intent_cleanup_pending"
                ] = True
                self._persist(record)
        return record

    def _recover_failed_create(self, record: SessionRecord) -> Path | None:
        """Remove a failed create identity and recover its exact workspace."""

        return self._recover_failed_create_workspace(
            record.session.session_id,
            record.workspace,
            expected_intent=SessionCreateIntent(
                record.session.session_id,
                record.session.input_name,
                record.session.input_sha256,
            ),
        )

    def _recover_failed_create_workspace(
        self,
        session_id: str,
        workspace: SessionWorkspace,
        *,
        expected_intent: SessionCreateIntent,
    ) -> Path | None:
        """Move one exact, marker-owned failed create to secret quarantine."""

        with self._lock:
            self._records.pop(session_id, None)
        self._delete_failed_create_row(session_id)
        root_descriptor = workspaces_descriptor = child_descriptor = -1
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            root_descriptor = os.open(self.root, flags)
            workspaces_descriptor = os.open(
                "workspaces", flags, dir_fd=root_descriptor,
            )
            child_descriptor = os.open(
                session_id, flags, dir_fd=workspaces_descriptor,
            )
            intent = read_create_intent_at(
                child_descriptor, expected_session_id=session_id,
            )
            if intent != expected_intent:
                raise SessionStateError("session_create_intent_invalid")
            staged_leaf = self._quarantine_create_intent_workspace(
                workspaces_descriptor, child_descriptor, session_id,
            )
            if staged_leaf is None:
                raise SessionStateError("session_create_intent_invalid")
        except FileNotFoundError:
            return None
        finally:
            for descriptor in (
                child_descriptor, workspaces_descriptor, root_descriptor,
            ):
                if descriptor >= 0:
                    os.close(descriptor)
        return self.root / "workspaces" / staged_leaf

    def _delete_failed_create_row(self, session_id: str) -> None:
        """Defensively remove only the exact failed-create identity."""

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,),
            )

    @staticmethod
    def _validated_upload_name(category: str, name: Any, content: bytes) -> str:
        """Apply the shared supporting-upload size and name boundary."""

        if len(content) > MAX_UPLOAD_BYTES:
            raise SessionStateError("supporting_upload_too_large")
        safe_name = (
            normalize_project_path(name)
            if category == "dependencies"
            else None
        )
        if safe_name is None:
            try:
                safe_name = validate_upload_display_leaf(name)
            except ValueError as exc:
                raise SessionStateError(str(exc)) from exc
        if safe_name in {"", ".", ".."}:
            raise SessionStateError("upload_name_invalid")
        return safe_name

    @staticmethod
    def _validated_weather_upload_name(name: Any, content: bytes) -> str:
        """Validate an attachment name without normalizing away path syntax."""

        try:
            return validate_weather_upload(
                name,
                content,
                max_bytes=MAX_UPLOAD_BYTES,
            )
        except ValueError as exc:
            raise SessionStateError(str(exc)) from exc

    @staticmethod
    def _publish_weather_blob(workspace_root: Path, content: bytes) -> WeatherBlob:
        """Map publication I/O to one path-free domain error at the manager boundary."""

        try:
            return publish_weather_blob(workspace_root, content)
        except OSError as exc:
            raise SessionStateError("weather_storage_write_failed") from exc

    def _store_upload(self, workspace: SessionWorkspace, category: str, name: str, content: bytes) -> Path:
        '''在会话工作区保存一个经过名称和大小约束的支持文件。'''
        safe_name = self._validated_upload_name(category, name, content)
        path = workspace.safe_path(f"uploads/{category}/{safe_name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def _get_locked(self, session_id: str) -> SessionRecord:
        """Load one session while its stable mutation guard is already held."""

        with self._lock:
            if session_id in self._create_intent_invalid:
                raise SessionStateError("session_create_intent_invalid")
            if session_id in self._create_commit_unknown:
                raise SessionStateError("session_create_commit_state_unknown")
            if session_id in self._parent_lineage_invalid:
                raise SessionStateError("parent_lineage_state_invalid")
            if session_id in self._parent_lineage_commit_unknown:
                raise SessionStateError("parent_lineage_commit_state_unknown")
            record = self._records.get(session_id)
            if record is None:
                record = self._load(session_id)
                self._records[session_id] = record
        return record

    def get(self, session_id: str) -> SessionRecord:
        '''从当前缓存或 SQLite 读取会话。'''
        with self._session_guard(session_id):
            return self._get_locked(session_id)

    def workspace_for_open(self, session_id: str) -> Path:
        """Resolve the Finder target without opening an untrusted workspace."""

        try:
            return self.get(session_id).workspace.root
        except SessionStateError as exc:
            row = self._durable_session_row(session_id)
            workspace = Path(str(row["workspace_path"]))
            try:
                node = workspace.lstat()
            except FileNotFoundError as missing:
                raise OSError("session_workspace_missing") from missing
            except NotADirectoryError as invalid:
                raise OSError("session_workspace_not_directory") from invalid
            except (OSError, RuntimeError, ValueError) as unreadable:
                raise OSError("session_workspace_unreadable") from unreadable
            if not stat.S_ISDIR(node.st_mode):
                raise OSError("session_workspace_not_directory")
            raise

    def list(self, *, include_archived: bool = False) -> tuple[dict[str, Any], ...]:
        '''按更新时间倒序列出持久会话。'''
        query = "SELECT session_id FROM sessions"
        if not include_archived:
            query += " WHERE archived = 0"
        query += " ORDER BY updated_at DESC, session_id"
        with self._connect() as connection:
            ids = [row[0] for row in connection.execute(query)]
        summaries: list[dict[str, Any]] = []
        for identity in ids:
            try:
                summaries.append(self.summary(identity))
            except SessionStateError as exc:
                summaries.append(self._blocked_summary(identity, exc))
        return tuple(summaries)

    def _blocked_summary(
        self,
        session_id: str,
        exc: SessionStateError,
    ) -> dict[str, Any]:
        """Build a file-free history row for one fail-closed session."""

        row = self._durable_session_row(session_id)
        try:
            decoded_context = json.loads(row["interaction_context_json"])
            context = decoded_context if type(decoded_context) is dict else {}
        except (TypeError, ValueError):
            context = {}
        components = component_statuses()
        input_sha256 = str(row["input_sha256"])
        return {
            "automatic_repair_release_authorized": False,
            "archived": bool(row["archived"]),
            "candidate_attempt_count": 0,
            "completed_round_count": 0,
            "created_at": str(row["created_at"]),
            "input_name": str(row["input_name"]),
            "input_sha256": input_sha256,
            **session_display_metadata({}, input_sha256=input_sha256),
            "lifecycle_status": str(row["lifecycle_status"]),
            "mode": str(row["mode"]),
            "message": error_message(exc),
            "source_type": str(context.get("source_type") or "IDF"),
            "source_input_name": (
                str(context["source_input_name"])
                if context.get("source_input_name") else None
            ),
            "osm_bridge_status": (
                str(context["osm_bridge_status"])
                if context.get("osm_bridge_status") else None
            ),
            "preflight_status": (
                str(context["preflight_status"])
                if context.get("preflight_status") else None
            ),
            "preflight_parent_session_id": (
                str(context["preflight_parent_session_id"])
                if context.get("preflight_parent_session_id") else None
            ),
            "preflight_child_session_id": (
                str(context["preflight_child_session_id"])
                if context.get("preflight_child_session_id") else None
            ),
            "preflight_summary": (
                dict(context["preflight_summary"])
                if isinstance(context.get("preflight_summary"), Mapping)
                else None
            ),
            "batch_id": str(context["batch_id"]) if context.get("batch_id") else None,
            "energyplus_version": (
                str(row["energyplus_version"]) if row["energyplus_version"] else None
            ),
            "last_completed_action": (
                str(context["last_completed_action"])
                if context.get("last_completed_action") else None
            ),
            "model_call_count": 0,
            "model_component_status": components["model_component_status"],
            "production_enabled": False,
            "questions": [],
            "release_profile_id": RELEASE_PROFILE_ID,
            "repair_memory_component_status": components[
                "repair_memory_component_status"
            ],
            "root_support": [],
            "selected_rule_set_id": str(row["selected_rule_set_id"]),
            "rule_save_available": False,
            "rule_save_candidates": [],
            "rule_save_scope_choices": [],
            "session_id": str(row["session_id"]),
            "status": str(row["status"]) if row["status"] else None,
            "support_coverage_summary": support_coverage_summary(()),
            "support_registry_sha256": EXPECTED_SUPPORT_REGISTRY_SHA256,
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _workbench_text(record: SessionRecord) -> str:
        """Use the latest committed/diagnosed text while preserving immutable input."""

        persisted = (record.persisted_outcome or {}).get("output_text")
        return persisted if isinstance(persisted, str) else record.input_text

    def _workbench_idd(self, record: SessionRecord) -> str:
        runtime = select_input_runtime(
            record.input_text,
            explicit=record.energyplus_path,
            requested_version=record.energyplus_version,
        )
        return runtime.idd_path.read_text(encoding="utf-8", errors="replace")

    def source_context_for(
        self,
        session_id: str,
        *,
        object_index: int,
        field_index: int | None = None,
        before_lines: int = 2,
        after_lines: int = 2,
    ) -> dict[str, Any]:
        """Return a bounded parser-span source fragment for one session object."""

        record = self.get(session_id)
        return build_source_context(
            self._workbench_text(record),
            object_index,
            field_index,
            before_lines,
            after_lines,
        )

    def field_context_for(
        self,
        session_id: str,
        *,
        object_index: int,
        field_index: int,
    ) -> dict[str, Any]:
        """Return the current value and bound-version IDD definition."""

        record = self.get(session_id)
        return build_field_context(
            self._workbench_text(record),
            self._workbench_idd(record),
            object_index,
            field_index,
        )

    def object_context_for(
        self,
        session_id: str,
        *,
        object_index: int,
        depth: int = 1,
        limit: int = 30,
    ) -> dict[str, Any]:
        """Return a bounded local object-reference graph."""

        record = self.get(session_id)
        return build_object_context(
            self._workbench_text(record),
            self._workbench_idd(record),
            object_index,
            depth,
            limit,
        )

    def readiness_for(
        self,
        session_id: str,
        *,
        weather: Path | None | object = _WEATHER_UNSET,
    ) -> dict[str, Any]:
        """Return pre-run project readiness for the session's selected runtime."""

        record = self.get(session_id)
        selected_weather = record.weather if weather is _WEATHER_UNSET else weather
        return self._readiness_for_record(record, weather=selected_weather)

    def _readiness_for_record(
        self,
        record: SessionRecord,
        *,
        weather: Path | None | object,
    ) -> dict[str, Any]:
        """Calculate readiness for a record without mutating cache or SQLite."""

        runtime = select_input_runtime(
            record.input_text,
            explicit=record.energyplus_path,
            requested_version=record.energyplus_version,
        )
        logical_files = tuple(
            dependency_run_path(path).as_posix() for path in record.dependencies
        )
        return inspect_readiness(
            self._workbench_text(record),
            runtime.idd_path.read_text(encoding="utf-8", errors="replace"),
            runtime_version=runtime.version,
            idd_ready=runtime.idd_path.is_file(),
            weather_supplied=(
                isinstance(weather, Path)
                and weather_asset_ready(weather)
            ),
            logical_files=logical_files,
        )

    def require_run_readiness(self, session_id: str) -> dict[str, Any]:
        """Persist the current readiness evidence and reject blocked execution."""

        with self._session_guard(session_id, mode="mutation"):
            return self._require_run_readiness_locked(
                self._get_locked(session_id)
            )

    def _require_run_readiness_locked(
        self, record: SessionRecord,
    ) -> dict[str, Any]:
        """Persist readiness while the stable session guard is held."""

        readiness = self._readiness_for_record(record, weather=record.weather)
        blocked = blocking_readiness_checks(readiness)
        record.interaction_context["run_readiness"] = readiness
        self._persist(record)
        if blocked:
            raise SessionStateError(f"run_readiness_blocked:{','.join(blocked)}")
        return readiness

    def attach_weather(
        self,
        session_id: str,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        """Durably publish one EPW and atomically attach its SQLite identity."""

        safe_name = self._validated_weather_upload_name(filename, content)
        with self._session_guard(session_id, mode="mutation") as entry:
            cached = self._get_locked(session_id)
            observed = self._load(session_id)
            if (
                observed.lifecycle_status != "CREATED"
                or observed.session.status is not None
                or observed.session.outcome is not None
                or observed.persisted_outcome is not None
                or observed.report is not None
                or observed.archived
            ):
                raise SessionStateError("weather_attachment_not_allowed")
            if observed.weather is not None:
                raise SessionStateError("weather_already_attached")

            blob = self._publish_weather_blob(observed.workspace.root, content)
            readiness = self._readiness_for_record(observed, weather=blob.path)
            attached_at = utc_now()
            try:
                outcome = self._compare_and_set_weather(
                    session_id,
                    observed_updated_at=observed.session.updated_at,
                    blob=blob,
                    original_name=safe_name,
                    readiness=readiness,
                    attached_at=attached_at,
                )
            except Exception as transaction_error:
                try:
                    state = self._read_weather_db_state(session_id)
                except Exception:
                    self._evict_cached_record(session_id)
                    raise SessionStateError(
                        "weather_commit_state_unknown"
                    ) from transaction_error
                if self._weather_candidate_matches(
                    state,
                    blob=blob,
                    original_name=safe_name,
                    readiness=readiness,
                    attached_at=attached_at,
                ):
                    outcome = "COMMITTED"
                elif (
                    self._durable_weather_kind(state) == "ABSENT"
                    and self._attachment_row_is_eligible(
                        state,
                        observed_updated_at=observed.session.updated_at,
                    )
                ):
                    raise
                else:
                    self._raise_current_weather_state(
                        session_id,
                        cause=transaction_error,
                    )

            if outcome == "COMMITTED":
                refreshed = self._refresh_weather_cache(session_id, cached)
                if entry.tombstone:
                    raise SessionStateError("session_deletion_pending")
                return {
                    "attached": True,
                    "filename": refreshed.weather_original_name or safe_name,
                    "readiness": dict(refreshed.weather_readiness or readiness),
                }
            if outcome == "ABSENT":
                self._evict_cached_record(session_id)
                raise KeyError(session_id)
            if outcome in {"ALREADY_ATTACHED", "CONFLICT"}:
                self._raise_current_weather_state(session_id)
            raise SessionStateError("weather_attachment_conflict")

    def _evict_cached_record(self, session_id: str) -> None:
        with self._lock:
            self._records.pop(session_id, None)

    def _raise_current_weather_state(
        self,
        session_id: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        """Map a known CAS miss without collapsing distinct durable states."""

        try:
            current = self._load(session_id)
        except KeyError:
            self._evict_cached_record(session_id)
            if cause is None:
                raise
            raise KeyError(session_id) from cause
        except SessionStateError as state_error:
            self._evict_cached_record(session_id)
            if cause is None:
                raise
            raise SessionStateError(str(state_error)) from cause
        except Exception:
            self._evict_cached_record(session_id)
            if cause is None:
                raise
            raise SessionStateError("weather_commit_state_unknown") from cause
        with self._lock:
            self._records[session_id] = current
        token = (
            "weather_already_attached"
            if current.weather is not None
            else "weather_attachment_conflict"
        )
        if cause is None:
            raise SessionStateError(token)
        raise SessionStateError(token) from cause

    def _refresh_weather_cache(
        self,
        session_id: str,
        cached: SessionRecord,
    ) -> SessionRecord:
        """Expose authoritative weather fields only after a known durable commit."""

        try:
            refreshed = self._load(session_id)
        except Exception:
            self._evict_cached_record(session_id)
            raise
        with self._lock:
            if self._records.get(session_id) is cached:
                cached.weather = refreshed.weather
                cached.weather_sha256 = refreshed.weather_sha256
                cached.weather_size_bytes = refreshed.weather_size_bytes
                cached.weather_original_name = refreshed.weather_original_name
                cached.weather_readiness = refreshed.weather_readiness
                cached.session.updated_at = refreshed.session.updated_at
                return cached
            self._records[session_id] = refreshed
        return refreshed

    def audit_for(
        self,
        session_id: str,
        *,
        checks: Iterable[str] | None = None,
        geometry_tolerance_m: float = 0.05,
    ) -> dict[str, Any]:
        """Run evidence-only model checks against the session's bound IDD."""

        record = self.get(session_id)
        runtime = select_input_runtime(
            record.input_text,
            explicit=record.energyplus_path,
            requested_version=record.energyplus_version,
        )
        return audit_model(
            record.input_text,
            runtime.idd_path.read_text(encoding="utf-8", errors="replace"),
            checks=checks,
            geometry_tolerance_m=geometry_tolerance_m,
        )

    def experimental_geometry_for(
        self,
        session_id: str,
        *,
        mechanisms: Iterable[str] | None = None,
        snap_absolute_m: float = 0.05,
        snap_relative: float = 0.001,
    ) -> dict[str, Any]:
        """Run preview-only detectors against the session's immutable input."""

        record = self.get(session_id)
        runtime = select_input_runtime(
            record.input_text,
            explicit=record.energyplus_path,
            requested_version=record.energyplus_version,
        )
        return preview_geometry_lab(
            record.input_text,
            runtime.idd_path.read_text(encoding="utf-8", errors="replace"),
            mechanisms=mechanisms,
            snap_absolute_m=snap_absolute_m,
            snap_relative=snap_relative,
        )

    def model_preflight_for(
        self,
        session_id: str,
        *,
        checks: Iterable[str] | None = None,
        tolerance_m: float = 0.05,
    ) -> dict[str, Any]:
        """Combine relationship/geometry checks before the normal diagnosis."""

        with self._session_guard(session_id, mode="mutation"):
            return self._model_preflight_for_locked(
                session_id, checks=checks, tolerance_m=tolerance_m,
            )

    def _model_preflight_for_locked(
        self,
        session_id: str,
        *,
        checks: Iterable[str] | None,
        tolerance_m: float,
    ) -> dict[str, Any]:
        """Build and persist model preflight while the session guard is held."""

        record = self._get_locked(session_id)
        runtime = select_input_runtime(
            record.input_text,
            explicit=record.energyplus_path,
            requested_version=record.energyplus_version,
        )
        report = build_model_preflight(
            record.input_text,
            runtime.idd_path.read_text(encoding="utf-8", errors="replace"),
            checks=checks,
            tolerance_m=tolerance_m,
        )
        ModelPreflightReport.model_validate(report)
        artifact = record.workspace.safe_path("artifacts/model-preflight.json")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        record.interaction_context.update({
            "preflight_status": "CHECKED",
            "preflight_tolerance_m": tolerance_m,
            "preflight_summary": dict(report["summary"]),
        })
        if record.interaction_context.get("source_type") == "OSM":
            bridge = self._osm_bridge_report_for_locked_record(record)
            bridge.update({
                "diagnostic_status": "PRECHECKED",
                "model_preflight": {
                    "schema_version": report["schema_version"],
                    "input_sha256": report["input_sha256"],
                    "tolerance_m": tolerance_m,
                    "summary": dict(report["summary"]),
                },
            })
            self._update_osm_bridge_report_locked(record, bridge)
        else:
            record.session.updated_at = utc_now()
            self._persist(record)
        return report

    def model_preflight_report_for(self, session_id: str) -> dict[str, Any]:
        record = self.get(session_id)
        artifact = record.workspace.safe_path("artifacts/model-preflight.json")
        if not artifact.is_file():
            raise SessionStateError("model_preflight_not_run")
        report = dict(json.loads(artifact.read_text(encoding="utf-8")))
        ModelPreflightReport.model_validate(report)
        return report

    def apply_model_preflight_for(
        self,
        session_id: str,
    ) -> tuple[SessionRecord, dict[str, Any]]:
        """Create a child session containing only preflight-approved changes."""

        with self._session_guard(session_id, mode="mutation"):
            return self._apply_model_preflight_locked(session_id)

    def _apply_model_preflight_locked(
        self,
        session_id: str,
    ) -> tuple[SessionRecord, dict[str, Any]]:
        """Apply preflight while the parent session guard remains held."""

        parent = self._get_locked(session_id)
        preview_artifact = parent.workspace.safe_path("artifacts/model-preflight.json")
        if not preview_artifact.is_file():
            raise SessionStateError("model_preflight_not_run")
        preview = dict(json.loads(preview_artifact.read_text(encoding="utf-8")))
        ModelPreflightReport.model_validate(preview)
        runtime = select_input_runtime(
            parent.input_text,
            explicit=parent.energyplus_path,
            requested_version=parent.energyplus_version,
        )
        idd_text = runtime.idd_path.read_text(encoding="utf-8", errors="replace")
        application = apply_model_preflight(
            parent.input_text,
            idd_text,
            preview,
        )
        weather = None
        if parent.weather is not None:
            if (
                parent.weather_sha256 is not None
                and parent.weather_size_bytes is not None
                and parent.weather_original_name is not None
            ):
                try:
                    verified_parent_weather = verify_weather_blob(
                        parent.workspace.root,
                        parent.weather_sha256,
                        parent.weather_size_bytes,
                    )
                except ValueError as exc:
                    raise SessionStateError("weather_blob_integrity_error") from exc
                weather = (
                    parent.weather_original_name,
                    verified_parent_weather.read_bytes(),
                )
            elif parent.weather.is_file():
                weather = (parent.weather.name, parent.weather.read_bytes())
        dependency_root = parent.workspace.safe_path("uploads/dependencies")
        dependencies = []
        for path in parent.dependencies:
            try:
                name = path.relative_to(dependency_root).as_posix()
            except ValueError:
                name = path.name
            dependencies.append((name, path.read_bytes()))
        osm_parent_inputs = None
        if parent.interaction_context.get("source_type") == "OSM":
            osm_parent_inputs = (
                self._osm_source_for_locked_record(parent),
                json.loads(json.dumps(
                    self._osm_bridge_report_for_locked_record(parent),
                    ensure_ascii=False, sort_keys=True,
                )),
                json.loads(json.dumps(
                    preview, ensure_ascii=False, sort_keys=True,
                )),
            )
        child_session_id = uuid4().hex
        initial_context = (
            {
                "osm_writeback_status": "OSM_WRITEBACK_IN_PROGRESS",
                "osm_repaired_available": False,
            }
            if osm_parent_inputs is not None else {}
        )
        child_guard_mode = "workflow" if osm_parent_inputs is not None else "mutation"
        with self._session_guard(child_session_id, mode=child_guard_mode):
            workspace_holder: list[SessionWorkspace] = []
            record_holder: list[SessionRecord] = []
            try:
                child = self.create(
                        input_name=f"{Path(parent.session.input_name).stem}-preprocessed.idf",
                        input_bytes=application.output_text.encode("utf-8"),
                        config=parent.config,
                        energyplus_path=parent.energyplus_path,
                        energyplus_version=parent.energyplus_version,
                        weather=weather,
                        dependencies=dependencies,
                        selected_rule_set_id=parent.selected_rule_set_id,
                        project_id=str(parent.interaction_context.get("project_id") or parent.selected_rule_set_id),
                        batch_id=(
                            str(parent.interaction_context["batch_id"])
                            if parent.interaction_context.get("batch_id") else None
                        ),
                        _session_id=child_session_id,
                        _initial_interaction_context=initial_context,
                        _workspace_holder=workspace_holder,
                        _record_holder=record_holder,
                    )
            except Exception as create_error:
                recovered_child: SessionRecord | None = None
                if workspace_holder:
                    try:
                        durable_row = self._durable_session_row(child_session_id)
                    except KeyError:
                        try:
                            self._recover_failed_create_workspace(
                                child_session_id,
                                workspace_holder[0],
                                expected_intent=SessionCreateIntent(
                                    child_session_id,
                                    f"{Path(parent.session.input_name).stem}-preprocessed.idf",
                                    text_sha256(application.output_text),
                                ),
                            )
                        except Exception:
                            if isinstance(create_error, SessionStateError) and str(
                                create_error
                            ) == "session_create_cleanup_failed":
                                raise create_error
                            raise SessionStateError(
                                "session_create_cleanup_failed"
                            ) from create_error
                    except Exception:
                        if record_holder:
                            with self._lock:
                                self._records[child_session_id] = record_holder[0]
                                self._create_commit_unknown.add(child_session_id)
                            raise SessionStateError(
                                "session_create_commit_state_unknown"
                            ) from create_error
                    else:
                        if record_holder:
                            expected = self._record_database_identity(record_holder[0])
                            if all(
                                durable_row[field] == value
                                for field, value in expected.items()
                            ):
                                recovered_child = record_holder[0]
                                with self._lock:
                                    self._records[child_session_id] = recovered_child
                                try:
                                    remove_create_intent(
                                        recovered_child.workspace.root,
                                    )
                                except SessionStateError:
                                    pass
                if recovered_child is None:
                    raise
                child = recovered_child
            return self._finalize_model_preflight_child_locked(
                parent,
                child,
                application,
                osm_parent_inputs=osm_parent_inputs,
                idd_text=idd_text,
            )

    def _finalize_model_preflight_child_locked(
        self,
        parent: SessionRecord,
        child: SessionRecord,
        application: Any,
        *,
        osm_parent_inputs: Any,
        idd_text: str,
    ) -> tuple[SessionRecord, dict[str, Any]]:
        """Finalize a child while parent then child stable guards are held."""

        missing = object()
        previous_child_id = parent.interaction_context.get(
            "preflight_child_session_id", missing,
        )
        previous_parent_updated_at = parent.session.updated_at
        old_parent_identity = self._record_database_identity(parent)
        preserve_child_evidence = False
        try:
            application_report = {
                **application.report,
                "parent_session_id": parent.session.session_id,
                "child_session_id": child.session.session_id,
                "rollback": {
                    "available": True,
                    "uses_parent_copy": True,
                    "parent_session_id": parent.session.session_id,
                },
            }
            child_artifact = child.workspace.safe_path(
                "artifacts/model-preflight-application.json"
            )
            child_artifact.parent.mkdir(parents=True, exist_ok=True)
            child_artifact.write_text(
                json.dumps(
                    application_report, ensure_ascii=False, indent=2, sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            applied_summary = dict(application_report["before"])
            applied_summary.update({
                "applied_repairs": int(application_report["applied_plan_count"]),
                "audit_findings_after": int(application_report["after"]["audit_findings"]),
                "audit_errors_after": int(application_report["after"]["audit_errors"]),
                "surfaces_checked_after": int(application_report["after"]["surfaces_checked"]),
            })
            child.interaction_context.update({
                "preflight_status": "APPLIED",
                "preflight_parent_session_id": parent.session.session_id,
                "preflight_summary": applied_summary,
            })
            if osm_parent_inputs is not None:
                (source_name, source_bytes), source_forward, authoritative_preflight = (
                    osm_parent_inputs
                )
                child_bridge = {
                    **source_forward,
                    "session_id": child.session.session_id,
                    "diagnostic_status": "PREPROCESSING_APPLIED",
                    "model_preflight_application": {
                        key: value for key, value in application_report.items()
                        if key not in {"changed_object_names", "applied_plan_ids"}
                    },
                    "preflight_parent_session_id": parent.session.session_id,
                }
                self._attach_osm_bridge_locked(
                    child,
                    source_name=source_name,
                    source_bytes=source_bytes,
                    derived_bytes=application.output_text.encode("utf-8"),
                    bridge_report=child_bridge,
                )
            else:
                child.session.updated_at = utc_now()
                self._persist(child)
            parent.interaction_context[
                "preflight_child_session_id"
            ] = child.session.session_id
            parent.session.updated_at = utc_now()
            new_parent_identity = self._record_database_identity(parent)
            try:
                self._persist(parent)
            except Exception as parent_persist_error:
                state = self._parent_lineage_commit_state(
                    parent.session.session_id,
                    old=old_parent_identity,
                    new=new_parent_identity,
                )
                if state == "NEW":
                    pass
                elif state == "OLD":
                    raise parent_persist_error
                else:
                    preserve_child_evidence = True
                    with self._lock:
                        self._parent_lineage_commit_unknown.update((
                            parent.session.session_id,
                            child.session.session_id,
                        ))
                    raise SessionStateError(
                        "parent_lineage_commit_state_unknown"
                    ) from parent_persist_error
        except Exception as finalization_error:
            if preserve_child_evidence:
                raise
            if previous_child_id is missing:
                parent.interaction_context.pop("preflight_child_session_id", None)
            else:
                parent.interaction_context["preflight_child_session_id"] = (
                    previous_child_id
                )
            parent.session.updated_at = previous_parent_updated_at
            try:
                self._delete_locked(child.session.session_id)
            except Exception as cleanup_error:
                raise cleanup_error from finalization_error
            raise
        if osm_parent_inputs is not None:
            (source_name, source_bytes), source_forward, authoritative_preflight = (
                osm_parent_inputs
            )
            self._attempt_osm_child_writeback(
                child,
                source_name=source_name,
                source_bytes=source_bytes,
                repaired_idf=application.output_text.encode("utf-8"),
                idd_text=idd_text,
                authoritative_preflight=authoritative_preflight,
                authoritative_forward_report=source_forward,
            )
        return child, application_report

    def _attempt_osm_child_writeback(
        self,
        child: SessionRecord,
        *,
        source_name: str,
        source_bytes: bytes,
        repaired_idf: bytes,
        idd_text: str,
        authoritative_preflight: Mapping[str, Any],
        authoritative_forward_report: Mapping[str, Any],
    ) -> None:
        """Keep the durable IDF child if exact OSM work or verification fails."""

        source_artifacts: dict[str, bytes] = {}
        try:
            authority = prepare_osm_execution(
                authoritative_preflight, authoritative_forward_report,
            )
            source_artifacts = self._osm_source_artifacts(
                authoritative_preflight, authoritative_forward_report, authority,
            )
        except Exception as exc:
            self._publish_failed_osm_workflow(
                child, source_artifacts=source_artifacts, exc=exc,
            )
            return
        adapter = self.osm_bridge
        if adapter is None or not hasattr(adapter, "apply_patch"):
            failure = SessionStateError("openstudio_writeback_bridge_unavailable")
            self._publish_failed_osm_workflow(
                child, source_artifacts=source_artifacts, exc=failure,
            )
            return
        simulation = {
            "status": "NOT_RUN",
            "simulation_ran": False,
            "passed": None,
            "semantic_equivalence_claimed": False,
        }
        try:
            evidence = execute_osm_writeback_verification(
                adapter,
                self.root,
                source_bytes=source_bytes,
                source_name=source_name,
                repaired_idf=repaired_idf,
                idd_text=idd_text,
                authority=authority,
                authoritative_forward_report=authoritative_forward_report,
            )
            simulation = self._validate_osm_child_simulation(child, repaired_idf)
            workflow_report = build_verified_osm_workflow_report(
                parent_session_id=str(child.interaction_context[
                    "preflight_parent_session_id"
                ]),
                child_session_id=child.session.session_id,
                source_bytes=source_bytes,
                repaired_idf=repaired_idf,
                authority=authority,
                evidence=evidence,
                simulation=simulation,
            )
            child.interaction_context.update({
                "osm_writeback_status": authority.writeback_status,
                "osm_writeback_commit_state": "COMMITTING",
                "osm_repaired_available": False,
            })
            child.session.updated_at = utc_now()
            self._persist(child)
            self._publish_verified_osm_child(
                child, source_artifacts, evidence, workflow_report,
            )
            child.interaction_context.update({
                "osm_writeback_status": authority.writeback_status,
                "osm_writeback_commit_state": "COMMITTED",
                "osm_repaired_available": True,
            })
            child.session.updated_at = utc_now()
            try:
                self._persist(child)
            except Exception:
                pass
        except Exception as exc:
            if str(exc) == "osm_child_final_simulation_failed":
                simulation = {
                    "status": "FAILED",
                    "simulation_ran": True,
                    "passed": False,
                    "semantic_equivalence_claimed": False,
                }
            self._publish_failed_osm_workflow(
                child,
                source_artifacts=source_artifacts,
                exc=exc,
                simulation=simulation,
            )

    @staticmethod
    def _osm_source_artifacts(
        authoritative_preflight: Mapping[str, Any],
        authoritative_forward_report: Mapping[str, Any],
        authority: OSMExecutionAuthority,
    ) -> dict[str, bytes]:
        return {
            "osm-source-forward.json": _json_artifact(authoritative_forward_report),
            "osm-source-preflight.json": _json_artifact(authoritative_preflight),
            "osm-patch.json": _json_artifact(authority.attempted_patch),
            "osm-execution-preflight.json": _json_artifact(
                authority.execution_preflight
            ),
            "osm-execution-patch.json": _json_artifact(authority.execution_patch),
        }

    def _validate_osm_child_simulation(
        self, child: SessionRecord, repaired_idf: bytes,
    ) -> dict[str, Any]:
        def run_final(repaired_text: str) -> Any:
            runtime = select_input_runtime(
                child.input_text,
                explicit=child.energyplus_path,
                requested_version=child.energyplus_version,
            )
            runner = EnergyPlusRunner(
                runtime,
                workspace=child.workspace,
                weather=child.weather,
                dependencies=child.dependencies,
                timeout_seconds=child.config.timeout_seconds,
                cache=EnergyPlusCache(child.workspace.safe_path("cache")),
            )
            return runner.run(repaired_text, 0)

        return validate_osm_simulation(
            repaired_idf,
            weather_ready=weather_asset_ready(child.weather),
            run_final=run_final,
        )

    def _publish_verified_osm_child(
        self,
        child: SessionRecord,
        source_artifacts: Mapping[str, bytes],
        evidence: OSMVerifiedEvidence,
        workflow_report: Mapping[str, Any],
    ) -> None:
        artifacts = {
            **source_artifacts,
            "osm-patcher-report.json": _json_artifact(evidence.patcher_report),
            "osm-source-audit.json": _json_artifact(evidence.source_audit),
            "osm-child-audit.json": _json_artifact(evidence.child_audit),
            "osm-post-forward.json": _json_artifact(evidence.forward_report),
            "osm-post-derived.idf": evidence.forward_idf,
            "osm-post-preflight.json": _json_artifact(evidence.post_preflight),
            "repaired.osm": evidence.repaired_osm,
            "osm-writeback.json": _json_artifact(workflow_report),
        }
        parsed = SessionManager._validated_osm_workflow_payload(
            child, workflow_report, artifacts=artifacts,
        )
        _publish_osm_artifacts(
            child.workspace.root,
            artifacts,
            commit_marker="osm-writeback.json",
        )
        self._osm_workflow_cache[child.session.session_id] = (
            self._osm_workflow_fingerprint(child), dict(parsed),
        )

    def _publish_failed_osm_workflow(
        self,
        child: SessionRecord,
        *,
        source_artifacts: Mapping[str, bytes],
        exc: Exception,
        simulation: Mapping[str, Any] | None = None,
    ) -> None:
        reason = _bounded_osm_failure_reason(exc)
        report = build_failed_osm_workflow_report(
            parent_session_id=str(child.interaction_context[
                "preflight_parent_session_id"
            ]),
            child_session_id=child.session.session_id,
            reason=reason,
            simulation=simulation,
            verification=(
                exc.verification_report
                if isinstance(exc, OSMChildVerificationFailed) else None
            ),
        )
        child.interaction_context.update({
            "osm_writeback_status": "OSM_WRITEBACK_FAILED",
            "osm_writeback_commit_state": "FAILED",
            "osm_repaired_available": False,
            "osm_writeback_failure_reason": reason,
        })
        child.session.updated_at = utc_now()
        try:
            self._persist(child)
        except Exception:
            pass
        try:
            artifacts = {
                **source_artifacts,
                "osm-writeback.json": _json_artifact(report),
            }
            self._validated_osm_workflow_payload(
                child, report, artifacts=artifacts,
            )
            _publish_osm_artifacts(
                child.workspace.root,
                artifacts,
                commit_marker="osm-writeback.json",
            )
        except SessionStateError:
            child.interaction_context["osm_writeback_artifact_status"] = "UNAVAILABLE"
            try:
                self._persist(child)
            except Exception:
                pass

    def preflight_parent_for(self, session_id: str) -> dict[str, Any]:
        record = self.get(session_id)
        parent_id = record.interaction_context.get("preflight_parent_session_id")
        if not isinstance(parent_id, str) or not parent_id:
            raise SessionStateError("preflight_parent_not_available")
        return self.summary(parent_id)

    def attach_osm_bridge(
        self,
        session_id: str,
        *,
        source_name: str,
        source_bytes: bytes,
        derived_bytes: bytes,
        bridge_report: Mapping[str, Any],
    ) -> None:
        """Persist the original OSM, derived IDF, and forward provenance together."""

        with self._session_guard(session_id, mode="mutation"):
            self._attach_osm_bridge_locked(
                self._get_locked(session_id),
                source_name=source_name,
                source_bytes=source_bytes,
                derived_bytes=derived_bytes,
                bridge_report=bridge_report,
            )

    def _attach_osm_bridge_locked(
        self,
        record: SessionRecord,
        *,
        source_name: str,
        source_bytes: bytes,
        derived_bytes: bytes,
        bridge_report: Mapping[str, Any],
    ) -> None:
        """Persist OSM bridge inputs while the stable session guard is held."""

        if len(source_bytes) > MAX_UPLOAD_BYTES:
            raise SessionStateError("osm_upload_too_large")
        safe_name = Path(source_name).name
        if not safe_name.casefold().endswith(".osm"):
            raise SessionStateError("osm_input_extension_required")
        if bridge_report.get("reverse_translation_used") is not False:
            raise SessionStateError("osm_bridge_reverse_translation_boundary_violation")
        if bridge_report.get("osm_writeback_authorized") is not False:
            raise SessionStateError("osm_bridge_writeback_boundary_violation")
        source = record.workspace.safe_path("uploads/source.osm")
        derived = record.workspace.safe_path("artifacts/derived.idf")
        report = record.workspace.safe_path("artifacts/osm-bridge.json")
        source.parent.mkdir(parents=True, exist_ok=True)
        derived.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(source_bytes)
        derived.write_bytes(derived_bytes)
        report.write_text(
            json.dumps(dict(bridge_report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        record.interaction_context.update({
            "source_type": "OSM",
            "source_input_name": safe_name,
            "osm_bridge_status": str(bridge_report.get("diagnostic_status") or "TRANSLATED"),
        })
        record.session.updated_at = utc_now()
        self._persist(record)

    def update_osm_bridge_report(
        self,
        session_id: str,
        bridge_report: Mapping[str, Any],
    ) -> None:
        """Update diagnostic mappings while keeping the no-writeback boundary immutable."""

        with self._session_guard(session_id, mode="mutation"):
            self._update_osm_bridge_report_locked(
                self._get_locked(session_id), bridge_report,
            )

    def _update_osm_bridge_report_locked(
        self,
        record: SessionRecord,
        bridge_report: Mapping[str, Any],
    ) -> None:
        """Update OSM bridge evidence while the stable session guard is held."""

        if bridge_report.get("reverse_translation_used") is not False:
            raise SessionStateError("osm_bridge_reverse_translation_boundary_violation")
        if bridge_report.get("osm_writeback_authorized") is not False:
            raise SessionStateError("osm_bridge_writeback_boundary_violation")
        if record.interaction_context.get("source_type") != "OSM":
            raise SessionStateError("session_is_not_osm_bridge")
        report = record.workspace.safe_path("artifacts/osm-bridge.json")
        report.write_text(
            json.dumps(dict(bridge_report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        record.interaction_context["osm_bridge_status"] = str(
            bridge_report.get("diagnostic_status") or "DIAGNOSED"
        )
        record.session.updated_at = utc_now()
        self._persist(record)

    def osm_source_for(self, session_id: str) -> tuple[str, bytes]:
        with self._session_guard(session_id):
            return self._osm_source_for_locked_record(self._get_locked(session_id))

    @staticmethod
    def _osm_source_for_locked_record(record: SessionRecord) -> tuple[str, bytes]:
        """Read OSM source data from a record whose stable guard is already held."""

        source = record.workspace.safe_path("uploads/source.osm")
        if record.interaction_context.get("source_type") != "OSM" or not source.is_file():
            raise SessionStateError("osm_source_not_available")
        name = str(record.interaction_context.get("source_input_name") or "source.osm")
        return Path(name).name, source.read_bytes()

    def osm_derived_for(self, session_id: str) -> tuple[str, bytes]:
        record = self.get(session_id)
        derived = record.workspace.safe_path("artifacts/derived.idf")
        if record.interaction_context.get("source_type") != "OSM" or not derived.is_file():
            raise SessionStateError("osm_derived_idf_not_available")
        source_name = str(record.interaction_context.get("source_input_name") or "source.osm")
        return f"{Path(source_name).stem}-derived.idf", derived.read_bytes()

    def osm_bridge_report_for(self, session_id: str) -> dict[str, Any]:
        with self._session_guard(session_id):
            return self._osm_bridge_report_for_locked_record(
                self._get_locked(session_id)
            )

    @staticmethod
    def _osm_bridge_report_for_locked_record(
        record: SessionRecord,
    ) -> dict[str, Any]:
        """Read OSM bridge JSON from a record whose stable guard is already held."""

        report = record.workspace.safe_path("artifacts/osm-bridge.json")
        if record.interaction_context.get("source_type") != "OSM" or not report.is_file():
            raise SessionStateError("osm_bridge_report_not_available")
        return dict(json.loads(report.read_text(encoding="utf-8")))

    def osm_repaired_for(self, session_id: str) -> tuple[str, bytes]:
        """Return a repaired OSM only when the commit marker verifies it."""

        record = self.get(session_id)
        try:
            report = self.osm_writeback_report_for(session_id)
        except SessionStateError as exc:
            if str(exc) in {
                "osm_writeback_report_not_available",
                "osm_writeback_report_invalid",
            }:
                raise SessionStateError("osm_repaired_not_available") from exc
            raise
        if (
            report.get("status") != "VERIFIED"
            or report.get("repaired_osm_available") is not True
        ):
            raise SessionStateError("osm_repaired_not_available")
        try:
            content = _read_osm_artifact(record.workspace.root, "repaired.osm")
        except FileNotFoundError as exc:
            raise SessionStateError("osm_repaired_not_available") from exc
        digest = report.get("repaired_osm_sha256")
        if not isinstance(digest, str) or sha256(content).hexdigest() != digest:
            raise SessionStateError("osm_repaired_artifact_invalid")
        source_name = str(
            record.interaction_context.get("source_input_name") or "source.osm"
        )
        return f"{Path(source_name).stem}-repaired.osm", content

    def osm_writeback_report_for(self, session_id: str) -> dict[str, Any]:
        """Read the finite workflow report that commits all OSM child artifacts."""

        with self._session_guard(session_id):
            return self._osm_writeback_report_for_locked_record(
                self._get_locked(session_id)
            )

    @staticmethod
    def _validated_osm_workflow_payload(
        record: SessionRecord,
        value: object,
        *,
        artifacts: Mapping[str, bytes] | None = None,
    ) -> dict[str, Any]:
        """Bind one marker to exact durable or not-yet-published companions."""

        def content(leaf: str) -> bytes:
            if artifacts is not None and leaf in artifacts:
                return artifacts[leaf]
            return _read_osm_artifact(record.workspace.root, leaf)

        def document(leaf: str) -> object:
            try:
                return json.loads(content(leaf).decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise SessionStateError("osm_writeback_report_invalid") from exc

        if not isinstance(value, Mapping):
            raise SessionStateError("osm_writeback_report_invalid")
        repaired_osm: bytes | None = None
        post_forward_idf: bytes | None = None
        if value.get("status") == "VERIFIED":
            try:
                repaired_osm = content("repaired.osm")
                post_forward_idf = content("osm-post-derived.idf")
                authoritative_preflight = document("osm-source-preflight.json")
                authoritative_forward = document("osm-source-forward.json")
                attempted_patch = document("osm-patch.json")
                execution_preflight = document("osm-execution-preflight.json")
                execution_patch = document("osm-execution-patch.json")
                patcher_report = document("osm-patcher-report.json")
                source_audit = document("osm-source-audit.json")
                child_audit = document("osm-child-audit.json")
                post_forward = document("osm-post-forward.json")
                post_preflight = document("osm-post-preflight.json")
                source_osm = SessionManager._osm_source_for_locked_record(record)[1]
            except (FileNotFoundError, SessionStateError) as exc:
                raise SessionStateError("osm_writeback_report_invalid") from exc
            try:
                authority = prepare_osm_execution(
                    authoritative_preflight, authoritative_forward,
                )
                post_model = ModelPreflightReport.model_validate(post_preflight)
            except Exception as exc:
                raise SessionStateError("osm_writeback_report_invalid") from exc
            verification = value.get("verification")
            remaining = [
                plan for plan in authority.execution_preflight["repair_plans"]
                if target_issue_remains(plan, post_model.repair_plans)
            ]
            forward_complete = _forward_report_evidence(
                _validated_inventory,
                post_forward,
                repaired_sha256=sha256(repaired_osm).hexdigest(),
                derived_sha256=sha256(post_forward_idf).hexdigest(),
            )[0]
            if (
                not isinstance(authoritative_forward, Mapping)
                or authoritative_forward.get("schema_version")
                != "idfrepair.openstudio-forward.v1"
                or post_model.schema_version != "idfrepair.model-preflight.v1"
                or
                _normalized_json(execution_preflight)
                != _normalized_json(authority.execution_preflight)
                or _normalized_json(execution_patch)
                != _normalized_json(authority.execution_patch)
                or not _valid_writeback_report(
                    patcher_report,
                    source_sha256=sha256(source_osm).hexdigest(),
                    repaired_sha256=sha256(repaired_osm).hexdigest(),
                    operations=authority.execution_patch.get("operations"),
                    trusted_loaded_inventory=(
                        authoritative_forward.get("loaded_handle_inventory")
                        if isinstance(authoritative_forward, Mapping) else None
                    ),
                    source_audit=source_audit,
                    child_audit=child_audit,
                )
                or not forward_complete
                or remaining
                or not isinstance(verification, Mapping)
                or verification.get("remaining_targeted_safe_issue_count") != 0
                or verification.get("post_forward_report_complete") is not True
            ):
                raise SessionStateError("osm_writeback_report_invalid")
        else:
            authoritative_preflight = {}
            attempted_patch = {}
            execution_patch = {}
            patcher_report = {}
            source_osm = None
            if artifacts is not None and "repaired.osm" in artifacts:
                raise SessionStateError("osm_writeback_report_invalid")
            if artifacts is None:
                try:
                    content("repaired.osm")
                except FileNotFoundError:
                    pass
                except SessionStateError as exc:
                    raise SessionStateError("osm_writeback_report_invalid") from exc
                else:
                    raise SessionStateError("osm_writeback_report_invalid")
        parent_id = record.interaction_context.get(
            "preflight_parent_session_id"
        )
        parsed = OSMWorkflowReport.from_mapping(
            value,
            authoritative_preflight=authoritative_preflight,
            attempted_patch=attempted_patch,
            execution_patch=execution_patch,
            patcher_report=patcher_report,
            expected_parent_session_id=(parent_id if isinstance(parent_id, str) else ""),
            expected_child_session_id=record.session.session_id,
            source_osm=source_osm,
            repaired_osm=repaired_osm,
            repaired_idf=(
                record.input_text.encode("utf-8")
                if value.get("status") == "VERIFIED" else None
            ),
            post_forward_idf=post_forward_idf,
        )
        if parsed is None:
            raise SessionStateError("osm_writeback_report_invalid")
        return parsed.as_dict()

    @staticmethod
    def _osm_workflow_fingerprint(
        record: SessionRecord,
    ) -> tuple[tuple[str, str], ...]:
        """Bind cached verification to the exact bytes of every committed leaf."""

        rows: list[tuple[str, str]] = []
        for leaf in _OSM_VERIFIED_LEAVES:
            try:
                content = (
                    _read_workspace_file_nofollow(
                        record.workspace,
                        "uploads/source.osm",
                        error_token="osm_writeback_report_invalid",
                    )
                    if leaf == "source.osm"
                    else _read_osm_artifact(record.workspace.root, leaf)
                )
            except SessionStateError as exc:
                raise SessionStateError("osm_writeback_report_invalid") from exc
            if content is None:  # required=True, retained for a total typed boundary
                raise SessionStateError("osm_writeback_report_invalid")
            rows.append((leaf, sha256(content).hexdigest()))
        return tuple(rows)

    def _osm_writeback_report_for_locked_record(
        self,
        record: SessionRecord,
    ) -> dict[str, Any]:
        """Read the minimal marker contract while the session guard is held."""

        session_id = record.session.session_id
        if record.interaction_context.get("source_type") != "OSM":
            raise SessionStateError("osm_writeback_report_not_available")
        fingerprint: tuple[tuple[str, str], ...] | None = None
        try:
            fingerprint = self._osm_workflow_fingerprint(record)
        except SessionStateError:
            self._osm_workflow_cache.pop(session_id, None)
            raise
        except ValueError as exc:
            self._osm_workflow_cache.pop(session_id, None)
            raise SessionStateError("osm_writeback_report_invalid") from exc
        except (FileNotFoundError, OSError):
            self._osm_workflow_cache.pop(session_id, None)
        cached = self._osm_workflow_cache.get(session_id)
        if fingerprint is not None and cached is not None and cached[0] == fingerprint:
            return dict(cached[1])
        try:
            content = _read_osm_artifact(
                record.workspace.root, "osm-writeback.json",
            )
            value = json.loads(content.decode("utf-8"))
        except FileNotFoundError as exc:
            raise SessionStateError("osm_writeback_report_not_available") from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SessionStateError("osm_writeback_report_invalid") from exc
        parsed = SessionManager._validated_osm_workflow_payload(record, value)
        if parsed.get("status") == "VERIFIED" and fingerprint is not None:
            self._osm_workflow_cache[session_id] = (fingerprint, dict(parsed))
        return parsed

    def verify_osm_child(self, session_id: str) -> dict[str, Any]:
        """Return the independently persisted child verification observation."""

        report = self.osm_writeback_report_for(session_id)
        verification = report.get("verification")
        if not isinstance(verification, Mapping):
            raise SessionStateError("osm_child_verification_not_available")
        return dict(verification)

    def execute(self, session_id: str, *, diagnose: bool = False) -> RepairOutcome:
        '''运行会话并在开始、结束和异常边界保存恢复快照。'''
        with self._session_guard(session_id, mode="mutation"):
            return self._execute_locked(session_id, diagnose=diagnose)

    def _execute_locked(self, session_id: str, *, diagnose: bool) -> RepairOutcome:
        """Execute one session while serializing its mutable state transitions."""

        record = self._get_locked(session_id)
        if record.lifecycle_status in {"CANCELLED", "ARCHIVED"}:
            raise SessionStateError("session_not_runnable")
        pending_state = self._pending_state_for_resume(record)
        run_weather = record.weather
        if (
            record.weather is not None
            and record.weather_sha256 is not None
            and record.weather_size_bytes is not None
        ):
            try:
                run_weather = verify_weather_blob(
                    record.workspace.root,
                    record.weather_sha256,
                    record.weather_size_bytes,
                )
            except ValueError as exc:
                raise SessionStateError("weather_blob_integrity_error") from exc
        self._require_run_readiness_locked(record)
        base = record.config
        config = EngineConfig(
            mode=RepairMode.ANALYZE_ONLY if diagnose else base.mode,
            max_rounds=base.max_rounds,
            max_candidates_per_root=base.max_candidates_per_root,
            max_total_energyplus_runs=max(2, base.max_total_energyplus_runs) if diagnose else base.max_total_energyplus_runs,
            max_backtracks=0 if diagnose else base.max_backtracks,
            max_wall_time=base.max_wall_time,
            max_model_tool_calls=base.max_model_tool_calls,
            maximum_automatic_risk=base.maximum_automatic_risk,
            minimum_automatic_confidence=base.minimum_automatic_confidence,
            model=base.model,
            model_base_path=base.model_base_path,
            model_adapter_path=base.model_adapter_path,
            model_runtime_python=base.model_runtime_python,
            timeout_seconds=base.timeout_seconds,
        )
        record.lifecycle_status = "RUNNING"
        record.session.updated_at = utc_now()
        self._persist(record)
        try:
            runtime = select_input_runtime(
                record.input_text,
                explicit=record.energyplus_path,
                requested_version=record.energyplus_version,
            )
            runner = EnergyPlusRunner(
                runtime,
                workspace=record.workspace,
                weather=run_weather,
                dependencies=record.dependencies,
                timeout_seconds=config.timeout_seconds,
                cache=EnergyPlusCache(record.workspace.safe_path("cache")),
            )
            engine = UnifiedEngine(
                runner,
                runtime.idd_path.read_text(encoding="utf-8", errors="replace"),
                config=config,
                context_metadata={
                    "target_version": runtime.version,
                    "template_fingerprint": template_fingerprint(record.input_text),
                    "selected_rule_set_id": record.selected_rule_set_id,
                    "model_energyplus_feedback": config.model != "none",
                    "rule_repository": self.rule_repository,
                    **record.interaction_context,
                },
            )
            outcome = engine.repair_text(
                record.input_text,
                approved_candidate_ids=record.approved_candidate_ids,
                extra_candidates=record.extra_candidates,
                pending_state=pending_state,
            )
        except Exception:
            record.lifecycle_status = "RECOVERABLE"
            record.session.updated_at = utc_now()
            self._persist(record)
            raise
        preprocessing = capture_preprocessing_artifact(
            record.workspace,
            getattr(runner, "results", ()),
            output_sha256=outcome.output_sha256,
        )
        self._store_outcome_locked(
            record,
            outcome,
            diagnose=diagnose,
            runtime_identity=runtime.identity,
            configuration=config,
            support_registry_audit=engine.support_registry_audit(),
            preprocessing=preprocessing,
        )
        return outcome

    @staticmethod
    def _validated_pending_state(
        record: SessionRecord,
    ) -> PendingRepairState | None:
        """Validate and type the private checkpoint before any answer mutation."""

        payload = (record.persisted_outcome or {}).get("pending_state")
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            raise SessionStateError("pending_repair_state_invalid")
        try:
            artifact_bytes = _read_workspace_file_nofollow(
                record.workspace,
                "artifacts/pending-state.json",
                error_token="pending_repair_state_invalid",
            )
            assert artifact_bytes is not None
            persisted_artifact = json.loads(artifact_bytes.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SessionStateError("pending_repair_state_invalid") from exc
        if _normalized_json(persisted_artifact) != _normalized_json(payload):
            raise SessionStateError("pending_repair_state_invalid")
        try:
            pending = TypeAdapter(PendingRepairState).validate_python(payload)
        except ValidationError as exc:
            raise SessionStateError("pending_repair_state_invalid") from exc
        if (
            not pending_repair_state_is_valid(
                pending,
                original_input_sha256=record.session.input_sha256,
            )
            or len(record.session.pending_questions) != 1
            or record.session.pending_questions[0] != pending.question
        ):
            raise SessionStateError("pending_repair_state_invalid")
        return pending

    def _resume_input_text(self, record: SessionRecord) -> str:
        """Select private working text only for a valid NEEDS_INPUT checkpoint."""

        if record.session.status is not RepairStatus.NEEDS_INPUT:
            return record.input_text
        pending = self._validated_pending_state(record)
        if pending is None:
            return record.input_text
        return pending.working_text

    def _pending_state_for_resume(
        self, record: SessionRecord,
    ) -> PendingRepairState | None:
        """Restore a fully typed checkpoint only from matching private evidence."""

        if record.session.status is not RepairStatus.NEEDS_INPUT:
            return None
        if record.lifecycle_status != "NEEDS_INPUT":
            raise SessionStateError("pending_repair_state_invalid")
        return self._validated_pending_state(record)

    def _store_outcome_locked(
        self,
        record: SessionRecord,
        outcome: RepairOutcome,
        *,
        diagnose: bool,
        runtime_identity: Mapping[str, Any],
        configuration: EngineConfig | None = None,
        support_registry_audit: Mapping[str, Any] | None = None,
        preprocessing: Mapping[str, Any] | None = None,
        lifecycle_status: str | None = None,
    ) -> None:
        """Publish one outcome while keeping a pending working copy private."""

        pending = outcome.pending_state
        pending_payload = to_primitive(pending) if pending is not None else None
        if pending is not None:
            if (
                outcome.status is not RepairStatus.NEEDS_INPUT
                or not pending_repair_state_is_valid(
                    pending,
                    original_input_sha256=record.session.input_sha256,
                )
                or len(outcome.questions) != 1
                or pending.question != outcome.questions[0]
            ):
                raise SessionStateError("pending_repair_state_invalid")
        previous_identity = self._record_database_identity(record)
        previous_last_action = record.interaction_context.get(
            "last_completed_action", _WEATHER_UNSET,
        )
        previous = (
            record.session.status,
            record.session.outcome,
            list(record.session.pending_questions),
            record.session.updated_at,
            dict(record.runtime_identity),
            list(record.model_calls),
            (
                json.loads(json.dumps(record.persisted_outcome))
                if record.persisted_outcome is not None else None
            ),
            (
                json.loads(json.dumps(record.report))
                if record.report is not None else None
            ),
            record.lifecycle_status,
        )
        pending_artifact = record.workspace.root / "artifacts/pending-state.json"
        report_artifact = record.workspace.root / "report.json"
        result_artifact = record.workspace.root / "result.idf"
        previous_artifacts = {
            pending_artifact: _read_workspace_file_nofollow(
                record.workspace,
                "artifacts/pending-state.json",
                required=False,
                error_token="pending_repair_state_invalid",
            ),
            report_artifact: _read_workspace_file_nofollow(
                record.workspace,
                "report.json",
                required=False,
                error_token="session_artifact_invalid",
            ),
            result_artifact: _read_workspace_file_nofollow(
                record.workspace,
                "result.idf",
                required=False,
                error_token="session_artifact_invalid",
            ),
        }

        def restore_record() -> None:
            (
                record.session.status,
                record.session.outcome,
                questions,
                record.session.updated_at,
                runtime,
                model_calls,
                record.persisted_outcome,
                record.report,
                record.lifecycle_status,
            ) = previous
            record.session.pending_questions = questions
            record.runtime_identity = runtime
            record.model_calls = model_calls
            if previous_last_action is _WEATHER_UNSET:
                record.interaction_context.pop("last_completed_action", None)
            else:
                record.interaction_context["last_completed_action"] = (
                    previous_last_action
                )

        def restore_artifacts() -> None:
            for artifact, content in previous_artifacts.items():
                if content is None:
                    artifact.unlink(missing_ok=True)
                else:
                    _atomic_replace_file(artifact, content)

        record.session.status = outcome.status
        record.session.outcome = outcome
        record.session.pending_questions = list(outcome.questions)
        record.session.updated_at = utc_now()
        record.runtime_identity = dict(runtime_identity)
        record.model_calls = [dict(row) for row in outcome.model_calls]
        record.persisted_outcome = outcome.to_dict()
        if pending_payload is None:
            record.persisted_outcome.pop("pending_state", None)
        try:
            record.report = build_session_report(
                session_id=record.session.session_id,
                input_name=record.session.input_name,
                input_text=record.input_text,
                outcome=outcome,
                configuration=configuration or record.config,
                runtime_identity=runtime_identity,
                user_answers=record.session.answers,
                support_registry_audit=support_registry_audit,
                preprocessing=preprocessing,
                input_had_utf8_bom=(
                    record.interaction_context.get("input_had_utf8_bom") is True
                ),
                output_has_utf8_bom=(
                    record.interaction_context.get("input_had_utf8_bom") is True
                ),
            )
            write_session_report(
                record.workspace.safe_path("report.json"), record.report,
            )
            if pending_payload is not None:
                checkpoint_bytes = (
                    json.dumps(
                        pending_payload,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ) + "\n"
                ).encode("utf-8")
                _atomic_replace_file(pending_artifact, checkpoint_bytes)
                _write_result_artifact(record, record.input_text)
            else:
                _write_result_artifact(record, outcome.output_text)
            record.interaction_context["last_completed_action"] = (
                "diagnose" if diagnose else "run"
            )
            record.lifecycle_status = lifecycle_status or (
                "NEEDS_INPUT"
                if outcome.status is RepairStatus.NEEDS_INPUT
                else "COMPLETE"
            )
        except Exception:
            restore_artifacts()
            restore_record()
            raise
        published_identity = self._record_database_identity(record)
        try:
            self._persist(record)
        except Exception as persist_error:
            try:
                durable = self._durable_session_row(record.session.session_id)
            except Exception as state_error:
                raise SessionStateError(
                    "pending_checkpoint_commit_state_unknown"
                ) from state_error
            if self._row_matches_identity(durable, published_identity):
                pass
            elif self._row_matches_identity(durable, previous_identity):
                restore_artifacts()
                restore_record()
                raise persist_error
            else:
                raise SessionStateError(
                    "pending_checkpoint_commit_state_unknown"
                ) from persist_error
        if pending_payload is None:
            pending_artifact.unlink(missing_ok=True)

    def resume(self, session_id: str) -> RepairOutcome:
        '''从持久输入、配置、回答和批准候选恢复执行。'''
        with self._session_guard(session_id, mode="mutation"):
            record = self._get_locked(session_id)
            if record.archived or record.lifecycle_status == "CANCELLED":
                raise SessionStateError("session_not_resumable")
            return self._execute_locked(session_id, diagnose=False)

    def create_settings_child(
        self,
        session_id: str,
        mode: RepairMode | str,
        runtime_id: str | None,
        *,
        energyplus_path: Path | None = None,
    ) -> SessionRecord:
        """Update pristine settings in place, otherwise create an inert linked copy."""

        selected_mode = mode if isinstance(mode, RepairMode) else RepairMode(mode)
        with self._session_guard(session_id, mode="mutation"):
            parent = self._get_locked(session_id)
            pristine = (
                parent.lifecycle_status == "CREATED"
                and parent.session.status is None
                and parent.persisted_outcome is None
                and parent.report is None
                and not parent.archived
            )
            if pristine:
                parent.config = _config({
                    **parent.config.to_dict(),
                    "mode": selected_mode.value,
                })
                parent.session.mode = selected_mode
                parent.energyplus_version = runtime_id
                parent.energyplus_path = energyplus_path
                parent.session.updated_at = utc_now()
                self._persist(parent)
                return parent

            child_session_id = uuid4().hex
            (
                input_bytes,
                weather,
                dependencies,
                staged_files,
                context,
            ) = self._settings_child_materials_locked(
                parent, child_session_id=child_session_id,
            )
            context.update({
                "settings_parent_session_id": parent.session.session_id,
                "settings_handoff_pending": True,
            })
            with self._session_guard(child_session_id, mode="mutation"):
                return self.create(
                    input_name=parent.session.input_name,
                    input_bytes=input_bytes,
                    config=_config({
                        **parent.config.to_dict(),
                        "mode": selected_mode.value,
                    }),
                    energyplus_path=energyplus_path,
                    energyplus_version=runtime_id,
                    weather=weather,
                    dependencies=dependencies,
                    selected_rule_set_id=parent.selected_rule_set_id,
                    project_id=str(
                        parent.interaction_context.get("project_id")
                        or parent.selected_rule_set_id
                    ),
                    batch_id=(
                        str(parent.interaction_context["batch_id"])
                        if parent.interaction_context.get("batch_id") else None
                    ),
                    _session_id=child_session_id,
                    _initial_interaction_context=context,
                    _staged_files=staged_files,
                )

    @staticmethod
    def _settings_child_materials_locked(
        parent: SessionRecord,
        *,
        child_session_id: str,
    ) -> tuple[
        bytes,
        tuple[str, bytes] | None,
        list[tuple[str, bytes]],
        dict[str, bytes],
        dict[str, Any],
    ]:
        """Stage and validate inherited bytes before publishing the child row."""

        try:
            input_bytes = _read_workspace_file_nofollow(
                parent.workspace, "uploads/input.idf",
            )
            assert input_bytes is not None
            input_text = input_bytes.decode("utf-8-sig")
            if text_sha256(input_text) != parent.session.input_sha256:
                raise SessionStateError("settings_inherited_asset_invalid")

            weather: tuple[str, bytes] | None = None
            if parent.weather is not None:
                if (
                    parent.weather_sha256 is not None
                    and parent.weather_size_bytes is not None
                    and parent.weather_original_name is not None
                ):
                    weather_relative = (
                        "uploads/weather/blobs/"
                        f"{parent.weather_sha256}.epw"
                    )
                    if parent.weather != parent.workspace.safe_path(weather_relative):
                        raise SessionStateError("settings_inherited_asset_invalid")
                    weather_bytes = _read_workspace_file_nofollow(
                        parent.workspace, weather_relative,
                    )
                    assert weather_bytes is not None
                    if (
                        len(weather_bytes) != parent.weather_size_bytes
                        or sha256(weather_bytes).hexdigest() != parent.weather_sha256
                    ):
                        raise SessionStateError("settings_inherited_asset_invalid")
                    weather = (parent.weather_original_name, weather_bytes)
                else:
                    try:
                        weather_relative = parent.weather.relative_to(
                            parent.workspace.root,
                        ).as_posix()
                    except ValueError as exc:
                        raise SessionStateError(
                            "settings_inherited_asset_invalid"
                        ) from exc
                    if not weather_relative.startswith("uploads/weather/"):
                        raise SessionStateError("settings_inherited_asset_invalid")
                    weather_bytes = _read_workspace_file_nofollow(
                        parent.workspace, weather_relative,
                    )
                    assert weather_bytes is not None
                    weather = (parent.weather.name, weather_bytes)

            dependency_root = parent.workspace.safe_path("uploads/dependencies")
            dependencies: list[tuple[str, bytes]] = []
            for path in parent.dependencies:
                try:
                    name = normalize_project_path(
                        path.relative_to(dependency_root).as_posix()
                    )
                except (ValueError, OSError) as exc:
                    raise SessionStateError(
                        "settings_inherited_asset_invalid"
                    ) from exc
                relative = f"uploads/dependencies/{name}"
                if path != parent.workspace.safe_path(relative):
                    raise SessionStateError("settings_inherited_asset_invalid")
                content = _read_workspace_file_nofollow(
                    parent.workspace, relative,
                )
                assert content is not None
                dependencies.append((name, content))

            context = {
                key: json.loads(json.dumps(value, ensure_ascii=False))
                for key, value in parent.interaction_context.items()
                if key not in {
                    "last_completed_action",
                    "preflight_child_session_id",
                    "settings_child_session_id",
                    "run_readiness",
                    "osm_writeback_status",
                    "osm_writeback_commit_state",
                    "osm_repaired_available",
                    "osm_writeback_failure_reason",
                    "osm_writeback_artifact_status",
                }
            }
            staged_files: dict[str, bytes] = {}

            preview_bytes = _read_workspace_file_nofollow(
                parent.workspace,
                "artifacts/model-preflight.json",
                required=False,
            )
            if preview_bytes is not None:
                preview = ModelPreflightReport.model_validate_json(preview_bytes)
                if (
                    preview.schema_version != "idfrepair.model-preflight.v1"
                    or preview.derived_copy_only is not True
                    or preview.original_input_changed is not False
                    or preview.input_sha256 != parent.session.input_sha256
                ):
                    raise SessionStateError("settings_inherited_asset_invalid")
                staged_files["artifacts/model-preflight.json"] = preview_bytes
            elif context.get("preflight_status") == "CHECKED":
                raise SessionStateError("settings_inherited_asset_invalid")

            application_bytes = _read_workspace_file_nofollow(
                parent.workspace,
                "artifacts/model-preflight-application.json",
                required=False,
            )
            if application_bytes is not None:
                application = json.loads(application_bytes.decode("utf-8"))
                if (
                    not isinstance(application, Mapping)
                    or application.get("schema_version")
                    != "idfrepair.model-preflight-application.v1"
                    or application.get("derived_copy_only") is not True
                    or application.get("original_input_changed") is not False
                    or application.get("output_sha256")
                    != parent.session.input_sha256
                    or not isinstance(application.get("validation"), Mapping)
                    or application["validation"].get("parsed") is not True
                ):
                    raise SessionStateError("settings_inherited_asset_invalid")
                staged_files[
                    "artifacts/model-preflight-application.json"
                ] = application_bytes
            elif context.get("preflight_status") == "APPLIED":
                raise SessionStateError("settings_inherited_asset_invalid")

            if context.get("source_type") == "OSM":
                source_bytes = _read_workspace_file_nofollow(
                    parent.workspace, "uploads/source.osm",
                )
                derived_bytes = _read_workspace_file_nofollow(
                    parent.workspace, "artifacts/derived.idf",
                )
                bridge_bytes = _read_workspace_file_nofollow(
                    parent.workspace, "artifacts/osm-bridge.json",
                )
                assert source_bytes is not None
                assert derived_bytes is not None
                assert bridge_bytes is not None
                if text_sha256(derived_bytes.decode("utf-8-sig")) != (
                    parent.session.input_sha256
                ):
                    raise SessionStateError("settings_inherited_asset_invalid")
                bridge = json.loads(bridge_bytes.decode("utf-8"))
                if (
                    not isinstance(bridge, Mapping)
                    or bridge.get("reverse_translation_used") is not False
                    or bridge.get("osm_writeback_authorized") is not False
                ):
                    raise SessionStateError("settings_inherited_asset_invalid")
                bridge = dict(bridge)
                for key in (
                    "diagnostic_mappings", "mapping_summary", "model_audit",
                ):
                    bridge.pop(key, None)
                bridge_status = {
                    "CHECKED": "PRECHECKED",
                    "APPLIED": "PREPROCESSING_APPLIED",
                }.get(str(context.get("preflight_status")), "PRECHECK_REQUIRED")
                bridge.update({
                    "session_id": child_session_id,
                    "diagnostic_status": bridge_status,
                    "reverse_translation_used": False,
                    "osm_writeback_authorized": False,
                })
                context["osm_bridge_status"] = bridge_status
                staged_files.update({
                    "uploads/source.osm": source_bytes,
                    "artifacts/derived.idf": derived_bytes,
                    "artifacts/osm-bridge.json": (
                        json.dumps(
                            bridge,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        ) + "\n"
                    ).encode("utf-8"),
                })
            return input_bytes, weather, dependencies, staged_files, context
        except SessionStateError:
            raise
        except (OSError, UnicodeError, ValueError, ValidationError, TypeError) as exc:
            raise SessionStateError("settings_inherited_asset_invalid") from exc

    def answer(self, session_id: str, *, question_id: str, value: Any) -> RepairOutcome:
        '''验证并持久化结构化回答，再从统一候选和验证流程恢复执行。'''
        with self._session_guard(session_id, mode="mutation"):
            return self._answer_locked(
                self._get_locked(session_id), question_id=question_id, value=value,
            )

    def _answer_locked(
        self,
        record: SessionRecord,
        *,
        question_id: str,
        value: Any,
    ) -> RepairOutcome:
        """Persist an answer and resume while the stable session guard is held."""

        pending = self._pending_state_for_resume(record)
        if pending is None:
            raise SessionStateError("pending_repair_state_invalid")
        question = pending.question
        if question.question_id != question_id:
            raise SessionStateError("pending_question_not_found")
        answer = UserAnswer(question_id=question_id, value=value)
        if value is None or (isinstance(value, str) and value in {"", "decline", "abort"}):
            self._save_answer(record, answer)
            outcome = RepairOutcome(
                status=RepairStatus.ROLLED_BACK,
                input_sha256=record.session.input_sha256,
                output_sha256=record.session.input_sha256,
                output_text=record.input_text,
                answers=list(record.session.answers),
                rollback_reason="user_declined",
            )
            self._store_outcome_locked(
                record,
                outcome,
                diagnose=False,
                runtime_identity=record.runtime_identity,
            )
            return outcome
        if question.question_type in {
            QuestionType.CHOOSE_CANDIDATE,
            QuestionType.CHOOSE_REFERENCE,
            QuestionType.CONFIRM_GEOMETRY,
            QuestionType.CONFIRM_VERSION,
        }:
            self._answer_candidate(record, question, value)
        elif question.question_type is QuestionType.ENTER_FIELD_VALUE:
            self._answer_field(
                record, question, answer, working_text=pending.working_text,
            )
        elif question.question_type is QuestionType.CHOOSE_OBJECT:
            self._answer_object(record, question, value)
        elif question.question_type is QuestionType.SELECT_REPAIR_FAMILY:
            self._answer_family(record, question, value)
        elif question.question_type is QuestionType.PROVIDE_EXTERNAL_FILE:
            raise SessionStateError("external_file_answer_requires_upload")
        else:
            raise SessionStateError("unsupported_question_type")
        self._save_answer(record, answer)
        self._persist(record)
        return self._execute_locked(record.session.session_id, diagnose=False)

    def _save_answer(self, record: SessionRecord, answer: UserAnswer) -> None:
        '''把同一回答同步写入会话快照和 Repair Memory 审计表。'''
        record.session.answers.append(answer)
        record.session.updated_at = utc_now()
        self.rule_repository.save_session_answer(
            session_id=record.session.session_id,
            question_id=answer.question_id,
            answer=answer.value,
        )

    @staticmethod
    def _answer_candidate(record: SessionRecord, question: UserQuestion, value: Any) -> None:
        '''验证候选身份属于当前问题，避免提交任意候选 ID。'''
        candidate_id = value.get("candidate_id") if isinstance(value, Mapping) else value
        if not isinstance(candidate_id, str):
            raise SessionStateError("answer_requires_candidate_id")
        valid_ids = {
            str(choice.get("candidate_id")) for choice in question.choices
            if choice.get("candidate_id") is not None
        }
        if candidate_id not in valid_ids:
            raise SessionStateError("selected_candidate_not_found")
        if candidate_id not in record.approved_candidate_ids:
            record.approved_candidate_ids.append(candidate_id)

    def _field_context(
        self,
        record: SessionRecord,
        *,
        working_text: str,
    ) -> CandidateContext:
        '''绑定会话当前输入、目标 IDD 和对象图，供用户字段值编译。'''
        runtime = select_input_runtime(
            working_text,
            explicit=record.energyplus_path,
            requested_version=record.energyplus_version,
        )
        document = parse_idf(working_text)
        idd = parse_idd(runtime.idd_path.read_text(encoding="utf-8", errors="replace"))
        return CandidateContext(
            document=document,
            idd=idd,
            roots=(),
            diagnostics_text="",
            rdd=parse_rdd(""),
            version=runtime.version or document.version,
            runtime_identity=runtime.identity,
            object_graph=build_object_graph(document, idd),
            metadata={
                "selected_rule_set_id": record.selected_rule_set_id,
                "template_fingerprint": template_fingerprint(working_text),
                **record.interaction_context,
            },
        )

    def _answer_field(
        self,
        record: SessionRecord,
        question: UserQuestion,
        answer: UserAnswer,
        *,
        working_text: str,
    ) -> None:
        '''把标量字段回答编译为 user_input 候选并保留全部统一门禁。'''
        candidate = answer_to_candidate(
            question,
            answer,
            (),
            self._field_context(record, working_text=working_text),
        )
        if candidate is None:
            raise SessionStateError("field_answer_did_not_create_candidate")
        record.extra_candidates = [
            row for row in record.extra_candidates if row.root_id != candidate.root_id
        ]
        record.extra_candidates.append(candidate)
        if candidate.candidate_id not in record.approved_candidate_ids:
            record.approved_candidate_ids.append(candidate.candidate_id)

    @staticmethod
    def _answer_object(record: SessionRecord, question: UserQuestion, value: Any) -> None:
        '''只接受问题列出的对象身份，并把选择绑定到当前错误根。'''
        supplied = value if isinstance(value, Mapping) else {"object_index": value}
        if supplied.get("object_index") is None:
            raise SessionStateError("selected_object_identity_required")
        selected = None
        for choice in question.choices:
            candidate_value = choice.get("value", choice)
            if isinstance(candidate_value, Mapping) and all(
                supplied.get(key) == candidate_value.get(key)
                for key in ("object_index", "object_type", "object_name")
                if key in supplied
            ):
                selected = dict(candidate_value)
                break
        if selected is None:
            raise SessionStateError("selected_object_not_found")
        rows = record.interaction_context.setdefault("user_selected_objects", {})
        rows[question.root_id] = selected

    @staticmethod
    def _answer_family(record: SessionRecord, question: UserQuestion, value: Any) -> None:
        '''只接受公开 family allowlist 中的英文 token。'''
        family = value.get("family") if isinstance(value, Mapping) else value
        if not isinstance(family, str) or family not in _REPAIR_FAMILIES:
            raise SessionStateError("selected_repair_family_invalid")
        rows = record.interaction_context.setdefault("user_selected_families", {})
        rows[question.root_id] = family

    def provide_external_file(
        self,
        session_id: str,
        *,
        question_id: str,
        filename: str,
        content: bytes,
    ) -> RepairOutcome:
        '''保存用户上传的外部依赖，并重新执行同一统一验证流程。'''
        with self._session_guard(session_id, mode="mutation"):
            return self._provide_external_file_locked(
                self._get_locked(session_id),
                question_id=question_id,
                filename=filename,
                content=content,
            )

    def _provide_external_file_locked(
        self,
        record: SessionRecord,
        *,
        question_id: str,
        filename: str,
        content: bytes,
    ) -> RepairOutcome:
        """Store a supplied dependency while the stable session guard is held."""

        pending = self._pending_state_for_resume(record)
        if (
            pending is None
            or pending.question.question_id != question_id
            or pending.question.question_type is not QuestionType.PROVIDE_EXTERNAL_FILE
        ):
            raise SessionStateError("external_file_question_not_found")
        # A direct browser upload supplies an untrusted client filename, not a
        # project-relative dependency manifest path.  Keep only its basename;
        # project-folder uploads still use normalize_project_path separately.
        path = self._store_upload(
            record.workspace, "dependencies", Path(filename).name, content,
        )
        if path not in record.dependencies:
            record.dependencies.append(path)
        answer = UserAnswer(question_id=question_id, value={"filename": path.name})
        self._save_answer(record, answer)
        self._persist(record)
        return self._execute_locked(record.session.session_id, diagnose=False)

    @staticmethod
    def _rule_rows(record: SessionRecord) -> tuple[dict[str, Any], ...]:
        '''返回用户参与且已提交的候选，排除自动结果和已保存身份。'''
        payload = record.persisted_outcome or {}
        if payload.get("status") != RepairStatus.REPAIRED.value:
            return ()
        saved = record.interaction_context.get("saved_rule_candidates", {})
        saved_ids = set(saved) if isinstance(saved, Mapping) else set()
        selected_roots = set()
        for key in ("user_selected_objects", "user_selected_families"):
            value = record.interaction_context.get(key, {})
            if isinstance(value, Mapping):
                selected_roots.update(str(item) for item in value)
        rows = []
        for round_row in payload.get("committed_rounds", ()):
            if not isinstance(round_row, Mapping):
                continue
            candidate = round_row.get("candidate")
            root = round_row.get("root")
            if not isinstance(candidate, Mapping) or not isinstance(root, Mapping):
                continue
            candidate_id = str(candidate.get("candidate_id", ""))
            root_id = str(candidate.get("root_id", ""))
            provenance = str(candidate.get("provenance", ""))
            user_participated = (
                candidate_id in record.approved_candidate_ids
                or provenance in {Provenance.USER_SELECTED.value, Provenance.USER_SUPPLIED.value}
                or str(candidate.get("provider", "")) == "user_value"
                or root_id in selected_roots
            )
            if not candidate_id or candidate_id in saved_ids or not user_participated:
                continue
            rows.append({
                "candidate_id": candidate_id,
                "family": str(candidate.get("family", root.get("family", "unknown"))),
                "provider": str(candidate.get("provider", "")),
                "root_id": root_id,
            })
        return tuple(rows)

    def save_rule(
        self,
        session_id: str,
        *,
        candidate_id: str,
        scope: str,
        name_zh: str,
        name_en: str,
        global_authorized: bool = False,
    ) -> RepairRule:
        '''把会话中完整验证通过的用户候选保存为受限 Repair Memory 规则。'''
        with self._session_guard(session_id, mode="mutation"):
            return self._save_rule_locked(
                self._get_locked(session_id),
                candidate_id=candidate_id,
                scope=scope,
                name_zh=name_zh,
                name_en=name_en,
                global_authorized=global_authorized,
            )

    def _save_rule_locked(
        self,
        record: SessionRecord,
        *,
        candidate_id: str,
        scope: str,
        name_zh: str,
        name_en: str,
        global_authorized: bool,
    ) -> RepairRule:
        """Persist a validated rule while the stable session guard is held."""

        session_id = record.session.session_id
        allowed = {row["candidate_id"] for row in self._rule_rows(record)}
        if candidate_id not in allowed:
            raise SessionStateError("validated_user_candidate_not_available")
        try:
            rule_scope = RuleScope(scope)
        except ValueError as exc:
            raise SessionStateError("rule_scope_invalid") from exc
        payload = record.persisted_outcome or {}
        round_rows = [
            row for row in payload.get("committed_rounds", ())
            if isinstance(row, Mapping)
            and isinstance(row.get("candidate"), Mapping)
            and row["candidate"].get("candidate_id") == candidate_id
        ]
        attempt_rows = [
            row for row in payload.get("attempts", ())
            if isinstance(row, Mapping)
            and row.get("candidate_id") == candidate_id
            and bool(row.get("accepted"))
        ]
        if len(round_rows) != 1 or len(attempt_rows) != 1:
            raise SessionStateError("validated_candidate_trace_incomplete")
        round_row = round_rows[0]
        attempt = attempt_rows[0]
        candidate = _candidate(round_row["candidate"])
        root = round_row.get("root", {})
        static_passed = bool((attempt.get("static_result") or {}).get("passed"))
        semantic_passed = bool((attempt.get("semantic_result") or {}).get("passed"))
        transition_passed = bool((attempt.get("transition_result") or {}).get("passed"))
        energyplus = attempt.get("energyplus_result") or {}
        energyplus_completed = not bool(
            energyplus.get("process_failure") or energyplus.get("timed_out")
        )
        if not isinstance(root, Mapping):
            raise SessionStateError("validated_candidate_root_missing")
        project_id = str(record.interaction_context.get("project_id") or "") or None
        batch_id = str(record.interaction_context.get("batch_id") or "") or None
        rule = save_validated_rule(
            self.rule_repository,
            candidate,
            name_zh=name_zh,
            name_en=name_en,
            scope=rule_scope,
            template_fingerprint=template_fingerprint(record.input_text),
            project_id=project_id,
            batch_id=batch_id,
            input_sha256=candidate.input_sha256,
            family=str(root.get("family") or candidate.family),
            error_signature=str(root.get("message") or candidate.family),
            energyplus_version=candidate.version,
            static_passed=static_passed,
            semantic_passed=semantic_passed,
            energyplus_passed=energyplus_completed and transition_passed,
            final_passed=payload.get("status") == RepairStatus.REPAIRED.value,
            rule_set_id=record.selected_rule_set_id,
            allow_global=global_authorized,
            root_object_type=(str(root["object_type"]) if root.get("object_type") else None),
            root_object_name=(str(root["object_name"]) if root.get("object_name") else None),
        )
        self.rule_repository.add_example(
            rule_id=rule.rule_id,
            input_fingerprint=candidate.input_sha256,
            before={"sha256": round_row.get("before_sha256")},
            after={"sha256": round_row.get("after_sha256")},
            validation={
                "static": attempt.get("static_result"),
                "semantic": attempt.get("semantic_result"),
                "transition": attempt.get("transition_result"),
                "final_status": payload.get("status"),
            },
        )
        saved = record.interaction_context.setdefault("saved_rule_candidates", {})
        if isinstance(saved, dict):
            saved[candidate_id] = rule.rule_id
        self.rule_repository.save_session_answer(
            session_id=session_id,
            question_id=f"save-rule:{candidate_id}",
            answer={"scope": rule_scope.value},
            saved_rule_id=rule.rule_id,
        )
        record.session.updated_at = utc_now()
        self._persist(record)
        return rule

    def cancel(self, session_id: str) -> RepairOutcome:
        '''把会话回滚到原始输入并持久标记为取消。'''
        with self._session_guard(session_id, mode="mutation"):
            return self._cancel_locked(session_id)

    def _cancel_locked(self, session_id: str) -> RepairOutcome:
        """Cancel while holding the stable session mutation lock."""

        record = self._get_locked(session_id)
        outcome = RepairOutcome(
            status=RepairStatus.ROLLED_BACK,
            input_sha256=record.session.input_sha256,
            output_sha256=record.session.input_sha256,
            output_text=record.input_text,
            answers=list(record.session.answers),
            rollback_reason="session_cancelled",
        )
        self._store_outcome_locked(
            record,
            outcome,
            diagnose=False,
            runtime_identity=record.runtime_identity,
            lifecycle_status="CANCELLED",
        )
        return outcome

    def archive(self, session_id: str) -> None:
        '''隐藏已结束会话但保留数据库和工作区以供审计恢复。'''
        with self._session_guard(session_id, mode="mutation"):
            self._archive_locked(session_id)

    def _archive_locked(self, session_id: str) -> None:
        """Archive while holding the stable session mutation lock."""

        record = self._get_locked(session_id)
        if record.lifecycle_status == "RUNNING":
            raise SessionStateError("running_session_cannot_be_archived")
        record.archived = True
        record.lifecycle_status = "ARCHIVED"
        record.session.updated_at = utc_now()
        self._persist(record)

    def delete(self, session_id: str) -> Path | None:
        '''删除数据库身份，并把工作区移动到本地回收目录而非永久擦除。'''
        with self._session_guard(session_id, mode="delete"):
            return self._delete_locked(session_id)

    def _delete_locked(self, session_id: str) -> Path | None:
        """Delete while retaining the tombstoned session lock identity."""

        record = self._get_locked(session_id)
        if record.lifecycle_status == "RUNNING":
            raise SessionStateError("running_session_cannot_be_deleted")
        parent_id = record.interaction_context.get("preflight_parent_session_id")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if isinstance(parent_id, str) and parent_id:
                parent_row = connection.execute(
                    "SELECT interaction_context_json FROM sessions WHERE session_id = ?",
                    (parent_id,),
                ).fetchone()
                if parent_row is not None:
                    try:
                        parent_context = json.loads(
                            parent_row["interaction_context_json"]
                        )
                    except (TypeError, ValueError) as exc:
                        raise SessionStateError(
                            "parent_lineage_state_invalid"
                        ) from exc
                    if not isinstance(parent_context, Mapping):
                        raise SessionStateError("parent_lineage_state_invalid")
                    if (
                        parent_context.get("preflight_child_session_id")
                        == session_id
                    ):
                        raise SessionStateError(
                            "session_is_current_preflight_child"
                        )
            connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        with self._lock:
            self._records.pop(session_id, None)
        if not record.workspace.root.exists():
            return None
        trash = self.root / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        target = trash / f"{session_id}-{utc_now().replace(':', '')}"
        shutil.move(str(record.workspace.root), str(target))
        return target

    def summary(self, session_id: str) -> dict[str, Any]:
        '''返回 API 可直接使用的会话摘要和恢复统计。'''
        with self._session_guard(session_id):
            return self._summary_locked(self._get_locked(session_id))

    def _summary_locked(self, record: SessionRecord) -> dict[str, Any]:
        """Build one summary while the stable per-session guard remains held."""

        osm_marker: Mapping[str, Any] | None = None
        if record.interaction_context.get("source_type") == "OSM":
            try:
                osm_marker = self._osm_writeback_report_for_locked_record(record)
            except SessionStateError:
                pass
        osm_writeback_status = record.interaction_context.get(
            "osm_writeback_status"
        )
        if record.interaction_context.get("osm_writeback_commit_state") == (
            "COMMITTING"
        ):
            osm_writeback_status = "OSM_WRITEBACK_COMMITTING"
        if osm_marker is not None:
            osm_writeback_status = (
                osm_marker.get("osm_writeback_status")
                if osm_marker.get("status") == "VERIFIED"
                else "OSM_WRITEBACK_FAILED"
            )
        outcome = record.persisted_outcome or {}
        root_support = [
            dict(row) for row in (record.report or {}).get("root_support", ())
            if isinstance(row, Mapping)
        ]
        components = component_statuses()
        rule_rows = self._rule_rows(record)
        scopes = [RuleScope.EXACT_FILE.value, RuleScope.EXACT_TEMPLATE.value]
        if record.interaction_context.get("project_id"):
            scopes.append(RuleScope.PROJECT.value)
        if record.interaction_context.get("batch_id"):
            scopes.append(RuleScope.BATCH.value)
        scopes.extend((RuleScope.OBJECT_PATTERN.value, RuleScope.GLOBAL.value))
        return {
            "automatic_repair_release_authorized": False,
            "archived": record.archived,
            "candidate_attempt_count": len(outcome.get("attempts", ())),
            "completed_round_count": len(outcome.get("committed_rounds", ())),
            "created_at": record.session.created_at,
            "input_name": record.session.input_name,
            "input_sha256": record.session.input_sha256,
            **session_display_metadata(
                outcome, input_sha256=record.session.input_sha256,
            ),
            "lifecycle_status": record.lifecycle_status,
            "mode": record.session.mode.value,
            "message": status_message(
                record.session.status.value if record.session.status else None,
                record.lifecycle_status,
            ),
            "source_type": str(record.interaction_context.get("source_type") or "IDF"),
            "source_input_name": (
                str(record.interaction_context["source_input_name"])
                if record.interaction_context.get("source_input_name") else None
            ),
            "osm_bridge_status": (
                str(record.interaction_context["osm_bridge_status"])
                if record.interaction_context.get("osm_bridge_status") else None
            ),
            "osm_writeback_status": (
                str(osm_writeback_status) if osm_writeback_status else None
            ),
            "idf_download_url": (
                f"/api/sessions/{record.session.session_id}/input"
                if record.interaction_context.get("preflight_status") == "APPLIED"
                else None
            ),
            "osm_download_url": (
                f"/api/sessions/{record.session.session_id}/osm-repaired"
                if (
                    osm_marker is not None
                    and osm_marker.get("status") == "VERIFIED"
                    and osm_marker.get("repaired_osm_available") is True
                )
                else None
            ),
            "osm_writeback_report_url": (
                f"/api/sessions/{record.session.session_id}/osm-writeback-report"
                if osm_marker is not None else None
            ),
            "preflight_status": (
                str(record.interaction_context["preflight_status"])
                if record.interaction_context.get("preflight_status") else None
            ),
            "preflight_parent_session_id": (
                str(record.interaction_context["preflight_parent_session_id"])
                if record.interaction_context.get("preflight_parent_session_id") else None
            ),
            "preflight_child_session_id": (
                str(record.interaction_context["preflight_child_session_id"])
                if record.interaction_context.get("preflight_child_session_id") else None
            ),
            "preflight_summary": (
                dict(record.interaction_context["preflight_summary"])
                if isinstance(record.interaction_context.get("preflight_summary"), Mapping)
                else None
            ),
            "batch_id": (
                str(record.interaction_context["batch_id"])
                if record.interaction_context.get("batch_id") else None
            ),
            "energyplus_version": record.energyplus_version,
            "last_completed_action": (
                str(record.interaction_context["last_completed_action"])
                if record.interaction_context.get("last_completed_action") else None
            ),
            "model_call_count": len(record.model_calls),
            "model_component_status": components["model_component_status"],
            "production_enabled": False,
            "questions": _question_display_rows(record),
            "release_profile_id": RELEASE_PROFILE_ID,
            "repair_memory_component_status": components["repair_memory_component_status"],
            "root_support": root_support,
            "selected_rule_set_id": record.selected_rule_set_id,
            "rule_save_available": bool(rule_rows),
            "rule_save_candidates": list(rule_rows),
            "rule_save_scope_choices": scopes if rule_rows else [],
            "session_id": record.session.session_id,
            "status": record.session.status.value if record.session.status else None,
            "support_coverage_summary": support_coverage_summary(root_support),
            "support_registry_sha256": EXPECTED_SUPPORT_REGISTRY_SHA256,
            "updated_at": record.session.updated_at,
        }

    def report_for(self, session_id: str) -> dict[str, Any]:
        '''返回持久报告，未运行会话明确拒绝。'''
        record = self.get(session_id)
        if record.report is None:
            raise SessionStateError("session_has_not_run")
        return record.report

    def output_for(self, session_id: str) -> tuple[str, bytes]:
        '''返回已运行结果；恢复会话从 result.idf 读取相同字节。'''
        record = self.get(session_id)
        result = record.workspace.safe_path("result.idf")
        if record.session.outcome is None or not result.is_file():
            raise SessionStateError("session_has_not_run")
        if repaired_artifact_allowed(record.session.outcome):
            name = f"{Path(record.session.input_name).stem}-repaired.idf"
            return name, result.read_bytes()
        name = f"{Path(record.session.input_name).stem}-unchanged.idf"
        original = record.workspace.safe_path("uploads/input.idf")
        return name, original.read_bytes()

    def input_for(self, session_id: str) -> tuple[str, bytes]:
        """Return the exact IDF copy currently bound to a session."""

        record = self.get(session_id)
        source = record.workspace.safe_path("uploads/input.idf")
        if not source.is_file():
            raise SessionStateError("session_input_not_available")
        return Path(record.session.input_name).name, source.read_bytes()

    def expanded_for(self, session_id: str) -> tuple[str, bytes]:
        """Return the independently labelled ExpandObjects simulation artifact."""
        record = self.get(session_id)
        artifact = record.workspace.safe_path("artifacts/expanded.expidf")
        if not artifact.is_file():
            raise SessionStateError("expanded_input_not_available")
        name = f"{Path(record.session.input_name).stem}-expanded.expidf"
        return name, artifact.read_bytes()


__all__ = [
    "MAX_UPLOAD_BYTES", "SessionManager", "SessionRecord", "capture_preprocessing_artifact",
]
