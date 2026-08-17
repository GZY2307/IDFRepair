"""按显式白名单构建无旧历史的公开发布 staging 树。

collect_public_paths(): 收集全部允许公开的普通文件。
build_staging(): 原子复制公开文件并生成确定性 content manifest。
main(): 提供命令行 staging 入口。
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Sequence

from tools.public_release.policy import (
    allowed_public_path,
    category_for,
    may_contain_public_path,
    sha256_file,
    verify_frozen_guard,
)


ROOT = Path(__file__).resolve().parents[2]
GENERATED_MANIFEST = PurePosixPath("reports/public_release/public_manifest.json")


def collect_public_paths(root: Path) -> tuple[PurePosixPath, ...]:
    """返回稳定排序的白名单普通文件，并拒绝白名单内符号链接。"""

    rows: list[PurePosixPath] = []
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        kept_names: list[str] = []
        for name in sorted(names):
            candidate = base / name
            relative = PurePosixPath(candidate.relative_to(root).as_posix())
            if not may_contain_public_path(relative):
                continue
            if candidate.is_symlink():
                raise ValueError(f"symlink_not_allowed:{relative.as_posix()}")
            kept_names.append(name)
        names[:] = kept_names
        for name in sorted(files):
            candidate = base / name
            relative = PurePosixPath(candidate.relative_to(root).as_posix())
            if relative == GENERATED_MANIFEST or not allowed_public_path(relative):
                continue
            if candidate.is_symlink():
                raise ValueError(f"symlink_not_allowed:{relative.as_posix()}")
            if candidate.is_file():
                rows.append(relative)
    return tuple(sorted(rows, key=PurePosixPath.as_posix))


def _snapshot_sha(members: list[dict[str, object]]) -> str:
    """从成员路径与内容哈希构造与绝对目录无关的树摘要。"""

    digest = sha256()
    for row in members:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _validate_destination(root: Path, destination: Path) -> None:
    """阻止把目的目录解析为源根或源根的祖先目录。"""

    source = root.resolve()
    target = destination.resolve()
    if target == source or source.is_relative_to(target):
        raise ValueError("unsafe_staging_destination")


def build_staging(
    root: Path,
    destination: Path,
    *,
    replace: bool = False,
    enforce_frozen_guard: bool = False,
) -> dict[str, object]:
    """复制公开白名单文件并原子发布一个确定性 staging 目录。"""

    root = root.resolve()
    destination = destination.resolve()
    _validate_destination(root, destination)
    if destination.exists() and not replace:
        raise FileExistsError(destination)
    if enforce_frozen_guard and (failures := verify_frozen_guard(root)):
        raise ValueError("frozen_guard_failed:" + "|".join(failures))

    paths = collect_public_paths(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-building-", dir=destination.parent)
    )
    try:
        members: list[dict[str, object]] = []
        for relative in paths:
            source = root / relative
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o644)
            members.append(
                {
                    "bytes": target.stat().st_size,
                    "category": category_for(relative),
                    "path": relative.as_posix(),
                    "sha256": sha256_file(target),
                }
            )
        manifest: dict[str, object] = {
            "schema_version": "idfrepair.public-manifest.v1",
            "member_count": len(members),
            "total_bytes": sum(int(row["bytes"]) for row in members),
            "snapshot_sha256": _snapshot_sha(members),
            "members": members,
            "policy": {
                "fresh_git_history_required": True,
                "private_oracle_included": False,
                "raw_terminal_model_included": False,
                "runtime_binary_or_weather_included": False,
            },
        }
        manifest_path = temporary / GENERATED_MANIFEST
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            if not destination.is_dir() or destination.is_symlink():
                raise ValueError("unsafe_existing_destination")
            shutil.rmtree(destination)
        temporary.rename(destination)
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--skip-frozen-guard",
        action="store_true",
        help="仅供独立测试 fixture 使用；真实项目 staging 不得设置。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行 staging 构建并打印紧凑 manifest 摘要。"""

    args = _parser().parse_args(argv)
    manifest = build_staging(
        args.root,
        args.destination,
        replace=args.replace,
        enforce_frozen_guard=not args.skip_frozen_guard,
    )
    print(
        json.dumps(
            {
                "destination": str(args.destination.resolve()),
                "member_count": manifest["member_count"],
                "snapshot_sha256": manifest["snapshot_sha256"],
                "total_bytes": manifest["total_bytes"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
