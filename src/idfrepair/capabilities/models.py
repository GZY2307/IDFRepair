'''
定义 Support Registry、Release Profile 和运行审计的稳定数据对象。

SupportEntry.from_mapping(): 从唯一 JSON 配置恢复并验证一个支持条目。
SupportDecision.to_dict(): 输出 CLI、API、网页和报告共享的根支持判断。
'''

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class SupportStatus(str, Enum):
    '''定义公共能力的六种稳定英文状态。'''

    SAFE_AUTO = "safe-auto"
    ASSISTED = "assisted"
    INTERACTIVE = "interactive"
    EVIDENCE_ONLY = "evidence-only"
    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class MetricFraction:
    '''保存带明确分母的冻结指标。'''

    numerator: int
    denominator: int

    @classmethod
    def from_value(cls, value: object, name: str) -> "MetricFraction | None":
        '''验证 null 或非负分子与正分母组成的指标。'''
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError(f"metric_not_object:{name}")
        if set(value) != {"numerator", "denominator"}:
            raise ValueError(f"metric_keys_invalid:{name}")
        numerator = value["numerator"]
        denominator = value["denominator"]
        if (
            not isinstance(numerator, int)
            or isinstance(numerator, bool)
            or numerator < 0
        ):
            raise ValueError(f"metric_numerator_invalid:{name}")
        if (
            not isinstance(denominator, int)
            or isinstance(denominator, bool)
            or denominator <= 0
        ):
            raise ValueError(f"metric_denominator_invalid:{name}")
        if numerator > denominator:
            raise ValueError(f"metric_fraction_invalid:{name}")
        return cls(numerator, denominator)

    def to_dict(self) -> dict[str, int]:
        '''返回 JSON 可序列化的分子和分母。'''
        return {"numerator": self.numerator, "denominator": self.denominator}


_ENTRY_FIELDS = frozenset({
    "entry_id",
    "mechanism_id",
    "provider_name",
    "family",
    "support_status",
    "public_enabled",
    "automatic_policy",
    "requires_user_confirmation",
    "supported_energyplus_versions",
    "supported_error_signatures",
    "supported_object_types",
    "supported_field_roles",
    "required_evidence",
    "required_runtime_assets",
    "rejection_conditions",
    "user_input_conditions",
    "candidate_limit",
    "operation_allowlist",
    "provenance_policy",
    "evaluation_exposure",
    "evidence_references",
    "conditional_correct",
    "exact_correct",
    "control_correct",
    "wrong_modification",
    "wbr",
    "partial_as_full",
    "process_failure",
    "notes_zh",
    "notes_en",
})
_METRIC_FIELDS = (
    "conditional_correct",
    "exact_correct",
    "control_correct",
    "wrong_modification",
    "wbr",
    "partial_as_full",
    "process_failure",
)
_ARRAY_FIELDS = (
    "supported_energyplus_versions",
    "supported_error_signatures",
    "supported_object_types",
    "supported_field_roles",
    "required_evidence",
    "required_runtime_assets",
    "rejection_conditions",
    "user_input_conditions",
    "operation_allowlist",
    "evidence_references",
)


def _strings(value: object, name: str) -> tuple[str, ...]:
    '''验证一个无重复字符串数组并保持配置顺序。'''
    if not isinstance(value, list) or not all(isinstance(row, str) for row in value):
        raise ValueError(f"string_array_invalid:{name}")
    rows = tuple(value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"string_array_duplicate:{name}")
    return rows


