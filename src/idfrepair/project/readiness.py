"""Deterministic project readiness and external-file resolution."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

from idfrepair.io.idf import IDFDocument, canonical, parse_idf
from idfrepair.knowledge.idd import IDDSchema, parse_idd
from idfrepair.runtime.discovery import normalize_version
from idfrepair.runtime.energyplus import preprocessing_requirements


MAX_PROJECT_FILES = 5_000
MAX_PROJECT_FILE_BYTES = 50 * 1024 * 1024
MAX_PROJECT_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
DEPENDENCY_OBJECT_TYPES = frozenset({"schedule:file", "schedule:file:shading"})
RUNNABLE_READINESS_STATUSES = frozenset({"READY", "NOT_REQUIRED"})


_COPY = {
    "parse": {
        "zh-CN": ("模型格式", "检查文件能否按 IDF 对象和字段读取。", "修正文件格式后重新选择模型。"),
        "en": ("Model format", "Checks whether the file can be read as IDF objects and fields.", "Correct the file format and select it again."),
    },
    "idf_version": {
        "zh-CN": ("IDF 版本", "读取模型声明的 EnergyPlus 版本。", "补充或修正 Version 对象。"),
        "en": ("IDF version", "Reads the EnergyPlus version declared by the model.", "Add or correct the Version object."),
    },
    "runtime": {
        "zh-CN": ("EnergyPlus 版本匹配", "比较模型版本和准备使用的本机 EnergyPlus。", "选择与模型相同的版本，或明确创建迁移副本。"),
        "en": ("EnergyPlus version match", "Compares the model version with the selected local EnergyPlus.", "Use the matching version or explicitly create a migrated copy."),
    },
    "idd": {
        "zh-CN": ("字段规则文件", "确认当前 EnergyPlus 的字段定义文件可用。", "重新扫描或修复对应 EnergyPlus 安装。"),
        "en": ("Field rules", "Checks that the selected EnergyPlus field-definition file is available.", "Rescan or repair the matching EnergyPlus installation."),
    },
    "expandobjects": {
        "zh-CN": ("模板展开", "检查运行前是否需要 EnergyPlus 官方 ExpandObjects。", "无需手动处理；运行时会使用官方工具。"),
        "en": ("Template expansion", "Checks whether official EnergyPlus ExpandObjects is required before the run.", "No manual step is needed; the official tool will be used."),
    },
    "weather": {
        "zh-CN": ("天气文件", "提前判断此次运行是否已经具备天气或设计日条件。", "提供项目使用的 EPW，或补充设计日对象。"),
        "en": ("Weather file", "Checks whether this run already has weather or design-day conditions.", "Provide the project EPW or add design-day objects."),
    },
    "dependencies": {
        "zh-CN": ("外部数据文件", "核对 Schedule:File 等对象引用的 CSV 相对路径。", "提供缺失文件；同名文件有歧义时请明确选择。"),
        "en": ("External data files", "Checks relative CSV paths referenced by Schedule:File objects.", "Provide missing files and choose explicitly when names are ambiguous."),
    },
}


def _presentation(check_id: str, *, next_action: bool) -> dict[str, dict[str, str | None]]:
    return {
        locale: {
            "title": values[0],
            "explanation": values[1],
            "next_action": values[2] if next_action else None,
        }
        for locale, values in _COPY[check_id].items()
    }


def _check(check_id: str, status: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "details": details,
        "presentation": _presentation(
            check_id,
            next_action=status in {"MISSING", "NEEDS_INPUT", "UNSUPPORTED"},
        ),
    }


def normalize_project_path(value: str) -> str:
    """Normalize one browser-authorized relative path without guessing."""

    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("project_path_invalid")
    path = PurePosixPath(value)
    raw_parts = value.split("/")
    if path.is_absolute() or not path.parts or any(part == "" for part in raw_parts):
        raise ValueError("project_path_invalid")
    if any(part in {".", ".."} for part in raw_parts):
        raise ValueError("project_path_escape")
    return path.as_posix()


def _file_field_index(schema: IDDSchema, object_type: str) -> tuple[int, str] | None:
    definition = schema.get(object_type)
    if definition is None:
        return None
    candidates = [
        field for field in definition.fields
        if canonical(field.name).replace("_", " ") in {"file name", "filename"}
        or ("file" in canonical(field.name) and "name" in canonical(field.name))
    ]
    if len(candidates) != 1:
        return None
    return candidates[0].index, candidates[0].name


def resolve_external_dependencies(
    document: IDFDocument,
    schema: IDDSchema,
    logical_files: Iterable[str],
) -> tuple[dict[str, Any], ...]:
    """Resolve only exact normalized Schedule:File family paths."""

    files = tuple(sorted({normalize_project_path(value) for value in logical_files}, key=str.casefold))
    file_set = set(files)
    by_basename: dict[str, list[str]] = {}
    for value in files:
        by_basename.setdefault(PurePosixPath(value).name.casefold(), []).append(value)
    rows: list[dict[str, Any]] = []
    for obj in document.objects:
        if canonical(obj.object_type).replace(" ", "") not in {
            value.replace(" ", "") for value in DEPENDENCY_OBJECT_TYPES
        }:
            continue
        identified = _file_field_index(schema, obj.object_type)
        if identified is None:
            continue
        field_index, field_name = identified
        if field_index > len(obj.fields) or not obj.fields[field_index - 1].value.strip():
            continue
        raw_path = obj.fields[field_index - 1].value.strip().replace("\\", "/")
        try:
            requested = normalize_project_path(raw_path)
        except ValueError:
            requested = raw_path
            suggestions: list[str] = []
            status = "MISSING"
            matched = None
        else:
            suggestions = sorted(
                by_basename.get(PurePosixPath(requested).name.casefold(), []),
                key=str.casefold,
            )
            if requested in file_set:
                status = "READY"
                matched = requested
                suggestions = []
            elif suggestions:
                status = "NEEDS_INPUT"
                matched = None
            else:
                status = "MISSING"
                matched = None
        rows.append({
            "object_index": obj.index,
            "object_type": obj.object_type,
            "object_name": obj.name or None,
            "field_index": field_index,
            "field_name": field_name,
            "requested_path": requested,
            "status": status,
            "matched_path": matched,
            "suggestions": suggestions,
        })
    return tuple(rows)


def _overall_status(checks: Iterable[dict[str, Any]]) -> str:
    statuses = {str(row["status"]) for row in checks}
    for status in ("MISSING", "UNSUPPORTED", "NEEDS_INPUT"):
        if status in statuses:
            return status
    return "READY"


def blocking_readiness_checks(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return checks that do not explicitly permit EnergyPlus execution."""

    return tuple(
        str(row.get("check_id") or "unknown")
        for row in payload.get("checks", ())
        if isinstance(row, Mapping)
        and str(row.get("status")) not in RUNNABLE_READINESS_STATUSES
    )


