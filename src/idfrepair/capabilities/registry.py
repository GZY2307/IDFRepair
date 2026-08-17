'''
加载冻结 Registry，并构造公共入口唯一允许使用的候选 Registry。

load_support_registry(): 校验 JSON、SHA、七类 safe-auto 和 Provider coverage。
ReleaseCandidateRegistry.generate(): 在 Provider 前后执行双重能力门禁并记录审计。
'''

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping

from idfrepair.capabilities.matching import (
    entry_matches_candidate,
    entry_matches_root,
    root_has_explicit_geometry_target,
)
from idfrepair.capabilities.models import (
    ProviderAudit,
    SupportDecision,
    SupportEntry,
    SupportStatus,
)
from idfrepair.capabilities.release_profile import (
    EXPECTED_SUPPORT_REGISTRY_SHA256,
    ReleaseProfile,
    load_release_profile,
    support_registry_path,
    support_registry_schema_path,
)
from idfrepair.candidates.base import CandidateContext, CandidateProvider
from idfrepair.candidates.ems import EmsProvider
from idfrepair.candidates.finite_keys import FiniteKeyProvider
from idfrepair.candidates.geometry import GeometryProvider
from idfrepair.candidates.geometry_reconstruct import GeometryReconstructProvider
from idfrepair.candidates.historical import ProvenanceObjectProvider, TypedDesignProvider
from idfrepair.candidates.hvac import HvacProvider
from idfrepair.candidates.migration import MigrationProvider
from idfrepair.candidates.outputs import OutputProvider
from idfrepair.candidates.references import ReferenceProvider
from idfrepair.candidates.schedules import ScheduleProvider
from idfrepair.candidates.schema import SchemaProvider
from idfrepair.candidates.syntax import SyntaxProvider
from idfrepair.candidates.transition_lineage import TransitionLineageProvider
from idfrepair.candidates.user import UserCandidateProvider
from idfrepair.domain.enums import Provenance, RepairMode, RepairStatus, RiskLevel
from idfrepair.domain.models import DiagnosticRoot, RepairCandidate, RepairOutcome


EXPECTED_SUPPORT_REGISTRY_SCHEMA_SHA256 = (
    "cebe58725cfa5a03c9d3173f11d9f02c6039b135f76adf62a0958dce256d16fd"
)
SAFE_AUTO_ENTRY_IDS = frozenset({
    "finite_key_unique_typo_safe_auto",
    "syntax_delimiter_safe_auto",
    "extra_field_idd_safe_auto",
    "schedule_reference_safe_auto",
    "output_variable_rdd_safe_auto",
    "object_reference_unique_typo_safe_auto",
    "geometry_graph_reconstruct_safe_auto",
})
_ENTRY_ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_STATUS_ORDER = {
    SupportStatus.SAFE_AUTO: 0,
    SupportStatus.ASSISTED: 1,
    SupportStatus.INTERACTIVE: 2,
    SupportStatus.EVIDENCE_ONLY: 3,
    SupportStatus.DISABLED: 4,
    SupportStatus.UNSUPPORTED: 5,
}


def _public_providers() -> tuple[CandidateProvider, ...]:
    '''实例化公共 Release Profile 可审计的 Provider，明确排除 Memory。'''
    rows: tuple[CandidateProvider, ...] = (
        SyntaxProvider(),
        SchemaProvider(),
        FiniteKeyProvider(),
        ScheduleProvider(),
        ReferenceProvider(),
        TypedDesignProvider(),
        ProvenanceObjectProvider(),
        OutputProvider(),
        TransitionLineageProvider(),
        GeometryReconstructProvider(),
        GeometryProvider(),
        MigrationProvider(),
        HvacProvider(),
        EmsProvider(),
        UserCandidateProvider(),
    )
    return tuple(sorted(rows, key=lambda row: row.name))


PUBLIC_PROVIDER_NAMES = frozenset(row.name for row in _public_providers())
KNOWN_DEFAULT_PROVIDER_NAMES = PUBLIC_PROVIDER_NAMES | {"repair_memory"}


