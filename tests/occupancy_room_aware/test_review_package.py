"""Lightweight room-aware review-package allowlist contracts."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

import idfrepair.analysis.occupancy_room_aware.review_package as package_module

from idfrepair.analysis.occupancy_room_aware.review_package import (
    build_review_zip,
    collect_review_files,
)


def _allowlist(root: Path, paths: list[str]) -> None:
    destination = root / "docs/research/occupancy/review_package_allowlist.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "schema_version": "idfrepair.room-aware-review-allowlist.v1",
                "paths": sorted(paths),
            }
        ),
        encoding="utf-8",
    )


def test_review_zip_is_allowlisted_deterministic_and_excludes_private_models(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    files = {
        "docs/research/occupancy/protocol.md": "protocol",
        "reports/occupancy_v2/results.md": "results",
        "src/idfrepair/analysis/occupancy_room_aware/example.py": "VALUE = 1\n",
        "tests/occupancy_room_aware/test_example.py": "def test_ok(): pass\n",
        "scripts/occupancy_room_aware/example.py": "print('review')\n",
        "src/idfrepair/web/static/occupancy-local.html": "<html></html>\n",
        "derived/occupancy_room_aware/private.idf": "private",
        "models/private.osm": "private",
        "examples/weather.epw": "private",
    }
    for relative, value in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    reviewed = [relative for relative in files if relative.startswith((
        "docs/research/occupancy/",
        "reports/occupancy_v2/",
        "src/idfrepair/analysis/occupancy_room_aware/",
        "tests/occupancy_room_aware/",
        "scripts/occupancy_room_aware/",
        "src/idfrepair/web/static/occupancy-local.html",
    )) and not relative.endswith((".idf", ".osm", ".epw"))]
    _allowlist(root, reviewed)

    destination = tmp_path / "review.zip"
    first = build_review_zip(root, destination)
    first_bytes = destination.read_bytes()
    second = build_review_zip(root, destination)

    assert destination.read_bytes() == first_bytes
    assert first["sha256"] == second["sha256"]
    assert first["bytes"] < 25 * 1024 * 1024
    with ZipFile(destination) as archive:
        names = archive.namelist()
        assert any(name.endswith("reports/occupancy_v2/results.md") for name in names)
        assert not any(name.endswith((".osm", ".idf", ".epw")) for name in names)
        manifest_name = next(name for name in names if name.endswith("PACKAGE_MANIFEST.json"))
        manifest = json.loads(archive.read(manifest_name))
    assert manifest["raw_private_models_included"] is False
    assert manifest["file_count"] == 6


def test_review_collection_never_walks_unrelated_private_tree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    report = root / "reports/occupancy_v2/results.md"
    report.parent.mkdir(parents=True)
    report.write_text("results\n", encoding="utf-8")
    _allowlist(root, ["reports/occupancy_v2/results.md"])
    private = root / ".private/raw"
    private.mkdir(parents=True)
    (private / "terminal.osm").write_text("private\n", encoding="utf-8")

    original_rglob = Path.rglob

    def guarded_rglob(path: Path, pattern: str):
        if path == root:
            raise AssertionError("review collection walked the repository root")
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", guarded_rglob)

    assert collect_review_files(root) == [
        ("reports/occupancy_v2/results.md", b"results\n")
    ]


def test_review_package_accepts_only_the_unified_demo_integration_members(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    reviewed = [
        "src/idfrepair/web/locales/en.json",
        "src/idfrepair/web/locales/zh-CN.json",
        "src/idfrepair/web/static/app.js",
        "src/idfrepair/web/static/index.html",
        "src/idfrepair/web/static/style.css",
        "tests/unified/test_viewer_bridge.py",
        "tests/unified/test_web_ui.py",
        "tests/unified/test_web_workflow_state.py",
    ]
    for relative in reviewed:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("safe\n", encoding="utf-8")
    _allowlist(root, reviewed)

    assert [relative for relative, _ in collect_review_files(root)] == sorted(reviewed)


@pytest.mark.parametrize(
    "sensitive",
    (
        "/" + "Users/" + "alice/private/model.osm",
        "gh" + "p_" + "0123456789abcdef",
        "BEGIN " + "PRIVATE" + " KEY",
    ),
)
def test_review_package_rejects_sensitive_content_under_allowlisted_path(
    tmp_path: Path, sensitive: str
) -> None:
    root = tmp_path / "repo"
    relative = "reports/occupancy_v2/results.md"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_text(sensitive, encoding="utf-8")
    _allowlist(root, [relative])

    with pytest.raises(ValueError, match="review_package_sensitive_content"):
        build_review_zip(root, tmp_path / "review.zip")


def test_review_package_failure_is_atomic_and_cleans_temporary_zip(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repo"
    relative = "reports/occupancy_v2/results.md"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_text("safe", encoding="utf-8")
    _allowlist(root, [relative])
    destination = tmp_path / "review.zip"
    destination.write_bytes(b"previous-valid-package")

    monkeypatch.setattr(package_module, "MAX_PACKAGE_BYTES", 1)
    with pytest.raises(ValueError, match="size_limit_exceeded"):
        build_review_zip(root, destination)
    assert destination.read_bytes() == b"previous-valid-package"
    assert not list(tmp_path.glob(".review.zip.*.tmp"))

    monkeypatch.setattr(package_module, "MAX_PACKAGE_BYTES", 25 * 1024 * 1024)
    monkeypatch.setattr(
        package_module,
        "_validate_zip",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("review_package_crc_failure")
        ),
    )
    with pytest.raises(ValueError, match="crc_failure"):
        build_review_zip(root, destination)
    assert destination.read_bytes() == b"previous-valid-package"
    assert not list(tmp_path.glob(".review.zip.*.tmp"))
