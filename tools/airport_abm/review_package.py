"""Allowlist-only, content-audited Airport ABM V3 review packaging."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PACKAGE_ROOT = "IDFRepair-AirportABM-V3-ChatGPT-review"
ALLOWLIST_PATH = Path("docs/research/occupancy_v3/review_package_allowlist.json")
ALLOWLIST_SCHEMA = "idfrepair.airport-abm-review-allowlist.v3"
MAX_PACKAGE_BYTES = 25 * 1024 * 1024
ALLOWED_PREFIXES = (
    "docs/research/occupancy_v3/",
    "examples/airport_abm_v3/",
    "reports/occupancy_v3/public/",
    "reports/occupancy_v3/figures/",
    "src/idfrepair/analysis/airport_abm/",
    "tests/airport_abm/",
    "scripts/airport_abm/",
)
ALLOWED_EXACT = {
    "scripts/run_airport_abm_v3.py",
    "src/idfrepair/web/static/app.js",
    "src/idfrepair/web/static/epshape-viewer.css",
    "src/idfrepair/web/static/epshape-viewer.html",
    "src/idfrepair/web/static/epshape-viewer.js",
    "src/idfrepair/web/static/index.html",
    "src/idfrepair/web/static/occupancy-viewer-state.js",
    "src/idfrepair/web/static/occupancy-local.html",
    "src/idfrepair/web/static/style.css",
    "src/idfrepair/web/static/viewer-bridge.js",
}
FORBIDDEN_SUFFIXES = {
    ".osm",
    ".idf",
    ".epw",
    ".dwg",
    ".dxf",
    ".tif",
    ".tiff",
    ".pdf",
    ".env",
    ".pem",
    ".key",
    ".zip",
}
ABSOLUTE_USER_PATH = re.compile(rb"/(?:Users|home)/[A-Za-z0-9._-]+/")
WINDOWS_USER_PATH = re.compile(rb"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+\\")
PRIVATE_ROOM_ID = re.compile(
    rb"\b(?:z-u-hall|z-d-hall|z-d-office|z-d-commerce|x-n-hall|"
    rb"x-b-hall|d-b-hall|n-hall|hall-1)-[0-9]+\b",
    re.IGNORECASE,
)
PRIVATE_SOURCE_NAME = b"overall_model0818.osm"
PRIVATE_KEY_MARKER = b"BEGIN " + b"PRIVATE" + b" KEY"
GITHUB_TOKEN_PREFIX = b"gh" + b"p_"
API_TOKEN_PREFIX = b"s" + b"k-"
AWS_ACCESS_KEY = re.compile(rb"\bAKIA[A-Z0-9]{16}\b")
CREDENTIAL_ASSIGNMENT = re.compile(
    rb"(?i)\b(?:api[_-]?key|access[_-]?token|password|client[_-]?secret)"
    rb"\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"
)


def allowed_path(relative: str) -> bool:
    return relative in ALLOWED_EXACT or relative.startswith(ALLOWED_PREFIXES)


def validate_relative_path(relative: str) -> None:
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
        raise ValueError(f"review_package_path_invalid:{relative}")


def load_allowlist(root: Path) -> list[str]:
    path = root / ALLOWLIST_PATH
    if not path.is_file() or path.is_symlink():
        raise ValueError("review_package_allowlist_not_found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("review_package_allowlist_invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != ALLOWLIST_SCHEMA:
        raise ValueError("review_package_allowlist_schema_invalid")
    paths = payload.get("paths")
    if not isinstance(paths, list) or not paths or any(not isinstance(row, str) for row in paths):
        raise ValueError("review_package_allowlist_paths_invalid")
    if paths != sorted(set(paths)):
        raise ValueError("review_package_allowlist_paths_not_sorted_unique")
    for relative in paths:
        validate_relative_path(relative)
        if not allowed_path(relative):
            raise ValueError(f"review_package_candidate_not_allowlisted:{relative}")
    return paths


def scan_content(relative: str, content: bytes) -> None:
    detections = (
        (ABSOLUTE_USER_PATH.search(content), "absolute_user_path"),
        (WINDOWS_USER_PATH.search(content), "windows_user_path"),
        (PRIVATE_ROOM_ID.search(content), "private_room_identifier"),
        (PRIVATE_SOURCE_NAME in content, "private_source_name"),
        (PRIVATE_KEY_MARKER in content, "private_key"),
        (GITHUB_TOKEN_PREFIX in content, "github_token"),
        (API_TOKEN_PREFIX in content, "api_token"),
        (AWS_ACCESS_KEY.search(content), "aws_access_key"),
        (CREDENTIAL_ASSIGNMENT.search(content), "credential_assignment"),
    )
    for detected, label in detections:
        if detected:
            raise ValueError(f"review_package_sensitive_content:{relative}:{label}")


def collect_review_files(project_root: Path) -> list[tuple[str, bytes]]:
    root = Path(project_root).resolve()
    result: list[tuple[str, bytes]] = []
    for relative in load_allowlist(root):
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"review_package_file_not_found:{relative}")
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES or "__pycache__" in path.parts:
            raise ValueError(f"review_package_forbidden_file:{relative}")
        content = path.read_bytes()
        scan_content(relative, content)
        result.append((relative, content))
    return result


def archive_entry(name: str, content: bytes) -> tuple[ZipInfo, bytes]:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info, content


def validate_archive(
    path: Path,
    *,
    files: list[tuple[str, bytes]],
    manifest: dict[str, object],
) -> None:
    expected = {f"{PACKAGE_ROOT}/{name}": content for name, content in files}
    expected_names = {
        *expected,
        f"{PACKAGE_ROOT}/README.md",
        f"{PACKAGE_ROOT}/PACKAGE_MANIFEST.json",
    }
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise ValueError("review_package_member_set_mismatch")
        for info in archive.infolist():
            relative = info.filename.removeprefix(f"{PACKAGE_ROOT}/")
            validate_relative_path(relative)
            mode = (info.external_attr >> 16) & 0o170000
            if mode != 0o100000:
                raise ValueError(f"review_package_member_not_regular:{info.filename}")
        for name, content in expected.items():
            if archive.read(name) != content:
                raise ValueError(f"review_package_member_content_mismatch:{name}")
        embedded = json.loads(archive.read(f"{PACKAGE_ROOT}/PACKAGE_MANIFEST.json"))
        if embedded != manifest:
            raise ValueError("review_package_manifest_mismatch")


def build_review_zip(project_root: Path, destination: Path) -> dict[str, object]:
    files = collect_review_files(project_root)
    manifest: dict[str, object] = {
        "schema_version": "idfrepair.airport-abm-review-package.v3",
        "file_count": len(files),
        "raw_private_models_included": False,
        "sensitive_information_audit": "PASS",
        "files": [{"path": name, "bytes": len(content)} for name, content in files],
    }
    readme = (
        "# IDFRepair Airport ABM V3 review package\n\n"
        "This package contains aggregate reports, figures, generic source, tests, "
        "and viewer integration only. It excludes raw or derived models, weather, "
        "drawings, EnergyPlus run directories, exact room mapping, and credentials.\n"
    ).encode("utf-8")
    manifest_content = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
    )
    temporary = Path(handle.name)
    handle.close()
    try:
        with ZipFile(temporary, "w") as archive:
            for name, content in files:
                info, payload = archive_entry(f"{PACKAGE_ROOT}/{name}", content)
                archive.writestr(info, payload)
            for name, content in (("README.md", readme), ("PACKAGE_MANIFEST.json", manifest_content)):
                info, payload = archive_entry(f"{PACKAGE_ROOT}/{name}", content)
                archive.writestr(info, payload)
        size = temporary.stat().st_size
        if size > MAX_PACKAGE_BYTES:
            raise ValueError(f"review_package_size_limit_exceeded:{size}")
        validate_archive(temporary, files=files, manifest=manifest)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "file_count": len(files),
        "raw_private_models_included": False,
        "sensitive_information_audit": "PASS",
    }


__all__ = ["ALLOWLIST_PATH", "build_review_zip", "collect_review_files"]
