'''
对公开案例的非答案元数据执行只读语义检索。

query_tokens(): 将错误、对象和字段语义转换为稳定检索特征。
CaseIndex.retrieve(): 返回相似度、匹配特征和使用状态，不返回修复正文。
'''

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


ALLOWED_USAGE = frozenset({
    "development-exposed",
    "evaluation-replay",
    "held-out",
    "demo-only",
})
DEFAULT_RETRIEVAL_USAGE = frozenset({"development-exposed", "demo-only"})
_WORDS = re.compile(r"[a-z0-9:_.+-]+", re.I)
_SAFE_KEYS = frozenset({
    "case_id", "usage_status", "error_signatures", "object_types", "field_roles",
    "repair_operations", "family", "version", "source_url", "source_commit",
    "license", "provenance", "tags",
})


def query_tokens(values: Iterable[str]) -> tuple[str, ...]:
    '''将语义文本拆为去重的大小写无关特征，同时保留完整短语。'''
    tokens: set[str] = set()
    for value in values:
        text = str(value).casefold().strip()
        if not text:
            continue
        tokens.add(text)
        tokens.update(match.group(0) for match in _WORDS.finditer(text))
    return tuple(sorted(tokens))


@dataclass(frozen=True, slots=True)
class RetrievedCase:
    '''封装不含 gold、fixed 或 oracle 内容的检索证据。'''

    case_id: str
    score: float
    evidence: Mapping[str, Any]
    matching_features: tuple[str, ...] = ()
    usage_status: str = "development-exposed"


class CaseIndex:
    '''保存公开案例的元数据索引，检索结果不能直接形成补丁。'''

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        values = []
        for raw in rows:
            row = {key: raw[key] for key in _SAFE_KEYS if key in raw}
            if row.get("usage_status") not in ALLOWED_USAGE:
                raise ValueError("invalid_case_usage_status")
            if not row.get("case_id"):
                raise ValueError("case_id_required")
            values.append(row)
        self.rows = tuple(values)

    @classmethod
    def load(cls, path: Path) -> "CaseIndex":
        '''从 JSON 列表或含 cases 的对象读取案例索引。'''
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("cases", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("case_index_must_contain_list")
        return cls(rows)

    def retrieve(
        self,
        *,
        error_tokens: Iterable[str],
        object_types: Iterable[str] = (),
        field_roles: Iterable[str] = (),
        limit: int = 5,
        allowed_usage: Iterable[str] = DEFAULT_RETRIEVAL_USAGE,
    ) -> tuple[RetrievedCase, ...]:
        '''
        计算查询与案例元数据的 Jaccard 相似度，并保留逐项匹配特征。

        evaluation-replay 和 held-out 默认不能为对应评测提供候选证据，调用方必须显式改变范围。
        '''
        query = set(query_tokens((*error_tokens, *object_types, *field_roles)))
        allowed = frozenset(str(value) for value in allowed_usage)
        if not allowed <= ALLOWED_USAGE:
            raise ValueError("invalid_retrieval_usage_filter")
        scored: list[RetrievedCase] = []
        for row in self.rows:
            usage_status = str(row["usage_status"])
            if usage_status not in allowed:
                continue
            raw_features = []
            for key in ("error_signatures", "object_types", "field_roles", "repair_operations", "family", "tags"):
                value = row.get(key, ())
                raw_features.extend(value if isinstance(value, list) else (str(value),))
            features = set(query_tokens(raw_features))
            matching = tuple(sorted(query & features))
            union = len(query | features) or 1
            score = len(matching) / union
            if score:
                scored.append(RetrievedCase(
                    case_id=str(row["case_id"]),
                    score=score,
                    matching_features=matching,
                    usage_status=usage_status,
                    evidence=dict(row),
                ))
        scored.sort(key=lambda item: (-item.score, item.case_id))
        return tuple(scored[:max(0, int(limit))])


__all__ = [
    "ALLOWED_USAGE", "DEFAULT_RETRIEVAL_USAGE", "CaseIndex", "RetrievedCase",
    "query_tokens",
]
