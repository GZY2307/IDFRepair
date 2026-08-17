"""实现不查看 repair outcome 的确定性 Formal Final 样本选择。

mutation_identity(): 生成 canonical mutation identity。
select_membership(): 执行预注册 strata、关系域与 source cap 选择。
choose_final_size(): 在 inference 前执行 Final200/Final100 固定规模门。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable, Mapping, Sequence


RELATION_CLASSES = (
    "branch_path",
    "loop_connector",
    "zone_equipment",
    "air_path",
    "outdoor_air_path",
)
RANKING_NAMESPACE = "idfrepair-semantic-graph-formal-final-v1"


@dataclass(frozen=True, slots=True)
class FinalEdit:
    object_index: int
    field_index: int
    old_value: str
    new_value: str


@dataclass(frozen=True, slots=True)
class FinalSupportObject:
    source_object_index: int
    object_type: str
    object_name: str
    object_text: str


@dataclass(frozen=True, slots=True)
class Candidate:
    source_id: str
    source_path: str
    qualified_artifact: str
    weather_path: str
    topology_fingerprint: str
    prototype: str
    corpus: str
    operator_id: str
    relation_class: str
    stratum: str
    semantic_edit_cost: int
    opportunity_id: str
    scope_keys: tuple[str, ...]
    edits: tuple[FinalEdit, ...]
    inverse_edits: tuple[FinalEdit, ...]
    metadata: tuple[tuple[str, str], ...]
    supporting_objects: tuple[FinalSupportObject, ...]
    builder_family: str

    @property
    def mutation_key(self) -> str:
        return mutation_identity(self)


def mutation_identity(row: Candidate) -> str:
    payload = {
        "source_fingerprint": row.topology_fingerprint,
        "operator": row.operator_id,
        "scope_keys": list(row.scope_keys),
        "edits": [
            [
                edit.object_index,
                edit.field_index,
                edit.old_value,
                edit.new_value,
            ]
            for edit in row.edits
        ],
        "support": [
            [item.source_object_index, item.object_type, item.object_name]
            for item in row.supporting_objects
        ],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def stable_rank(row: Candidate) -> str:
    return sha256(
        f"{RANKING_NAMESPACE}|{row.mutation_key}".encode("utf-8")
    ).hexdigest()


def _deduplicate(rows: Iterable[Candidate]) -> list[Candidate]:
    unique: dict[str, Candidate] = {}
    for row in rows:
        key = row.mutation_key
        current = unique.get(key)
        if current is None or (
            stable_rank(row), row.opportunity_id
        ) < (
            stable_rank(current), current.opportunity_id
        ):
            unique[key] = row
    return list(unique.values())


class _Picker:
    def __init__(self, rows: Iterable[Candidate], source_cap: int) -> None:
        self.available = {row.mutation_key: row for row in _deduplicate(rows)}
        self.source_cap = source_cap
        self.source_counts: Counter[str] = Counter()
        self.operator_counts: Counter[str] = Counter()
        self.selected: list[Candidate] = []

    def pick(
        self,
        predicate,
        count: int,
        *,
        operator_cap: int | None = None,
        distinct_sources: bool = False,
    ) -> list[Candidate]:
        chosen: list[Candidate] = []
        local_sources: Counter[str] = Counter()
        while len(chosen) < count:
            eligible = [
                row for row in self.available.values()
                if predicate(row)
                and self.source_counts[row.source_id] < self.source_cap
                and (
                    operator_cap is None
                    or self.operator_counts[row.operator_id] < operator_cap
                )
                and (not distinct_sources or local_sources[row.source_id] == 0)
            ]
            if not eligible:
                break
            row = min(
                eligible,
                key=lambda item: (
                    self.source_counts[item.source_id],
                    local_sources[item.source_id],
                    self.operator_counts[item.operator_id],
                    stable_rank(item),
                    item.mutation_key,
                ),
            )
            self.available.pop(row.mutation_key)
            self.source_counts[row.source_id] += 1
            self.operator_counts[row.operator_id] += 1
            local_sources[row.source_id] += 1
            self.selected.append(row)
            chosen.append(row)
        return chosen


def _select_singles(picker: _Picker, final_size: int) -> None:
    target = 100 if final_size == 200 else 50
    base = 20 if final_size == 200 else 10
    minimum = 10 if final_size == 200 else 5
    maximum = 30 if final_size == 200 else 15
    selected_by_relation: Counter[str] = Counter()
    for relation in RELATION_CLASSES:
        rows = picker.pick(
            lambda row, value=relation: (
                row.stratum == "single" and row.relation_class == value
            ),
            base,
        )
        selected_by_relation[relation] += len(rows)
    while sum(selected_by_relation.values()) < target:
        progress = False
        for relation in RELATION_CLASSES:
            if (
                sum(selected_by_relation.values()) >= target
                or selected_by_relation[relation] >= maximum
            ):
                continue
            rows = picker.pick(
                lambda row, value=relation: (
                    row.stratum == "single" and row.relation_class == value
                ),
                1,
            )
            if rows:
                selected_by_relation[relation] += 1
                progress = True
        if not progress:
            break
    if sum(selected_by_relation.values()) != target:
        raise ValueError(
            f"single_quota_unavailable:{dict(selected_by_relation)}:{target}"
        )
    below = {
        relation: selected_by_relation[relation]
        for relation in RELATION_CLASSES
        if selected_by_relation[relation] < minimum
    }
    if below:
        raise ValueError(f"single_relation_minimum_unavailable:{below}")


def _select_connected(picker: _Picker, final_size: int) -> None:
    target = 20 if final_size == 200 else 10
    desired = (
        ("branch_path", 7 if final_size == 200 else 4),
        ("loop_connector", 7 if final_size == 200 else 3),
        ("zone_equipment", 6 if final_size == 200 else 3),
    )
    maximum = 10 if final_size == 200 else 5
    counts: Counter[str] = Counter()
    for relation, count in desired:
        rows = picker.pick(
            lambda row, value=relation: (
                row.stratum == "connected_double" and row.relation_class == value
            ),
            count,
        )
        counts[relation] += len(rows)
    while sum(counts.values()) < target:
        progress = False
        for relation, _ in desired:
            if sum(counts.values()) >= target or counts[relation] >= maximum:
                continue
            rows = picker.pick(
                lambda row, value=relation: (
                    row.stratum == "connected_double" and row.relation_class == value
                ),
                1,
            )
            if rows:
                counts[relation] += 1
                progress = True
        if not progress:
            break
    if sum(counts.values()) != target:
        raise ValueError(f"connected_quota_unavailable:{dict(counts)}:{target}")


def _select_safety(picker: _Picker, final_size: int) -> None:
    ambiguity_target = 20 if final_size == 200 else 10
    insufficient_target = 30 if final_size == 200 else 15
    total = ambiguity_target + insufficient_target
    before = len(picker.selected)
    picker.pick(
        lambda row: row.stratum == "ambiguity",
        ambiguity_target,
        operator_cap=25,
    )
    picker.pick(
        lambda row: row.stratum == "insufficient",
        insufficient_target,
        operator_cap=25,
    )
    while len(picker.selected) - before < total:
        progress = False
        for stratum in ("ambiguity", "insufficient"):
            if len(picker.selected) - before >= total:
                break
            rows = picker.pick(
                lambda row, value=stratum: row.stratum == value,
                1,
                operator_cap=25,
            )
            progress |= bool(rows)
        if not progress:
            break
    if len(picker.selected) - before != total:
        raise ValueError(
            f"safety_quota_unavailable:{len(picker.selected) - before}:{total}"
        )


def select_membership(
    candidates: Iterable[Candidate], final_size: int,
) -> list[Candidate]:
    if final_size not in {100, 200}:
        raise ValueError(f"unsupported_final_size:{final_size}")
    source_cap = 25 if final_size == 200 else 20
    picker = _Picker(candidates, source_cap)
    _select_singles(picker, final_size)
    _select_connected(picker, final_size)
    independent_target = 20 if final_size == 200 else 10
    independent = picker.pick(
        lambda row: row.stratum == "independent_double",
        independent_target,
    )
    if len(independent) != independent_target:
        raise ValueError(
            f"independent_quota_unavailable:{len(independent)}:{independent_target}"
        )
    _select_safety(picker, final_size)
    control_target = 10 if final_size == 200 else 5
    controls = picker.pick(
        lambda row: row.stratum == "control" and row.operator_id == "clean_control",
        control_target,
        distinct_sources=True,
    )
    if len(controls) != control_target:
        raise ValueError(
            f"clean_control_quota_unavailable:{len(controls)}:{control_target}"
        )
    if len(picker.selected) != final_size:
        raise ValueError(
            f"final_membership_count_mismatch:{len(picker.selected)}:{final_size}"
        )
    if max(picker.source_counts.values(), default=0) > source_cap:
        raise ValueError("source_concentration_cap_exceeded")
    keys = [row.mutation_key for row in picker.selected]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_mutation_identity")
    return list(picker.selected)


def _gate_summary(
    candidates: Sequence[Candidate],
    qualified: Sequence[Mapping[str, str]],
    final_size: int,
) -> dict[str, object]:
    passed = [row for row in qualified if row.get("qualification_status") == "PASSED"]
    fingerprints = {row.get("topology_fingerprint", "") for row in passed}
    prototypes = {row.get("prototype", "") for row in passed}
    corpora = {row.get("corpus", "") for row in passed}
    fingerprint_minimum = 10 if final_size == 200 else 6
    prototype_minimum = 8 if final_size == 200 else 5
    candidate_rows = [row for row in candidates if row.topology_fingerprint in fingerprints]
    relation_opportunities = {
        relation: sum(
            row.stratum == "single" and row.relation_class == relation
            for row in candidate_rows
        )
        for relation in RELATION_CLASSES
    }
    reasons = []
    if len(fingerprints) < fingerprint_minimum:
        reasons.append("qualified_fingerprint_gate")
    if len(prototypes) < prototype_minimum:
        reasons.append("qualified_prototype_gate")
    if len(corpora) < 2:
        reasons.append("qualified_corpus_gate")
    if any(value == 0 for value in relation_opportunities.values()):
        reasons.append("missing_relation_opportunity")
    selection_error = ""
    if not reasons:
        try:
            select_membership(candidate_rows, final_size)
        except ValueError as exc:
            selection_error = str(exc)
            reasons.append("candidate_pool_gate")
    return {
        "final_size": final_size,
        "passed": not reasons,
        "qualified_fingerprint_count": len(fingerprints),
        "qualified_prototype_count": len(prototypes),
        "qualified_corpus_count": len(corpora),
        "candidate_count": len(candidate_rows),
        "relation_opportunities": relation_opportunities,
        "reasons": reasons,
        "selection_error": selection_error,
    }


def choose_final_size(
    candidates: Sequence[Candidate],
    qualified: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    final200 = _gate_summary(candidates, qualified, 200)
    final100 = _gate_summary(candidates, qualified, 100)
    status = (
        "FINAL200" if final200["passed"]
        else "FINAL100" if final100["passed"]
        else "FINAL_NOT_RUN_INSUFFICIENT_SEALED_EVIDENCE"
    )
    return {
        "schema_version": "idfrepair.semantic-graph-formal-size-decision.v1",
        "status": status,
        "selected_size": 200 if status == "FINAL200" else 100 if status == "FINAL100" else 0,
        "inference_executed": False,
        "final200_gate": final200,
        "final100_gate": final100,
    }


__all__ = [
    "Candidate",
    "FinalEdit",
    "FinalSupportObject",
    "RANKING_NAMESPACE",
    "RELATION_CLASSES",
    "choose_final_size",
    "mutation_identity",
    "select_membership",
    "stable_rank",
]
