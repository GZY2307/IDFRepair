'''
把案例相似度附加到已有有限候选，不创建补丁或改变候选来源。

attach_retrieval_evidence(): 按候选操作与案例特征的交集补充证据。
'''

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from idfrepair.domain.models import CandidateEvidence, RepairCandidate
from idfrepair.io.idf import canonical
from idfrepair.knowledge.case_retrieval import RetrievedCase, query_tokens


def _candidate_features(candidate: RepairCandidate) -> set[str]:
    '''提取候选 family、provider、有限操作、对象和字段语义。'''
    values = [candidate.family, candidate.provider]
    for operation in candidate.operations:
        values.extend(filter(None, (
            operation.kind.value,
            operation.object_type,
            operation.field_name,
        )))
    return set(query_tokens(values))


def attach_retrieval_evidence(
    candidate: RepairCandidate,
    cases: Iterable[RetrievedCase],
) -> RepairCandidate:
    '''只附加与当前有限候选特征相交的检索证据，并保留原 provenance。'''
    features = _candidate_features(candidate)
    matched = []
    for row in cases:
        declared_operations = {
            canonical(str(value)) for value in row.evidence.get("repair_operations", ())
        }
        candidate_operations = {canonical(operation.kind.value) for operation in candidate.operations}
        if declared_operations and not declared_operations.intersection(candidate_operations):
            continue
        case_values = []
        for key in ("family", "object_types", "field_roles", "repair_operations", "tags"):
            value = row.evidence.get(key, ())
            case_values.extend(value if isinstance(value, list) else (str(value),))
        candidate_matches = tuple(sorted(features & set(query_tokens(case_values))))
        if candidate_matches:
            matched.append((row, candidate_matches))
    if not matched:
        return candidate
    details = tuple({
        "case_id": row.case_id,
        "similarity": round(row.score, 12),
        "matching_features": tuple(sorted(set(row.matching_features) | set(candidate_matches))),
        "usage_status": row.usage_status,
    } for row, candidate_matches in matched)
    evidence = CandidateEvidence(
        kind="public_case_similarity",
        source="case_index",
        strength=max(row.score for row, _ in matched),
        details={
            "retrieved_cases": details,
            "retrieved_case_ids": tuple(row.case_id for row, _ in matched),
        },
    )
    return replace(
        candidate,
        evidence=candidate.evidence + (evidence,),
        metadata={
            **candidate.metadata,
            "retrieval": {
                "retrieved_case_ids": tuple(row.case_id for row, _ in matched),
                "cases": details,
                "usage_status": "used_for_ranking_and_evidence",
            },
        },
    )


__all__ = ["attach_retrieval_evidence"]