@dataclass(frozen=True, slots=True)
class SupportRegistry:
    '''封装经过 SHA 和完整性校验的唯一 Support Registry。'''

    registry_id: str
    entries: tuple[SupportEntry, ...]
    disabled_provider_names: frozenset[str]
    sha256: str

    def entry(self, entry_id: str) -> SupportEntry:
        '''按稳定 entry_id 返回唯一条目。'''
        matches = [row for row in self.entries if row.entry_id == entry_id]
        if len(matches) != 1:
            raise KeyError(entry_id)
        return matches[0]

    def provider_entries(self, provider_name: str) -> tuple[SupportEntry, ...]:
        '''返回一个 Provider 的全部条目并按状态和身份排序。'''
        rows = [row for row in self.entries if row.provider_name == provider_name]
        return tuple(sorted(rows, key=lambda row: (_STATUS_ORDER[row.support_status], row.entry_id)))

    def to_dict(self) -> dict[str, Any]:
        '''输出 CLI 和 API 使用的稳定 Registry 结构。'''
        return {
            "schema_version": "idfrepair.support_registry.v1",
            "registry_id": self.registry_id,
            "disabled_provider_names": sorted(self.disabled_provider_names),
            "entries": [row.to_dict() for row in self.entries],
        }


def _read_payload() -> Mapping[str, Any]:
    '''验证 Registry 和 JSON Schema 原始字节身份后读取配置。'''
    schema_content = support_registry_schema_path().read_bytes()
    if sha256(schema_content).hexdigest() != EXPECTED_SUPPORT_REGISTRY_SCHEMA_SHA256:
        raise ValueError("SUPPORT_REGISTRY_INVALID:schema_sha256_mismatch")
    content = support_registry_path().read_bytes()
    if sha256(content).hexdigest() != EXPECTED_SUPPORT_REGISTRY_SHA256:
        raise ValueError("SUPPORT_REGISTRY_INVALID:registry_sha256_mismatch")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("SUPPORT_REGISTRY_INVALID:registry_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("SUPPORT_REGISTRY_INVALID:registry_not_object")
    return payload


def load_support_registry() -> SupportRegistry:
    '''验证 schema 等价约束、条目互斥性和全部默认 Provider coverage。'''
    try:
        payload = _read_payload()
        if set(payload) != {
            "schema_version", "registry_id", "disabled_provider_names", "entries",
        }:
            raise ValueError("top_level_fields_invalid")
        if payload.get("schema_version") != "idfrepair.support_registry.v1":
            raise ValueError("schema_version_invalid")
        if payload.get("registry_id") != "idfrepair.support_registry.v1":
            raise ValueError("registry_id_invalid")
        raw_disabled = payload.get("disabled_provider_names")
        if (
            not isinstance(raw_disabled, list)
            or not all(isinstance(row, str) and row for row in raw_disabled)
            or len(raw_disabled) != len(set(raw_disabled))
        ):
            raise ValueError("disabled_provider_names_invalid")
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list) or len(raw_entries) < 20:
            raise ValueError("entry_count_invalid")
        entries = tuple(
            SupportEntry.from_mapping(row)
            for row in raw_entries
            if isinstance(row, Mapping)
        )
        if len(entries) != len(raw_entries):
            raise ValueError("entry_not_object")
        entry_ids = [row.entry_id for row in entries]
        if len(entry_ids) != len(set(entry_ids)) or not all(_ENTRY_ID.fullmatch(row) for row in entry_ids):
            raise ValueError("entry_ids_invalid")
        safe_auto = {
            row.entry_id for row in entries
            if row.support_status is SupportStatus.SAFE_AUTO
        }
        if safe_auto != SAFE_AUTO_ENTRY_IDS:
            raise ValueError("safe_auto_entries_changed")
        disabled = frozenset(raw_disabled)
        for name in KNOWN_DEFAULT_PROVIDER_NAMES:
            rows = [row for row in entries if row.provider_name == name]
            if not rows and name not in disabled:
                raise ValueError(f"provider_uncovered:{name}")
        if "repair_memory" not in disabled:
            raise ValueError("repair_memory_not_disabled")
        for row in entries:
            if row.provider_name in disabled and row.support_status not in {
                SupportStatus.DISABLED, SupportStatus.EVIDENCE_ONLY,
            }:
                raise ValueError(f"disabled_provider_public_entry:{row.provider_name}")
        return SupportRegistry(
            registry_id="idfrepair.support_registry.v1",
            entries=entries,
            disabled_provider_names=disabled,
            sha256=EXPECTED_SUPPORT_REGISTRY_SHA256,
        )
    except ValueError as exc:
        if str(exc).startswith("SUPPORT_REGISTRY_INVALID:"):
            raise
        raise ValueError(f"SUPPORT_REGISTRY_INVALID:{exc}") from exc


