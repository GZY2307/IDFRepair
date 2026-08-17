"""验证公开 fresh-tree smoke 的命令证据和失败传播。

test_run_command_records_nonzero_exit_without_raising(): 验证失败被结构化记录。
test_run_command_records_success_output(): 验证成功输出和返回码。
test_public_test_targets_only_returns_existing_paths(): 验证 smoke 不引用缺失测试。
test_smoke_result_requires_every_phase_to_pass(): 验证任一失败阻断整体状态。
"""

from __future__ import annotations

from pathlib import Path
import sys

from tools.public_release.smoke import (
    CommandResult,
    SmokeResult,
    public_test_targets,
    run_command,
)


def test_run_command_records_nonzero_exit_without_raising(tmp_path: Path) -> None:
    """子命令非零退出应成为失败证据，而不是丢失的异常。"""

    result = run_command(
        (sys.executable, "-c", "raise SystemExit(7)"),
        cwd=tmp_path,
    )

    assert result.returncode == 7
    assert result.passed is False
    assert result.timed_out is False


def test_run_command_records_success_output(tmp_path: Path) -> None:
    """成功命令应保存可审计输出尾部。"""

    result = run_command(
        (sys.executable, "-c", "print('smoke-ok')"),
        cwd=tmp_path,
    )

    assert result.passed is True
    assert "smoke-ok" in result.output_tail


def test_public_test_targets_only_returns_existing_paths(tmp_path: Path) -> None:
    """测试目标由已存在的公开测试集合确定。"""

    (tmp_path / "tests/public_release").mkdir(parents=True)
    (tmp_path / "tests/public_release/test_one.py").write_text("", encoding="utf-8")

    assert public_test_targets(tmp_path) == ("tests/public_release",)


def test_public_test_targets_excludes_legacy_compatibility_directory(
    tmp_path: Path,
) -> None:
    """legacy compatibility 测试依赖未公开历史工具，不得进入 core smoke。"""

    (tmp_path / "tests/compatibility").mkdir(parents=True)
    (tmp_path / "tests/compatibility/test_legacy.py").write_text("", encoding="utf-8")

    assert "tests/compatibility" not in public_test_targets(tmp_path)


def test_smoke_result_requires_every_phase_to_pass() -> None:
    """整体 smoke 仅在全部阶段成功时通过。"""

    passed = CommandResult("one", ("true",), 0, False, 0.1, "")
    failed = CommandResult("two", ("false",), 1, False, 0.1, "")

    assert SmokeResult((passed,)).passed is True
    assert SmokeResult((passed, failed)).passed is False
