"""验证公开发布路径策略与冻结证据保护。

test_verify_frozen_guard_accepts_current_snapshot(): 验证当前冻结源代码与 Final 证据哈希。
test_forbidden_reason_rejects_private_or_raw_assets(): 验证敏感和原始资产被拒绝。
test_allowlist_is_explicit_and_never_admits_private_models(): 验证公开树只采用显式白名单。
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import subprocess

import pytest

from scripts.public_reproduce_formal_v2 import build_summary
from tools.public_release.policy import (
    PUBLIC_EXACT,
    allowed_public_path,
    forbidden_reason,
    verify_frozen_guard,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_verify_frozen_guard_accepts_current_snapshot() -> None:
    """冻结快照中受保护的源码与 Final 证据必须逐字节匹配。"""

    assert verify_frozen_guard(PROJECT_ROOT) == ()


def test_every_frozen_guard_member_is_publicly_allowlisted() -> None:
    """公开快照必须携带 guard 校验所需的全部只读冻结证据。"""

    guard = json.loads(
        (PROJECT_ROOT / "reports/post_final/frozen_evidence_guard.json").read_text(
            encoding="utf-8"
        )
    )
    guarded = set(guard["protected_source_sha256"]) | set(
        guard["protected_final_sha256"]
    )

    assert all(allowed_public_path(PurePosixPath(path)) for path in guarded)


def test_frozen_guard_members_are_not_silently_git_ignored() -> None:
    """构建树中的冻结文件必须能被普通 `git add --all` 纳入 fresh history。"""

    guard = json.loads(
        (PROJECT_ROOT / "reports/post_final/frozen_evidence_guard.json").read_text(
            encoding="utf-8"
        )
    )
    guarded = (
        set(guard["protected_source_sha256"])
        | set(guard["protected_final_sha256"])
    )
    reviewed_manifests = {
        path.as_posix() for path in PUBLIC_EXACT if path.parts[0] == "datasets"
    }
    guarded = sorted(guarded | reviewed_manifests)
    ignored: list[str] = []
    for path in guarded:
        result = subprocess.run(
            ("git", "check-ignore", "--quiet", "--no-index", path),
            cwd=PROJECT_ROOT,
            check=False,
        )
        if result.returncode == 0:
            ignored.append(path)
        elif result.returncode != 1:
            raise AssertionError(f"git_check_ignore_failed:{path}:{result.returncode}")

    assert ignored == []


def test_reviewed_csv_manifests_are_byte_preserved_git_evidence() -> None:
    """冻结 CSV 禁止文本转换，并从空白 diff 中排除以保留原始哈希。"""

    assert allowed_public_path(PurePosixPath(".gitattributes"))
    reviewed_csv = sorted(
        path.as_posix()
        for path in PUBLIC_EXACT
        if path.parts[0] == "datasets" and path.suffix == ".csv"
    )
    for path in reviewed_csv:
        result = subprocess.run(
            ("git", "check-attr", "text", "diff", "--", path),
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert f"{path}: text: unset" in result.stdout
        assert f"{path}: diff: unset" in result.stdout


@pytest.mark.parametrize(
    "name",
    [
        "SERVER_TRAINING.md",
        ".env",
        "deepseek.env",
        "weather/site.epw",
        "paper/source.pdf",
        "runs/a/eplusout.err",
        "models/terminal.osm",
        "src/idfrepair.egg-info/PKG-INFO",
        ".private/final_oracle.json",
        "release/all-refs.bundle",
    ],
)
def test_forbidden_reason_rejects_private_or_raw_assets(name: str) -> None:
    """任何服务器、凭据、原始模型/天气、运行或 bundle 路径均应拒绝。"""

    assert forbidden_reason(PurePosixPath(name)) is not None


def test_allowlist_is_explicit_and_never_admits_private_models() -> None:
    """合法源码可公开，但两个原始 OSM 与任意未列入路径不可公开。"""

    assert allowed_public_path(PurePosixPath("src/idfrepair/io/idf.py"))
    assert allowed_public_path(PurePosixPath("src/idfrepair/models/integration.py"))
    assert allowed_public_path(PurePosixPath("README.md"))
    assert not allowed_public_path(
        PurePosixPath("models/overall_model0116_complete.osm")
    )
    assert not allowed_public_path(PurePosixPath("notes/unreviewed.txt"))
    assert not allowed_public_path(
        PurePosixPath("tests/compatibility/test_baseline_compatibility.py")
    )
    assert allowed_public_path(
        PurePosixPath("tests/semantic_graph_v2/test_runtime.py")
    )
    assert allowed_public_path(
        PurePosixPath("reports/occupancy_v2/paper_admission.md")
    )
    assert allowed_public_path(
        PurePosixPath("scripts/run_airport_occupancy_room_aware.py")
    )
    assert allowed_public_path(
        PurePosixPath("tests/occupancy_room_aware/test_provenance.py")
    )
    assert not allowed_public_path(
        PurePosixPath("derived/occupancy_room_aware/baseline_r/derived.osm")
    )
    assert not allowed_public_path(
        PurePosixPath("tests/semantic_graph_v2/test_v2_runner.py")
    )


def test_readmes_use_formal_v2_headline_and_not_legacy_final400() -> None:
    """中英文首屏必须使用冻结 Formal V2 指标而非旧 Final400 主线。"""

    english = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (PROJECT_ROOT / "README_zh.md").read_text(encoding="utf-8")
    for text in (english, chinese):
        assert "Formal V2 Final100" in text
        assert "81/100" in text
        assert "78/95" in text
        assert "66/66" in text
        assert "66/95" in text
        assert "Final400 outcome" not in text
        assert "/" + "Users/dy/" not in text


def test_release_license_citation_and_reproduction_docs_are_public_safe() -> None:
    """许可证、引用和复现说明必须存在且不依赖本机路径。"""

    for relative in (
        "LICENSE",
        "CITATION.cff",
        "docs/reproducibility/public_release.md",
    ):
        path = PROJECT_ROOT / relative
        assert path.is_file(), relative
        text = path.read_text(encoding="utf-8")
        assert "/" + "Users/dy/" not in text
        assert "private oracle" not in text.casefold()


def test_public_metric_reproduction_reads_frozen_results_without_inference() -> None:
    """公开指标入口只能汇总冻结 JSON，不得生成新 prediction 或 score。"""

    summary = build_summary(PROJECT_ROOT)

    assert summary["formal_v2_final100"] == "81/100"
    assert summary["support"] == "78/95"
    assert summary["conditional_auto_repair"] == "66/66"
    assert summary["overall_auto_repair"] == "66/95"
    assert summary["method_modified_after_final"] is False
