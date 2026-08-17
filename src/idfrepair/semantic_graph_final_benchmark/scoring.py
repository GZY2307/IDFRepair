"""计算 Formal Final contract 指标与 source-cluster bootstrap 统计。

score_prediction(): 依据冻结 oracle 判定单条 contract 与安全结果。
bootstrap_cluster_rate(): 以 topology fingerprint 为抽样簇计算置信区间。
"""

from __future__ import annotations

from collections import defaultdict
import random
from typing import Mapping, Sequence


def _signature(value: object) -> tuple[tuple[object, ...], ...]:
    if not isinstance(value, list):
        return ()
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        rows.append((
            item.get("object_index"),
            item.get("field_index"),
            str(item.get("old_value", "")).strip().casefold(),
            str(item.get("new_value", "")).strip().casefold(),
        ))
    return tuple(sorted(rows))


def score_prediction(
    prediction: Mapping[str, object],
    oracle: Mapping[str, object],
    *,
    semantic_equivalent: bool | None = None,
    non_target_preserved: bool | None = None,
) -> dict[str, object]:
    stratum = str(oracle.get("stratum", ""))
    expected = _signature(oracle.get("oracle_inverse_edits", []))
    selected = _signature(prediction.get("selected_field_edits", []))
    exact = selected == expected
    semantic = exact if semantic_equivalent is None else semantic_equivalent
    status = str(prediction.get("status", "PROCESS_FAILURE"))
    static = prediction.get("static_validation", {})
    static_passed = bool(
        isinstance(static, Mapping) and static.get("passed") is True
    )
    process_failure = status == "PROCESS_FAILURE" or bool(
        prediction.get("process_failure")
    )
    safety = stratum in {"ambiguity", "insufficient"}
    control = stratum == "control"
    input_preserved = bool(prediction.get("input_preserved", not selected))
    abstention = bool(
        safety
        and status in {"NEEDS_INPUT", "UNSUPPORTED", "SEARCH_EXHAUSTED"}
        and not selected
        and input_preserved
        and static_passed
    )
    clean_correct = bool(
        control
        and status == "VALID"
        and not selected
        and input_preserved
        and static_passed
        and int(prediction.get("remaining_hard_violation_count", 0) or 0) == 0
    )
    auto_correct = bool(
        not safety
        and not control
        and status == "REPAIRED_COMPLETE"
        and static_passed
        and int(prediction.get("remaining_hard_violation_count", 0) or 0) == 0
        and semantic
        and (non_target_preserved is not False)
    )
    contract_correct = abstention or clean_correct or auto_correct
    unsafe_commit = bool(safety and selected)
    wrong_modification = bool(
        selected and not auto_correct and not exact
    )
    partial_as_full = bool(
        status == "REPAIRED_COMPLETE"
        and not auto_correct
        and not process_failure
    )
    return {
        "record_id": str(oracle.get("record_id", prediction.get("record_id", ""))),
        "contract_correct": contract_correct,
        "automatic_repair_correct": auto_correct,
        "correct_abstention": abstention,
        "clean_control_correct": clean_correct,
        "exact_field_edits": exact,
        "semantic_equivalent": semantic,
        "non_target_preserved": non_target_preserved is not False,
        "wrong_modification": wrong_modification,
        "unsafe_commit": unsafe_commit,
        "partial_as_full": partial_as_full,
        "process_failure": process_failure,
        "input_preserved": input_preserved,
    }


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("empty_quantile")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(probability * len(ordered))))
    return ordered[index]


def bootstrap_cluster_rate(
    rows: Sequence[Mapping[str, object]],
    metric: str,
    *,
    cluster_key: str = "topology_fingerprint",
    replicates: int = 10_000,
    seed: int = 2201,
) -> dict[str, object]:
    if replicates <= 0:
        raise ValueError("bootstrap_replicates_must_be_positive")
    groups: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        cluster = str(row.get(cluster_key, ""))
        if not cluster:
            raise ValueError(f"bootstrap_cluster_missing:{cluster_key}")
        groups[cluster].append(bool(row.get(metric)))
    if not groups:
        raise ValueError("bootstrap_rows_empty")
    keys = sorted(groups)
    estimate = sum(value for values in groups.values() for value in values) / sum(
        len(values) for values in groups.values()
    )
    rng = random.Random(seed)
    samples = []
    for _ in range(replicates):
        selected = [rng.choice(keys) for _ in keys]
        values = [value for key in selected for value in groups[key]]
        samples.append(sum(values) / len(values))
    return {
        "estimate": estimate,
        "lower_95": _quantile(samples, 0.025),
        "upper_95": _quantile(samples, 0.975),
        "replicates": replicates,
        "seed": seed,
        "cluster_count": len(keys),
    }


__all__ = ["bootstrap_cluster_rate", "score_prediction"]
