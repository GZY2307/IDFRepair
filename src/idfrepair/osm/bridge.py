"""Discover OpenStudio and forward-translate OSM for read-only diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from idfrepair.io.idf import parse_idf
from idfrepair.osm.verification import (
    OSMChildVerification,
    audit_validity_evidence,
    verify_repaired_osm,
)
from idfrepair.osm.validity import validate_validity_chain, validate_validity_stage
from idfrepair.osm.workflow import (
    build_osm_execution_authority,
    compile_committed_osm_operations,
    summarize_osm_patch_rejections,
)
from idfrepair.osm.writeback import build_osm_patch
from idfrepair.preflight.analysis import GeometryAnalysisContext
from idfrepair.preflight.model import build_model_preflight, target_issue_remains
from idfrepair.runtime.discovery import normalize_version


MAX_OSM_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_DERIVED_IDF_BYTES = 100 * 1024 * 1024
MAX_OSM_PATCH_BYTES = 50 * 1024 * 1024
_OUTPUT_TAIL_CHARS = 12_000
_HANDLE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class OSMTranslation:
    """A derived IDF and its explicit, forward-only provenance report."""

    derived_idf: bytes
    report: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OSMWriteback:
    """A repaired OSM whose child report passed every writeback gate."""

    repaired_osm: bytes
    report: dict[str, Any]
    source_audit: dict[str, Any]
    child_audit: dict[str, Any]


def _default_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, **kwargs)  # type: ignore[arg-type]


def _tail(value: str | None) -> str:
    return str(value or "")[-_OUTPUT_TAIL_CHARS:]


def _failure_reason(value: str | None) -> str:
    """Keep the actionable tail while collapsing repeated OpenStudio validation noise."""

    unique_lines: list[str] = []
    seen: set[str] = set()
    for raw_line in _tail(value).splitlines():
        line = raw_line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        unique_lines.append(line)
    reason = " | ".join(unique_lines)
    return reason[-1_200:] or "openstudio_process_failed_without_output"


class OpenStudioBridge:
    """Run forward diagnostics and exact typed writeback without reverse translation."""

    def __init__(
        self,
        cli_path: Path | None = None,
        *,
        search_paths: Iterable[Path] | None = None,
        environ: Mapping[str, str] | None = None,
        runner: Runner | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self._explicit_cli = cli_path.expanduser() if cli_path is not None else None
        self._search_paths = (
            tuple(Path(path).expanduser() for path in search_paths)
            if search_paths is not None
            else (
                Path("/Applications/OpenStudio/bin/openstudio"),
                Path("/usr/local/bin/openstudio"),
                Path("/opt/openstudio/bin/openstudio"),
            )
        )
        self._environ = dict(os.environ if environ is None else environ)
        self._runner = runner or _default_runner
        self.timeout_seconds = timeout_seconds
        self._capability: dict[str, Any] | None = None

    @property
    def script_path(self) -> Path:
        return Path(__file__).with_name("forward_translate.rb")

    @property
    def patch_script_path(self) -> Path:
        return Path(__file__).with_name("apply_repairs.rb")

    @property
    def audit_script_path(self) -> Path:
        return Path(__file__).with_name("inspect_model.rb")

    def _candidate_paths(self) -> tuple[Path, ...]:
        if self._explicit_cli is not None:
            return (self._explicit_cli,)
        candidates: list[Path] = []
        configured = self._environ.get("OPENSTUDIO_CLI")
        if configured:
            candidates.append(Path(configured).expanduser())
        on_path = shutil.which("openstudio", path=self._environ.get("PATH", ""))
        if on_path:
            candidates.append(Path(on_path))
        candidates.extend(self._search_paths)
        unique: dict[str, Path] = {}
        for candidate in candidates:
            try:
                unique[str(candidate.resolve())] = candidate.resolve()
            except OSError:
                continue
        return tuple(unique.values())

    def _command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return self._runner(
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
            env=self._environ,
        )

    def _audit_model(
        self,
        cli_path: str,
        model_path: Path,
        report_path: Path,
    ) -> dict[str, Any]:
        command = [
            cli_path,
            str(self.audit_script_path),
            str(model_path),
            str(report_path),
        ]
        try:
            completed = self._command(command)
            if completed.returncode != 0 or not report_path.is_file():
                raise ValueError("openstudio_writeback_artifact_invalid")
            result = json.loads(report_path.read_text(encoding="utf-8"))
        except (subprocess.TimeoutExpired, OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("openstudio_writeback_artifact_invalid") from exc
        finally:
            report_path.unlink(missing_ok=True)
        if not isinstance(result, dict):
            raise ValueError("openstudio_writeback_artifact_invalid")
        return result

    def capability(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._capability is not None and not refresh:
            return dict(self._capability)
        base: dict[str, Any] = {
            "schema_version": "idfrepair.openstudio-capability.v1",
            "experimental": True,
            "installed": False,
            "status": "UNAVAILABLE",
            "cli_path": None,
            "openstudio_version": None,
            "energyplus_version": None,
            "diagnostic_bridge_available": False,
            "model_writeback_bridge_available": False,
            "osm_writeback_authorized": False,
            "reverse_translation_used": False,
            "mapping_contract": "exact-source-handle-typed-surface-v2",
        }
        for candidate in self._candidate_paths():
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            try:
                version = self._command([str(candidate), "--version"])
                energyplus = self._command([str(candidate), "energyplus_version"])
            except (OSError, subprocess.SubprocessError) as exc:
                base["reason"] = f"openstudio_probe_failed:{type(exc).__name__}"
                continue
            if version.returncode != 0 or energyplus.returncode != 0:
                base["reason"] = "openstudio_probe_failed"
                continue
            version_text = next(
                (line.strip() for line in version.stdout.splitlines() if line.strip()), ""
            )
            energyplus_text = next(
                (line.strip() for line in energyplus.stdout.splitlines() if line.strip()), ""
            )
            base.update({
                "installed": True,
                "status": "AVAILABLE",
                "cli_path": str(candidate.resolve()),
                "openstudio_version": version_text,
                "energyplus_version": normalize_version(energyplus_text),
                "diagnostic_bridge_available": self.script_path.is_file(),
                "model_writeback_bridge_available": (
                    self.patch_script_path.is_file() and self.audit_script_path.is_file()
                ),
                "reason": None,
            })
            break
        self._capability = base
        return dict(base)

    def translate(
        self,
        source: bytes,
        input_name: str,
        output_root: Path,
    ) -> OSMTranslation:
        """Version-load and forward-translate one OSM into a derived diagnostic IDF."""

        if not Path(input_name).name.casefold().endswith(".osm"):
            raise ValueError("osm_input_extension_required")
        if len(source) > MAX_OSM_UPLOAD_BYTES:
            raise ValueError("osm_upload_too_large")
        capability = self.capability()
        if not capability["diagnostic_bridge_available"]:
            raise ValueError("openstudio_cli_unavailable")
        output_root = output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        source_path = output_root / "source.osm"
        derived_path = output_root / "derived.idf"
        report_path = output_root / "openstudio-forward.json"
        source_path.write_bytes(source)
        command = [
            str(capability["cli_path"]),
            str(self.script_path),
            str(source_path),
            str(derived_path),
            str(report_path),
        ]
        try:
            completed = self._command(command)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("openstudio_forward_translation_timeout") from exc
        except OSError as exc:
            raise ValueError("openstudio_forward_translation_failed") from exc
        if completed.returncode != 0:
            reason = _failure_reason(completed.stderr or completed.stdout)
            raise ValueError(f"openstudio_forward_translation_failed:{reason}")
        if not derived_path.is_file() or not report_path.is_file():
            raise ValueError("openstudio_forward_artifact_missing")
        derived = derived_path.read_bytes()
        if len(derived) > MAX_DERIVED_IDF_BYTES:
            raise ValueError("openstudio_derived_idf_too_large")
        try:
            document = parse_idf(derived.decode("utf-8-sig"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError, OSError, ValueError) as exc:
            raise ValueError("openstudio_forward_artifact_invalid") from exc
        if not isinstance(report, dict):
            raise ValueError("openstudio_forward_report_invalid")
        if report.get("reverse_translation_used") is not False:
            raise ValueError("osm_bridge_reverse_translation_boundary_violation")
        if report.get("osm_writeback_authorized") is not False:
            raise ValueError("osm_bridge_writeback_boundary_violation")
        if not document.version:
            raise ValueError("openstudio_derived_idf_version_missing")
        report = {
            **report,
            "derived_idf_version": normalize_version(document.version),
            "openstudio_capability": capability,
            "cli_stdout_tail": _tail(completed.stdout),
            "cli_stderr_tail": (
                _failure_reason(completed.stderr) if completed.stderr else ""
            ),
            "source_name": Path(input_name).name,
            "source_bytes": len(source),
            "derived_idf_bytes": len(derived),
            "reverse_translation_used": False,
            "osm_writeback_authorized": False,
        }
        return OSMTranslation(derived_idf=derived, report=report)

    def apply_patch(
        self,
        source: bytes,
        input_name: str,
        patch: Mapping[str, Any],
        output_root: Path,
        *,
        authoritative_preflight: Mapping[str, Any] | None = None,
        authoritative_forward_report: Mapping[str, Any] | None = None,
    ) -> OSMWriteback:
        """Apply one finite exact-handle patch to a staged copy of ``source``."""

        if not Path(input_name).name.casefold().endswith(".osm"):
            raise ValueError("osm_input_extension_required")
        if len(source) > MAX_OSM_UPLOAD_BYTES:
            raise ValueError("osm_upload_too_large")
        try:
            serialized_patch = json.dumps(
                patch,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            if len(serialized_patch.encode("utf-8")) > MAX_OSM_PATCH_BYTES:
                raise ValueError("openstudio_patch_document_too_large")
            patch_document = json.loads(serialized_patch)
        except (TypeError, ValueError, OverflowError, json.JSONDecodeError) as exc:
            if isinstance(exc, ValueError) and str(exc) == "openstudio_patch_document_too_large":
                raise
            raise ValueError("openstudio_patch_document_invalid") from exc
        if (
            not isinstance(patch_document, dict)
            or set(patch_document) != {
                "schema_version", "mapping_contract", "source", "preflight",
                "operations", "rejected_plans", "counts",
            }
            or patch_document.get("schema_version") != "idfrepair.openstudio-patch.v1"
            or patch_document.get("mapping_contract")
            != "exact-source-handle-typed-surface-v2"
            or not isinstance(patch_document.get("source"), dict)
        ):
            raise ValueError("openstudio_patch_document_invalid")
        if (
            authoritative_preflight is None
            or authoritative_forward_report is None
        ):
            raise ValueError("openstudio_writeback_authority_required")
        if (
            not isinstance(authoritative_preflight, Mapping)
            or not isinstance(authoritative_forward_report, Mapping)
        ):
            raise ValueError("openstudio_writeback_authority_invalid")
        try:
            authorized_patch = build_osm_patch(
                authoritative_preflight,
                authoritative_forward_report,
            )
            serialized_authorized_patch = json.dumps(
                authorized_patch,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except Exception as exc:
            raise ValueError("openstudio_writeback_authority_invalid") from exc
        if serialized_patch != serialized_authorized_patch:
            raise ValueError("openstudio_writeback_authority_mismatch")
        source_sha256 = sha256(source).hexdigest()
        if patch_document["source"].get("sha256") != source_sha256:
            raise ValueError("openstudio_writeback_failed:source_sha256_mismatch")
        capability = self.capability()
        if not capability.get("model_writeback_bridge_available"):
            raise ValueError("openstudio_cli_unavailable")

        output_root = output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        source_path = output_root / "source.osm"
        patch_path = output_root / "openstudio-patch.json"
        repaired_path = output_root / "repaired.osm"
        report_path = output_root / "openstudio-writeback.json"
        source_audit_path = output_root / "openstudio-source-audit.json"
        child_audit_path = output_root / "openstudio-child-audit.json"
        if any(path.exists() for path in (
            repaired_path, report_path, source_audit_path, child_audit_path,
        )):
            raise ValueError("openstudio_writeback_output_exists")
        source_path.write_bytes(source)
        patch_path.write_text(
            serialized_patch,
            encoding="utf-8",
        )
        source_audit = self._audit_model(
            str(capability["cli_path"]), source_path, source_audit_path,
        )
        command = [
            str(capability["cli_path"]),
            str(self.patch_script_path),
            str(source_path),
            str(patch_path),
            str(repaired_path),
            str(report_path),
        ]
        try:
            completed = self._command(command)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("openstudio_writeback_timeout") from exc
        except OSError as exc:
            raise ValueError("openstudio_writeback_failed") from exc

        if completed.returncode != 0:
            repaired_path.unlink(missing_ok=True)
            failure_code = _writeback_failure_code(report_path)
            suffix = f":{failure_code}" if failure_code else ""
            raise ValueError(f"openstudio_writeback_failed{suffix}")
        if not repaired_path.is_file() or not report_path.is_file():
            repaired_path.unlink(missing_ok=True)
            raise ValueError("openstudio_writeback_artifact_missing")
        repaired = repaired_path.read_bytes()
        if len(repaired) > MAX_OSM_UPLOAD_BYTES:
            repaired_path.unlink(missing_ok=True)
            raise ValueError("openstudio_repaired_osm_too_large")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError, OSError) as exc:
            repaired_path.unlink(missing_ok=True)
            raise ValueError("openstudio_writeback_artifact_invalid") from exc
        try:
            child_audit = self._audit_model(
                str(capability["cli_path"]), repaired_path, child_audit_path,
            )
        except ValueError:
            repaired_path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)
            raise
        if not _valid_writeback_report(
            report,
            source_sha256=source_sha256,
            repaired_sha256=sha256(repaired).hexdigest(),
            operations=patch_document.get("operations"),
            trusted_loaded_inventory=authoritative_forward_report.get(
                "loaded_handle_inventory"
            ),
            source_audit=source_audit,
            child_audit=child_audit,
        ) or source_path.read_bytes() != source:
            repaired_path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)
            raise ValueError("openstudio_writeback_artifact_invalid")
        return OSMWriteback(
            repaired_osm=repaired,
            report=report,
            source_audit=source_audit,
            child_audit=child_audit,
        )

    def verify_repaired(
        self,
        repaired_osm: bytes,
        input_name: str,
        output_root: Path,
        *,
        source_osm: bytes,
        source_audit: Mapping[str, Any],
        writeback_child_audit: Mapping[str, Any],
        repaired_idf: bytes,
        idd_text: str,
        authoritative_preflight: Mapping[str, Any],
        authoritative_forward_report: Mapping[str, Any],
        patch: Mapping[str, Any],
        writeback_report: Mapping[str, Any],
    ) -> OSMChildVerification:
        """Reopen and independently compare a repaired OSM/IDF child pair."""
        capability = self.capability()
        if not capability.get("model_writeback_bridge_available"):
            raise ValueError("openstudio_cli_unavailable")
        output_root = output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        repaired_path = output_root / "repaired-audit.osm"
        audit_path = output_root / "repaired-audit.json"
        repaired_path.write_bytes(repaired_osm)
        fresh_child_audit = self._audit_model(
            str(capability["cli_path"]), repaired_path, audit_path,
        )
        audit_evidence = audit_validity_evidence(
            source_osm,
            repaired_osm,
            source_audit=source_audit,
            writeback_child_audit=writeback_child_audit,
            fresh_child_audit=fresh_child_audit,
            writeback_validity=writeback_report.get("model_validity"),
            inventory_validator=_validated_inventory,
        )
        return verify_repaired_osm(
            self.translate,
            _validated_inventory,
            repaired_osm,
            input_name,
            output_root,
            repaired_idf=repaired_idf,
            idd_text=idd_text,
            authoritative_preflight=authoritative_preflight,
            authoritative_forward_report=authoritative_forward_report,
            patch=patch,
            writeback_report=writeback_report,
            audit_evidence=audit_evidence,
        )


def _writeback_failure_code(report_path: Path) -> str | None:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(report, dict):
        return None
    failure_code = report.get("failure_code")
    if (
        report.get("schema_version") == "idfrepair.openstudio-writeback.v1"
        and report.get("status") == "REJECTED"
        and report.get("source_osm_modified") is False
        and report.get("reverse_translation_used") is False
        and report.get("osm_writeback_authorized") is False
        and isinstance(failure_code, str)
        and 0 < len(failure_code) <= 160
        and all(character.isalnum() or character == "_" for character in failure_code)
    ):
        return failure_code
    return None


def _validated_inventory(
    value: object,
) -> tuple[str, dict[str, dict[str, str]]] | None:
    if not isinstance(value, dict) or set(value) != {
        "status", "count", "sha256", "objects", "objects_truncated",
    }:
        return None
    objects = value.get("objects")
    if (
        value.get("status") != "COMPLETE"
        or value.get("objects_truncated") is not False
        or not isinstance(objects, list)
        or value.get("count") != len(objects)
        or not isinstance(value.get("sha256"), str)
        or not _SHA_RE.fullmatch(value["sha256"])
    ):
        return None
    rows: list[list[str]] = []
    index: dict[str, dict[str, str]] = {}
    for row in objects:
        if not isinstance(row, dict) or set(row) != {"handle", "object_type", "name"}:
            return None
        handle = row.get("handle")
        object_type = row.get("object_type")
        name = row.get("name")
        if (
            not isinstance(handle, str)
            or not _HANDLE_RE.fullmatch(handle)
            or handle in index
            or not isinstance(object_type, str)
            or not isinstance(name, str)
        ):
            return None
        normalized = {
            "handle": handle,
            "object_type": object_type,
            "name": name,
        }
        index[handle] = normalized
        rows.append([handle, object_type, name])
    if rows != sorted(rows):
        return None
    digest = sha256(json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    if digest != value["sha256"]:
        return None
    return digest, index


def _validated_child_audit(
    value: object,
    *,
    artifact_sha256: str,
) -> tuple[
    tuple[str, dict[str, dict[str, str]]], object,
] | None:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "status", "source_sha256",
        "source_handle_inventory", "loaded_handle_inventory",
        "source_loaded_handle_inventories_match", "model_validity",
        "reverse_translation_used", "osm_writeback_authorized",
    }:
        return None
    source_inventory = _validated_inventory(value.get("source_handle_inventory"))
    loaded_inventory = _validated_inventory(value.get("loaded_handle_inventory"))
    if (
        value.get("schema_version") != "idfrepair.openstudio-child-audit.v1"
        or value.get("status") != "COMPLETE"
        or value.get("source_sha256") != artifact_sha256
        or value.get("source_loaded_handle_inventories_match") is not True
        or value.get("reverse_translation_used") is not False
        or value.get("osm_writeback_authorized") is not False
        or not isinstance(value.get("model_validity"), dict)
        or value["model_validity"].get("no_regression") is not True
        or validate_validity_stage(value.get("model_validity")) is None
        or source_inventory is None
        or loaded_inventory is None
        or source_inventory != loaded_inventory
    ):
        return None
    return loaded_inventory, value.get("model_validity")


def _valid_writeback_report(
    report: object,
    *,
    source_sha256: str,
    repaired_sha256: str,
    operations: object,
    trusted_loaded_inventory: object,
    source_audit: object,
    child_audit: object,
) -> bool:
    trusted_inventory = _validated_inventory(trusted_loaded_inventory)
    validated_source_audit = _validated_child_audit(
        source_audit, artifact_sha256=source_sha256,
    )
    validated_child_audit = _validated_child_audit(
        child_audit, artifact_sha256=repaired_sha256,
    )
    if (
        not isinstance(report, dict)
        or not isinstance(operations, list)
        or trusted_inventory is None
        or validated_source_audit is None
        or validated_child_audit is None
        or validated_source_audit[0] != trusted_inventory
    ):
        return False
    repaired_inventory, child_validity_payload = validated_child_audit
    source_validity = validate_validity_stage(validated_source_audit[1])
    child_validity = validate_validity_stage(child_validity_payload)
    if source_validity is None or child_validity is None:
        return False
    required = {
        "schema_version", "status", "mapping_contract", "source_sha256",
        "repaired_sha256", "source_osm_modified", "reverse_translation_used",
        "osm_writeback_authorized", "operations", "counts",
        "generated_lineage", "retained_lineage", "model_validity",
        "inventory_audit", "api_deviations",
    }
    if set(report) != required or any(not isinstance(row, dict) for row in operations):
        return False
    operation_results = report.get("operations")
    requested_ids = [row.get("operation_id") for row in operations]
    if (
        not isinstance(operation_results, list)
        or any(not isinstance(row, dict) for row in operation_results)
        or [row.get("operation_id") for row in operation_results] != requested_ids
        or any(
            set(result) != {"operation_id", "operation", "status"}
            or result.get("operation") != operation.get("operation")
            or result.get("status") != "APPLIED"
            for result, operation in zip(operation_results, operations, strict=True)
        )
    ):
        return False
    validity = report.get("model_validity")
    inventory = report.get("inventory_audit")
    counts = report.get("counts")
    generated_lineage = report.get("generated_lineage")
    retained_lineage = report.get("retained_lineage")
    api_deviations = report.get("api_deviations")
    create_operations = [
        row for row in operations if row.get("operation") == "create_surface_piece"
    ]
    remove_operations = [
        row for row in operations
        if row.get("operation") == "remove_unreferenced_air_boundary"
    ]
    retained_operations = [
        row for row in operations
        if row.get("operation") == "set_surface_vertices"
        and row.get("lineage") is not None
    ]
    expected_deviations = ([{
        "operation": "create_surface_piece",
        "reason": (
            "openstudio_3_6_1_surface_constructor_requires_model_then_"
            "typed_initializers"
        ),
        "typed_initializers": ["setSpace", "setSurfaceType"],
    }] if create_operations else [])
    if (
        not isinstance(generated_lineage, list)
        or len(generated_lineage) != len(create_operations)
        or not isinstance(retained_lineage, list)
        or len(retained_lineage) != len(retained_operations)
    ):
        return False
    generated_handles: list[str] = []
    for lineage, operation in zip(
        generated_lineage, create_operations, strict=True,
    ):
        operation_lineage = operation.get("lineage")
        if not isinstance(lineage, dict) or set(lineage) != {
            "parent_surface_handle", "piece_index", "part_name", "identity",
            "generated_object_id", "generated_handle", "space_handle",
            "surface_type", "construction_handle",
        }:
            return False
        generated_handle = lineage.get("generated_handle")
        if (
            not isinstance(generated_handle, str)
            or not _HANDLE_RE.fullmatch(generated_handle)
            or not isinstance(operation_lineage, dict)
            or any(
                lineage.get(key) != operation_lineage.get(key)
                for key in (
                    "parent_surface_handle", "piece_index", "part_name", "identity",
                )
            )
            or lineage.get("generated_object_id") != operation.get("generated_object_id")
            or lineage.get("space_handle") != operation.get("space_handle")
            or lineage.get("surface_type") != operation.get("surface_type")
            or lineage.get("construction_handle") != operation.get("construction_handle")
            or repaired_inventory[1].get(generated_handle, {}).get("object_type")
            != "OS:Surface"
        ):
            return False
        generated_handles.append(generated_handle)
    expected_retained = [
        {**operation["lineage"], "surface_handle": operation["surface"]["handle"]}
        for operation in retained_operations
    ]
    if retained_lineage != expected_retained:
        return False
    if not isinstance(inventory, dict) or set(inventory) != {
        "initial_sha256", "final_sha256", "generated_handles", "removed_handles",
        "untracked_generated_handles", "missing_generated_handles",
        "unexpected_removed_handles",
    }:
        return False
    initial_handles = set(trusted_inventory[1])
    final_handles = set(repaired_inventory[1])
    added_handles = sorted(final_handles - initial_handles)
    removed_handles = sorted(initial_handles - final_handles)
    expected_removed_handles = sorted(
        str(operation.get("construction_handle")) for operation in remove_operations
    )
    if (
        inventory != {
            "initial_sha256": trusted_inventory[0],
            "final_sha256": repaired_inventory[0],
            "generated_handles": sorted(generated_handles),
            "removed_handles": expected_removed_handles,
            "untracked_generated_handles": [],
            "missing_generated_handles": [],
            "unexpected_removed_handles": [],
        }
        or added_handles != sorted(generated_handles)
        or removed_handles != expected_removed_handles
        or len(set(generated_handles)) != len(generated_handles)
        or any(handle in initial_handles for handle in generated_handles)
    ):
        return False
    return bool(
        report.get("schema_version") == "idfrepair.openstudio-writeback.v1"
        and report.get("status") == "VALIDATED"
        and report.get("mapping_contract") == "exact-source-handle-typed-surface-v2"
        and report.get("source_sha256") == source_sha256
        and report.get("repaired_sha256") == repaired_sha256
        and report.get("source_osm_modified") is False
        and report.get("reverse_translation_used") is False
        and report.get("osm_writeback_authorized") is True
        and counts == {
            "operations_requested": len(operations),
            "operations_applied": len(operations),
            "generated_surfaces": len(create_operations),
            "removed_air_boundaries": len(remove_operations),
        }
        and api_deviations == expected_deviations
        and validate_validity_chain(
            validity,
            independent_source=source_validity,
            independent_child=child_validity,
        )
    )


def _mapping_index(
    mappings: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    index: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for mapping in mappings:
        if mapping.get("mapping_status") != "EXPLICIT_EXACT_TYPE_NAME":
            continue
        object_type = mapping.get("derived_idf_object_type")
        object_name = mapping.get("derived_idf_object_name")
        if not isinstance(object_type, str) or not isinstance(object_name, str):
            continue
        index.setdefault((object_type.casefold(), object_name), []).append(mapping)
    return index


def _mapped_finding(
    finding: Mapping[str, Any],
    *,
    stage: str,
    index: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    object_type = finding.get("object_type")
    object_name = finding.get("object_name")
    matches = (
        index.get((object_type.casefold(), object_name), ())
        if isinstance(object_type, str) and isinstance(object_name, str)
        else ()
    )
    mapped = matches[0] if len(matches) == 1 else None
    return {
        "finding_id": finding.get("root_id") or finding.get("finding_id"),
        "finding_stage": stage,
        "family": finding.get("family") or finding.get("rule_id"),
        "message": finding.get("message") or finding.get("message_id"),
        "derived_idf_object": {
            "type": object_type,
            "name": object_name,
            "field": finding.get("field_name"),
        },
        "mapping_status": "MAPPED_EXACT" if mapped is not None else "OSM_MAPPING_UNSUPPORTED",
        "mapping_id": mapped.get("mapping_id") if mapped is not None else None,
        "provenance_basis": mapped.get("provenance_basis") if mapped is not None else None,
        "stable_target": mapped.get("stable_target") if mapped is not None else None,
        "osm_object": ({
            "handle": mapped.get("osm_handle"),
            "type": mapped.get("osm_object_type"),
            "name": mapped.get("osm_object_name"),
            "context": mapped.get("context", {}),
        } if mapped is not None else None),
        "osm_candidate_preview_authorized": False,
        "osm_writeback_authorized": False,
        "mapping_reason": (
            None if mapped is not None
            else "exact_unique_forward_provenance_not_available"
        ),
    }


def map_idf_findings_to_osm(
    report: Mapping[str, Any],
    mappings: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Map diagnostics only when exact type+name provenance is unique."""

    index = _mapping_index(mappings)
    rows: list[dict[str, Any]] = []
    for key, stage in (("initial_diagnostics", "initial"), ("final_diagnostics", "final")):
        for finding in report.get(key, ()):
            if isinstance(finding, Mapping):
                rows.append(_mapped_finding(finding, stage=stage, index=index))
    return rows


def map_audit_findings_to_osm(
    audit: Mapping[str, Any],
    mappings: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply the same exact provenance rule to read-only surface audit findings."""

    index = _mapping_index(mappings)
    rows = []
    for finding in audit.get("findings", ()):
        if not isinstance(finding, Mapping):
            continue
        surface = finding.get("surface")
        if not isinstance(surface, Mapping):
            continue
        normalized = {
            **finding,
            "object_type": surface.get("object_type"),
            "object_name": surface.get("name"),
            "field_name": None,
        }
        rows.append(_mapped_finding(normalized, stage="model_audit", index=index))
    return rows


__all__ = [
    "MAX_OSM_UPLOAD_BYTES",
    "OSMTranslation",
    "OpenStudioBridge",
    "build_osm_execution_authority",
    "map_audit_findings_to_osm",
    "map_idf_findings_to_osm",
    "summarize_osm_patch_rejections",
]