def inspect_readiness(
    text: str,
    idd_text: str,
    *,
    runtime_version: str | None,
    idd_ready: bool,
    weather_supplied: bool,
    logical_files: Iterable[str],
) -> dict[str, Any]:
    """Explain whether an IDF project is ready before EnergyPlus is launched."""

    try:
        document = parse_idf(text)
    except Exception as exc:
        parse_check = _check("parse", "UNSUPPORTED", {"reason": f"{type(exc).__name__}:{exc}"})
        return {
            "schema_version": "idfrepair.run-readiness.v1",
            "overall_status": "UNSUPPORTED",
            "checks": [parse_check],
        }
    schema = parse_idd(idd_text)
    checks: list[dict[str, Any]] = [_check("parse", "READY", {"object_count": len(document.objects)})]
    model_version = normalize_version(document.version)
    checks.append(_check(
        "idf_version",
        "READY" if model_version else "MISSING",
        {"model_version": model_version or None},
    ))
    normalized_runtime = normalize_version(runtime_version or "")
    runtime_status = (
        "READY" if model_version and normalized_runtime == model_version
        else "NEEDS_INPUT" if normalized_runtime
        else "MISSING"
    )
    checks.append(_check(
        "runtime",
        runtime_status,
        {"model_version": model_version or None, "runtime_version": normalized_runtime or None},
    ))
    checks.append(_check(
        "idd",
        "READY" if idd_ready else "UNSUPPORTED",
        {"idd_version": normalize_version(schema.version) or None},
    ))
    preprocessing = list(preprocessing_requirements(text))
    checks.append(_check(
        "expandobjects",
        "READY" if preprocessing else "NOT_REQUIRED",
        {"required": bool(preprocessing), "object_types": preprocessing},
    ))
    has_design_day = any(
        canonical(obj.object_type) == "sizingperiod:designday" for obj in document.objects
    )
    if weather_supplied:
        weather_status = "READY"
    elif has_design_day:
        weather_status = "NOT_REQUIRED"
    else:
        weather_status = "MISSING"
    checks.append(_check(
        "weather",
        weather_status,
        {"weather_supplied": weather_supplied, "design_day_only": not weather_supplied and has_design_day},
    ))
    dependency_rows = list(resolve_external_dependencies(document, schema, logical_files))
    dependency_states = {str(row["status"]) for row in dependency_rows}
    if not dependency_rows:
        dependency_status = "NOT_REQUIRED"
    elif "MISSING" in dependency_states:
        dependency_status = "MISSING"
    elif "NEEDS_INPUT" in dependency_states:
        dependency_status = "NEEDS_INPUT"
    else:
        dependency_status = "READY"
    checks.append(_check(
        "dependencies",
        dependency_status,
        {"items": dependency_rows},
    ))
    return {
        "schema_version": "idfrepair.run-readiness.v1",
        "overall_status": _overall_status(checks),
        "checks": checks,
    }


