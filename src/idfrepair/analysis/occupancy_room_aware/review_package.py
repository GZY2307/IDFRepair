"""Atomic, deterministic and content-audited room-aware review packaging."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PACKAGE_ROOT = "IDFRepair-AirportOccupancy-RoomAware-review"
MAX_PACKAGE_BYTES = 25 * 1024 * 1024
ALLOWLIST_PATH = Path("docs/research/occupancy/review_package_allowlist.json")
ALLOWLIST_SCHEMA = "idfrepair.room-aware-review-allowlist.v1"
_ALLOWED_PREFIXES = (
    "docs/research/occupancy/",
    "reports/occupancy_v2/",
    "src/idfrepair/analysis/occupancy_room_aware/",
    "tests/occupancy_room_aware/",
    "scripts/occupancy_room_aware/",
)
_ALLOWED_EXACT = {
    "scripts/run_airport_occupancy_room_aware.py",
    "src/idfrepair/web/locales/en.json",
    "src/idfrepair/web/locales/zh-CN.json",
    "src/idfrepair/web/static/app.js",
    "src/idfrepair/web/static/occupancy-local.html",
    "src/idfrepair/web/static/occupancy-viewer-state.js",
    "src/idfrepair/web/static/epshape-viewer.html",
    "src/idfrepair/web/static/epshape-viewer.js",
    "src/idfrepair/web/static/epshape-viewer.css",
    "src/idfrepair/web/static/epshape-three.js",
    "src/idfrepair/web/static/index.html",
    "src/idfrepair/web/static/style.css",
    "src/idfrepair/web/static/viewer-bridge.js",
    "src/idfrepair/web/static/viewer-issue-state.js",
    "tests/unified/test_viewer_bridge.py",
    "tests/unified/test_web_ui.py",
    "tests/unified/test_web_workflow_state.py",
}
_FORBIDDEN_SUFFIXES = {
    ".osm", ".idf", ".epw", ".dwg", ".dxf", ".tif", ".tiff", ".pdf",
    ".env", ".pem", ".key",
}
_ABSOLUTE_USER_PATH = re.compile(
    b"/" + b"Users" + rb"/[A-Za-z0-9._-]+/"
)
_WINDOWS_USER_PATH = re.compile(
    rb"[A-Za-z]:\\" + b"Users" + rb"\\[A-Za-z0-9._-]+\\"
)
_AWS_ACCESS_KEY = re.compile(rb"\bAKIA[A-Z0-9]{16}\b")
_CREDENTIAL_ASSIGNMENT = re.compile(
    rb"(?i)\b(?:api[_-]?key|access[_-]?token|password|client[_-]?secret)"
    rb"\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"
)
_PRIVATE_KEY_MARKER = b"BEGIN " + b"PRIVATE" + b" KEY"
_GITHUB_TOKEN_PREFIX = b"gh" + b"p_"
_OPENAI_TOKEN_PREFIX = b"s" + b"k-"
_PRIVATE_SOURCE_BASENAME = b"overall_model0116_" + b"complete.osm"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _allowed(relative: str) -> bool:
    return relative in _ALLOWED_EXACT or relative.startswith(_ALLOWED_PREFIXES)


def _validate_relative_path(relative: str) -> None:
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != relative
    ):
        raise ValueError(f"review_package_path_invalid:{relative}")


def _load_allowlist(root: Path) -> list[str]:
    path = root / ALLOWLIST_PATH
    if not path.is_file() or path.is_symlink():
        raise ValueError("review_package_allowlist_not_found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("review_package_allowlist_invalid_json") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != ALLOWLIST_SCHEMA:
        raise ValueError("review_package_allowlist_schema_invalid")
    paths = payload.get("paths")
    if (
        not isinstance(paths, list)
        or not paths
        or any(not isinstance(row, str) for row in paths)
    ):
        raise ValueError("review_package_allowlist_paths_invalid")
    if paths != sorted(set(paths)):
        raise ValueError("review_package_allowlist_paths_not_sorted_unique")
    for relative in paths:
        _validate_relative_path(relative)
        if not _allowed(relative):
            raise ValueError(f"review_package_candidate_not_allowlisted:{relative}")
    return paths


def _scan_content(relative: str, payload: bytes) -> None:
    detections = (
        (_ABSOLUTE_USER_PATH.search(payload), "absolute_user_path"),
        (_WINDOWS_USER_PATH.search(payload), "windows_user_path"),
        (_AWS_ACCESS_KEY.search(payload), "aws_access_key"),
        (_CREDENTIAL_ASSIGNMENT.search(payload), "credential_assignment"),
        (_PRIVATE_KEY_MARKER in payload, "private_key"),
        (_GITHUB_TOKEN_PREFIX in payload, "github_token"),
        (_OPENAI_TOKEN_PREFIX in payload, "api_token"),
        (_PRIVATE_SOURCE_BASENAME in payload, "private_source_basename"),
    )
    for detected, label in detections:
        if detected:
            raise ValueError(f"review_package_sensitive_content:{relative}:{label}")


def collect_review_files(project_root: Path) -> list[tuple[str, bytes]]:
    """Read only exact manifest members; never traverse repository/private trees."""

    root = Path(project_root).resolve()
    result: list[tuple[str, bytes]] = []
    for relative in _load_allowlist(root):
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"review_package_allowlisted_file_not_found:{relative}")
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            raise ValueError(f"review_package_forbidden_cache_file:{relative}")
        if path.suffix.casefold() in _FORBIDDEN_SUFFIXES:
            raise ValueError(f"review_package_forbidden_file:{relative}")
        payload = path.read_bytes()
        _scan_content(relative, payload)
        result.append((relative, payload))
    return result


def _entry(name: str, payload: bytes) -> tuple[ZipInfo, bytes]:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info, payload


def _validate_zip(
    archive_path: Path,
    *,
    files: list[tuple[str, bytes]],
    manifest: dict[str, Any],
) -> None:
    expected_payloads = {
        f"{PACKAGE_ROOT}/{name}": payload for name, payload in files
    }
    expected_names = {
        *expected_payloads,
        f"{PACKAGE_ROOT}/README.md",
        f"{PACKAGE_ROOT}/PACKAGE_MANIFEST.json",
    }
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("review_package_crc_failure")
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise ValueError("review_package_member_set_mismatch")
        for info in archive.infolist():
            relative = info.filename.removeprefix(f"{PACKAGE_ROOT}/")
            _validate_relative_path(relative)
            mode = (info.external_attr >> 16) & 0o170000
            if mode != 0o100000:
                raise ValueError(f"review_package_member_not_regular:{info.filename}")
        for name, payload in expected_payloads.items():
            if archive.read(name) != payload:
                raise ValueError(f"review_package_member_content_mismatch:{name}")
        parsed = json.loads(
            archive.read(f"{PACKAGE_ROOT}/PACKAGE_MANIFEST.json")
        )
        if parsed != manifest:
            raise ValueError("review_package_embedded_manifest_mismatch")

    with tempfile.TemporaryDirectory(
        prefix="room-aware-review-unpack-", dir=archive_path.parent
    ) as directory:
        unpack_root = Path(directory)
        with ZipFile(archive_path) as archive:
            archive.extractall(unpack_root)
        extracted = sorted(
            path.relative_to(unpack_root).as_posix()
            for path in unpack_root.rglob("*")
            if path.is_file()
        )
        if extracted != sorted(expected_names):
            raise ValueError("review_package_fresh_unpack_member_mismatch")
        for name, payload in expected_payloads.items():
            path = unpack_root / name
            if (
                path.is_symlink()
                or _sha256_bytes(path.read_bytes()) != _sha256_bytes(payload)
            ):
                raise ValueError(f"review_package_fresh_unpack_hash_mismatch:{name}")


def build_review_zip(project_root: Path, destination: Path) -> dict[str, Any]:
    """Atomically replace the destination only after complete ZIP validation."""

    files = collect_review_files(project_root)
    file_manifest = [
        {"path": name, "bytes": len(payload), "sha256": _sha256_bytes(payload)}
        for name, payload in files
    ]
    manifest = {
        "schema_version": "idfrepair.room-aware-review-package.v2",
        "file_count": len(files),
        "raw_private_models_included": False,
        "content_sensitive_information_scan": "PASS",
        "excluded_types": sorted(_FORBIDDEN_SUFFIXES),
        "files": file_manifest,
    }
    readme = (
        "# IDFRepair room-aware airport occupancy review\n\n"
        "This package contains compact reports, figures, source and tests only.\n"
        "It intentionally excludes raw private OSM, derived IDF, weather files, "
        "EnergyPlus run directories, construction drawings and credentials.\n"
    ).encode("utf-8")
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
    )
    temporary = Path(handle.name)
    handle.close()
    try:
        with ZipFile(temporary, "w") as archive:
            for name, payload in files:
                info, content = _entry(f"{PACKAGE_ROOT}/{name}", payload)
                archive.writestr(info, content)
            for name, payload in (
                ("README.md", readme),
                ("PACKAGE_MANIFEST.json", manifest_bytes),
            ):
                info, content = _entry(f"{PACKAGE_ROOT}/{name}", payload)
                archive.writestr(info, content)
        size = temporary.stat().st_size
        if size > MAX_PACKAGE_BYTES:
            raise ValueError(f"review_package_size_limit_exceeded:{size}")
        _validate_zip(temporary, files=files, manifest=manifest)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "file_count": len(files),
        "raw_private_models_included": False,
        "content_sensitive_information_scan": "PASS",
    }


__all__ = ["ALLOWLIST_PATH", "build_review_zip", "collect_review_files"]
