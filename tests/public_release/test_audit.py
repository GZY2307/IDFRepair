"""验证公开树与 fresh Git 历史的安全审计。

test_audit_tree_reports_secret_absolute_path_and_large_file(): 验证多类阻断。
test_audit_tree_never_echoes_secret_value(): 验证报告不会泄露检测值。
test_audit_tree_allows_domain_keys_and_parser_tokens(): 验证业务键名不被误判。
test_audit_tree_rejects_symlink(): 验证任何符号链接均失败。
test_audit_git_history_finds_deleted_sensitive_file(): 验证历史对象扫描。
"""

from __future__ import annotations

from pathlib import Path
import subprocess

from tools.public_release.audit import audit_git_history, audit_tree


def _write(path: Path, value: str) -> None:
    """创建父目录并写入测试文本。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    """在临时仓库执行无交互 Git 命令。"""

    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def test_audit_tree_reports_secret_absolute_path_and_large_file(
    tmp_path: Path,
) -> None:
    """同一公开候选中的凭据、绝对路径和超限文件必须同时可见。"""

    _write(tmp_path / "LICENSE", "MIT\n")
    _write(tmp_path / "CITATION.cff", "cff-version: 1.2.0\n")
    _write(tmp_path / "README.md", "local=/" + "Users/dy/private\n")
    _write(
        tmp_path / ".env",
        "OPENAI_API_KEY=" + "sk-" + "live-secretvalue123456789\n",
    )
    (tmp_path / "large.bin").write_bytes(b"x" * 1025)

    findings = audit_tree(tmp_path, max_file_bytes=1024)
    codes = {finding.code for finding in findings}

    assert {"FORBIDDEN_PATH", "SECRET", "ABSOLUTE_PATH", "OVERSIZED_FILE"} <= codes


def test_audit_tree_never_echoes_secret_value(tmp_path: Path) -> None:
    """审计只返回规则和位置，不能复制原始 token。"""

    secret = "sk-" + "live-secretvalue123456789"
    _write(tmp_path / "LICENSE", "MIT\n")
    _write(tmp_path / "CITATION.cff", "cff-version: 1.2.0\n")
    credential_name = "OPENAI" + "_API_KEY"
    _write(tmp_path / "README.md", credential_name + "=" + secret + "\n")

    serialized = "\n".join(finding.detail for finding in audit_tree(tmp_path))

    assert secret not in serialized
    assert "credential_assignment:OPENAI_API_KEY" in serialized


def test_audit_tree_allows_domain_keys_and_parser_tokens(tmp_path: Path) -> None:
    """普通查找键和解析 token 不属于凭据，公开源码不应被误阻断。"""

    _write(tmp_path / "LICENSE", "MIT\n")
    _write(tmp_path / "CITATION.cff", "cff-version: 1.2.0\n")
    _write(
        tmp_path / "README.md",
        "zone_key = normalized_name\nstatusToken = parser.next()\nerror_token = None\n",
    )

    assert "SECRET" not in {finding.code for finding in audit_tree(tmp_path)}


def test_audit_tree_rejects_symlink(tmp_path: Path) -> None:
    """公开树中的符号链接必须被显式报告。"""

    _write(tmp_path / "LICENSE", "MIT\n")
    _write(tmp_path / "CITATION.cff", "cff-version: 1.2.0\n")
    _write(tmp_path / "README.md", "# Safe\n")
    outside = tmp_path.parent / "outside-release-audit.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/link.py").symlink_to(outside)

    assert "SYMLINK" in {finding.code for finding in audit_tree(tmp_path)}


def test_audit_git_history_finds_deleted_sensitive_file(tmp_path: Path) -> None:
    """即使工作树已删除 `.env`，历史 blob 仍必须阻断公开发布。"""

    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Release Test")
    _git(tmp_path, "config", "user.email", "release-test@example.invalid")
    _write(
        tmp_path / ".env",
        "TOKEN=" + "ghp_" + "abcdefghijklmnopqrstuvwxyz123456\n",
    )
    _git(tmp_path, "add", ".env")
    _git(tmp_path, "commit", "-m", "add sensitive file")
    (tmp_path / ".env").unlink()
    _git(tmp_path, "add", "-u")
    _git(tmp_path, "commit", "-m", "remove sensitive file")

    codes = {finding.code for finding in audit_git_history(tmp_path)}

    assert "HISTORY_FORBIDDEN_PATH" in codes
    assert "HISTORY_SECRET" in codes
