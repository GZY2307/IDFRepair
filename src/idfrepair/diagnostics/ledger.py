'''
维护初始、已解决、新暴露和剩余语义问题，并签发完整修复证书。

LatentFaultLedger: 在已提交状态之间维护稳定问题 lineage。
completion_certificate(): 只有全部审计通过且剩余问题为零时签发通过。
'''

from __future__ import annotations

from typing import Any, Iterable, Mapping

from idfrepair.domain.models import DiagnosticRoot


def _snapshot(root: DiagnosticRoot) -> dict[str, Any]:
    '''把诊断根转换为不含原始 IDF 字节的稳定 ledger 项。'''
    return {
        "family": root.family,
        "field_name": root.field_name,
        "issue_id": str(root.metadata.get("semantic_issue_id") or root.root_id),
        "object_name": root.object_name,
        "object_type": root.object_type,
        "recoverability": str(
            root.metadata.get("recoverability") or "RECOVERABLE"
        ),
        "root_id": root.root_id,
        "severity": root.severity,
    }


class LatentFaultLedger:
    '''记录已提交状态的问题集合，拒绝因 EnergyPlus pass 清空账本。'''

    def __init__(self) -> None:
        self.initial: dict[str, dict[str, Any]] = {}
        self.seen: dict[str, dict[str, Any]] = {}
        self.current: dict[str, dict[str, Any]] = {}
        self.newly_revealed: dict[str, dict[str, Any]] = {}
        self.initialized = False

    def initialize(self, roots: Iterable[DiagnosticRoot]) -> None:
        '''冻结第一次诊断得到的 supported 与 ambiguous 问题。'''
        rows = {_snapshot(root)["issue_id"]: _snapshot(root) for root in roots}
        self.initial = rows
        self.seen = dict(rows)
        self.current = dict(rows)
        self.newly_revealed = {}
        self.initialized = True

    def update(self, roots: Iterable[DiagnosticRoot]) -> None:
        '''用一个已提交状态更新 remaining、resolved 与 newly revealed。'''
        if not self.initialized:
            self.initialize(roots)
            return
        rows = {_snapshot(root)["issue_id"]: _snapshot(root) for root in roots}
        for issue_id, row in rows.items():
            if issue_id not in self.seen:
                self.newly_revealed[issue_id] = row
            self.seen[issue_id] = row
        self.current = rows

    def to_dict(self) -> dict[str, Any]:
        '''返回初始、已解决、新暴露和剩余问题的完整 lineage。'''
        resolved = {
            issue_id: row
            for issue_id, row in self.seen.items()
            if issue_id not in self.current
        }
        initial_supported = [
            row for row in self.initial.values()
            if row["recoverability"] == "RECOVERABLE"
        ]
        initial_ambiguous = [
            row for row in self.initial.values()
            if row["recoverability"] == "AMBIGUOUS"
        ]
        remaining_ambiguous = [
            row for row in self.current.values()
            if row["recoverability"] == "AMBIGUOUS"
        ]
        return {
            "initial_ambiguous_issues": initial_ambiguous,
            "initial_issue_count": len(self.initial),
            "initial_supported_issues": initial_supported,
            "newly_revealed_issue_count": len(self.newly_revealed),
            "newly_revealed_issues": list(self.newly_revealed.values()),
            "remaining_ambiguous_issue_count": len(remaining_ambiguous),
            "remaining_issue_count": len(self.current),
            "remaining_issues": list(self.current.values()),
            "resolved_issue_count": len(resolved),
            "resolved_issues": list(resolved.values()),
        }


def completion_certificate(
    ledger: LatentFaultLedger,
    roots: Iterable[DiagnosticRoot],
    audit: Mapping[str, Any],
    *,
    energyplus_passed: bool,
) -> dict[str, Any]:
    '''组合 ledger 与六项审计，任一缺失均拒绝 REPAIRED。'''
    current = tuple(roots)
    ledger.update(current)
    ledger_payload = ledger.to_dict()
    remaining_supported = [
        root for root in current
        if root.metadata.get("recoverability") != "AMBIGUOUS"
    ]
    newly_remaining = [
        row for row in ledger_payload["newly_revealed_issues"]
        if any(
            current_row["issue_id"] == row["issue_id"]
            for current_row in ledger_payload["remaining_issues"]
        )
    ]
    fields = {
        "energyplus_passed": energyplus_passed,
        "geometry_audit_passed": bool(audit.get("geometry_audit_passed")),
        "idd_audit_passed": bool(audit.get("idd_audit_passed")),
        "rdd_audit_passed": bool(audit.get("rdd_audit_passed")),
        "reference_audit_passed": bool(audit.get("reference_audit_passed")),
        "warning_audit_passed": bool(audit.get("warning_audit_passed")),
    }
    passed = bool(
        all(fields.values())
        and ledger_payload["remaining_issue_count"] == 0
        and ledger_payload["remaining_ambiguous_issue_count"] == 0
        and not remaining_supported
        and not newly_remaining
    )
    return {
        **fields,
        "initial_issue_count": ledger_payload["initial_issue_count"],
        "newly_revealed_remaining_count": len(newly_remaining),
        "passed": passed,
        "remaining_ambiguous_issue_count": ledger_payload[
            "remaining_ambiguous_issue_count"
        ],
        "remaining_issue_count": ledger_payload["remaining_issue_count"],
        "remaining_supported_issue_count": len(remaining_supported),
        "resolved_issue_count": ledger_payload["resolved_issue_count"],
        "schema_version": "idfrepair.all_fault_completion_certificate.v1",
    }


__all__ = ["LatentFaultLedger", "completion_certificate"]
