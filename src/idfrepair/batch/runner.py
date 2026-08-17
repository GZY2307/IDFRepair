'''
发现批量输入，并为每个 IDF 建立独立 workspace、报告和分类输出。

discover_inputs(): 安全读取目录、ZIP 或多个 IDF 文件。
run_batch(): 在冻结输入清单上逐文件执行回调并写出 batch_summary.json。
'''

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import posixpath
from typing import Any, Callable, Iterable, Mapping
import zipfile

from idfrepair.domain.enums import RepairStatus
from idfrepair.domain.models import RepairOutcome, to_primitive
from idfrepair.io.idf import parse_idf, text_sha256
from idfrepair.knowledge.idd import parse_idd
from idfrepair.project.readiness import (
    MAX_PROJECT_FILE_BYTES,
    MAX_PROJECT_FILES,
    MAX_PROJECT_TOTAL_BYTES,
    inspect_readiness,
    normalize_project_path,
    resolve_external_dependencies,
)
from idfrepair.validation.terminal_safety import repaired_artifact_allowed


MAX_BATCH_FILES = 5000
MAX_BATCH_FILE_BYTES = 50 * 1024 * 1024
MAX_BATCH_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BatchInput:
    '''封装不依赖原始路径可变状态的批量 IDF 记录。'''

    record_id: str
    logical_name: str
    text: str
    input_sha256: str
    source_kind: str
    source_identity: str
    input_bytes: bytes
    weather: tuple[str, bytes] | None = None
    dependencies: tuple[tuple[str, bytes], ...] = ()
    dependency_manifest: Mapping[str, Any] = field(default_factory=dict)
    readiness: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BatchResult:
    '''封装单文件统一引擎结果和可选完整报告。'''

    outcome: RepairOutcome
    report: Mapping[str, Any] | None = None


BatchCallback = Callable[[BatchInput, Path], BatchResult]


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    '''生成同时保留分子、分母和零分母语义的批量比率。'''
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6) if denominator else None,
    }


def _support_category(report: Mapping[str, Any]) -> str:
    '''把一条记录的全部根折叠为最保守的互斥支持类别。'''
    roots = report.get("root_support", ())
    if not isinstance(roots, list) or not roots:
        return "unsupported"
    statuses = {
        str(row.get("support_status", "unsupported"))
        for row in roots if isinstance(row, Mapping)
    }
    if statuses & {"unsupported", "disabled", "evidence-only"}:
        return "unsupported"
    if "interactive" in statuses:
        return "interactive"
    if "assisted" in statuses:
        return "assisted"
    if statuses == {"safe-auto"}:
        return "safe-auto"
    return "unsupported"


def _decode(name: str, content: bytes) -> str:
    '''验证批量 IDF 的大小、UTF-8 编码和基本解析边界。'''
    if len(content) > MAX_BATCH_FILE_BYTES:
        raise ValueError(f"batch_input_too_large:{name}")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"batch_input_not_utf8:{name}") from exc
    parse_idf(text)
    return text


def _record(logical_name: str, content: bytes, source_kind: str, source_identity: str) -> BatchInput:
    '''根据逻辑名称和内容摘要生成稳定批量记录身份。'''
    text = _decode(logical_name, content)
    digest = text_sha256(text)
    identity = sha256(f"{logical_name}\0{digest}".encode("utf-8")).hexdigest()[:24]
    return BatchInput(identity, logical_name, text, digest, source_kind, source_identity, content)


