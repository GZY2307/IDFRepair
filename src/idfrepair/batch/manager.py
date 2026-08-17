"""Durable, sequential batch orchestration over the existing SessionManager."""

from __future__ import annotations

import csv
from io import BytesIO
from io import StringIO
import json
from pathlib import Path, PurePosixPath
import sqlite3
import threading
import time
from typing import Any, Mapping
from uuid import uuid4
import zipfile

from idfrepair.batch.runner import BatchInput
from idfrepair.config import EngineConfig
from idfrepair.domain.enums import RepairMode, RepairStatus, RiskLevel
from idfrepair.domain.models import utc_now
from idfrepair.io.idf import parse_idf


BATCH_TERMINAL_STATES = frozenset({
    "COMPLETED", "COMPLETED_WITH_ACTION_REQUIRED", "CANCELLED",
})
RECORD_TERMINAL_STATES = frozenset({
    "REPAIRED", "VALID", "NEEDS_INPUT", "UNSUPPORTED", "SEARCH_EXHAUSTED",
    "FAILED", "CANCELLED",
})
RECORD_ACTIVE_STATES = frozenset({
    "PREPARING", "DIAGNOSING", "REPAIRING", "VALIDATING",
})


def _config(payload: Mapping[str, Any]) -> EngineConfig:
    """Restore only public EngineConfig values from a persisted snapshot."""
    return EngineConfig(
        mode=RepairMode(str(payload.get("mode", RepairMode.SAFE_AUTO.value))),
        max_rounds=int(payload.get("max_rounds", 6)),
        max_candidates_per_root=int(payload.get("max_candidates_per_root", 3)),
        max_total_energyplus_runs=int(payload.get("max_total_energyplus_runs", 20)),
        max_backtracks=int(payload.get("max_backtracks", 1)),
        max_wall_time=float(payload.get("max_wall_time", 600.0)),
        max_model_tool_calls=int(payload.get("max_model_tool_calls", 12)),
        maximum_automatic_risk=RiskLevel(str(payload.get("maximum_automatic_risk", "LOW"))),
        minimum_automatic_confidence=float(payload.get("minimum_automatic_confidence", 0.85)),
        model=str(payload.get("model", "none")),
        model_base_path=(str(payload["model_base_path"]) if payload.get("model_base_path") else None),
        model_adapter_path=(str(payload["model_adapter_path"]) if payload.get("model_adapter_path") else None),
        model_runtime_python=(str(payload["model_runtime_python"]) if payload.get("model_runtime_python") else None),
        timeout_seconds=int(payload.get("timeout_seconds", 120)),
    )


def _record_state(status: RepairStatus) -> str:
    return {
        RepairStatus.REPAIRED: "REPAIRED",
        RepairStatus.VALID: "VALID",
        RepairStatus.NEEDS_INPUT: "NEEDS_INPUT",
        RepairStatus.UNSUPPORTED: "UNSUPPORTED",
        RepairStatus.SEARCH_EXHAUSTED: "SEARCH_EXHAUSTED",
        RepairStatus.PROCESS_FAILED: "FAILED",
        RepairStatus.ROLLED_BACK: "FAILED",
        RepairStatus.LIMIT_REACHED: "FAILED",
    }[status]


