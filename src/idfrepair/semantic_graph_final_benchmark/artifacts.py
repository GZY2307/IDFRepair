"""提供 Formal Final 各阶段共享的稳定 artifact 序列化。

write_json()/write_jsonl()/write_csv(): 原子写入结构化证据。
candidate_to_dict()/candidate_from_dict(): 往返序列化独立 candidate。
"""

from __future__ import annotations

import csv
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable, Mapping, Sequence

from .builder import Candidate, FinalEdit, FinalSupportObject


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, value: object) -> None:
    write_text_atomic(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    text = "".join(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    )
    write_text_atomic(path, text)


def write_csv(
    path: Path, rows: Sequence[Mapping[str, object]], fields: Sequence[str] | None = None,
) -> None:
    if fields is None:
        fields = tuple(dict.fromkeys(
            key for row in rows for key in row
        ))
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def candidate_to_dict(row: Candidate) -> dict[str, object]:
    return {
        **asdict(row),
        "mutation_key": row.mutation_key,
        "edits": [asdict(edit) for edit in row.edits],
        "inverse_edits": [asdict(edit) for edit in row.inverse_edits],
        "metadata": dict(row.metadata),
        "scope_keys": list(row.scope_keys),
        "supporting_objects": [asdict(value) for value in row.supporting_objects],
    }


def candidate_from_dict(value: Mapping[str, object]) -> Candidate:
    metadata_value = value.get("metadata", {})
    if not isinstance(metadata_value, Mapping):
        raise ValueError("candidate_metadata_not_mapping")
    return Candidate(
        source_id=str(value["source_id"]),
        source_path=str(value["source_path"]),
        qualified_artifact=str(value["qualified_artifact"]),
        weather_path=str(value.get("weather_path", "")),
        topology_fingerprint=str(value["topology_fingerprint"]),
        prototype=str(value.get("prototype", "")),
        corpus=str(value.get("corpus", "")),
        operator_id=str(value["operator_id"]),
        relation_class=str(value["relation_class"]),
        stratum=str(value["stratum"]),
        semantic_edit_cost=int(value["semantic_edit_cost"]),
        opportunity_id=str(value["opportunity_id"]),
        scope_keys=tuple(str(item) for item in value.get("scope_keys", [])),  # type: ignore[arg-type]
        edits=tuple(
            FinalEdit(
                int(item["object_index"]), int(item["field_index"]),
                str(item["old_value"]), str(item["new_value"]),
            )
            for item in value.get("edits", [])  # type: ignore[union-attr]
        ),
        inverse_edits=tuple(
            FinalEdit(
                int(item["object_index"]), int(item["field_index"]),
                str(item["old_value"]), str(item["new_value"]),
            )
            for item in value.get("inverse_edits", [])  # type: ignore[union-attr]
        ),
        metadata=tuple(
            (str(key), str(item)) for key, item in sorted(metadata_value.items())
        ),
        supporting_objects=tuple(
            FinalSupportObject(
                int(item["source_object_index"]), str(item["object_type"]),
                str(item["object_name"]), str(item["object_text"]),
            )
            for item in value.get("supporting_objects", [])  # type: ignore[union-attr]
        ),
        builder_family=str(value["builder_family"]),
    )


__all__ = [
    "candidate_from_dict",
    "candidate_to_dict",
    "relative_path",
    "write_csv",
    "write_json",
    "write_jsonl",
    "write_text_atomic",
]