def discover_uploaded_inputs(
    uploads: Iterable[tuple[str, bytes]],
) -> tuple[BatchInput, ...]:
    """Freeze browser-authorized IDF uploads with safe POSIX logical paths."""
    rows: list[BatchInput] = []
    identities: dict[str, str] = {}
    total = 0
    for raw_name, content in uploads:
        if not isinstance(raw_name, str) or not raw_name or "\\" in raw_name:
            raise ValueError("batch_upload_path_invalid")
        name = PurePosixPath(raw_name)
        if name.is_absolute() or not name.parts or any(part in {"", ".", ".."} for part in name.parts):
            raise ValueError("batch_upload_path_escape")
        logical_name = name.as_posix()
        if name.suffix.casefold() == ".zip":
            if len(content) > MAX_BATCH_TOTAL_BYTES:
                raise ValueError("batch_upload_total_size_exceeded")
            discovered: list[BatchInput] = []
            names: set[str] = set()
            archive_total = 0
            with zipfile.ZipFile(BytesIO(content)) as archive:
                for info in sorted(archive.infolist(), key=lambda item: item.filename):
                    if info.is_dir():
                        continue
                    if "\\" in info.filename:
                        raise ValueError("batch_zip_path_invalid")
                    member = PurePosixPath(info.filename)
                    if member.suffix.casefold() != ".idf":
                        continue
                    if member.is_absolute() or ".." in member.parts or not member.parts:
                        raise ValueError("batch_zip_path_escape")
                    member_name = member.as_posix()
                    if member_name in names:
                        raise ValueError("batch_zip_duplicate_member")
                    names.add(member_name)
                    if info.file_size > MAX_BATCH_FILE_BYTES:
                        raise ValueError(f"batch_input_too_large:{member_name}")
                    archive_total += info.file_size
                    if archive_total > MAX_BATCH_TOTAL_BYTES:
                        raise ValueError("batch_upload_total_size_exceeded")
                    discovered.append(_record(
                        member_name,
                        archive.read(info),
                        "zip-upload",
                        f"browser-authorized-zip:{logical_name}",
                    ))
            if not discovered:
                raise ValueError(f"batch_zip_contains_no_idf:{logical_name}")
        elif name.suffix.casefold() == ".idf":
            discovered = [
                _record(
                    logical_name,
                    content,
                    "upload",
                    "browser-authorized-upload",
                )
            ]
        else:
            raise ValueError(f"unsupported_batch_input:{logical_name}")
        for record in discovered:
            total += len(record.input_bytes)
            if total > MAX_BATCH_TOTAL_BYTES:
                raise ValueError("batch_upload_total_size_exceeded")
            existing = identities.get(record.logical_name)
            if existing is not None:
                if existing != record.input_sha256:
                    raise ValueError(
                        f"batch_duplicate_logical_path:{record.logical_name}"
                    )
                continue
            identities[record.logical_name] = record.input_sha256
            rows.append(record)
    if not rows:
        raise ValueError("batch_contains_no_idf")
    if len(rows) > MAX_BATCH_FILES:
        raise ValueError("batch_file_count_exceeded")
    return tuple(sorted(rows, key=lambda row: (row.logical_name.casefold(), row.record_id)))


def _relative_support_paths(idf_path: str, support_paths: Iterable[str]) -> dict[str, str]:
    parent = PurePosixPath(idf_path).parent.as_posix()
    start = parent if parent != "." else "."
    rows: dict[str, str] = {}
    for project_path in support_paths:
        relative = posixpath.relpath(project_path, start=start)
        try:
            normalized = normalize_project_path(relative)
        except ValueError:
            continue
        rows[normalized] = project_path
    return rows


def _weather_choice(idf_path: str, weather_paths: tuple[str, ...]) -> dict[str, Any]:
    parent = PurePosixPath(idf_path).parent
    local = [path for path in weather_paths if PurePosixPath(path).parent == parent]
    if len(local) == 1:
        matched = local[0]
    elif len(weather_paths) == 1:
        matched = weather_paths[0]
    else:
        matched = None
    return {
        "status": (
            "READY" if matched is not None
            else "NOT_PROVIDED" if not weather_paths
            else "NEEDS_INPUT"
        ),
        "matched_path": matched,
        "suggestions": [] if matched is not None else list(weather_paths),
    }


