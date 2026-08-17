"""房间感知航站楼 occupancy 受控研究工具。

该命名空间与历史 ``analysis.occupancy`` 隔离，避免改变已经归档的
neutral-group demo，也不修改冻结的 semantic-repair 实现。
"""

from idfrepair.analysis.occupancy_room_aware.classification import (
    classify_space_name,
)
from idfrepair.analysis.occupancy_room_aware.models import (
    ClassificationDecision,
    ClassificationStatus,
    EvidenceStatus,
    MetadataStatus,
    RoomCategory,
    SpaceAuditRow,
)

__all__ = [
    "ClassificationDecision",
    "ClassificationStatus",
    "EvidenceStatus",
    "MetadataStatus",
    "RoomCategory",
    "SpaceAuditRow",
    "classify_space_name",
]