def inspect_project_files(files: Iterable[tuple[str, bytes]]) -> dict[str, Any]:
    """Inspect a browser-authorized project manifest without selecting an IDF."""

    rows = tuple(files)
    if len(rows) > MAX_PROJECT_FILES:
        raise ValueError("project_file_count_exceeded")
    seen: set[str] = set()
    total = 0
    idfs: list[dict[str, Any]] = []
    weather: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    for raw_path, content in rows:
        logical_path = normalize_project_path(raw_path)
        if logical_path in seen:
            raise ValueError(f"project_duplicate_path:{logical_path}")
        seen.add(logical_path)
        if len(content) > MAX_PROJECT_FILE_BYTES:
            raise ValueError(f"project_file_too_large:{logical_path}")
        total += len(content)
        if total > MAX_PROJECT_TOTAL_BYTES:
            raise ValueError("project_total_size_exceeded")
        item = {"logical_path": logical_path, "size": len(content)}
        suffix = PurePosixPath(logical_path).suffix.casefold()
        if suffix == ".idf":
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError(f"project_idf_not_utf8:{logical_path}") from exc
            document = parse_idf(text)
            idfs.append({**item, "version": normalize_version(document.version) or None})
        elif suffix == ".epw":
            weather.append(item)
        else:
            dependencies.append(item)
    if not idfs:
        raise ValueError("project_contains_no_idf")
    idfs.sort(key=lambda row: str(row["logical_path"]).casefold())
    weather.sort(key=lambda row: str(row["logical_path"]).casefold())
    dependencies.sort(key=lambda row: str(row["logical_path"]).casefold())
    return {
        "schema_version": "idfrepair.project-manifest.v1",
        "disposition": "SINGLE" if len(idfs) == 1 else "BATCH",
        "idf_count": len(idfs),
        "idfs": idfs,
        "weather_files": weather,
        "dependency_files": dependencies,
        "file_count": len(rows),
        "total_size": total,
    }


__all__ = [
    "blocking_readiness_checks",
    "inspect_project_files",
    "inspect_readiness",
    "normalize_project_path",
    "resolve_external_dependencies",
]