def discover_project_inputs(
    uploads: Iterable[tuple[str, bytes]],
    *,
    idd_text: str,
    runtime_version: str | None,
) -> tuple[BatchInput, ...]:
    """Build per-IDF project manifests without guessing support-file relationships."""

    rows = tuple(uploads)
    if len(rows) > MAX_PROJECT_FILES:
        raise ValueError("project_file_count_exceeded")
    normalized: dict[str, bytes] = {}
    total = 0
    for raw_path, content in rows:
        logical_path = normalize_project_path(raw_path)
        if logical_path in normalized:
            raise ValueError(f"project_duplicate_path:{logical_path}")
        if len(content) > MAX_PROJECT_FILE_BYTES:
            raise ValueError(f"project_file_too_large:{logical_path}")
        total += len(content)
        if total > MAX_PROJECT_TOTAL_BYTES:
            raise ValueError("project_total_size_exceeded")
        normalized[logical_path] = content
    idf_paths = tuple(sorted(
        (path for path in normalized if PurePosixPath(path).suffix.casefold() == ".idf"),
        key=str.casefold,
    ))
    if not idf_paths:
        raise ValueError("project_contains_no_idf")
    weather_paths = tuple(sorted(
        (path for path in normalized if PurePosixPath(path).suffix.casefold() == ".epw"),
        key=str.casefold,
    ))
    support_paths = tuple(sorted(
        (path for path in normalized if path not in idf_paths and path not in weather_paths),
        key=str.casefold,
    ))
    schema = parse_idd(idd_text)
    discovered: list[BatchInput] = []
    for idf_path in idf_paths:
        base = _record(
            idf_path,
            normalized[idf_path],
            "project-upload",
            "browser-authorized-project",
        )
        document = parse_idf(base.text)
        relative_support = _relative_support_paths(idf_path, support_paths)
        dependency_rows = []
        dependencies: list[tuple[str, bytes]] = []
        for row in resolve_external_dependencies(document, schema, relative_support):
            projected = dict(row)
            matched = row.get("matched_path")
            if isinstance(matched, str) and matched in relative_support:
                project_path = relative_support[matched]
                projected["matched_project_path"] = project_path
                dependencies.append((matched, normalized[project_path]))
            projected["suggestions"] = [
                suggestion for suggestion in row.get("suggestions", [])
                if isinstance(suggestion, str)
            ]
            dependency_rows.append(projected)
        weather = _weather_choice(idf_path, weather_paths)
        matched_weather = weather["matched_path"]
        weather_upload = (
            (PurePosixPath(str(matched_weather)).name, normalized[str(matched_weather)])
            if isinstance(matched_weather, str)
            else None
        )
        readiness = inspect_readiness(
            base.text,
            idd_text,
            runtime_version=runtime_version,
            idd_ready=bool(idd_text.strip()),
            weather_supplied=weather_upload is not None,
            logical_files=relative_support,
        )
        if weather["status"] == "NEEDS_INPUT":
            readiness = {**readiness, "overall_status": "NEEDS_INPUT"}
        manifest = {
            "schema_version": "idfrepair.batch-project-manifest.v1",
            "idf_path": idf_path,
            "weather": weather,
            "dependencies": dependency_rows,
            "available_support_files": list(support_paths),
        }
        discovered.append(replace(
            base,
            weather=weather_upload,
            dependencies=tuple(dependencies),
            dependency_manifest=manifest,
            readiness=readiness,
        ))
    return tuple(discovered)


def _directory(path: Path) -> tuple[BatchInput, ...]:
    '''读取目录内的非链接 IDF，并保证解析路径仍位于授权目录。'''
    root = path.resolve()
    rows = []
    for item in sorted(root.rglob("*.idf")):
        if item.is_symlink() or not item.is_file():
            continue
        resolved = item.resolve()
        if root not in resolved.parents:
            raise ValueError("batch_directory_path_escape")
        rows.append(_record(
            item.relative_to(root).as_posix(), item.read_bytes(), "directory", str(root),
        ))
    return tuple(rows)


def _archive(path: Path) -> tuple[BatchInput, ...]:
    '''读取 ZIP 中的 IDF，拒绝绝对路径、上级跳转、重复成员和体积异常。'''
    rows = []
    names: set[str] = set()
    total = 0
    with zipfile.ZipFile(path) as archive:
        for info in sorted(archive.infolist(), key=lambda item: item.filename):
            name = PurePosixPath(info.filename)
            if info.is_dir() or name.suffix.casefold() != ".idf":
                continue
            if name.is_absolute() or ".." in name.parts or not name.parts:
                raise ValueError("batch_zip_path_escape")
            logical = name.as_posix()
            if logical in names:
                raise ValueError("batch_zip_duplicate_member")
            names.add(logical)
            if info.file_size > MAX_BATCH_FILE_BYTES:
                raise ValueError(f"batch_input_too_large:{logical}")
            total += info.file_size
            if total > MAX_BATCH_TOTAL_BYTES:
                raise ValueError("batch_zip_total_size_exceeded")
            rows.append(_record(logical, archive.read(info), "zip", str(path.resolve())))
    return tuple(rows)


def discover_inputs(paths: Iterable[Path]) -> tuple[BatchInput, ...]:
    '''
    发现多个 IDF、目录和 ZIP 中的记录，并在执行前冻结去重清单。

    :param paths: 调用方明确选择的文件或目录。
    :return: 按来源和逻辑名称排序且身份唯一的记录。
    '''
    rows = []
    for raw in paths:
        path = raw.expanduser().resolve()
        if path.is_dir():
            rows.extend(_directory(path))
        elif path.is_file() and path.suffix.casefold() == ".zip":
            rows.extend(_archive(path))
        elif path.is_file() and path.suffix.casefold() == ".idf":
            rows.append(_record(path.name, path.read_bytes(), "file", str(path)))
        else:
            raise ValueError(f"unsupported_batch_input:{path}")
    if not rows:
        raise ValueError("batch_contains_no_idf")
    if len(rows) > MAX_BATCH_FILES:
        raise ValueError("batch_file_count_exceeded")
    identities: set[tuple[str, str]] = set()
    unique = []
    for row in sorted(rows, key=lambda item: (item.source_identity, item.logical_name, item.record_id)):
        key = (row.logical_name, row.input_sha256)
        if key in identities:
            continue
        identities.add(key)
        unique.append(row)
    return tuple(unique)