def _unsupported(root: DiagnosticRoot, reason: str) -> SupportDecision:
    '''构造不会进入候选池的稳定 unsupported 判断。'''
    return SupportDecision(
        root_id=root.root_id,
        family=root.family,
        support_status=SupportStatus.UNSUPPORTED,
        support_entry_id=None,
        support_reason=reason,
        provider_allowed=False,
    )


class ReleaseCandidateRegistry:
    '''以 frozen Support Registry 约束公共 Provider 调用和候选输出。'''

    def __init__(
        self,
        mode: RepairMode,
        *,
        registry: SupportRegistry | None = None,
        profile: ReleaseProfile | None = None,
        providers: Iterable[CandidateProvider] | None = None,
    ) -> None:
        self.mode = mode
        self.support_registry = registry or load_support_registry()
        self.release_profile = profile or load_release_profile()
        if self.release_profile.support_registry_sha256 != self.support_registry.sha256:
            raise ValueError("SUPPORT_REGISTRY_INVALID:profile_registry_mismatch")
        rows = tuple(providers) if providers is not None else _public_providers()
        names = [row.name for row in rows]
        if len(names) != len(set(names)):
            raise ValueError("SUPPORT_REGISTRY_INVALID:duplicate_provider_name")
        if set(names) != set(PUBLIC_PROVIDER_NAMES):
            raise ValueError("SUPPORT_REGISTRY_INVALID:public_provider_factory_changed")
        self.providers = tuple(sorted(rows, key=lambda row: row.name))
        for provider in self.providers:
            entries = self.support_registry.provider_entries(provider.name)
            if not entries:
                raise ValueError(
                    f"SUPPORT_REGISTRY_INVALID:public_provider_uncovered:{provider.name}"
                )
            if provider.name in self.support_registry.disabled_provider_names:
                raise ValueError(
                    f"SUPPORT_REGISTRY_INVALID:disabled_provider_instantiated:{provider.name}"
                )
        self.audit = ProviderAudit()

    def provider(self, name: str) -> CandidateProvider:
        '''只返回 Release Profile 工厂已覆盖且未禁用的 Provider。'''
        matches = [row for row in self.providers if row.name == name]
        if len(matches) != 1:
            raise KeyError(name)
        return matches[0]

    def authorize_injected_candidates(
        self,
        candidates: Iterable[RepairCandidate],
        approved_candidate_ids: Iterable[str],
    ) -> tuple[RepairCandidate, ...]:
        '''只接收 interactive 模式中由明确问题回答编译的有限候选。'''
        rows = tuple(candidates)
        if not rows:
            return ()
        approved = frozenset(approved_candidate_ids)
        if self.mode is not RepairMode.INTERACTIVE:
            raise ValueError("user_candidate_not_release_authorized_for_mode")
        entry = self.support_registry.entry("user_input_interactive")
        if entry.support_status is not SupportStatus.INTERACTIVE:
            raise ValueError("SUPPORT_REGISTRY_INVALID:user_entry_status")
        allowed_operations = set(entry.operation_allowlist)
        authorized = []
        for candidate in rows:
            operations = {row.kind.value for row in candidate.operations}
            if (
                candidate.provider != "user_input"
                or candidate.candidate_id not in approved
                or candidate.provenance is not Provenance.USER_SUPPLIED
                or not isinstance(candidate.metadata.get("user_question_id"), str)
                or not candidate.metadata.get("user_question_id")
                or not operations
                or not operations <= allowed_operations
            ):
                raise ValueError("user_candidate_not_compiled_from_explicit_answer")
            authorized.append(self._tighten(candidate, entry))
        self.audit.record_invoked("user_input")
        self.audit.record_generated("user_input", len(authorized))
        return tuple(authorized)

    def record_unreached_decisions(
        self,
        roots: Iterable[DiagnosticRoot],
        context: CandidateContext,
    ) -> None:
        '''为 analyze-only 等未进入搜索轮次的根补充只读 support matching。'''
        known = set(self.audit.decisions)
        for root in roots:
            if root.root_id not in known:
                self.audit.record_decision(self.decision_for_root(root, context))
                known.add(root.root_id)

    def apply_terminal_disposition(self, outcome: RepairOutcome) -> RepairOutcome:
        '''把已登记但当前模式不可自动执行的根稳定映射为需要输入。'''
        if (
            self.mode is RepairMode.SAFE_AUTO
            and outcome.status is RepairStatus.UNSUPPORTED
            and any(
                decision.support_entry_id == "geometry_topology_assisted"
                for decision in self.audit.decisions.values()
            )
        ):
            outcome.status = RepairStatus.NEEDS_INPUT
            outcome.rollback_reason = "assisted_or_interactive_mode_required"
            if "assisted_or_interactive_mode_required" not in outcome.limitations:
                outcome.limitations.append("assisted_or_interactive_mode_required")
        return outcome

    def _root_entries(
        self,
        root: DiagnosticRoot,
        context: CandidateContext,
        *,
        allowed_only: bool,
    ) -> tuple[SupportEntry, ...]:
        '''返回通过公共状态、模式和生成前匹配的候选条目。'''
        allowed = self.release_profile.allowed_statuses(self.mode)
        rows = []
        for entry in self.support_registry.entries:
            if entry.support_status not in {
                SupportStatus.SAFE_AUTO,
                SupportStatus.ASSISTED,
                SupportStatus.INTERACTIVE,
            }:
                continue
            if not entry.public_enabled or entry.candidate_limit <= 0:
                continue
            if allowed_only and entry.support_status not in allowed:
                continue
            if entry_matches_root(entry, root, context):
                rows.append(entry)
        return tuple(sorted(rows, key=lambda row: (_STATUS_ORDER[row.support_status], row.entry_id)))

    def decision_for_root(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> SupportDecision:
        '''在没有生成候选时给出保守、模式感知的根支持判断。'''
        rows = list(self._root_entries(root, context, allowed_only=False))
        if root.family == "geometry":
            rows = [
                row for row in rows
                if row.entry_id != "geometry_graph_reconstruct_safe_auto"
            ]
            if not root_has_explicit_geometry_target(root):
                rows = [
                    row for row in rows
                    if row.entry_id != "geometry_topology_assisted"
                ]
        if not rows:
            return _unsupported(root, "no_registry_entry_matches_root")
        entry = rows[0]
        allowed = entry.support_status in self.release_profile.allowed_statuses(self.mode)
        return SupportDecision(
            root_id=root.root_id,
            family=root.family,
            support_status=entry.support_status,
            support_entry_id=entry.entry_id,
            support_reason=(
                "registry_entry_matches_root"
                if allowed else "registry_entry_not_enabled_for_current_mode"
            ),
            required_evidence=entry.required_evidence,
            user_input_conditions=entry.user_input_conditions,
            provider_allowed=allowed,
        )

    @staticmethod
    def _tighten(candidate: RepairCandidate, entry: SupportEntry) -> RepairCandidate:
        '''只增加确认、风险和 Registry provenance，不放宽候选任何属性。'''
        assisted = entry.support_status is not SupportStatus.SAFE_AUTO
        risk = candidate.risk
        if assisted and risk.order < RiskLevel.MEDIUM.order:
            risk = RiskLevel.MEDIUM
        return replace(
            candidate,
            risk=risk,
            requires_user_confirmation=(
                candidate.requires_user_confirmation
                or entry.requires_user_confirmation
                or assisted
            ),
            metadata={
                **candidate.metadata,
                "release_profile_id": "idfrepair.research_release.v1",
                "support_registry_sha256": EXPECTED_SUPPORT_REGISTRY_SHA256,
                "support_entry_id": entry.entry_id,
                "support_status": entry.support_status.value,
                "release_automatic_policy": entry.automatic_policy,
            },
        )

    def generate(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> tuple[RepairCandidate, ...]:
        '''在 generate 前阻止未授权 Provider，并在生成后匹配候选证书。'''
        initial = self.decision_for_root(root, context)
        self.audit.record_decision(initial)
        if self.mode is RepairMode.ANALYZE_ONLY:
            for provider in self.providers:
                if provider.supports(root, context):
                    self.audit.record_blocked(provider.name)
            return ()
        allowed = self.release_profile.allowed_statuses(self.mode)
        accepted: dict[str, tuple[RepairCandidate, SupportEntry]] = {}
        for provider in self.providers:
            if provider.name == "user_input":
                if provider.supports(root, context):
                    self.audit.record_blocked(provider.name)
                continue
            if not provider.supports(root, context):
                continue
            entries = tuple(
                row for row in self.support_registry.provider_entries(provider.name)
                if row.support_status in allowed
                and row.public_enabled
                and row.candidate_limit > 0
                and entry_matches_root(row, root, context)
            )
            if not entries:
                self.audit.record_blocked(provider.name)
                continue
            self.audit.record_invoked(provider.name)
            generated = tuple(provider.generate(root, context))
            matched_count = 0
            for candidate in generated:
                if candidate.provider != provider.name:
                    raise ValueError("candidate_provider_identity_mismatch")
                if candidate.root_id != root.root_id:
                    raise ValueError("candidate_root_identity_mismatch")
                matches = [
                    entry for entry in entries
                    if entry_matches_candidate(entry, root, candidate)
                ]
                if not matches:
                    continue
                entry = sorted(
                    matches,
                    key=lambda row: (_STATUS_ORDER[row.support_status], row.entry_id),
                )[0]
                accepted[candidate.candidate_id] = (self._tighten(candidate, entry), entry)
                matched_count += 1
            self.audit.record_generated(provider.name, matched_count)
            self.audit.record_unmatched(provider.name, len(generated) - matched_count)
        limited: dict[str, tuple[RepairCandidate, SupportEntry]] = {}
        by_entry: dict[str, int] = {}
        for candidate_id in sorted(accepted):
            candidate, entry = accepted[candidate_id]
            used = by_entry.get(entry.entry_id, 0)
            if used >= entry.candidate_limit:
                continue
            by_entry[entry.entry_id] = used + 1
            limited[candidate_id] = candidate, entry
        if limited:
            entry = sorted(
                (row[1] for row in limited.values()),
                key=lambda row: (_STATUS_ORDER[row.support_status], row.entry_id),
            )[0]
            self.audit.record_decision(SupportDecision(
                root_id=root.root_id,
                family=root.family,
                support_status=entry.support_status,
                support_entry_id=entry.entry_id,
                support_reason="candidate_evidence_certificate_matched",
                required_evidence=entry.required_evidence,
                user_input_conditions=entry.user_input_conditions,
                provider_allowed=True,
            ))
        elif root.family == "geometry":
            assisted = [
                row for row in self._root_entries(root, context, allowed_only=False)
                if row.support_status is SupportStatus.ASSISTED
            ]
            if assisted:
                entry = assisted[0]
                self.audit.record_decision(SupportDecision(
                    root_id=root.root_id,
                    family=root.family,
                    support_status=entry.support_status,
                    support_entry_id=entry.entry_id,
                    support_reason=(
                        "safe_auto_geometry_certificate_missing_assisted_preview_available"
                    ),
                    required_evidence=entry.required_evidence,
                    user_input_conditions=entry.user_input_conditions,
                    provider_allowed=entry.support_status in allowed,
                ))
            else:
                self.audit.record_decision(_unsupported(
                    root, "geometry_candidate_evidence_certificate_missing",
                ))
        return tuple(limited[key][0] for key in sorted(limited))

    def audit_snapshot(self) -> dict[str, Any]:
        '''返回包含 Release Profile 身份的不可变审计快照。'''
        return {
            "release_profile_id": self.release_profile.release_profile_id,
            "support_registry_sha256": self.support_registry.sha256,
            **self.audit.to_dict(),
        }


def build_release_candidate_registry(mode: RepairMode) -> ReleaseCandidateRegistry:
    '''为公共 CLI、API、网页和 batch 构造同一个受限 Registry。'''
    return ReleaseCandidateRegistry(mode)


__all__ = [
    "EXPECTED_SUPPORT_REGISTRY_SCHEMA_SHA256",
    "KNOWN_DEFAULT_PROVIDER_NAMES",
    "PUBLIC_PROVIDER_NAMES",
    "ReleaseCandidateRegistry",
    "SAFE_AUTO_ENTRY_IDS",
    "SupportRegistry",
    "build_release_candidate_registry",
    "load_support_registry",
]
