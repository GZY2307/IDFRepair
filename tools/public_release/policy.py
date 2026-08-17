"""定义 IDFRepair 公开发布的显式白名单和冻结保护策略。

sha256_file(): 计算文件的流式 SHA-256。
forbidden_reason(): 识别任何不得进入公开树的路径。
allowed_public_path(): 判断相对路径是否同时满足白名单与排除规则。
category_for(): 返回 manifest 使用的稳定文件类别。
verify_frozen_guard(): 复核冻结 Formal V2 源码和 Final 证据哈希。
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath


FROZEN_GUARD = PurePosixPath("reports/post_final/frozen_evidence_guard.json")

PUBLIC_EXACT = frozenset(
    {
        PurePosixPath(".gitignore"),
        PurePosixPath("CITATION.cff"),
        PurePosixPath("LICENSE"),
        PurePosixPath("README.md"),
        PurePosixPath("README_zh.md"),
        PurePosixPath("REPRODUCIBILITY.md"),
        PurePosixPath("pyproject.toml"),
        PurePosixPath("requirements.txt"),
        PurePosixPath("tools/analysis/post_final_native_diagnostics.py"),
        PurePosixPath("reports/post_final/final_evidence_status.md"),
        PurePosixPath("reports/post_final/frozen_evidence_guard.json"),
        PurePosixPath("reports/post_final/formal_final_reconciliation.json"),
        PurePosixPath("reports/post_final/mechanism_evidence.md"),
        PurePosixPath("reports/post_final/simulation_relevance.md"),
        PurePosixPath("reports/semantic_graph_final/main_results.json"),
        PurePosixPath("reports/semantic_graph_final/main_results.md"),
        PurePosixPath("reports/semantic_graph_final/final_status.json"),
        PurePosixPath("reports/semantic_graph_final/final_status.md"),
        PurePosixPath("reports/semantic_graph_final/greedy_comparison.md"),
        PurePosixPath("reports/semantic_graph_final/safety_results.md"),
        PurePosixPath("reports/semantic_graph_final/annual_energy_fidelity.md"),
        PurePosixPath("reports/semantic_graph_final/final_freeze.json"),
        PurePosixPath("reports/semantic_graph_final/source_cluster_results.md"),
        PurePosixPath("reports/semantic_graph_final/scored_records.jsonl"),
        PurePosixPath("reports/semantic_graph_final/scoring_freeze.json"),
        PurePosixPath("reports/semantic_graph_final/v2_certificates.jsonl"),
        PurePosixPath("reports/semantic_graph_final/v2_prediction_freeze.json"),
        PurePosixPath("reports/semantic_graph_final/v2_predictions.jsonl"),
        PurePosixPath("reports/semantic_graph_v22/method_freeze_candidate.json"),
        PurePosixPath("datasets/manifests/doe_prototype_inventory.csv"),
        PurePosixPath("datasets/manifests/doe_topology_clusters.csv"),
        PurePosixPath("datasets/manifests/doe_topology_profiles.json"),
        PurePosixPath("datasets/manifests/semantic_graph_final_membership.csv"),
        PurePosixPath("datasets/manifests/semantic_graph_final_operator_registry.json"),
        PurePosixPath("datasets/manifests/semantic_graph_final_source_qualification.csv"),
    }
)

PUBLIC_PREFIXES = (
    PurePosixPath(".github/workflows"),
    PurePosixPath("configs"),
    PurePosixPath("docs/method"),
    PurePosixPath("docs/reproducibility"),
    PurePosixPath("docs/research/occupancy"),
    PurePosixPath("docs/research/post_final"),
    PurePosixPath("docs/research/semantic_graph_v22"),
    PurePosixPath("examples/public"),
    PurePosixPath("reports/occupancy"),
    PurePosixPath("reports/public_release"),
    PurePosixPath("reports/publication"),
    PurePosixPath("scripts/occupancy"),
    PurePosixPath("src/idfrepair"),
    PurePosixPath("tests/occupancy"),
    PurePosixPath("tests/post_final"),
    PurePosixPath("tests/public_release"),
    PurePosixPath("tools/public_release"),
)

PUBLIC_SCRIPT_EXACT = frozenset(
    {
        PurePosixPath("scripts/public_reproduce_formal_v2.py"),
        PurePosixPath("scripts/run_airport_occupancy.py"),
    }
)

_SEMANTIC_CORE_TEST_NAMES = (
    "__init__.py",
    "compound_fixtures.py",
    "compound_relation_fixtures.py",
    "conftest.py",
    "test_air_to_air_hx_projection.py",
    "test_airpath_candidate_completeness.py",
    "test_build_ir.py",
    "test_candidates.py",
    "test_compound_projection_provenance.py",
    "test_compound_projection_version_binding.py",
    "test_conflicts.py",
    "test_constraint_semantics.py",
    "test_edits.py",
    "test_extensible_port_projection.py",
    "test_flow_transition_ir.py",
    "test_ir.py",
    "test_joint_solver.py",
    "test_merge_projection.py",
    "test_multi_circuit_projection.py",
    "test_oa_compound_candidate_completeness.py",
    "test_oa_context.py",
    "test_oa_equipment_order.py",
    "test_outdoorair_mixer_projection.py",
    "test_ports.py",
    "test_registry.py",
    "test_return_plenum_projection.py",
    "test_returnpath_compound_scan.py",
    "test_runtime.py",
    "test_scanner.py",
    "test_split_projection.py",
    "test_supply_plenum_projection.py",
    "test_supplypath_compound_scan.py",
    "test_unsupported_compound_abstention.py",
    "test_zone_mixer_projection.py",
    "test_zone_splitter_projection.py",
)

PUBLIC_TEST_EXACT = frozenset(
    PurePosixPath("tests/semantic_graph_v2") / name
    for name in _SEMANTIC_CORE_TEST_NAMES
)

FORBIDDEN_PARTS = frozenset(
    {
        ".git",
        ".idea",
        ".local",
        ".private",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "checkpoints",
        "deliverables",
        "node_modules",
        "paper",
        "runs",
        "tmp",
        "venv",
        "weather",
    }
)

FORBIDDEN_SUFFIXES = frozenset(
    {
        ".bundle",
        ".ckpt",
        ".docx",
        ".dylib",
        ".epw",
        ".exe",
        ".gguf",
        ".key",
        ".onnx",
        ".osm",
        ".pdf",
        ".pem",
        ".pt",
        ".pth",
        ".safetensors",
        ".so",
        ".tar",
        ".zip",
        ".zst",
    }
)


def sha256_file(path: Path) -> str:
    """以固定块大小计算文件 SHA-256，避免把大文件一次读入内存。"""

    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def forbidden_reason(path: PurePosixPath) -> str | None:
    """返回路径的首个公开排除原因；合法路径返回空值。"""

    if path.is_absolute() or ".." in path.parts or not path.parts:
        return "unsafe_relative_path"
    lowered = tuple(part.casefold() for part in path.parts)
    basename = lowered[-1]
    suffix = path.suffix.casefold()
    if set(lowered).intersection(FORBIDDEN_PARTS):
        return "forbidden_path_component"
    if lowered[0] == "models":
        return "private_model_asset_tree"
    if basename == "server_training.md":
        return "server_training_material"
    if basename == "deepseek.env" or basename == ".env" or basename.startswith(".env."):
        return "credential_file"
    if basename.startswith("eplusout."):
        return "raw_energyplus_output"
    if basename == "all-refs.bundle":
        return "git_bundle"
    if suffix in FORBIDDEN_SUFFIXES:
        return "forbidden_asset_type"
    if suffix == ".idf" and not path.is_relative_to(PurePosixPath("examples/public")):
        return "raw_or_unreviewed_idf"
    if any("private_oracle" in part or part == "oracles" for part in lowered):
        return "private_oracle"
    return None


def _under(path: PurePosixPath, prefix: PurePosixPath) -> bool:
    """判断路径是否位于指定公开前缀下且不是前缀目录本身。"""

    return path != prefix and path.is_relative_to(prefix)


def allowed_public_path(path: PurePosixPath) -> bool:
    """仅当路径在显式白名单内且不触发排除规则时返回真。"""

    if forbidden_reason(path) is not None:
        return False
    if path in PUBLIC_EXACT or path in PUBLIC_SCRIPT_EXACT or path in PUBLIC_TEST_EXACT:
        return True
    return any(_under(path, prefix) for prefix in PUBLIC_PREFIXES)


def may_contain_public_path(path: PurePosixPath) -> bool:
    """判断目录是否是 allowlist 前缀/文件的祖先或内部目录。"""

    if not path.parts or path.is_absolute() or ".." in path.parts:
        return False
    if forbidden_reason(path / "__public_probe__") is not None:
        return False
    exact = PUBLIC_EXACT | PUBLIC_SCRIPT_EXACT | PUBLIC_TEST_EXACT
    return any(
        prefix == path
        or prefix.is_relative_to(path)
        or path.is_relative_to(prefix)
        for prefix in PUBLIC_PREFIXES
    ) or any(member.is_relative_to(path) for member in exact)


def category_for(path: PurePosixPath) -> str:
    """将公开文件映射为 manifest 使用的稳定类别。"""

    top = path.parts[0]
    if top == "src":
        return "source"
    if top == "tests":
        return "test"
    if top in {"scripts", "tools"}:
        return "reproducibility_tool"
    if top == "reports":
        return "compact_evidence"
    if top == "datasets":
        return "manifest"
    if top == "examples":
        return "example"
    if top == "docs" or path.suffix.casefold() in {".md", ".cff"}:
        return "documentation"
    return "package_metadata"


def verify_frozen_guard(root: Path) -> tuple[str, ...]:
    """复核 guard 声明的全部冻结源码与 Final 文件哈希。"""

    guard_path = root / FROZEN_GUARD
    if not guard_path.is_file():
        return (f"missing_frozen_guard:{FROZEN_GUARD.as_posix()}",)
    try:
        guard = json.loads(guard_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (f"invalid_frozen_guard:{type(exc).__name__}",)
    failures: list[str] = []
    for section in ("protected_source_sha256", "protected_final_sha256"):
        values = guard.get(section)
        if not isinstance(values, dict):
            failures.append(f"missing_guard_section:{section}")
            continue
        for relative, expected in sorted(values.items()):
            path = root / str(relative)
            if not path.is_file():
                failures.append(f"missing_frozen_file:{relative}")
                continue
            actual = sha256_file(path)
            if actual != expected:
                failures.append(f"frozen_hash_mismatch:{relative}:{actual}")
    return tuple(failures)


__all__ = [
    "FROZEN_GUARD",
    "PUBLIC_EXACT",
    "PUBLIC_PREFIXES",
    "PUBLIC_SCRIPT_EXACT",
    "PUBLIC_TEST_EXACT",
    "allowed_public_path",
    "category_for",
    "forbidden_reason",
    "may_contain_public_path",
    "sha256_file",
    "verify_frozen_guard",
]
