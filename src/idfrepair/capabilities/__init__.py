'''
公开 IDFRepair 的冻结 Support Registry 与 Release Profile 读取接口。
'''

from idfrepair.capabilities.models import SupportDecision, SupportEntry, SupportStatus
from idfrepair.capabilities.registry import (
    ReleaseCandidateRegistry,
    SupportRegistry,
    build_release_candidate_registry,
    load_support_registry,
)
from idfrepair.capabilities.release_profile import (
    RELEASE_PROFILE_ID,
    ReleaseProfile,
    load_release_profile,
)
from idfrepair.capabilities.reporting import capabilities_payload, support_coverage_summary


__all__ = [
    "RELEASE_PROFILE_ID",
    "ReleaseCandidateRegistry",
    "ReleaseProfile",
    "SupportDecision",
    "SupportEntry",
    "SupportRegistry",
    "SupportStatus",
    "build_release_candidate_registry",
    "capabilities_payload",
    "load_release_profile",
    "load_support_registry",
    "support_coverage_summary",
]
