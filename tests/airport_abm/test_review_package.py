from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest


def write_allowlist(root: Path, paths: list[str]) -> None:
    destination = root / "docs/research/occupancy_v3/review_package_allowlist.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "schema_version": "idfrepair.airport-abm-review-allowlist.v3",
                "paths": sorted(paths),
            }
        ),
        encoding="utf-8",
    )


def test_review_zip_is_allowlisted_deterministic_and_excludes_private_assets(
    tmp_path: Path,
) -> None:
    from tools.airport_abm.review_package import build_review_zip

    root = tmp_path / "repo"
    files = {
        "docs/research/occupancy_v3/method.md": "method\n",
        "reports/occupancy_v3/public/summary.md": "controlled results\n",
        "src/idfrepair/analysis/airport_abm/model.py": "VALUE = 1\n",
        "tests/airport_abm/test_model.py": "def test_ok(): pass\n",
        "scripts/airport_abm/example.py": "print('review')\n",
        "examples/airport_abm_v3/synthetic_terminal.json": "{}\n",
        "private/terminal.osm": "private\n",
        "private/terminal.idf": "private\n",
        "private/weather.epw": "private\n",
    }
    reviewed = [name for name in files if not name.startswith("private/")]
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    write_allowlist(root, reviewed)
    destination = tmp_path / "review.zip"

    first = build_review_zip(root, destination)
    first_bytes = destination.read_bytes()
    second = build_review_zip(root, destination)

    assert destination.read_bytes() == first_bytes
    assert first == second
    assert first["bytes"] < 25 * 1024 * 1024
    with ZipFile(destination) as archive:
        names = archive.namelist()
        manifest_name = next(name for name in names if name.endswith("PACKAGE_MANIFEST.json"))
        manifest = json.loads(archive.read(manifest_name))
    assert manifest["raw_private_models_included"] is False
    assert manifest["file_count"] == 6
    assert not any(name.endswith((".osm", ".idf", ".epw")) for name in names)


@pytest.mark.parametrize(
    "content",
    (
        "/" + "Users/alice/private/model.osm",
        "overall_model0818.osm",
        "z-u-hall-9",
        "gh" + "p_0123456789abcdef",
        "BEGIN " + "PRIVATE KEY",
    ),
)
def test_review_package_rejects_private_or_sensitive_content(
    tmp_path: Path,
    content: str,
) -> None:
    from tools.airport_abm.review_package import build_review_zip

    root = tmp_path / "repo"
    relative = "reports/occupancy_v3/public/summary.md"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    write_allowlist(root, [relative])

    with pytest.raises(ValueError, match="review_package_sensitive_content"):
        build_review_zip(root, tmp_path / "review.zip")
