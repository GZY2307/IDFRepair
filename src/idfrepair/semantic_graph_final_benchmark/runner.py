"""提供 one-shot runner 的不可覆盖持久化原语。

append_immutable_jsonl(): 追加唯一记录并拒绝覆盖已有 prediction。
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def append_immutable_jsonl(path: Path, row: dict[str, object]) -> None:
    record_id = str(row.get("record_id", ""))
    if not record_id:
        raise ValueError("missing_record_id")
    existing: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            prior_id = str(value.get("record_id", ""))
            if prior_id in existing:
                raise ValueError(f"duplicate_existing_record_id:{prior_id}")
            existing.add(prior_id)
    if record_id in existing:
        raise ValueError(f"immutable_record_exists:{record_id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(descriptor, payload.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["append_immutable_jsonl"]
