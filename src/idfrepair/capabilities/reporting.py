'''
把同一 Registry 投影为 CLI、API、会话报告和批量统计合同。

capabilities_payload(): 生成完整或按 family 过滤的公共能力清单。
support_coverage_summary(): 计算根级支持覆盖率并保留明确分母。
'''

from __future__ import annotations

from typing import Any, Iterable, Mapping

from idfrepair.capabilities.models import SupportEntry, SupportStatus
from idfrepair.capabilities.registry import SupportRegistry, load_support_registry
from idfrepair.capabilities.release_profile import ReleaseProfile, load_release_profile


def _fraction(numerator: int, denominator: int) -> dict[str, Any]:
    '''生成带分子、分母和可空小数值的统一比率。'''
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6) if denominator else None,
    }


def component_statuses() -> dict[str, Any]:
    '''返回模型和 Repair Memory 的固定公共状态。'''
    return {
        "model_component_status": {
            "status": "disabled",
            "model": "none",
            "model_enabled": False,
            "model_calls": 0,
            "reason": "model_component_not_release_authorized",
        },
        "repair_memory_component_status": {
            "status": "disabled_pending_qualification",
            "management_available": True,
            "candidate_generation_enabled": False,
            "reason": "repair_memory_candidate_generation_not_release_authorized",
        },
    }


def capabilities_payload(
    *,
    family: str | None = None,
    registry: SupportRegistry | None = None,
    profile: ReleaseProfile | None = None,
) -> dict[str, Any]:
    '''输出 Release Profile、Registry 条目、证据边界和授权状态。'''
    support = registry or load_support_registry()
    release = profile or load_release_profile()
    entries = [
        row for row in support.entries
        if family is None or row.family in {family, "*"}
    ]
    counts = {
        status.value: sum(row.support_status is status for row in entries)
        for status in SupportStatus
    }
    return {
        "schema_version": "idfrepair.capabilities.v1",
        "release_profile_id": release.release_profile_id,
        "release_profile_sha256": release.sha256,
        "support_registry_id": support.registry_id,
        "support_registry_sha256": support.sha256,
        "family_filter": family,
        "entry_count": len(entries),
        "status_counts": counts,
        "safe_auto_entry_ids": [
            row.entry_id for row in entries
            if row.support_status is SupportStatus.SAFE_AUTO
        ],
        "assisted_entry_ids": [
            row.entry_id for row in entries
            if row.support_status is SupportStatus.ASSISTED
        ],
        "interactive_entry_ids": [
            row.entry_id for row in entries
            if row.support_status is SupportStatus.INTERACTIVE
        ],
        "evidence_only_entry_ids": [
            row.entry_id for row in entries
            if row.support_status is SupportStatus.EVIDENCE_ONLY
        ],
        "disabled_entry_ids": [
            row.entry_id for row in entries
            if row.support_status is SupportStatus.DISABLED
        ],
        "entries": [row.to_dict() for row in entries],
        **component_statuses(),
        "production_enabled": False,
        "automatic_repair_release_authorized": False,
        "model_retraining_authorized": False,
        "model_product_integration_authorized": False,
        "repair_memory_release_authorized": False,
        "final_external_evaluation_authorized": False,
    }


def _entry_line(entry: SupportEntry, locale: str) -> str:
    '''按语言选择说明文本，同时保留稳定英文 token。'''
    note = entry.notes_zh if locale == "zh-CN" else entry.notes_en
    return f"- {entry.entry_id} [{entry.support_status.value}] {note}"


def capabilities_text(payload: Mapping[str, Any], locale: str) -> str:
    '''把 capabilities JSON 投影为中英文只读文本。'''
    if locale not in {"zh-CN", "en"}:
        raise ValueError("unsupported_locale")
    entries = [
        SupportEntry.from_mapping(row)
        for row in payload.get("entries", ())
        if isinstance(row, Mapping)
    ]
    if locale == "zh-CN":
        headings = {
            "profile": "Release Profile",
            "registry": "Support Registry SHA",
            "entries": "能力条目",
            "safety": "发布状态",
        }
        safety = "production_enabled=false；automatic_repair_release_authorized=false"
    else:
        headings = {
            "profile": "Release Profile",
            "registry": "Support Registry SHA",
            "entries": "Capability entries",
            "safety": "Release status",
        }
        safety = "production_enabled=false; automatic_repair_release_authorized=false"
    lines = [
        f"{headings['profile']}: {payload['release_profile_id']}",
        f"{headings['registry']}: {payload['support_registry_sha256']}",
        f"{headings['entries']}:",
        *[_entry_line(row, locale) for row in entries],
        f"{headings['safety']}: {safety}",
    ]
    return "\n".join(lines)


def support_coverage_summary(
    root_support: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    '''按互斥支持状态统计根，并输出支持与 safe-auto 覆盖率。'''
    rows = tuple(root_support)
    counts = {status.value: 0 for status in SupportStatus}
    for row in rows:
        token = str(row.get("support_status", SupportStatus.UNSUPPORTED.value))
        if token not in counts:
            token = SupportStatus.UNSUPPORTED.value
        counts[token] += 1
    supported = sum(
        counts[status.value]
        for status in (
            SupportStatus.SAFE_AUTO,
            SupportStatus.ASSISTED,
            SupportStatus.INTERACTIVE,
        )
    )
    total = len(rows)
    return {
        "total_roots": total,
        "status_counts": counts,
        "supported_roots": supported,
        "support_coverage": _fraction(supported, total),
        "safe_auto_coverage": _fraction(counts[SupportStatus.SAFE_AUTO.value], total),
    }


def empty_registry_audit() -> dict[str, Any]:
    '''为取消、拒绝或未生成候选的会话提供完整空审计。'''
    profile = load_release_profile()
    return {
        "release_profile_id": profile.release_profile_id,
        "support_registry_sha256": profile.support_registry_sha256,
        "invoked": {},
        "blocked": {},
        "generated": {},
        "unmatched_candidates": {},
        "root_support": [],
    }


__all__ = [
    "capabilities_payload",
    "capabilities_text",
    "component_statuses",
    "empty_registry_audit",
    "support_coverage_summary",
]
