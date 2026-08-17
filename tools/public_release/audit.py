"""扫描公开候选树及其 Git 历史中的敏感信息与不可发布资产。

AuditFinding: 保存不含原始敏感值的结构化审计结果。
audit_tree(): 扫描路径、symlink、secret、绝对路径和文件/树大小。
audit_git_history(): 扫描 fresh Git 全部可达历史 blob。
main(): 输出人类可读或 JSON 审计结果并以阻断状态退出。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Iterable, Sequence

from tools.public_release.policy import allowed_public_path, forbidden_reason


DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_TREE_BYTES = 50 * 1024 * 1024
MAX_TEXT_SCAN_BYTES = 4 * 1024 * 1024

_ASSIGNMENT = re.compile(
    r"(?im)\b("
    r"[A-Z][A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|CLIENT_SECRET|"
    r"SECRET_ACCESS_KEY|PASSWORD|PASSWD)"
    r"|API_KEY|ACCESS_TOKEN|AUTH_TOKEN|CLIENT_SECRET|SECRET|PASSWORD|PASSWD"
    r")\s*[:=]\s*[\"']?([^\s\"']{8,})"
)
_PROVIDER_TOKEN = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"
)
_LOCAL_PATH_PATTERNS = (
    ("mac_user_path", re.compile("/" + "Users" + r"/[^/\s]+(?:/[^\s`'\"]*)?")),
    ("linux_home_path", re.compile("/" + "home" + r"/[^/\s]+(?:/[^\s`'\"]*)?")),
    ("mac_private_path", re.compile("/" + "private" + r"/(?:tmp|var)(?:/[^\s`'\"]*)?")),
    ("windows_user_path", re.compile(r"[A-Za-z]:\\" + "Users" + r"\\[^\s]+")),
)


@dataclass(frozen=True, slots=True, order=True)
class AuditFinding:
    """保存一个可排序、不会回显原始 secret 的审计发现。"""

    code: str
    path: str
    detail: str
    blocking: bool = True

    def to_dict(self) -> dict[str, object]:
        """返回 JSON 可序列化记录。"""

        return asdict(self)


def _text_findings(path: str, text: str) -> tuple[AuditFinding, ...]:
    """扫描文本内容，结果只包含规则名而不包含匹配值。"""

    rows: set[AuditFinding] = set()
    for match in _ASSIGNMENT.finditer(text):
        name = match.group(1)
        value = match.group(2).casefold()
        if any(marker in value for marker in ("example", "placeholder", "your-")):
            continue
        rows.add(AuditFinding("SECRET", path, f"credential_assignment:{name}"))
    if _PROVIDER_TOKEN.search(text):
        rows.add(AuditFinding("SECRET", path, "provider_token_pattern"))
    if _PRIVATE_KEY.search(text):
        rows.add(AuditFinding("SECRET", path, "private_key_material"))
    for name, pattern in _LOCAL_PATH_PATTERNS:
        if pattern.search(text):
            rows.add(AuditFinding("ABSOLUTE_PATH", path, name))
    return tuple(sorted(rows))


def _decode_text(path: Path) -> str | None:
    """有界读取可能的 UTF-8 文本；二进制或超大文本只扫描前缀。"""

    with path.open("rb") as handle:
        payload = handle.read(MAX_TEXT_SCAN_BYTES + 1)
    payload = payload[:MAX_TEXT_SCAN_BYTES]
    if b"\0" in payload:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _iter_tree(root: Path) -> Iterable[tuple[PurePosixPath, Path, bool]]:
    """遍历公开树，跳过 `.git` 内容并显式暴露 symlink。"""

    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        kept_names: list[str] = []
        for name in sorted(names):
            candidate = base / name
            relative = PurePosixPath(candidate.relative_to(root).as_posix())
            if relative.parts and relative.parts[0] == ".git":
                continue
            if candidate.is_symlink():
                yield relative, candidate, True
            else:
                kept_names.append(name)
        names[:] = kept_names
        for name in sorted(files):
            candidate = base / name
            relative = PurePosixPath(candidate.relative_to(root).as_posix())
            if relative.parts and relative.parts[0] == ".git":
                continue
            yield relative, candidate, candidate.is_symlink()


def audit_tree(
    root: Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_tree_bytes: int = DEFAULT_MAX_TREE_BYTES,
) -> tuple[AuditFinding, ...]:
    """对公开候选目录执行 fail-closed 静态审计。"""

    root = root.resolve()
    if not root.is_dir():
        return (AuditFinding("MISSING_ROOT", ".", str(root)),)
    findings: set[AuditFinding] = set()
    total_bytes = 0
    for metadata in ("LICENSE", "CITATION.cff"):
        if not (root / metadata).is_file():
            findings.add(AuditFinding("MISSING_METADATA", metadata, "required_release_file"))
    for relative, path, is_symlink in _iter_tree(root):
        name = relative.as_posix()
        if is_symlink:
            findings.add(AuditFinding("SYMLINK", name, "symlink_not_allowed"))
            continue
        if not path.is_file():
            continue
        if reason := forbidden_reason(relative):
            findings.add(AuditFinding("FORBIDDEN_PATH", name, reason))
        elif not allowed_public_path(relative) and relative != PurePosixPath(
            "reports/public_release/public_manifest.json"
        ):
            findings.add(AuditFinding("UNLISTED_PATH", name, "not_in_public_allowlist"))
        size = path.stat().st_size
        total_bytes += size
        if size > max_file_bytes:
            findings.add(AuditFinding("OVERSIZED_FILE", name, f"bytes:{size}"))
        text = _decode_text(path)
        if text is not None:
            findings.update(_text_findings(name, text))
    if total_bytes > max_tree_bytes:
        findings.add(AuditFinding("OVERSIZED_TREE", ".", f"bytes:{total_bytes}"))
    return tuple(sorted(findings))


def _git(root: Path, *args: str, binary: bool = False) -> bytes | str:
    """在指定仓库执行只读 Git 命令并返回完整输出。"""

    result = subprocess.run(
        ("git", *args),
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
    )
    if result.returncode:
        error = result.stderr if isinstance(result.stderr, str) else result.stderr.decode(
            "utf-8", errors="replace"
        )
        raise RuntimeError(f"git_audit_failed:{' '.join(args)}:{error[-500:]}")
    return result.stdout


def audit_git_history(
    root: Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> tuple[AuditFinding, ...]:
    """扫描 fresh Git 中全部可达、具名 blob 的路径与敏感文本。"""

    root = root.resolve()
    if not (root / ".git").exists():
        return (AuditFinding("MISSING_GIT_HISTORY", ".", "git_repository_required"),)
    listing = str(_git(root, "rev-list", "--objects", "--all"))
    findings: set[AuditFinding] = set()
    visited: set[tuple[str, str]] = set()
    for line in listing.splitlines():
        if " " not in line:
            continue
        object_id, raw_path = line.split(" ", 1)
        relative = PurePosixPath(raw_path)
        key = (object_id, relative.as_posix())
        if key in visited:
            continue
        visited.add(key)
        object_type = str(_git(root, "cat-file", "-t", object_id)).strip()
        if object_type != "blob":
            continue
        name = relative.as_posix()
        if reason := forbidden_reason(relative):
            findings.add(
                AuditFinding("HISTORY_FORBIDDEN_PATH", name, f"{reason}:{object_id[:12]}")
            )
        size = int(str(_git(root, "cat-file", "-s", object_id)).strip())
        if size > max_file_bytes:
            findings.add(
                AuditFinding("HISTORY_OVERSIZED_BLOB", name, f"bytes:{size}:{object_id[:12]}")
            )
        if size > MAX_TEXT_SCAN_BYTES:
            continue
        payload = bytes(_git(root, "cat-file", "blob", object_id, binary=True))
        if b"\0" in payload:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for finding in _text_findings(name, text):
            code = "HISTORY_SECRET" if finding.code == "SECRET" else "HISTORY_ABSOLUTE_PATH"
            findings.add(AuditFinding(code, name, f"{finding.detail}:{object_id[:12]}"))
    return tuple(sorted(findings))


def _parser() -> argparse.ArgumentParser:
    """构造公开审计命令行参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--include-git-history", action="store_true")
    parser.add_argument("--json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行审计、可选写入 JSON，并按阻断发现设置退出码。"""

    args = _parser().parse_args(argv)
    findings = list(audit_tree(args.root))
    if args.include_git_history:
        findings.extend(audit_git_history(args.root))
    findings = sorted(set(findings))
    payload = {
        "schema_version": "idfrepair.public-release-audit.v1",
        "root_name": args.root.resolve().name,
        "blocking_count": sum(row.blocking for row in findings),
        "findings": [row.to_dict() for row in findings],
        "status": "PASSED" if not findings else "BLOCKED",
    }
    output = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["AuditFinding", "audit_git_history", "audit_tree"]