@dataclass(frozen=True, slots=True)
class SupportEntry:
    '''封装一个不可变、可审计的能力登记项。'''

    entry_id: str
    mechanism_id: str
    provider_name: str | None
    family: str
    support_status: SupportStatus
    public_enabled: bool
    automatic_policy: str
    requires_user_confirmation: bool
    supported_energyplus_versions: tuple[str, ...]
    supported_error_signatures: tuple[str, ...]
    supported_object_types: tuple[str, ...]
    supported_field_roles: tuple[str, ...]
    required_evidence: tuple[str, ...]
    required_runtime_assets: tuple[str, ...]
    rejection_conditions: tuple[str, ...]
    user_input_conditions: tuple[str, ...]
    candidate_limit: int
    operation_allowlist: tuple[str, ...]
    provenance_policy: str
    evaluation_exposure: str
    evidence_references: tuple[str, ...]
    conditional_correct: MetricFraction | None
    exact_correct: MetricFraction | None
    control_correct: MetricFraction | None
    wrong_modification: MetricFraction | None
    wbr: MetricFraction | None
    partial_as_full: MetricFraction | None
    process_failure: MetricFraction | None
    notes_zh: str
    notes_en: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SupportEntry":
        '''拒绝缺失、额外或类型错误的 Registry Entry 字段。'''
        if set(value) != _ENTRY_FIELDS:
            missing = sorted(_ENTRY_FIELDS - set(value))
            extra = sorted(set(value) - _ENTRY_FIELDS)
            raise ValueError(
                "entry_fields_invalid:"
                + ",".join((*[f"missing={row}" for row in missing], *[f"extra={row}" for row in extra]))
            )
        text_fields = (
            "entry_id", "mechanism_id", "family", "automatic_policy",
            "provenance_policy", "evaluation_exposure", "notes_zh", "notes_en",
        )
        for name in text_fields:
            if not isinstance(value[name], str) or not value[name]:
                raise ValueError(f"entry_text_invalid:{name}")
        provider_name = value["provider_name"]
        if provider_name is not None and not isinstance(provider_name, str):
            raise ValueError("entry_provider_invalid")
        if value["automatic_policy"] not in {"allowed", "forbidden"}:
            raise ValueError("entry_automatic_policy_invalid")
        for name in ("public_enabled", "requires_user_confirmation"):
            if not isinstance(value[name], bool):
                raise ValueError(f"entry_boolean_invalid:{name}")
        candidate_limit = value["candidate_limit"]
        if (
            not isinstance(candidate_limit, int)
            or isinstance(candidate_limit, bool)
            or not 0 <= candidate_limit <= 3
        ):
            raise ValueError("entry_candidate_limit_invalid")
        arrays = {name: _strings(value[name], name) for name in _ARRAY_FIELDS}
        metrics = {
            name: MetricFraction.from_value(value[name], name)
            for name in _METRIC_FIELDS
        }
        try:
            status = SupportStatus(str(value["support_status"]))
        except ValueError as exc:
            raise ValueError("entry_support_status_invalid") from exc
        if status is SupportStatus.SAFE_AUTO and (
            value["automatic_policy"] != "allowed"
            or bool(value["requires_user_confirmation"])
            or not bool(value["public_enabled"])
        ):
            raise ValueError("safe_auto_entry_policy_invalid")
        if status is not SupportStatus.SAFE_AUTO and value["automatic_policy"] != "forbidden":
            raise ValueError("non_safe_auto_automatic_policy_invalid")
        if status in {SupportStatus.DISABLED, SupportStatus.EVIDENCE_ONLY} and candidate_limit != 0:
            raise ValueError("non_runtime_entry_candidate_limit_invalid")
        return cls(
            entry_id=str(value["entry_id"]),
            mechanism_id=str(value["mechanism_id"]),
            provider_name=provider_name,
            family=str(value["family"]),
            support_status=status,
            public_enabled=bool(value["public_enabled"]),
            automatic_policy=str(value["automatic_policy"]),
            requires_user_confirmation=bool(value["requires_user_confirmation"]),
            candidate_limit=candidate_limit,
            provenance_policy=str(value["provenance_policy"]),
            evaluation_exposure=str(value["evaluation_exposure"]),
            notes_zh=str(value["notes_zh"]),
            notes_en=str(value["notes_en"]),
            **arrays,
            **metrics,
        )

    def to_dict(self) -> dict[str, Any]:
        '''返回与唯一 JSON 配置字段完全一致的公共对象。'''
        payload: dict[str, Any] = {
            "entry_id": self.entry_id,
            "mechanism_id": self.mechanism_id,
            "provider_name": self.provider_name,
            "family": self.family,
            "support_status": self.support_status.value,
            "public_enabled": self.public_enabled,
            "automatic_policy": self.automatic_policy,
            "requires_user_confirmation": self.requires_user_confirmation,
            "candidate_limit": self.candidate_limit,
            "provenance_policy": self.provenance_policy,
            "evaluation_exposure": self.evaluation_exposure,
            "notes_zh": self.notes_zh,
            "notes_en": self.notes_en,
        }
        for name in _ARRAY_FIELDS:
            payload[name] = list(getattr(self, name))
        for name in _METRIC_FIELDS:
            metric = getattr(self, name)
            payload[name] = metric.to_dict() if metric is not None else None
        return payload


