"""仅按源 Space name 明确 token 分类房间功能。"""

from __future__ import annotations

import re
from types import MappingProxyType

from idfrepair.analysis.occupancy_room_aware.models import (
    ClassificationDecision,
    ClassificationStatus,
    RoomCategory,
)


TOKEN_TO_CATEGORY = MappingProxyType(
    {
        "hall": RoomCategory.TERMINAL_HALL,
        "office": RoomCategory.OFFICE,
        "commerce": RoomCategory.COMMERCE_RETAIL,
        "dining": RoomCategory.DINING,
        "restroom": RoomCategory.RESTROOM,
        "breakroom": RoomCategory.BREAKROOM,
    }
)

# 数字、空格、下划线和连字符均可作为边界；英文字母不能。
_TOKEN_PATTERNS = {
    token: re.compile(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", re.IGNORECASE)
    for token in TOKEN_TO_CATEGORY
}


def classify_space_name(source_space_name: str) -> ClassificationDecision:
    """返回唯一类别；缺失或命中多个 token 时结构化拒绝。"""

    matched = tuple(
        token
        for token, pattern in _TOKEN_PATTERNS.items()
        if pattern.search(source_space_name)
    )
    if len(matched) == 1:
        return ClassificationDecision(
            source_space_name=source_space_name,
            status=ClassificationStatus.CLASSIFIED,
            category=TOKEN_TO_CATEGORY[matched[0]],
            matched_tokens=matched,
            reason="EXACT_SOURCE_NAME_TOKEN",
        )
    if not matched:
        return ClassificationDecision(
            source_space_name=source_space_name,
            status=ClassificationStatus.UNKNOWN,
            category=None,
            matched_tokens=(),
            reason="NO_EXPLICIT_ROOM_TOKEN",
        )
    return ClassificationDecision(
        source_space_name=source_space_name,
        status=ClassificationStatus.MULTIPLE,
        category=None,
        matched_tokens=matched,
        reason="MULTIPLE_EXPLICIT_ROOM_TOKENS",
    )


__all__ = ["TOKEN_TO_CATEGORY", "classify_space_name"]

