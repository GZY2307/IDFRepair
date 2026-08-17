"""管理 Formal Final 哈希封印、import 边界与 runtime 泄漏防护。

collect_file_hashes(): 生成稳定的文件哈希映射。
verify_file_hashes(): 验证冻结文件未发生漂移。
assert_builder_independence(): 拒绝 builder 依赖 production repair semantics。
assert_runtime_manifest(): 验证 runtime manifest 仅含 opaque 必需字段。
"""

from __future__ import annotations

import ast
import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence


RUNTIME_FIELDS = (
    "record_id",
    "faulty_artifact",
    "energyplus_version",
    "idd_artifact",
)


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_identity(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def collect_file_hashes(
    root: Path, paths: Iterable[Path],
) -> dict[str, str]:
    rows: dict[str, str] = {}
    for raw in sorted({path.resolve() for path in paths}, key=str):
        if not raw.is_file():
            raise FileNotFoundError(f"sealed_file_missing:{raw}")
        try:
            key = raw.relative_to(root.resolve()).as_posix()
        except ValueError:
            key = str(raw)
        rows[key] = sha256_file(raw)
    return rows


def verify_file_hashes(root: Path, expected: Mapping[str, str]) -> None:
    for name, identity in sorted(expected.items()):
        path = Path(name)
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            raise ValueError(f"sealed_file_missing:{name}")
        actual = sha256_file(path)
        if actual != identity:
            raise ValueError(
                f"sealed_file_hash_mismatch:{name}:{identity}:{actual}"
            )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rows: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            rows.add(node.module)
    return rows


def assert_builder_independence(paths: Iterable[Path]) -> None:
    forbidden = (
        "idfrepair.semantic_graph_v2.build_ir",
        "idfrepair.semantic_graph_v2.candidates",
        "idfrepair.semantic_graph_v2.edits",
        "idfrepair.semantic_graph_v2.flow",
        "idfrepair.semantic_graph_v2.ir",
        "idfrepair.semantic_graph_v2.ports",
        "idfrepair.semantic_graph_v2.registry",
        "idfrepair.semantic_graph_v2.runtime",
        "idfrepair.semantic_graph_v2.scan",
        "idfrepair.semantic_graph_v2.solver",
    )
    forbidden_calls = {"repair_model", "scan_model", "generate_candidates"}
    for path in paths:
        imports = _imports(path)
        bad = sorted(
            name for name in imports
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
        )
        if bad:
            raise ValueError(f"forbidden_builder_import:{path}:{'|'.join(bad)}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        names = sorted(called & forbidden_calls)
        if names:
            raise ValueError(f"forbidden_builder_call:{path}:{'|'.join(names)}")


def _duplicate(values: Sequence[str]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


def assert_runtime_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        rows = list(reader)
    if fields != RUNTIME_FIELDS:
        raise ValueError(
            "runtime_manifest_fields:"
            f"expected={','.join(RUNTIME_FIELDS)}:actual={','.join(fields)}"
        )
    record_ids = [row.get("record_id", "") for row in rows]
    if any(not value for value in record_ids):
        raise ValueError("missing_runtime_record_id")
    duplicate = _duplicate(record_ids)
    if duplicate is not None:
        raise ValueError(f"duplicate_runtime_record_id:{duplicate}")
    forbidden_tokens = (
        "branch", "loop", "zone", "airpath", "outdoor", "operator",
        "oracle", "clean", "family", "locator", "prototype",
    )
    for row in rows:
        filename = Path(row["faulty_artifact"]).name.casefold()
        if any(token in filename for token in forbidden_tokens):
            raise ValueError(
                f"runtime_artifact_name_leakage:{row['record_id']}:{filename}"
            )
    return rows


def unique_jsonl(path: Path, *, label: str) -> list[dict[str, object]]:
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [str(row.get("record_id", "")) for row in rows]
    if any(not value for value in ids):
        raise ValueError(f"missing_{label}_record_id")
    duplicate = _duplicate(ids)
    if duplicate is not None:
        raise ValueError(f"duplicate_{label}_record_id:{duplicate}")
    return rows


__all__ = [
    "RUNTIME_FIELDS",
    "assert_builder_independence",
    "assert_runtime_manifest",
    "collect_file_hashes",
    "json_identity",
    "sha256_file",
    "unique_jsonl",
    "verify_file_hashes",
]
