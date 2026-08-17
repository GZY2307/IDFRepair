"""在独立目录执行公开包安装、测试与冻结指标复现 smoke。

CommandResult: 保存一个子命令的完整状态和有界输出。
SmokeResult: 汇总全部阶段并实行全通过判定。
run_command(): 执行带超时的命令并保留失败证据。
public_test_targets(): 选择公开树中实际存在的测试目标。
run_smoke(): 执行指标、测试、编译、构建、安装、导入和 Git 检查。
main(): 运行 smoke 并写入 JSON 报告。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Sequence

from tools.public_release.policy import PUBLIC_TEST_EXACT


OUTPUT_TAIL_BYTES = 6000
DEFAULT_TIMEOUT_SECONDS = 600

CORE_TEST_CANDIDATES = (
    "tests/public_release",
    "tests/occupancy",
    "tests/occupancy_room_aware",
    "tests/post_final",
    *tuple(
        path.as_posix()
        for path in sorted(PUBLIC_TEST_EXACT, key=lambda value: value.as_posix())
        if path.name.startswith("test_")
    ),
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """保存一个可复查 smoke 阶段的命令、状态与截断日志。"""

    phase: str
    command: tuple[str, ...]
    returncode: int
    timed_out: bool
    duration_seconds: float
    output_tail: str

    @property
    def passed(self) -> bool:
        """仅在未超时且返回码为零时通过。"""

        return not self.timed_out and self.returncode == 0

    def to_dict(self) -> dict[str, object]:
        """返回不含当前工作目录的 JSON 记录。"""

        value = asdict(self)
        value["passed"] = self.passed
        return value


@dataclass(frozen=True, slots=True)
class SmokeResult:
    """保存公开复现 smoke 的有序阶段集合。"""

    phases: tuple[CommandResult, ...]

    @property
    def passed(self) -> bool:
        """空集合或任一失败都不能得到通过状态。"""

        return bool(self.phases) and all(row.passed for row in self.phases)

    def to_dict(self) -> dict[str, object]:
        """生成稳定的 smoke 报告结构。"""

        return {
            "schema_version": "idfrepair.public-reproducibility-smoke.v1",
            "status": "PASSED" if self.passed else "FAILED",
            "phase_count": len(self.phases),
            "phases": [row.to_dict() for row in self.phases],
        }


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    phase: str = "command",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> CommandResult:
    """执行命令并将非零退出或超时转换为结构化证据。"""

    started = time.monotonic()
    try:
        result = subprocess.run(
            tuple(command),
            cwd=cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
        )
        output = result.stdout or ""
        return CommandResult(
            phase=phase,
            command=tuple(str(value) for value in command),
            returncode=result.returncode,
            timed_out=False,
            duration_seconds=round(time.monotonic() - started, 3),
            output_tail=output[-OUTPUT_TAIL_BYTES:],
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return CommandResult(
            phase=phase,
            command=tuple(str(value) for value in command),
            returncode=124,
            timed_out=True,
            duration_seconds=round(time.monotonic() - started, 3),
            output_tail=str(output)[-OUTPUT_TAIL_BYTES:],
        )
    except OSError as exc:
        return CommandResult(
            phase=phase,
            command=tuple(str(value) for value in command),
            returncode=127,
            timed_out=False,
            duration_seconds=round(time.monotonic() - started, 3),
            output_tail=f"{type(exc).__name__}: {exc}"[-OUTPUT_TAIL_BYTES:],
        )


def public_test_targets(root: Path) -> tuple[str, ...]:
    """按固定顺序返回公开候选中实际存在的测试文件或目录。"""

    return tuple(relative for relative in CORE_TEST_CANDIDATES if (root / relative).exists())


def _missing_phase(phase: str, detail: str) -> CommandResult:
    """为缺失前置条件构造无需启动进程的失败阶段。"""

    return CommandResult(phase, (), 2, False, 0.0, detail)


def run_smoke(root: Path, workspace: Path) -> SmokeResult:
    """执行公开树的冻结指标、测试、编译、wheel、安装、导入和 Git 检查。"""

    root = root.resolve()
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    phases: list[CommandResult] = []
    metric_script = root / "scripts/public_reproduce_formal_v2.py"
    if metric_script.is_file():
        phases.append(
            run_command(
                (sys.executable, "scripts/public_reproduce_formal_v2.py", "--json"),
                cwd=root,
                phase="frozen_metric_reproduction",
            )
        )
    else:
        phases.append(_missing_phase("frozen_metric_reproduction", "missing_metric_script"))

    targets = public_test_targets(root)
    if targets:
        phases.append(
            run_command(
                (sys.executable, "-m", "pytest", "-q", *targets),
                cwd=root,
                phase="public_pytest",
                timeout_seconds=1200,
            )
        )
    else:
        phases.append(_missing_phase("public_pytest", "no_public_tests"))

    phases.append(
        run_command(
            (sys.executable, "-m", "compileall", "-q", "src", "tools", "scripts", "tests"),
            cwd=root,
            phase="compileall",
        )
    )

    wheel_directory = workspace / "wheel"
    wheel_directory.mkdir(parents=True, exist_ok=True)
    phases.append(
        run_command(
            (
                sys.executable,
                "-m",
                "pip",
                "wheel",
                ".",
                "--no-deps",
                "--wheel-dir",
                str(wheel_directory),
            ),
            cwd=root,
            phase="wheel_build",
        )
    )

    environment = workspace / "venv"
    phases.append(
        run_command(
            (sys.executable, "-m", "venv", "--system-site-packages", str(environment)),
            cwd=root,
            phase="venv_create",
        )
    )
    wheels = tuple(sorted(wheel_directory.glob("idfrepair-*.whl")))
    if wheels and phases[-1].passed:
        python = environment / "bin/python"
        install = run_command(
            (str(python), "-m", "pip", "install", "--no-deps", str(wheels[-1])),
            cwd=root,
            phase="wheel_install",
        )
        phases.append(install)
        if install.passed:
            phases.append(
                run_command(
                    (
                        str(python),
                        "-c",
                        "import idfrepair; import idfrepair.semantic_graph_v2; print('import-ok')",
                    ),
                    cwd=workspace,
                    phase="installed_import",
                )
            )
            cli = environment / "bin/idfrepair"
            phases.append(
                run_command((str(cli), "--help"), cwd=workspace, phase="installed_cli_help")
            )
        else:
            phases.extend(
                (
                    _missing_phase("installed_import", "wheel_install_failed"),
                    _missing_phase("installed_cli_help", "wheel_install_failed"),
                )
            )
    else:
        phases.extend(
            (
                _missing_phase("wheel_install", "wheel_or_venv_unavailable"),
                _missing_phase("installed_import", "wheel_not_installed"),
                _missing_phase("installed_cli_help", "wheel_not_installed"),
            )
        )

    if (root / ".git").exists():
        phases.append(
            run_command(("git", "diff", "--check"), cwd=root, phase="git_diff_check")
        )
    return SmokeResult(tuple(phases))


def _parser() -> argparse.ArgumentParser:
    """构造 smoke 命令行参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行 smoke、写入报告并返回整体状态。"""

    args = _parser().parse_args(argv)
    workspace = args.workspace or Path(
        tempfile.mkdtemp(prefix="idfrepair-public-smoke-", dir=tempfile.gettempdir())
    )
    result = run_smoke(args.root, workspace)
    payload = result.to_dict()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CommandResult",
    "SmokeResult",
    "public_test_targets",
    "run_command",
    "run_smoke",
]
