"""Runtime/oracle boundary records for the V2.2 Air/OA extension set."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


RUNTIME_FIELDS = (
    "record_id", "faulty_artifact", "energyplus_version", "idd_artifact",
)


@dataclass(frozen=True, slots=True)
class MutationFieldEdit:
    object_index: int
    field_index: int
    old_value: str
    new_value: str


@dataclass(frozen=True, slots=True)
class ExtensionOpportunity:
    opportunity_id: str
    operator_id: str
    relation_class: str
    stratum: str
    semantic_edit_cost: int
    scope_keys: tuple[str, ...]
    edits: tuple[MutationFieldEdit, ...]
    inverse_edits: tuple[MutationFieldEdit, ...]
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeRecord:
    record_id: str
    faulty_artifact: str
    energyplus_version: str
    idd_artifact: str


@dataclass(frozen=True, slots=True)
class OracleRecord:
    record_id: str
    source_path: str
    clean_artifact: str
    topology_fingerprint: str
    operator_id: str
    relation_class: str
    stratum: str
    semantic_edit_cost: int
    mutation_edits: tuple[MutationFieldEdit, ...]
    oracle_inverse_edits: tuple[MutationFieldEdit, ...]
    scope_keys: tuple[str, ...]
    metadata: tuple[tuple[str, str], ...] = ()


def write_runtime_manifest(path: Path, rows: Iterable[RuntimeRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUNTIME_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_oracle_manifest(path: Path, rows: Iterable[OracleRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = asdict(row)
            payload["mutation_edits"] = [asdict(edit) for edit in row.mutation_edits]
            payload["oracle_inverse_edits"] = [
                asdict(edit) for edit in row.oracle_inverse_edits
            ]
            payload["scope_keys"] = list(row.scope_keys)
            payload["metadata"] = dict(row.metadata)
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
