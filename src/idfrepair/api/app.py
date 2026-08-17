"""FastAPI routes and bundled local web application."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from idfrepair.api.messages import error_message, message
from idfrepair.api.presentation import capability_display_metadata
from idfrepair.api.schemas import (
    AnswerRequest, AuditRequest, BatchAnswerRequest, BatchRetryRequest, ExperimentalPreviewRequest,
    MigrationRequest, ModelPreflightRequest, RuleSaveRequest, RuleSetRequest, SessionCreated,
    SessionSummary, SettingsChildRequest,
)
from idfrepair.api.sessions import SessionManager
from idfrepair.batch.manager import BatchManager
from idfrepair.batch.runner import discover_project_inputs, discover_uploaded_inputs
from idfrepair.capabilities.reporting import capabilities_payload
from idfrepair.config import EngineConfig
from idfrepair.domain.enums import RepairMode
from idfrepair.domain.errors import IDFRepairError
from idfrepair.memory.import_export import import_rules
from idfrepair.memory.repository import RuleRepository
from idfrepair.osm.bridge import (
    OpenStudioBridge, map_audit_findings_to_osm, map_idf_findings_to_osm,
)
from idfrepair.project.readiness import inspect_project_files
from idfrepair.io.idf import parse_idf
from idfrepair.runtime.catalog import RuntimeCatalog
from idfrepair.runtime.discovery import normalize_version
from idfrepair.runtime.transition import (
    discover_transitions, migrate_copy, migration_artifact, migration_report, transition_chain,
)


def _failure(exc: Exception) -> HTTPException:
    status = 404 if isinstance(exc, KeyError) else 400
    return HTTPException(status_code=status, detail=error_message(exc))


async def _upload_tuple(
    upload: UploadFile | None,
    *,
    preserve_filename: bool = False,
) -> tuple[str, bytes] | None:
    if upload is None:
        return None
    supplied_name = upload.filename or "upload"
    return (
        supplied_name if preserve_filename else Path(supplied_name).name,
        await upload.read(),
    )


def open_local_folder(path: Path, runner=subprocess.run) -> None:  # type: ignore[no-untyped-def]
    """Open one already-resolved session workspace in the local file manager."""

    try:
        target = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise OSError("session_workspace_missing") from exc
    except NotADirectoryError as exc:
        raise OSError("session_workspace_not_directory") from exc
    except PermissionError as exc:
        raise OSError("session_workspace_unreadable") from exc
    except OSError as exc:
        raise OSError("session_workspace_unreadable") from exc
    if not target.is_dir():
        raise OSError("session_workspace_not_directory")
    if sys.platform == "darwin":
        command = ["open", "-a", "Finder", str(target)]
    elif sys.platform.startswith("linux"):
        command = ["xdg-open", str(target)]
    else:
        raise OSError("local_folder_opener_unavailable")
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("local_folder_open_timed_out") from exc
    except FileNotFoundError as exc:
        raise OSError("local_folder_opener_missing") from exc
    if completed.returncode != 0:
        raise OSError(f"local_folder_open_failed:{completed.returncode}")


def create_app(
    *,
    session_root: Path | None = None,
    manager: SessionManager | None = None,
    rule_repository: RuleRepository | None = None,
    runtime_catalog: RuntimeCatalog | None = None,
    batch_manager: BatchManager | None = None,
    osm_bridge: OpenStudioBridge | None = None,
) -> FastAPI:
    capabilities_payload()
    sessions = manager or SessionManager(
        session_root, rule_repository=rule_repository, osm_bridge=osm_bridge,
    )
    rules = rule_repository or sessions.rule_repository
    runtimes = runtime_catalog or RuntimeCatalog()
    batches = batch_manager or BatchManager(sessions.root, sessions=sessions)
    osm_adapter = osm_bridge or OpenStudioBridge()
    sessions.osm_bridge = osm_adapter
    app = FastAPI(
        title="IDFRepair",
        version="1.0.0a1",
        description="EnergyPlus IDF Repair Workbench research prototype.",
    )
    app.state.sessions = sessions
    app.state.rules = rules
    app.state.runtimes = runtimes
    app.state.batches = batches
    app.state.osm_bridge = osm_adapter
    static_root = Path(__file__).resolve().parents[1] / "web" / "static"
    locale_root = Path(__file__).resolve().parents[1] / "web" / "locales"
    app.mount("/static", StaticFiles(directory=static_root), name="static")
    app.mount("/locales", StaticFiles(directory=locale_root), name="locales")

    def _finish_osm_diagnostic(session_id: str) -> None:
        record = sessions.get(session_id)
        if record.interaction_context.get("source_type") != "OSM":
            return
        diagnostic_report = sessions.report_for(session_id)
        bridge = sessions.osm_bridge_report_for(session_id)
        mappings = [
            row for row in bridge.get("mappings", ()) if isinstance(row, dict)
        ]
        diagnostic_mappings = map_idf_findings_to_osm(diagnostic_report, mappings)
        audit = sessions.audit_for(session_id, geometry_tolerance_m=0.05)
        audit_mappings = map_audit_findings_to_osm(audit, mappings)
        mapped_diagnostics = sum(
            row["mapping_status"] == "MAPPED_EXACT" for row in diagnostic_mappings
        )
        explicit_mappings = sum(
            row.get("mapping_status") == "EXPLICIT_EXACT_TYPE_NAME" for row in mappings
        )
        bridge.update({
            "diagnostic_status": str(
                diagnostic_report.get("final_status") or "DIAGNOSED"
            ),
            "diagnostic_mappings": diagnostic_mappings,
            "model_audit": {
                "summary": audit.get("summary", {}),
                "mapped_findings": audit_mappings,
            },
            "mapping_summary": {
                "source_objects": int(bridge.get("mapping_source_count") or 0),
                "explicit_object_mappings": explicit_mappings,
                "unsupported_object_mappings": len(mappings) - explicit_mappings,
                "diagnostics": len(diagnostic_mappings),
                "diagnostics_mapped_exact": mapped_diagnostics,
                "diagnostics_unsupported": len(diagnostic_mappings) - mapped_diagnostics,
                "audit_findings": len(audit_mappings),
            },
            "osm_candidate_preview_authorized": False,
            "osm_writeback_authorized": False,
            "reverse_translation_used": False,
        })
        sessions.update_osm_bridge_report(session_id, bridge)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_root / "index.html")

    @app.get("/api/capabilities")
    def capabilities(family: str | None = None) -> dict[str, object]:
        '''返回唯一 Release Profile 的完整或按 family 过滤的只读能力清单。'''
        payload = capabilities_payload(family=family)
        return {
            **payload,
            "display_metadata": capability_display_metadata(payload),
            "runtime_catalog": runtimes.snapshot(),
            "osm_bridge": osm_adapter.capability(),
        }

    @app.get("/api/runtimes")
    def runtime_list() -> dict[str, object]:
        """Return validated local runtimes without accepting arbitrary paths."""
        return runtimes.snapshot()

    @app.post("/api/runtimes/rescan")
    def runtime_rescan() -> dict[str, object]:
        """Refresh local runtime discovery and replace the prior snapshot."""
        return runtimes.rescan()

    @app.post("/api/projects/inspect")
    async def inspect_project(
        files: Annotated[list[UploadFile], File()],
        logical_paths: Annotated[list[str], Form()],
    ) -> dict[str, object]:
        """Inspect a browser-authorized project folder without choosing an IDF."""

        try:
            if len(files) != len(logical_paths):
                raise ValueError("project_manifest_length_mismatch")
            rows = []
            for upload, logical_path in zip(files, logical_paths):
                rows.append((logical_path, await upload.read()))
            return inspect_project_files(rows)
        except (OSError, UnicodeError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/osm/capability")
    def osm_capability() -> dict[str, object]:
        return osm_adapter.capability()

    @app.post("/api/osm/import")
    @app.post("/api/osm/diagnose", deprecated=True)
    async def import_osm(
        osm_file: Annotated[UploadFile, File()],
        epw: Annotated[UploadFile | None, File()] = None,
        dependencies: Annotated[list[UploadFile] | None, File()] = None,
        runtime_id: Annotated[str | None, Form()] = None,
        mode: Annotated[str, Form()] = RepairMode.SAFE_AUTO.value,
    ) -> dict[str, object]:
        """Forward-translate OSM into a session without starting IDFRepair."""

        try:
            source_name = Path(osm_file.filename or "model.osm").name
            source_bytes = await osm_file.read()
            weather = await _upload_tuple(epw, preserve_filename=True)
            support = []
            for upload in dependencies or []:
                row = await _upload_tuple(upload)
                if row is not None:
                    support.append(row)
            with tempfile.TemporaryDirectory(
                prefix="idfrepair-osm-forward-", dir=sessions.root,
            ) as directory:
                translation = osm_adapter.translate(
                    source_bytes, source_name, Path(directory),
                )
            derived_version = normalize_version(
                str(translation.report.get("derived_idf_version") or "")
            )
            if not derived_version:
                raise ValueError("openstudio_derived_idf_version_missing")
            selected_runtime = (
                runtimes.resolve(runtime_id)
                if runtime_id is not None
                else runtimes.resolve_version(derived_version)
            )
            if normalize_version(selected_runtime.version) != derived_version:
                raise ValueError(
                    f"osm_runtime_version_mismatch:{derived_version}:{selected_runtime.version}"
                )
            record = sessions.create(
                input_name=f"{Path(source_name).stem}-derived.idf",
                input_bytes=translation.derived_idf,
                config=EngineConfig(mode=RepairMode(mode)),
                energyplus_path=selected_runtime.executable,
                energyplus_version=selected_runtime.version,
                weather=weather,
                dependencies=support,
                project_id=f"osm:{Path(source_name).stem}",
            )
            initial_bridge = {
                **translation.report,
                "session_id": record.session.session_id,
                "source_name": source_name,
                "diagnostic_status": "PRECHECK_REQUIRED",
                "derived_runtime_version": selected_runtime.version,
                "weather_file_supplied": weather is not None,
                "osm_candidate_preview_authorized": False,
                "osm_writeback_authorized": False,
                "reverse_translation_used": False,
            }
            sessions.attach_osm_bridge(
                record.session.session_id,
                source_name=source_name,
                source_bytes=source_bytes,
                derived_bytes=translation.derived_idf,
                bridge_report=initial_bridge,
            )
            return {
                "schema_version": "idfrepair.osm-import.v2",
                "experimental": True,
                "session": sessions.summary(record.session.session_id),
                "bridge": initial_bridge,
                "next_action": "RUN_MODEL_PREFLIGHT",
                "derived_idf_url": f"/api/sessions/{record.session.session_id}/osm-derived-idf",
                "source_osm_url": f"/api/sessions/{record.session.session_id}/osm-source",
                "bridge_report_url": f"/api/sessions/{record.session.session_id}/osm-bridge-report",
            }
        except (IDFRepairError, KeyError, OSError, UnicodeError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/batches")
    def batch_list() -> dict[str, object]:
        return {"batches": list(batches.list())}

    @app.post("/api/batches")
    async def create_batch(
        files: Annotated[list[UploadFile], File()],
        logical_paths: Annotated[list[str] | None, Form()] = None,
        mode: Annotated[str, Form()] = RepairMode.SAFE_AUTO.value,
        max_rounds: Annotated[int, Form()] = 6,
        max_candidates_per_root: Annotated[int, Form()] = 3,
        max_energyplus_runs: Annotated[int, Form()] = 20,
        max_backtracks: Annotated[int, Form()] = 1,
        max_wall_time: Annotated[float, Form()] = 600.0,
        runtime_id: Annotated[str | None, Form()] = None,
        rule_set_id: Annotated[str, Form()] = "default",
    ) -> dict[str, object]:
        try:
            paths = logical_paths or [upload.filename or "input.idf" for upload in files]
            if len(paths) != len(files):
                raise ValueError("batch_logical_path_count_mismatch")
            uploads = []
            for path, upload in zip(paths, files, strict=True):
                uploads.append((path, await upload.read()))
            selected_runtime = runtimes.resolve(runtime_id) if runtime_id is not None else None
            project_upload = any(
                Path(path).suffix.casefold() not in {".idf", ".zip"}
                for path, _content in uploads
            )
            if project_upload:
                if selected_runtime is None:
                    raise ValueError("batch_project_runtime_required")
                inputs = discover_project_inputs(
                    uploads,
                    idd_text=selected_runtime.idd_path.read_text(
                        encoding="utf-8", errors="replace",
                    ),
                    runtime_version=selected_runtime.version,
                )
            else:
                inputs = discover_uploaded_inputs(uploads)
            config = EngineConfig(
                mode=RepairMode(mode),
                max_rounds=max_rounds,
                max_candidates_per_root=max_candidates_per_root,
                max_total_energyplus_runs=max_energyplus_runs,
                max_backtracks=max_backtracks,
                max_wall_time=max_wall_time,
            )
            return batches.create(
                inputs,
                configuration=config,
                energyplus_path=(selected_runtime.executable if selected_runtime else None),
                energyplus_version=(selected_runtime.version if selected_runtime else None),
                rule_set_id=rule_set_id,
            )
        except (IDFRepairError, OSError, UnicodeError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/batches/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, object]:
        try:
            return batches.get(batch_id)
        except KeyError as exc:
            raise _failure(exc) from exc

    @app.post("/api/batches/{batch_id}/start")
    def start_batch(batch_id: str) -> dict[str, object]:
        try:
            return batches.start(batch_id)
        except (KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/batches/{batch_id}/cancel")
    def cancel_batch(batch_id: str) -> dict[str, object]:
        try:
            return batches.cancel(batch_id)
        except (KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/batches/{batch_id}/records")
    def batch_records(batch_id: str) -> dict[str, object]:
        try:
            return {"records": list(batches.records(batch_id))}
        except KeyError as exc:
            raise _failure(exc) from exc

    @app.get("/api/batches/{batch_id}/records/{record_id}")
    def batch_record(batch_id: str, record_id: str) -> dict[str, object]:
        try:
            row = batches.record(batch_id, record_id)
            session_id = row.get("session_id")
            return {
                **row,
                "session_url": f"/api/sessions/{session_id}" if session_id else None,
                "report_url": f"/api/sessions/{session_id}/report" if session_id else None,
                "download_url": f"/api/sessions/{session_id}/download" if session_id else None,
            }
        except KeyError as exc:
            raise _failure(exc) from exc

    @app.post("/api/batches/{batch_id}/records/{record_id}/answers")
    def answer_batch_record(
        batch_id: str,
        record_id: str,
        request: BatchAnswerRequest,
    ) -> dict[str, object]:
        try:
            return batches.answer_record(
                batch_id,
                record_id,
                question_id=request.question_id,
                value=request.value,
            )
        except (KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/batches/{batch_id}/retry")
    async def retry_batch_records(
        batch_id: str,
        record_ids: Annotated[list[str], Form()],
        files: Annotated[list[UploadFile] | None, File()] = None,
        logical_paths: Annotated[list[str] | None, Form()] = None,
        runtime_id: Annotated[str | None, Form()] = None,
        mode: Annotated[str | None, Form()] = None,
    ) -> dict[str, object]:
        try:
            request = BatchRetryRequest(
                record_ids=record_ids,
                runtime_id=runtime_id,
                mode=mode,
            )
            selected_runtime = (
                runtimes.resolve(request.runtime_id)
                if request.runtime_id is not None
                else None
            )
            replacements = None
            support_uploads = list(files or [])
            if support_uploads:
                support_paths = logical_paths or [
                    upload.filename or "support.dat" for upload in support_uploads
                ]
                if len(support_paths) != len(support_uploads):
                    raise ValueError("batch_retry_support_path_count_mismatch")
                if any(Path(path).suffix.casefold() == ".idf" for path in support_paths):
                    raise ValueError("batch_retry_idf_replacement_not_allowed")
                effective_runtime = selected_runtime
                if effective_runtime is None:
                    version = str(batches.get(batch_id).get("energyplus_version") or "")
                    if not version:
                        raise ValueError("batch_retry_project_runtime_required")
                    effective_runtime = runtimes.resolve_version(version)
                source_rows = [
                    batches.source_for_record(batch_id, record_id)
                    for record_id in request.record_ids
                ]
                uploaded_rows = [
                    (path, await upload.read())
                    for path, upload in zip(support_paths, support_uploads, strict=True)
                ]
                project_inputs = discover_project_inputs(
                    (*source_rows, *uploaded_rows),
                    idd_text=effective_runtime.idd_path.read_text(
                        encoding="utf-8", errors="replace",
                    ),
                    runtime_version=effective_runtime.version,
                )
                by_name = {row.logical_name: row for row in project_inputs}
                replacements = {
                    record_id: by_name[name]
                    for record_id, (name, _content) in zip(
                        request.record_ids, source_rows, strict=True,
                    )
                }
                selected_runtime = effective_runtime
            return batches.retry_records(
                batch_id,
                request.record_ids,
                energyplus_path=(selected_runtime.executable if selected_runtime else None),
                energyplus_version=(selected_runtime.version if selected_runtime else None),
                mode=request.mode,
                replacement_inputs=replacements,
            )
        except (IDFRepairError, KeyError, OSError, UnicodeError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/batches/{batch_id}/export.csv")
    def export_batch_csv(batch_id: str) -> Response:
        try:
            return Response(
                content=batches.export_csv(batch_id),
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="idfrepair-batch-{batch_id[:8]}.csv"'
                    ),
                },
            )
        except (KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/batches/{batch_id}/export.json")
    def export_batch_json(batch_id: str) -> Response:
        try:
            return Response(
                content=batches.export_json(batch_id),
                media_type="application/json",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="idfrepair-batch-{batch_id[:8]}.json"'
                    ),
                },
            )
        except (KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/batches/{batch_id}/download")
    def download_batch(batch_id: str) -> Response:
        try:
            return Response(
                content=batches.download(batch_id),
                media_type="application/zip",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="idfrepair-batch-{batch_id[:8]}.zip"'
                    ),
                },
            )
        except (KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/capabilities/{entry_id}")
    def capability(entry_id: str) -> dict[str, object]:
        '''按稳定 entry_id 返回一个能力条目和相同发布身份。'''
        payload = capabilities_payload()
        entries = [
            row for row in payload["entries"]
            if isinstance(row, dict) and row.get("entry_id") == entry_id
        ]
        if len(entries) != 1:
            raise _failure(KeyError(entry_id))
        return {
            "schema_version": "idfrepair.capability.v1",
            "release_profile_id": payload["release_profile_id"],
            "release_profile_sha256": payload["release_profile_sha256"],
            "support_registry_sha256": payload["support_registry_sha256"],
            "entry": entries[0],
            "production_enabled": False,
            "automatic_repair_release_authorized": False,
        }

    @app.post("/api/sessions", response_model=SessionCreated)
    async def create_session(
        input_file: Annotated[UploadFile, File()],
        epw: Annotated[UploadFile | None, File()] = None,
        dependencies: Annotated[list[UploadFile] | None, File()] = None,
        dependency_paths: Annotated[list[str] | None, Form()] = None,
        mode: Annotated[str, Form()] = RepairMode.SAFE_AUTO.value,
        max_rounds: Annotated[int, Form()] = 6,
        max_candidates_per_root: Annotated[int, Form()] = 3,
        max_energyplus_runs: Annotated[int, Form()] = 20,
        max_backtracks: Annotated[int, Form()] = 1,
        max_wall_time: Annotated[float, Form()] = 600.0,
        model: Annotated[str, Form()] = "none",
        model_base: Annotated[str | None, Form()] = None,
        model_adapter: Annotated[str | None, Form()] = None,
        model_runtime_python: Annotated[str | None, Form()] = None,
        energyplus: Annotated[str | None, Form()] = None,
        energyplus_version: Annotated[str | None, Form()] = None,
        runtime_id: Annotated[str | None, Form()] = None,
        rule_set_id: Annotated[str, Form()] = "default",
        project_id: Annotated[str | None, Form()] = None,
        batch_id: Annotated[str | None, Form()] = None,
    ) -> SessionCreated:
        try:
            if (
                model != "none"
                or model_base is not None
                or model_adapter is not None
                or model_runtime_python is not None
            ):
                raise ValueError("model_component_not_release_authorized")
            config = EngineConfig(
                mode=RepairMode(mode),
                max_rounds=max_rounds,
                max_candidates_per_root=max_candidates_per_root,
                max_total_energyplus_runs=max_energyplus_runs,
                max_backtracks=max_backtracks,
                max_wall_time=max_wall_time,
                model=model,
                model_base_path=(str(Path(model_base).expanduser().resolve()) if model_base else None),
                model_adapter_path=(
                    str(Path(model_adapter).expanduser().resolve()) if model_adapter else None
                ),
                model_runtime_python=(
                    str(Path(model_runtime_python).expanduser().absolute())
                    if model_runtime_python else None
                ),
            )
            dependency_uploads = list(dependencies or [])
            if dependency_paths is not None and len(dependency_paths) != len(dependency_uploads):
                raise ValueError("dependency_manifest_length_mismatch")
            support = [
                (
                    dependency_paths[index]
                    if dependency_paths is not None
                    else Path(upload.filename or "dependency").name,
                    await upload.read(),
                )
                for index, upload in enumerate(dependency_uploads)
            ]
            weather = await _upload_tuple(epw, preserve_filename=True)
            selected_runtime = runtimes.resolve(runtime_id) if runtime_id is not None else None
            record = sessions.create(
                input_name=input_file.filename or "input.idf",
                input_bytes=await input_file.read(),
                config=config,
                energyplus_path=(
                    selected_runtime.executable
                    if selected_runtime is not None
                    else Path(energyplus).expanduser() if energyplus else None
                ),
                energyplus_version=(
                    selected_runtime.version
                    if selected_runtime is not None
                    else energyplus_version
                ),
                weather=weather,
                dependencies=support,
                selected_rule_set_id=rule_set_id,
                project_id=project_id,
                batch_id=batch_id,
            )
            return SessionCreated(
                session_id=record.session.session_id,
                status=None,
                message=message("session.lifecycle.created", "CREATED"),
            )
        except (IDFRepairError, OSError, UnicodeError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/diagnose")
    def diagnose(session_id: str) -> dict[str, object]:
        try:
            record = sessions.get(session_id)
            if (
                record.interaction_context.get("source_type") == "OSM"
                and record.interaction_context.get("osm_bridge_status")
                in {"TRANSLATED", "PRECHECK_REQUIRED"}
            ):
                raise ValueError("osm_preflight_required")
            sessions.execute(session_id, diagnose=True)
            _finish_osm_diagnostic(session_id)
            return sessions.summary(session_id)
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/run")
    def run(session_id: str) -> dict[str, object]:
        try:
            sessions.execute(session_id)
            return sessions.summary(session_id)
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/settings-child")
    def settings_child(
        session_id: str,
        request: SettingsChildRequest,
    ) -> dict[str, object]:
        """Apply pristine settings or explicitly hand off to an inert linked copy."""

        try:
            runtime_version = request.runtime_id
            runtime_path = None
            if request.runtime_id is not None:
                selected_runtime = runtimes.resolve(request.runtime_id)
                runtime_version = selected_runtime.version
                runtime_path = selected_runtime.executable
            record = sessions.create_settings_child(
                session_id,
                RepairMode(request.mode),
                runtime_version,
                energyplus_path=runtime_path,
            )
            return {
                "auto_started": False,
                "created_child": record.session.session_id != session_id,
                "parent_session_id": session_id,
                "session": sessions.summary(record.session.session_id),
            }
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/weather")
    async def attach_weather(
        session_id: str,
        file: Annotated[UploadFile, File()],
    ) -> dict[str, object]:
        """Attach an EPW to a pre-diagnosis session without starting a run."""

        try:
            return sessions.attach_weather(
                session_id,
                file.filename or "",
                await file.read(),
            )
        except (IDFRepairError, KeyError, OSError, UnicodeError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}", response_model=SessionSummary)
    def get_session(session_id: str) -> dict[str, object]:
        try:
            return sessions.summary(session_id)
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/open-workspace")
    def open_session_workspace(session_id: str) -> dict[str, object]:
        """Open only the resolved workspace belonging to this known session."""

        try:
            workspace = sessions.workspace_for_open(session_id)
            open_local_folder(workspace)
            return {
                "opened": True,
                "session_id": session_id,
                "folder_name": workspace.name,
            }
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/source-context")
    def source_context(
        session_id: str,
        object_index: int,
        field_index: int | None = None,
        before_lines: int = 2,
        after_lines: int = 2,
    ) -> dict[str, object]:
        try:
            return sessions.source_context_for(
                session_id,
                object_index=object_index,
                field_index=field_index,
                before_lines=before_lines,
                after_lines=after_lines,
            )
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/field-context")
    def field_context(
        session_id: str,
        object_index: int,
        field_index: int,
    ) -> dict[str, object]:
        try:
            return sessions.field_context_for(
                session_id,
                object_index=object_index,
                field_index=field_index,
            )
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/object-context")
    def object_context(
        session_id: str,
        object_index: int,
        depth: int = 1,
        limit: int = 30,
    ) -> dict[str, object]:
        try:
            return sessions.object_context_for(
                session_id,
                object_index=object_index,
                depth=depth,
                limit=limit,
            )
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/readiness")
    def readiness(session_id: str) -> dict[str, object]:
        try:
            return sessions.readiness_for(session_id)
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/migration-capability")
    def migration_capability(session_id: str) -> dict[str, object]:
        """Describe proven official upgrade paths for the immutable uploaded IDF."""

        try:
            record = sessions.get(session_id)
            source_version = normalize_version(parse_idf(record.input_text).version)
            runtime_rows = runtimes.snapshot()["runtimes"]
            transitions = discover_transitions(runtimes.specs())
            targets = []
            matching_runtime_id = None
            for row in runtime_rows:
                runtime_id = str(row["runtime_id"])
                target_version = normalize_version(str(row["version"]))
                if target_version == source_version and matching_runtime_id is None:
                    matching_runtime_id = runtime_id
                chain = transition_chain(source_version, target_version, transitions)
                if target_version == source_version:
                    reason = "same_version"
                elif not chain:
                    source_tokens = source_version.split(".")
                    target_tokens = target_version.split(".")
                    numeric_versions = all(
                        part.isdigit() for part in (*source_tokens, *target_tokens)
                    )
                    source_parts = tuple(int(part) for part in source_tokens) if numeric_versions else ()
                    target_parts = tuple(int(part) for part in target_tokens) if numeric_versions else ()
                    reason = (
                        "downgrade_not_supported"
                        if numeric_versions and target_parts < source_parts
                        else "missing_transition_step"
                    )
                else:
                    reason = None
                targets.append({
                    "runtime_id": runtime_id,
                    "version": target_version,
                    "available": bool(chain),
                    "reason": reason,
                    "step_count": len(chain),
                    "steps": [
                        {
                            "source_version": step.source_version,
                            "target_version": step.target_version,
                            "tool": step.executable.name,
                        }
                        for step in chain
                    ],
                    "creates_copy": True,
                })
            return {
                "schema_version": "idfrepair.transition-capability.v1",
                "source_version": source_version,
                "matching_runtime_id": matching_runtime_id,
                "original_preserved": True,
                "creates_copy": True,
                "targets": targets,
            }
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/migrations")
    def create_migration(session_id: str, request: MigrationRequest) -> dict[str, object]:
        """Run a complete official Transition chain into a separate artifact."""

        try:
            record = sessions.get(session_id)
            target = runtimes.resolve(request.target_runtime_id)
            return migrate_copy(
                record,
                target,
                transitions=discover_transitions(runtimes.specs()),
                run_energyplus=request.run_energyplus,
            )
        except (IDFRepairError, KeyError, OSError, UnicodeError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/migrations/{migration_id}")
    def get_migration(session_id: str, migration_id: str) -> dict[str, object]:
        try:
            return migration_report(sessions.get(session_id), migration_id)
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/migrations/{migration_id}/download")
    def download_migration(session_id: str, migration_id: str) -> FileResponse:
        try:
            record = sessions.get(session_id)
            report = migration_report(record, migration_id)
            path = migration_artifact(record, migration_id)
            target = str(report.get("target_version") or "updated").replace("/", "-")
            stem = Path(record.session.input_name).stem
            return FileResponse(
                path,
                media_type="text/plain; charset=utf-8",
                filename=f"{stem}-EnergyPlus-{target}.idf",
            )
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions")
    def list_sessions(include_archived: bool = False) -> dict[str, object]:
        return {"sessions": sessions.list(include_archived=include_archived)}

    @app.post("/api/sessions/{session_id}/resume")
    def resume(session_id: str) -> dict[str, object]:
        try:
            sessions.resume(session_id)
            return sessions.summary(session_id)
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/cancel")
    def cancel(session_id: str) -> dict[str, object]:
        try:
            sessions.cancel(session_id)
            return sessions.summary(session_id)
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/archive")
    def archive(session_id: str) -> dict[str, object]:
        try:
            sessions.archive(session_id)
            return sessions.summary(session_id)
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.delete("/api/sessions/{session_id}")
    def delete(session_id: str) -> dict[str, object]:
        try:
            recovery_path = sessions.delete(session_id)
            return {
                "deleted": session_id,
                "recoverable_workspace": str(recovery_path) if recovery_path else None,
            }
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/questions")
    def questions(session_id: str) -> dict[str, object]:
        try:
            return {"questions": sessions.summary(session_id)["questions"]}
        except KeyError as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/answers")
    def answer(session_id: str, request: AnswerRequest) -> dict[str, object]:
        try:
            sessions.answer(session_id, question_id=request.question_id, value=request.value)
            return sessions.summary(session_id)
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/external-file")
    async def provide_external_file(
        session_id: str,
        question_id: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
    ) -> dict[str, object]:
        try:
            sessions.provide_external_file(
                session_id,
                question_id=question_id,
                filename=file.filename or "dependency",
                content=await file.read(),
            )
            return sessions.summary(session_id)
        except (IDFRepairError, KeyError, OSError, UnicodeError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/report")
    def report(session_id: str) -> dict[str, object]:
        try:
            return sessions.report_for(session_id)
        except (IDFRepairError, KeyError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/audit")
    def model_audit(session_id: str, request: AuditRequest) -> dict[str, object]:
        try:
            return sessions.audit_for(
                session_id,
                checks=request.checks,
                geometry_tolerance_m=request.geometry_tolerance_m,
            )
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/experimental/geometry-preview")
    def experimental_geometry_preview(
        session_id: str,
        request: ExperimentalPreviewRequest,
    ) -> dict[str, object]:
        try:
            return sessions.experimental_geometry_for(
                session_id,
                mechanisms=request.mechanisms,
                snap_absolute_m=request.snap_absolute_m,
                snap_relative=request.snap_relative,
            )
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/model-preflight")
    def model_preflight(
        session_id: str,
        request: ModelPreflightRequest,
    ) -> dict[str, object]:
        """Check relationships and geometry before the normal IDF diagnosis."""

        try:
            return sessions.model_preflight_for(
                session_id,
                checks=request.checks,
                tolerance_m=request.tolerance_m,
            )
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/model-preflight")
    def model_preflight_report(session_id: str) -> dict[str, object]:
        try:
            return sessions.model_preflight_report_for(session_id)
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/model-preflight/apply")
    def apply_model_preflight_copy(session_id: str) -> dict[str, object]:
        try:
            child, report = sessions.apply_model_preflight_for(session_id)
            return {
                "session": sessions.summary(child.session.session_id),
                "application": report,
                "input_url": f"/api/sessions/{child.session.session_id}/input",
                "osm_derived_idf_url": (
                    f"/api/sessions/{child.session.session_id}/osm-derived-idf"
                    if child.interaction_context.get("source_type") == "OSM" else None
                ),
            }
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/model-preflight/rollback")
    def rollback_model_preflight_copy(session_id: str) -> dict[str, object]:
        try:
            parent = sessions.preflight_parent_for(session_id)
            parent_id = str(parent["session_id"])
            return {
                "session": parent,
                "input_url": f"/api/sessions/{parent_id}/input",
            }
        except (IDFRepairError, KeyError, OSError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/download")
    def download(session_id: str) -> Response:
        try:
            name, content = sessions.output_for(session_id)
            return Response(
                content=content,
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
        except (IDFRepairError, KeyError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/input")
    def session_input(session_id: str) -> Response:
        try:
            name, content = sessions.input_for(session_id)
            return Response(
                content=content,
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
        except (IDFRepairError, KeyError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/expanded-input")
    def expanded_input(session_id: str) -> Response:
        try:
            name, content = sessions.expanded_for(session_id)
            return Response(
                content=content,
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
        except (IDFRepairError, KeyError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/osm-source")
    def osm_source(session_id: str) -> Response:
        try:
            name, content = sessions.osm_source_for(session_id)
            return Response(
                content=content,
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
        except (IDFRepairError, KeyError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/osm-derived-idf")
    def osm_derived_idf(session_id: str) -> Response:
        try:
            name, content = sessions.osm_derived_for(session_id)
            return Response(
                content=content,
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
        except (IDFRepairError, KeyError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/osm-bridge-report")
    def osm_bridge_report(session_id: str) -> dict[str, object]:
        try:
            return sessions.osm_bridge_report_for(session_id)
        except (IDFRepairError, KeyError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/osm-repaired")
    def osm_repaired(session_id: str) -> Response:
        try:
            name, content = sessions.osm_repaired_for(session_id)
            return Response(
                content=content,
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
        except (IDFRepairError, KeyError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/sessions/{session_id}/osm-writeback-report")
    def osm_writeback_report(session_id: str) -> dict[str, object]:
        try:
            return sessions.osm_writeback_report_for(session_id)
        except (IDFRepairError, KeyError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/sessions/{session_id}/rules")
    def save_session_rule(session_id: str, request: RuleSaveRequest) -> dict[str, object]:
        '''仅把用户参与且完整验证通过的提交候选保存为有限规则。'''
        try:
            rule = sessions.save_rule(
                session_id,
                candidate_id=request.candidate_id,
                scope=request.scope,
                name_zh=request.name_zh,
                name_en=request.name_en,
                global_authorized=request.global_authorized,
            )
            return {
                "message": message("rule.saved_from_session", rule.rule_id),
                "rule": rule.to_dict(),
            }
        except (IDFRepairError, KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/rule-sets")
    def list_rule_sets() -> dict[str, object]:
        return {"rule_sets": rules.list_rule_sets()}

    @app.post("/api/rule-sets")
    def create_rule_set(request: RuleSetRequest) -> dict[str, object]:
        try:
            identity = rules.create_rule_set(**request.model_dump())
            return {
                "rule_set_id": identity,
                "message": message("rule_set.created", identity),
            }
        except (KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/rules/export")
    def export_rule_library(rule_set_id: str | None = None) -> Response:
        payload = {
            "format": "json-yaml-1.2",
            "rule_sets": rules.list_rule_sets(),
            "rules": [row.to_dict() for row in rules.list_rules(rule_set_id=rule_set_id)],
            "schema_version": "idfrepair.repair_memory.export.v1",
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="idfrepair-rules.json"'},
        )

    @app.post("/api/rules/import")
    async def import_rule_library(
        file: Annotated[UploadFile, File()],
        rule_set_id: Annotated[str | None, Form()] = None,
    ) -> dict[str, object]:
        try:
            content = await file.read()
            if len(content) > 10 * 1024 * 1024:
                raise ValueError("rule_import_too_large")
            with tempfile.TemporaryDirectory(prefix="idfrepair-rule-import-") as directory:
                path = Path(directory) / Path(file.filename or "rules.json").name
                path.write_bytes(content)
                created = import_rules(rules, path, rule_set_id=rule_set_id)
            return {
                "created_rule_ids": created,
                "message": message("rules.imported", "IMPORTED", {"count": len(created)}),
            }
        except (KeyError, OSError, UnicodeError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/rules")
    def list_rules(
        search: str | None = None,
        rule_set_id: str | None = None,
        enabled: bool | None = None,
        family: str | None = None,
    ) -> dict[str, object]:
        try:
            rows = rules.list_rules(
                search=search,
                rule_set_id=rule_set_id,
                enabled=enabled,
                family=family,
            )
            return {"rules": [row.to_dict() for row in rows]}
        except (KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/rules")
    def create_rule(payload: dict[str, object]) -> dict[str, object]:
        try:
            return {"rule": rules.create_rule(payload).to_dict()}
        except (KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/rules/{rule_id}")
    def get_rule(rule_id: str) -> dict[str, object]:
        try:
            return {"rule": rules.get_rule(rule_id).to_dict()}
        except KeyError as exc:
            raise _failure(exc) from exc

    @app.patch("/api/rules/{rule_id}")
    def update_rule(rule_id: str, payload: dict[str, object]) -> dict[str, object]:
        try:
            return {"rule": rules.update_rule(rule_id, payload).to_dict()}
        except (KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.delete("/api/rules/{rule_id}")
    def delete_rule(rule_id: str) -> dict[str, object]:
        try:
            rules.delete_rule(rule_id)
            return {"message": message("rule.deleted", rule_id)}
        except KeyError as exc:
            raise _failure(exc) from exc

    @app.post("/api/rules/{rule_id}/enable")
    def enable_rule(rule_id: str) -> dict[str, object]:
        try:
            return {"rule": rules.set_enabled(rule_id, True).to_dict()}
        except (KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/rules/{rule_id}/disable")
    def disable_rule(rule_id: str) -> dict[str, object]:
        try:
            return {"rule": rules.set_enabled(rule_id, False).to_dict()}
        except (KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.post("/api/rules/{rule_id}/clone")
    def clone_rule(rule_id: str, rule_set_id: str | None = None) -> dict[str, object]:
        try:
            return {"rule": rules.clone_rule(rule_id, rule_set_id=rule_set_id).to_dict()}
        except (KeyError, ValueError) as exc:
            raise _failure(exc) from exc

    @app.get("/api/rules/{rule_id}/versions")
    def rule_versions(rule_id: str) -> dict[str, object]:
        try:
            rules.get_rule(rule_id)
            return {"versions": rules.rule_versions(rule_id)}
        except KeyError as exc:
            raise _failure(exc) from exc

    @app.get("/api/rules/{rule_id}/applications")
    def rule_applications(rule_id: str) -> dict[str, object]:
        try:
            rules.get_rule(rule_id)
            return {"applications": rules.list_applications(rule_id)}
        except KeyError as exc:
            raise _failure(exc) from exc

    return app


app = create_app()
