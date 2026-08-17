"""Disk cache for deterministic EnergyPlus process results."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from idfrepair.domain.models import EnergyPlusResult, to_primitive


def cache_key(identity: Mapping[str, Any]) -> str:
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


class EnergyPlusCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.memory: dict[str, EnergyPlusResult] = {}

    def get(self, key: str) -> EnergyPlusResult | None:
        if key in self.memory:
            return replace(self.memory[key], cache_hit=True)
        if self.root is None:
            return None
        path = self.root / key[:2] / key / "result.json"
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = EnergyPlusResult(
            passed=bool(payload["passed"]),
            returncode=payload.get("returncode"),
            severe_count=int(payload.get("severe_count", 0)),
            fatal_count=int(payload.get("fatal_count", 0)),
            warning_count=int(payload.get("warning_count", 0)),
            diagnostics=str(payload.get("diagnostics", "")),
            rdd_text=str(payload.get("rdd_text", "")),
            process_failure=bool(payload.get("process_failure", False)),
            timed_out=bool(payload.get("timed_out", False)),
            stdout_sha256=payload.get("stdout_sha256"),
            stderr_sha256=payload.get("stderr_sha256"),
            err_sha256=payload.get("err_sha256"),
            input_sha256=payload.get("input_sha256"),
            runtime_identity=payload.get("runtime_identity", {}),
            command=tuple(payload.get("command", ())),
            cache_hit=True,
            wall_seconds=float(payload.get("wall_seconds", 0.0)),
            preprocessing_required=bool(payload.get("preprocessing_required", False)),
            preprocessing_used=bool(payload.get("preprocessing_used", False)),
            preprocessing_object_types=tuple(payload.get("preprocessing_object_types", ())),
            expanded_input_path=payload.get("expanded_input_path"),
            expanded_input_sha256=payload.get("expanded_input_sha256"),
        )
        self.memory[key] = replace(result, cache_hit=False)
        return result

    def put(self, key: str, result: EnergyPlusResult) -> None:
        if result.process_failure or result.timed_out:
            return
        self.memory[key] = replace(result, cache_hit=False)
        if self.root is None:
            return
        path = self.root / key[:2] / key / "result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(to_primitive(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
