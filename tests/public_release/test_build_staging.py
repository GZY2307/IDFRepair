"""验证公开 staging 的显式白名单、确定性和路径安全。

test_build_staging_is_deterministic_and_excludes_unlisted_files(): 验证确定性清单。
test_build_staging_rejects_allowlisted_symlink(): 验证符号链接无法进入公开树。
test_build_staging_requires_replace_for_existing_destination(): 验证目的目录不会被隐式覆盖。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.public_release.build_staging import build_staging


def _write(path: Path, value: str) -> None:
    """创建父目录并写入一个测试文本文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _release_fixture(root: Path) -> Path:
    """构造同时含公开与排除文件的最小源树。"""

    _write(root / "README.md", "# Public\n")
    _write(root / "src/idfrepair/__init__.py", '"""Package."""\n')
    _write(root / "SERVER_TRAINING.md", "private\n")
    _write(root / "notes/unreviewed.txt", "not allowlisted\n")
    return root


def test_build_staging_is_deterministic_and_excludes_unlisted_files(
    tmp_path: Path,
) -> None:
    """两个独立目的目录应获得完全相同且只含白名单成员的清单。"""

    source = _release_fixture(tmp_path / "source")

    first = build_staging(source, tmp_path / "one")
    second = build_staging(source, tmp_path / "two")

    assert first == second
    assert {row["path"] for row in first["members"]} == {
        "README.md",
        "src/idfrepair/__init__.py",
    }
    assert not (tmp_path / "one" / "SERVER_TRAINING.md").exists()
    assert not (tmp_path / "one" / "notes/unreviewed.txt").exists()
    assert (tmp_path / "one" / "reports/public_release/public_manifest.json").is_file()


def test_build_staging_rejects_allowlisted_symlink(tmp_path: Path) -> None:
    """即使 symlink 名称位于白名单前缀，也必须拒绝整个 staging。"""

    source = _release_fixture(tmp_path / "source")
    outside = tmp_path / "outside.py"
    outside.write_text("secret\n", encoding="utf-8")
    (source / "src/idfrepair/link.py").symlink_to(outside)

    with pytest.raises(ValueError, match="symlink_not_allowed"):
        build_staging(source, tmp_path / "stage")


def test_build_staging_prunes_forbidden_subtrees_before_traversal(
    tmp_path: Path,
) -> None:
    """`.private` 等目录应在 walk 层剪枝，内部 symlink 也不被访问。"""

    source = _release_fixture(tmp_path / "source")
    outside = tmp_path / "outside-private.py"
    outside.write_text("private\n", encoding="utf-8")
    private = source / ".private"
    private.mkdir()
    (private / "link.py").symlink_to(outside)

    manifest = build_staging(source, tmp_path / "stage")

    assert {row["path"] for row in manifest["members"]} == {
        "README.md",
        "src/idfrepair/__init__.py",
    }


def test_build_staging_requires_replace_for_existing_destination(
    tmp_path: Path,
) -> None:
    """已存在目的目录只能在显式 replace 时重建。"""

    source = _release_fixture(tmp_path / "source")
    destination = tmp_path / "stage"
    destination.mkdir()

    with pytest.raises(FileExistsError):
        build_staging(source, destination)

    manifest = build_staging(source, destination, replace=True)
    assert manifest["member_count"] == 2