def _safe_name(record: BatchInput) -> str:
    '''生成不会泄露目录层级且保持可读性的输出文件名。'''
    stem = Path(record.logical_name).stem
    safe = "".join(character if character.isalnum() or character in "-_." else "-" for character in stem)
    return f"{safe or 'input'}-{record.record_id[:8]}.idf"


def run_batch(
    inputs: tuple[BatchInput, ...],
    output_root: Path,
    callback: BatchCallback,
    *,
    configuration: Mapping[str, Any],
    rule_set_id: str = "default",
) -> dict[str, Any]:
    '''
    在冻结清单上逐文件执行隔离回调，并写出分类结果和汇总。

    已存在的非空输出目录会被拒绝，避免覆盖上一批次证据。
    '''
    root = output_root.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("batch_output_directory_not_empty")
    for name in (
        "workspaces", "per_file_reports", "repaired", "unchanged", "needs_input", "failed",
    ):
        (root / name).mkdir(parents=True, exist_ok=True)
    results = []
    counts = {"repaired": 0, "unchanged": 0, "needs_input": 0, "failed": 0}
    support_counts = {
        "safe-auto": 0,
        "assisted": 0,
        "interactive": 0,
        "unsupported": 0,
    }
    safe_auto_repaired = 0
    process_failure_count = 0
    for record in inputs:
        workspace = root / "workspaces" / record.record_id
        workspace.mkdir(parents=True, exist_ok=False)
        try:
            result = callback(record, workspace)
            outcome = result.outcome
            if (
                outcome.status is RepairStatus.REPAIRED
                and repaired_artifact_allowed(outcome)
            ):
                category = "repaired"
            elif outcome.status is RepairStatus.REPAIRED:
                category = "failed"
            elif outcome.status is RepairStatus.VALID:
                category = "unchanged"
            elif outcome.status is RepairStatus.NEEDS_INPUT:
                category = "needs_input"
            else:
                category = "failed"
            output_text = outcome.output_text if category == "repaired" else record.text
            report = dict(result.report) if result.report is not None else outcome.to_dict()
            error = None
            process_failed = outcome.status is RepairStatus.PROCESS_FAILED
        except Exception as exc:
            category = "failed"
            output_text = record.text
            report = {
                "schema_version": "idfrepair.batch.failure.v1",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "production_enabled": False,
            }
            error = f"{type(exc).__name__}:{exc}"
            process_failed = True
        if process_failed:
            process_failure_count += 1
        counts[category] += 1
        support_category = _support_category(report)
        support_counts[support_category] += 1
        if support_category == "safe-auto" and category == "repaired":
            safe_auto_repaired += 1
        output_name = _safe_name(record)
        (root / category / output_name).write_text(output_text, encoding="utf-8")
        report_path = root / "per_file_reports" / f"{record.record_id}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        results.append({
            "record_id": record.record_id,
            "logical_name": record.logical_name,
            "input_sha256": record.input_sha256,
            "category": category,
            "output": f"{category}/{output_name}",
            "report": f"per_file_reports/{record.record_id}.json",
            "support_category": support_category,
            "workspace": f"workspaces/{record.record_id}",
            "error": error,
        })
    total = len(inputs)
    safe_auto_supported = support_counts["safe-auto"]
    summary = {
        "schema_version": "idfrepair.batch.summary.v1",
        "input_count": total,
        "total_records": total,
        "counts": counts,
        "safe_auto_supported_records": safe_auto_supported,
        "assisted_supported_records": support_counts["assisted"],
        "interactive_only_records": support_counts["interactive"],
        "unsupported_records": support_counts["unsupported"],
        "support_coverage": _ratio(safe_auto_supported, total),
        "conditional_repair_rate": _ratio(safe_auto_repaired, safe_auto_supported),
        "overall_repair_rate": _ratio(counts["repaired"], total),
        "wrong_modification": None,
        "wbr": None,
        "partial_as_full": None,
        "process_failure": _ratio(process_failure_count, total),
        "safety_metric_denominator": total,
        "safety_metrics_scored": False,
        "safety_metric_note": "Independent scorer evidence is required; unrun metrics remain null.",
        "configuration": to_primitive(configuration),
        "rule_set_id": rule_set_id,
        "results": results,
        "production_enabled": False,
        "automatic_repair_release_authorized": False,
        "repair_memory_release_authorized": False,
        "model_product_integration_authorized": False,
    }
    (root / "batch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


__all__ = [
    "BatchInput", "BatchResult", "discover_inputs", "discover_project_inputs",
    "discover_uploaded_inputs", "run_batch",
]