@dataclass(frozen=True, slots=True)
class SupportDecision:
    '''描述一个错误根在当前模式下的支持判断。'''

    root_id: str
    family: str
    support_status: SupportStatus
    support_entry_id: str | None
    support_reason: str
    required_evidence: tuple[str, ...] = ()
    user_input_conditions: tuple[str, ...] = ()
    provider_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        '''输出公共诊断和报告共享的六个支持字段。'''
        return {
            "root_id": self.root_id,
            "family": self.family,
            "support_status": self.support_status.value,
            "support_entry_id": self.support_entry_id,
            "support_reason": self.support_reason,
            "required_evidence": list(self.required_evidence),
            "user_input_conditions": list(self.user_input_conditions),
            "provider_allowed": self.provider_allowed,
        }


@dataclass(slots=True)
class ProviderAudit:
    '''累计单次引擎运行中的 Provider 门禁与候选计数。'''

    invoked: dict[str, int] = field(default_factory=dict)
    blocked: dict[str, int] = field(default_factory=dict)
    generated: dict[str, int] = field(default_factory=dict)
    unmatched_candidates: dict[str, int] = field(default_factory=dict)
    decisions: dict[str, SupportDecision] = field(default_factory=dict)

    @staticmethod
    def _increment(rows: dict[str, int], name: str, count: int = 1) -> None:
        '''对一个稳定 Provider 名称增加计数。'''
        rows[name] = rows.get(name, 0) + count

    def record_invoked(self, name: str) -> None:
        '''记录一次获准的 Provider.generate 调用。'''
        self._increment(self.invoked, name)

    def record_blocked(self, name: str) -> None:
        '''记录一次在 generate 前被 Registry 阻止的 Provider。'''
        self._increment(self.blocked, name)

    def record_generated(self, name: str, count: int) -> None:
        '''记录通过 Registry 候选级证据门禁的候选数。'''
        if count:
            self._increment(self.generated, name, count)

    def record_unmatched(self, name: str, count: int) -> None:
        '''记录 Provider 已调用但没有对应条目的候选数。'''
        if count:
            self._increment(self.unmatched_candidates, name, count)

    def record_decision(self, decision: SupportDecision) -> None:
        '''以最新状态保存一个根的公共支持判断。'''
        self.decisions[decision.root_id] = decision

    def to_dict(self) -> dict[str, Any]:
        '''输出稳定排序的 Provider 审计快照。'''
        return {
            "invoked": dict(sorted(self.invoked.items())),
            "blocked": dict(sorted(self.blocked.items())),
            "generated": dict(sorted(self.generated.items())),
            "unmatched_candidates": dict(sorted(self.unmatched_candidates.items())),
            "root_support": [
                self.decisions[key].to_dict() for key in sorted(self.decisions)
            ],
        }


__all__ = [
    "MetricFraction",
    "ProviderAudit",
    "SupportDecision",
    "SupportEntry",
    "SupportStatus",
]
