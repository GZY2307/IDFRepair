"""Room-aware occupancy 使用的不可变领域记录。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class _StringEnum(str, Enum):
    """兼容 Python 3.10 的字符串枚举。"""

    def __str__(self) -> str:
        return self.value


class RoomCategory(_StringEnum):
    """只能由源 ``OS:Space.Name`` 明确 token 得出的六类房间。"""

    TERMINAL_HALL = "terminal_hall"
    OFFICE = "office"
    COMMERCE_RETAIL = "commerce_retail"
    DINING = "dining"
    RESTROOM = "restroom"
    BREAKROOM = "breakroom"


class ClassificationStatus(_StringEnum):
    """自动分类的 fail-closed 状态。"""

    CLASSIFIED = "CLASSIFIED"
    UNKNOWN = "UNKNOWN_ROOM_TOKEN"
    MULTIPLE = "MULTIPLE_ROOM_TOKENS"


class MetadataStatus(_StringEnum):
    """源名称与显式 metadata 的一致性状态。"""

    CONSISTENT = "SOURCE_METADATA_CONSISTENT"
    DEFAULTED = "SOURCE_METADATA_DEFAULTED"
    CONFLICT = "SOURCE_METADATA_CONFLICT"


class EvidenceStatus(_StringEnum):
    """数值参数的证据等级或拒绝自动补全状态。"""

    SOURCE_BACKED = "TIER_A_SOURCE_BACKED"
    STANDARD_OR_LITERATURE_BACKED = "TIER_B_STANDARD_OR_LITERATURE_BACKED"
    CONTROLLED_SCENARIO_ASSUMPTION = "TIER_C_CONTROLLED_NOT_MEASURED"
    DO_NOT_AUTOFILL = "DO_NOT_AUTOFILL"


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    """一个 Space name 的确定性分类结果或结构化拒绝。"""

    source_space_name: str
    status: ClassificationStatus
    category: RoomCategory | None
    matched_tokens: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class SpaceAuditRow:
    """OpenStudio 审计输出中一个 Space 的关键只读事实。"""

    source_space_name: str
    source_handle: str
    room_category: RoomCategory
    thermal_zone: str | None
    floor_area_m2: float
    design_people: float
    people_per_m2: float | None
    m2_per_person: float | None
    explicit_space_type: str | None
    effective_space_type: str | None
    space_type_defaulted: bool
    metadata_status: MetadataStatus
    metadata_conflicts: tuple[str, ...]
    people_sources: tuple[Mapping[str, Any], ...]
    oa: Mapping[str, Any] | None
    oa_defaulted: bool
    exterior_area_m2: float


__all__ = [
    "ClassificationDecision",
    "ClassificationStatus",
    "EvidenceStatus",
    "MetadataStatus",
    "RoomCategory",
    "SpaceAuditRow",
]