class BatchManager:
    """Persist batch/record state and run one EnergyPlus transaction at a time."""

    def __init__(self, root: Path, *, sessions: Any, recover: bool = True) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace_root = self.root / "batch-workspaces"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "batches.sqlite3"
        self.sessions = sessions
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._initialize()
        if recover and self._has_runnable_batches():
            self._ensure_worker()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    configuration_json TEXT NOT NULL,
                    energyplus_path TEXT,
                    energyplus_version TEXT,
                    rule_set_id TEXT NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS batch_records (
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
                    record_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    logical_name TEXT NOT NULL,
                    input_path TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    session_id TEXT,
                    error TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    duration_seconds REAL,
                    issue_count INTEGER NOT NULL DEFAULT 0,
                    remaining_issue_count INTEGER NOT NULL DEFAULT 0,
                    committed_candidate_count INTEGER NOT NULL DEFAULT 0,
                    energyplus_runs INTEGER NOT NULL DEFAULT 0,
                    pending_answer_json TEXT,
                    PRIMARY KEY (batch_id, record_id),
                    UNIQUE (batch_id, ordinal),
                    UNIQUE (batch_id, logical_name)
                );
                CREATE INDEX IF NOT EXISTS batch_record_queue
                ON batch_records(batch_id, state, ordinal);
            """)
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(batch_records)")
            }
            migrations = {
                "parent_record_id": "TEXT",
                "attempt_number": "INTEGER NOT NULL DEFAULT 1",
                "dependency_manifest_json": "TEXT NOT NULL DEFAULT '{}'",
                "readiness_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE batch_records ADD COLUMN {name} {definition}"
                    )
            active = tuple(RECORD_ACTIVE_STATES)
            placeholders = ",".join("?" for _ in active)
            connection.execute(
                f"UPDATE batch_records SET state='QUEUED', error='recovered_after_restart' "
                f"WHERE state IN ({placeholders})",
                active,
            )
            connection.commit()

    def create(
        self,
        inputs: tuple[BatchInput, ...],
        *,
        configuration: EngineConfig,
        energyplus_path: Path | None = None,
        energyplus_version: str | None = None,
        rule_set_id: str = "default",
        lineage: Mapping[str, tuple[str | None, int]] | None = None,
    ) -> dict[str, Any]:
        if not inputs:
            raise ValueError("batch_contains_no_idf")
        batch_id = uuid4().hex
        created = utc_now()
        directory = self.workspace_root / batch_id / "inputs"
        directory.mkdir(parents=True, exist_ok=False)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO batches VALUES (?,?,?,?,?,?,?,?,0)",
                (
                    batch_id, "CREATED", created, created,
                    json.dumps(configuration.to_dict(), sort_keys=True),
                    str(energyplus_path.expanduser().resolve()) if energyplus_path else None,
                    energyplus_version, rule_set_id,
                ),
            )
            for ordinal, record in enumerate(inputs):
                input_path = directory / f"{record.record_id}.idf"
                input_path.write_bytes(record.input_bytes)
                manifest = self._stage_support_files(batch_id, record)
                parent_record_id, attempt_number = (lineage or {}).get(
                    record.record_id,
                    (None, 1),
                )
                readiness = dict(record.readiness)
                initial_state = (
                    "NEEDS_INPUT"
                    if readiness.get("overall_status") in {
                        "MISSING", "NEEDS_INPUT", "UNSUPPORTED"
                    }
                    else "QUEUED"
                )
                connection.execute(
                    """INSERT INTO batch_records (
                        batch_id,record_id,ordinal,logical_name,input_path,input_sha256,state,
                        parent_record_id,attempt_number,dependency_manifest_json,readiness_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        batch_id, record.record_id, ordinal, record.logical_name,
                        str(input_path), record.input_sha256, initial_state,
                        parent_record_id, max(1, int(attempt_number)),
                        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                        json.dumps(readiness, ensure_ascii=False, sort_keys=True),
                    ),
                )
            connection.commit()
        return self.get(batch_id)

    def _stage_support_files(self, batch_id: str, record: BatchInput) -> dict[str, Any]:
        manifest = dict(record.dependency_manifest)
        support_root = self.workspace_root / batch_id / "support" / record.record_id
        staged: dict[str, Any] = {"weather": None, "dependencies": []}
        if record.weather is not None:
            name, content = record.weather
            support_root.mkdir(parents=True, exist_ok=True)
            suffix = Path(name).suffix or ".epw"
            path = support_root / f"weather{suffix}"
            path.write_bytes(content)
            staged["weather"] = {"logical_name": Path(name).name, "stored_path": str(path)}
        for index, (name, content) in enumerate(record.dependencies):
            support_root.mkdir(parents=True, exist_ok=True)
            suffix = Path(name).suffix
            path = support_root / f"dependency-{index:04d}{suffix}"
            path.write_bytes(content)
            staged["dependencies"].append({
                "logical_name": str(name),
                "stored_path": str(path),
            })
        if staged["weather"] is not None or staged["dependencies"]:
            manifest["_staged"] = staged
        return manifest

    def start(self, batch_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM batches WHERE batch_id=?", (batch_id,),
            ).fetchone()
            if row is None:
                raise KeyError(batch_id)
            if row["status"] not in {"CREATED", "COMPLETED_WITH_ACTION_REQUIRED", "RUNNING"}:
                raise ValueError("batch_not_startable")
            now = utc_now()
            connection.execute(
                "UPDATE batches SET status='RUNNING', updated_at=? WHERE batch_id=?",
                (now, batch_id),
            )
            connection.commit()
        self._ensure_worker()
        return self.get(batch_id)

    def cancel(self, batch_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM batches WHERE batch_id=?", (batch_id,),
            ).fetchone()
            if row is None:
                raise KeyError(batch_id)
            if row["status"] in {"COMPLETED", "CANCELLED"}:
                return self.get(batch_id)
            now = utc_now()
            connection.execute(
                "UPDATE batches SET status='CANCELLING',cancel_requested=1,updated_at=? WHERE batch_id=?",
                (now, batch_id),
            )
            connection.execute(
                "UPDATE batch_records SET state='CANCELLED',finished_at=? "
                "WHERE batch_id=? AND state='QUEUED'",
                (now, batch_id),
            )
            connection.commit()
        self._ensure_worker()
        return self.get(batch_id)

    def answer_record(
        self,
        batch_id: str,
        record_id: str,
        *,
        question_id: str,
        value: Any,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state,session_id FROM batch_records WHERE batch_id=? AND record_id=?",
                (batch_id, record_id),
            ).fetchone()
            if row is None:
                raise KeyError(record_id)
            if row["state"] != "NEEDS_INPUT" or not row["session_id"]:
                raise ValueError("batch_record_not_waiting_for_input")
            now = utc_now()
            connection.execute(
                """UPDATE batch_records SET
                    state='QUEUED',pending_answer_json=?,error=NULL,
                    started_at=NULL,finished_at=NULL,duration_seconds=NULL
                   WHERE batch_id=? AND record_id=?""",
                (json.dumps({"question_id": question_id, "value": value}, ensure_ascii=False), batch_id, record_id),
            )
            connection.execute(
                "UPDATE batches SET status='RUNNING',cancel_requested=0,updated_at=? WHERE batch_id=?",
                (now, batch_id),
            )
            connection.commit()
        self._ensure_worker()
        return self.record(batch_id, record_id)

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="idfrepair-batch-worker",
                daemon=True,
            )
            self._worker.start()

    def _has_runnable_batches(self) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM batches WHERE status IN ('RUNNING','CANCELLING') LIMIT 1"
            ).fetchone() is not None

    def _claim_next(self) -> sqlite3.Row | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("""
                SELECT r.*, b.configuration_json, b.energyplus_path,
                       b.energyplus_version, b.rule_set_id
                FROM batch_records AS r
                JOIN batches AS b ON b.batch_id=r.batch_id
                WHERE b.status='RUNNING' AND b.cancel_requested=0 AND r.state='QUEUED'
                ORDER BY b.created_at, b.batch_id, r.ordinal
                LIMIT 1
            """).fetchone()
            if row is not None:
                now = utc_now()
                connection.execute(
                    "UPDATE batch_records SET state='PREPARING',started_at=? "
                    "WHERE batch_id=? AND record_id=? AND state='QUEUED'",
                    (now, row["batch_id"], row["record_id"]),
                )
                connection.execute(
                    "UPDATE batches SET updated_at=? WHERE batch_id=?",
                    (now, row["batch_id"]),
                )
            connection.commit()
            return row

    def _worker_loop(self) -> None:
        while True:
            row = self._claim_next()
            if row is None:
                self._finalize_batches()
                row = self._claim_next()
                if row is None:
                    return
            self._process(row)
            self._finalize_batches()

    def _set_record(self, batch_id: str, record_id: str, **values: Any) -> None:
        if not values:
            return
        assignments = ",".join(f"{key}=?" for key in values)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE batch_records SET {assignments} WHERE batch_id=? AND record_id=?",
                (*values.values(), batch_id, record_id),
            )
            connection.execute(
                "UPDATE batches SET updated_at=? WHERE batch_id=?",
                (utc_now(), batch_id),
            )
            connection.commit()

    @staticmethod
    def _support_uploads(row: Mapping[str, Any]) -> tuple[
        tuple[str, bytes] | None,
        tuple[tuple[str, bytes], ...],
    ]:
        raw_manifest = (
            row["dependency_manifest_json"]
            if "dependency_manifest_json" in row.keys()
            else "{}"
        )
        manifest = json.loads(str(raw_manifest or "{}"))
        staged = manifest.get("_staged") if isinstance(manifest, dict) else None
        if not isinstance(staged, dict):
            return None, ()
        weather_row = staged.get("weather")
        weather = None
        if isinstance(weather_row, dict) and weather_row.get("stored_path"):
            weather = (
                str(weather_row.get("logical_name") or "weather.epw"),
                Path(str(weather_row["stored_path"])).read_bytes(),
            )
        dependencies = []
        for item in staged.get("dependencies") or ():
            if not isinstance(item, dict) or not item.get("stored_path"):
                continue
            dependencies.append((
                str(item.get("logical_name") or "dependency.dat"),
                Path(str(item["stored_path"])).read_bytes(),
            ))
        return weather, tuple(dependencies)

    def _process(self, row: sqlite3.Row) -> None:
        batch_id = str(row["batch_id"])
        record_id = str(row["record_id"])
        started = time.perf_counter()
        try:
            session_id = str(row["session_id"] or "")
            pending = json.loads(row["pending_answer_json"]) if row["pending_answer_json"] else None
            if pending is not None:
                self._set_record(batch_id, record_id, state="REPAIRING")
                outcome = self.sessions.answer(
                    session_id,
                    question_id=str(pending["question_id"]),
                    value=pending.get("value"),
                )
            else:
                if not session_id:
                    content = Path(str(row["input_path"])).read_bytes()
                    weather, dependencies = self._support_uploads(row)
                    created = self.sessions.create(
                        input_name=Path(str(row["logical_name"])).name,
                        input_bytes=content,
                        config=_config(json.loads(row["configuration_json"])),
                        energyplus_path=(Path(str(row["energyplus_path"])) if row["energyplus_path"] else None),
                        energyplus_version=(str(row["energyplus_version"]) if row["energyplus_version"] else None),
                        selected_rule_set_id=str(row["rule_set_id"]),
                        batch_id=batch_id,
                        weather=weather,
                        dependencies=dependencies,
                    )
                    session_id = str(created.session.session_id)
                    self._set_record(batch_id, record_id, session_id=session_id)
                self._set_record(batch_id, record_id, state="DIAGNOSING")
                diagnosis = self.sessions.execute(session_id, diagnose=True)
                if diagnosis.status is RepairStatus.VALID:
                    outcome = diagnosis
                elif diagnosis.status is RepairStatus.PROCESS_FAILED:
                    outcome = diagnosis
                else:
                    self._set_record(batch_id, record_id, state="REPAIRING")
                    outcome = self.sessions.execute(session_id)
            self._set_record(batch_id, record_id, state="VALIDATING")
            summary = self.sessions.summary(session_id)
            try:
                report = self.sessions.report_for(session_id)
            except Exception:
                report = {}
            state = _record_state(outcome.status)
            self._set_record(
                batch_id,
                record_id,
                state=state,
                pending_answer_json=None,
                error=None,
                finished_at=utc_now(),
                duration_seconds=round(time.perf_counter() - started, 6),
                issue_count=int(summary.get("initial_issue_count", 0)),
                remaining_issue_count=int(summary.get("remaining_issue_count", 0)),
                committed_candidate_count=int(summary.get("committed_candidate_count", 0)),
                energyplus_runs=int(report.get("energyplus_runs", 0)),
            )
        except Exception as exc:
            self._set_record(
                batch_id,
                record_id,
                state="FAILED",
                error=f"{type(exc).__name__}:{exc}",
                finished_at=utc_now(),
                duration_seconds=round(time.perf_counter() - started, 6),
            )

    def _finalize_batches(self) -> None:
        with self._connect() as connection:
            batches = connection.execute(
                "SELECT batch_id,status,cancel_requested FROM batches "
                "WHERE status IN ('RUNNING','CANCELLING')"
            ).fetchall()
            now = utc_now()
            for batch in batches:
                batch_id = str(batch["batch_id"])
                if bool(batch["cancel_requested"]):
                    connection.execute(
                        "UPDATE batch_records SET state='CANCELLED',finished_at=? "
                        "WHERE batch_id=? AND state='QUEUED'",
                        (now, batch_id),
                    )
                active = connection.execute(
                    "SELECT 1 FROM batch_records WHERE batch_id=? AND state IN "
                    "('QUEUED','PREPARING','DIAGNOSING','REPAIRING','VALIDATING') LIMIT 1",
                    (batch_id,),
                ).fetchone()
                if active is not None:
                    continue
                if bool(batch["cancel_requested"]):
                    status = "CANCELLED"
                else:
                    action = connection.execute(
                        "SELECT 1 FROM batch_records WHERE batch_id=? AND state IN "
                        "('NEEDS_INPUT','UNSUPPORTED','SEARCH_EXHAUSTED','FAILED') LIMIT 1",
                        (batch_id,),
                    ).fetchone()
                    status = "COMPLETED_WITH_ACTION_REQUIRED" if action else "COMPLETED"
                connection.execute(
                    "UPDATE batches SET status=?,updated_at=? WHERE batch_id=?",
                    (status, now, batch_id),
                )
            connection.commit()

    def get(self, batch_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            batch = connection.execute(
                "SELECT * FROM batches WHERE batch_id=?", (batch_id,),
            ).fetchone()
            if batch is None:
                raise KeyError(batch_id)
            states = [
                str(row[0]) for row in connection.execute(
                    "SELECT state FROM batch_records WHERE batch_id=? ORDER BY ordinal",
                    (batch_id,),
                )
            ]
            current = connection.execute(
                "SELECT logical_name,state FROM batch_records WHERE batch_id=? AND state IN "
                "('PREPARING','DIAGNOSING','REPAIRING','VALIDATING') ORDER BY ordinal LIMIT 1",
                (batch_id,),
            ).fetchone()
        counts = {state: states.count(state) for state in sorted(set(states) | RECORD_TERMINAL_STATES)}
        completed = sum(state in RECORD_TERMINAL_STATES for state in states)
        configuration = json.loads(str(batch["configuration_json"]))
        return {
            "schema_version": "idfrepair.batch.state.v1",
            "batch_id": batch_id,
            "status": str(batch["status"]),
            "created_at": str(batch["created_at"]),
            "updated_at": str(batch["updated_at"]),
            "mode": str(configuration.get("mode", RepairMode.SAFE_AUTO.value)),
            "energyplus_version": (
                str(batch["energyplus_version"])
                if batch["energyplus_version"] else None
            ),
            "progress": {"completed": completed, "total": len(states)},
            "counts": counts,
            "current": ({"logical_name": current["logical_name"], "state": current["state"]} if current else None),
            "production_enabled": False,
            "automatic_repair_release_authorized": False,
        }

    def list(self) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            identities = [
                str(row[0]) for row in connection.execute(
                    "SELECT batch_id FROM batches ORDER BY updated_at DESC, batch_id"
                )
            ]
        return tuple(self.get(batch_id) for batch_id in identities)

    def records(self, batch_id: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM batches WHERE batch_id=?", (batch_id,),
            ).fetchone() is None:
                raise KeyError(batch_id)
            rows = connection.execute(
                "SELECT * FROM batch_records WHERE batch_id=? ORDER BY ordinal",
                (batch_id,),
            ).fetchall()
        return tuple(self._record_payload(row) for row in rows)

    def record(self, batch_id: str, record_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM batch_records WHERE batch_id=? AND record_id=?",
                (batch_id, record_id),
            ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return self._record_payload(row)

    def source_for_record(self, batch_id: str, record_id: str) -> tuple[str, bytes]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT logical_name,input_path FROM batch_records "
                "WHERE batch_id=? AND record_id=?",
                (batch_id, record_id),
            ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return str(row["logical_name"]), Path(str(row["input_path"])).read_bytes()

    def retry_records(
        self,
        batch_id: str,
        record_ids: list[str] | tuple[str, ...],
        *,
        energyplus_path: Path | None = None,
        energyplus_version: str | None = None,
        mode: str | None = None,
        replacement_inputs: Mapping[str, BatchInput] | None = None,
    ) -> dict[str, Any]:
        """Create a new sequential batch for selected actionable records only."""

        requested = tuple(dict.fromkeys(str(value) for value in record_ids if str(value)))
        if not requested:
            raise ValueError("batch_retry_contains_no_records")
        with self._connect() as connection:
            batch = connection.execute(
                "SELECT * FROM batches WHERE batch_id=?", (batch_id,),
            ).fetchone()
            if batch is None:
                raise KeyError(batch_id)
            if str(batch["status"]) not in BATCH_TERMINAL_STATES:
                raise ValueError("batch_retry_source_not_terminal")
            placeholders = ",".join("?" for _ in requested)
            rows = connection.execute(
                f"SELECT * FROM batch_records WHERE batch_id=? "
                f"AND record_id IN ({placeholders}) ORDER BY ordinal",
                (batch_id, *requested),
            ).fetchall()
        if len(rows) != len(requested):
            raise KeyError("batch_retry_record_unknown")
        retryable = {"FAILED", "NEEDS_INPUT", "UNSUPPORTED", "SEARCH_EXHAUSTED"}
        if any(str(row["state"]) not in retryable for row in rows):
            raise ValueError("batch_record_not_retryable")
        configuration_payload = json.loads(str(batch["configuration_json"]))
        if mode is not None:
            configuration_payload["mode"] = RepairMode(mode).value
        configuration = _config(configuration_payload)
        inputs: list[BatchInput] = []
        lineage: dict[str, tuple[str | None, int]] = {}
        replacements = replacement_inputs or {}
        for row in rows:
            parent_id = str(row["record_id"])
            replacement = replacements.get(parent_id)
            if replacement is not None and replacement.logical_name != str(row["logical_name"]):
                raise ValueError("batch_retry_replacement_path_mismatch")
            if replacement is None:
                content = Path(str(row["input_path"])).read_bytes()
                weather, dependencies = self._support_uploads(row)
                manifest = json.loads(str(row["dependency_manifest_json"] or "{}"))
                if isinstance(manifest, dict):
                    manifest.pop("_staged", None)
                readiness = json.loads(str(row["readiness_json"] or "{}"))
                replacement = BatchInput(
                    record_id=parent_id,
                    logical_name=str(row["logical_name"]),
                    text=content.decode("utf-8-sig"),
                    input_sha256=str(row["input_sha256"]),
                    source_kind="batch-retry",
                    source_identity=f"batch:{batch_id}:{parent_id}",
                    input_bytes=content,
                    weather=weather,
                    dependencies=dependencies,
                    dependency_manifest=manifest if isinstance(manifest, dict) else {},
                    readiness=readiness if isinstance(readiness, dict) else {},
                )
            new_id = uuid4().hex[:24]
            inputs.append(BatchInput(
                record_id=new_id,
                logical_name=replacement.logical_name,
                text=replacement.text,
                input_sha256=replacement.input_sha256,
                source_kind="batch-retry",
                source_identity=f"batch:{batch_id}:{parent_id}",
                input_bytes=replacement.input_bytes,
                weather=replacement.weather,
                dependencies=replacement.dependencies,
                dependency_manifest=replacement.dependency_manifest,
                readiness=replacement.readiness,
            ))
            lineage[new_id] = (parent_id, int(row["attempt_number"]) + 1)
        created = self.create(
            tuple(inputs),
            configuration=configuration,
            energyplus_path=(
                energyplus_path
                if energyplus_path is not None
                else Path(str(batch["energyplus_path"])) if batch["energyplus_path"] else None
            ),
            energyplus_version=(
                energyplus_version
                if energyplus_version is not None
                else str(batch["energyplus_version"]) if batch["energyplus_version"] else None
            ),
            rule_set_id=str(batch["rule_set_id"]),
            lineage=lineage,
        )
        return self.start(str(created["batch_id"]))

    @staticmethod
    def _record_payload(row: sqlite3.Row) -> dict[str, Any]:
        manifest = json.loads(str(row["dependency_manifest_json"] or "{}"))
        if isinstance(manifest, dict):
            manifest.pop("_staged", None)
        readiness = json.loads(str(row["readiness_json"] or "{}"))
        try:
            idf_version = parse_idf(
                Path(str(row["input_path"])).read_text(encoding="utf-8-sig")
            ).version or None
        except (OSError, UnicodeError, ValueError):
            idf_version = None
        return {
            "record_id": str(row["record_id"]),
            "ordinal": int(row["ordinal"]),
            "logical_name": str(row["logical_name"]),
            "input_sha256": str(row["input_sha256"]),
            "idf_version": idf_version,
            "state": str(row["state"]),
            "parent_record_id": (
                str(row["parent_record_id"]) if row["parent_record_id"] else None
            ),
            "attempt_number": int(row["attempt_number"]),
            "dependency_manifest": manifest if isinstance(manifest, dict) else {},
            "readiness": readiness if isinstance(readiness, dict) else {},
            "session_id": (str(row["session_id"]) if row["session_id"] else None),
            "error": row["error"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_seconds": row["duration_seconds"],
            "issue_count": int(row["issue_count"]),
            "remaining_issue_count": int(row["remaining_issue_count"]),
            "committed_candidate_count": int(row["committed_candidate_count"]),
            "energyplus_runs": int(row["energyplus_runs"]),
        }

    def wait(self, batch_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = self.get(batch_id)
            if snapshot["status"] in BATCH_TERMINAL_STATES:
                return snapshot
            time.sleep(0.02)
        raise TimeoutError(f"batch_wait_timeout:{batch_id}")

    def export_json(self, batch_id: str) -> bytes:
        snapshot = self.get(batch_id)
        records = list(self.records(batch_id))
        payload = {
            "schema_version": "idfrepair.batch.export.v1",
            "batch": snapshot,
            "records": records,
            "production_enabled": False,
        }
        return (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

    def export_csv(self, batch_id: str) -> bytes:
        snapshot = self.get(batch_id)
        records = self.records(batch_id)
        columns = [
            "relative_path", "status", "idf_version", "runtime_version", "root_count",
            "committed_repairs", "energyplus_pass", "duration_seconds", "action_required",
            "attempt_number", "parent_record_id",
        ]
        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        actionable = {"NEEDS_INPUT", "UNSUPPORTED", "SEARCH_EXHAUSTED", "FAILED"}
        for row in records:
            state = str(row["state"])
            writer.writerow({
                "relative_path": row["logical_name"],
                "status": state,
                "idf_version": row.get("idf_version") or "",
                "runtime_version": snapshot.get("energyplus_version") or "",
                "root_count": row["issue_count"],
                "committed_repairs": row["committed_candidate_count"],
                "energyplus_pass": "true" if state in {"REPAIRED", "VALID"} else "false",
                "duration_seconds": "" if row["duration_seconds"] is None else row["duration_seconds"],
                "action_required": "true" if state in actionable else "false",
                "attempt_number": row["attempt_number"],
                "parent_record_id": row["parent_record_id"] or "",
            })
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    @staticmethod
    def _zip_path(logical_name: str) -> str:
        path = PurePosixPath(logical_name)
        safe = [
            "".join(character if character.isalnum() or character in "-_." else "-" for character in part)
            or "input"
            for part in path.parts
        ]
        return "/".join(safe)

    def download(self, batch_id: str) -> bytes:
        snapshot = self.get(batch_id)
        if snapshot["status"] not in BATCH_TERMINAL_STATES:
            raise ValueError("batch_download_not_ready")
        records = self.records(batch_id)
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for row in records:
                logical = self._zip_path(str(row["logical_name"]))
                input_path = self.workspace_root / batch_id / "inputs" / f"{row['record_id']}.idf"
                state = str(row["state"])
                if state == "REPAIRED" and row["session_id"]:
                    _, content = self.sessions.output_for(str(row["session_id"]))
                    category = "repaired"
                else:
                    content = input_path.read_bytes()
                    category = {
                        "VALID": "unchanged",
                        "NEEDS_INPUT": "needs_input",
                    }.get(state, "failed")
                archive.writestr(f"{category}/{logical}", content)
                if row["session_id"]:
                    try:
                        report = self.sessions.report_for(str(row["session_id"]))
                    except Exception:
                        report = {"error": row["error"], "state": state}
                else:
                    report = {"error": row["error"], "state": state}
                archive.writestr(
                    f"reports/{row['record_id']}.json",
                    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                )
            archive.writestr(
                "batch_summary.json",
                json.dumps(
                    {**snapshot, "records": list(records)},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
            )
        return buffer.getvalue()


__all__ = [
    "BATCH_TERMINAL_STATES", "BatchManager", "RECORD_TERMINAL_STATES",
]
