'''
定义 Repair Memory 的规则来源、作用域、规则和匹配上下文。

RepairRule.from_mapping(): 验证并构造完整规则记录。
'''

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from idfrepair.domain.models import utc_now


class RuleSource(str, Enum):
    '''限定规则的可信来源。'''

    BUILTIN = "BUILTIN"
    USER_CREATED = "USER_CREATED"
    USER_CONFIRMED = "USER_CONFIRMED"
    IMPORTED = "IMPORTED"
    MODEL_SUGGESTED = "MODEL_SUGGESTED"


class RuleScope(str, Enum):
    '''限定规则可匹配的文件、模板、项目、批次或对象范围。'''

    EXACT_FILE = "EXACT_FILE"
    EXACT_TEMPLATE = "EXACT_TEMPLATE"
    PROJECT = "PROJECT"
    BATCH = "BATCH"
    OBJECT_PATTERN = "OBJECT_PATTERN"
    GLOBAL = "GLOBAL"


@dataclass(frozen=True, slots=True)
class RepairRule:
    '''封装可持久化、可版本化且只能生成有限操作的修复规则。'''

    rule_id: str
    rule_set_id: str
    name_zh: str
    name_en: str
    description_zh: str = ""
    description_en: str = ""
    enabled: bool = True
    priority: int = 0
    scope: RuleScope = RuleScope.EXACT_TEMPLATE
    source: RuleSource = RuleSource.USER_CREATED
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    energyplus_version_min: str | None = None
    energyplus_version_max: str | None = None
    error_signature: str = ""
    family: str = ""
    object_type: str | None = None
    field_name: str | None = None
    field_index: int | None = None
    field_role: str | None = None
    graph_fingerprint: str | None = None
    conditions: Mapping[str, Any] = field(default_factory=dict)
    candidate_template: Mapping[str, Any] = field(default_factory=dict)
    finite_operations: tuple[Mapping[str, Any], ...] = ()
    requires_confirmation: bool = True
    confidence: float = 0.8
    success_count: int = 0
    failure_count: int = 0
    last_validation_status: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id or not self.rule_set_id:
            raise ValueError("rule_identity_required")
        if not self.name_zh or not self.name_en:
            raise ValueError("rule_names_required")
        if not -1000 <= self.priority <= 1000:
            raise ValueError("rule_priority_out_of_range")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("rule_confidence_out_of_range")
        if self.field_index is not None and self.field_index <= 0:
            raise ValueError("rule_field_index_must_be_positive")
        if self.success_count < 0 or self.failure_count < 0:
            raise ValueError("rule_statistics_must_be_non_negative")
        if self.source is RuleSource.MODEL_SUGGESTED and self.enabled:
            raise ValueError("model_suggested_rule_must_start_disabled")
        if not self.finite_operations:
            raise ValueError("rule_finite_operations_required")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RepairRule":
        '''验证外部映射并补全安全默认值。'''
        source = RuleSource(str(value.get("source", RuleSource.USER_CREATED.value)))
        scope = RuleScope(str(value.get("scope", RuleScope.EXACT_TEMPLATE.value)))
        enabled = bool(value.get("enabled", True)) and source is not RuleSource.MODEL_SUGGESTED
        operations = value.get("finite_operations", ())
        if not isinstance(operations, (list, tuple)) or not all(isinstance(row, Mapping) for row in operations):
            raise ValueError("finite_operations_must_be_array")
        return cls(
            rule_id=str(value.get("rule_id") or uuid4().hex),
            rule_set_id=str(value.get("rule_set_id") or "default"),
            name_zh=str(value.get("name_zh") or value.get("name_en") or "未命名规则"),
            name_en=str(value.get("name_en") or value.get("name_zh") or "Unnamed rule"),
            description_zh=str(value.get("description_zh", "")),
            description_en=str(value.get("description_en", "")),
            enabled=enabled,
            priority=int(value.get("priority", 0)),
            scope=scope,
            source=source,
            created_at=str(value.get("created_at") or utc_now()),
            updated_at=str(value.get("updated_at") or utc_now()),
            energyplus_version_min=(str(value["energyplus_version_min"]) if value.get("energyplus_version_min") else None),
            energyplus_version_max=(str(value["energyplus_version_max"]) if value.get("energyplus_version_max") else None),
            error_signature=str(value.get("error_signature", "")),
            family=str(value.get("family", "")),
            object_type=(str(value["object_type"]) if value.get("object_type") else None),
            field_name=(str(value["field_name"]) if value.get("field_name") else None),
            field_index=(int(value["field_index"]) if value.get("field_index") is not None else None),
            field_role=(str(value["field_role"]) if value.get("field_role") else None),
            graph_fingerprint=(str(value["graph_fingerprint"]) if value.get("graph_fingerprint") else None),
            conditions=dict(value.get("conditions", {})),
            candidate_template=dict(value.get("candidate_template", {})),
            finite_operations=tuple(dict(row) for row in operations),
            requires_confirmation=bool(value.get("requires_confirmation", True)),
            confidence=float(value.get("confidence", 0.8)),
            success_count=int(value.get("success_count", 0)),
            failure_count=int(value.get("failure_count", 0)),
            last_validation_status=(str(value["last_validation_status"]) if value.get("last_validation_status") else None),
            tags=tuple(str(tag) for tag in value.get("tags", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        '''转换为 JSON 和 YAML 可序列化的完整规则。'''
        row = asdict(self)
        row["scope"] = self.scope.value
        row["source"] = self.source.value
        return row


@dataclass(frozen=True, slots=True)
class RuleMatchContext:
    '''封装规则作用域和错误语义匹配所需的当前会话身份。'''

    input_sha256: str
    template_fingerprint: str | None = None
    project_id: str | None = None
    batch_id: str | None = None
    family: str = ""
    error_signature: str = ""
    energyplus_version: str = ""
    object_type: str | None = None
    field_name: str | None = None
    field_index: int | None = None
    field_role: str | None = None
    graph_fingerprint: str | None = None


__all__ = ["RepairRule", "RuleMatchContext", "RuleScope", "RuleSource"]
