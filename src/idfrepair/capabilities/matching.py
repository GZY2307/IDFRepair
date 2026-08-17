'''
在 Provider 调用前匹配支持条目，并在候选生成后验证证据证书。

entry_matches_root(): 判断条目能否进入当前根的 Provider 前门禁。
entry_matches_candidate(): 验证候选操作和 geometry 专用证据边界。
'''

from __future__ import annotations

from fnmatch import fnmatchcase

from idfrepair.capabilities.runtime import runtime_capability
from idfrepair.capabilities.models import SupportEntry
from idfrepair.candidates.base import CandidateContext
from idfrepair.domain.models import DiagnosticRoot, RepairCandidate
from idfrepair.io.idf import canonical


_GEOMETRY_EVIDENCE = frozenset({
    "unique_cyclic_reverse_geometry_solution",
    "zone_closure_improvement",
    "outward_orientation_consensus",
})


def _version_matches(entry: SupportEntry, context: CandidateContext) -> bool:
    '''优先以 exact runtime/IDD/RDD 自检替代易过期的手写版本数组。'''
    runtime_assets = {value.casefold() for value in entry.required_runtime_assets}
    if (
        entry.support_status.value == "safe-auto"
        and (
            "energyplus executable" in runtime_assets
            or "bound idd" in runtime_assets
        )
    ):
        evidence = runtime_capability(
            context,
            require_rdd="runtime-generated rdd" in runtime_assets,
        )
        return evidence.passed
    if "*" in entry.supported_energyplus_versions:
        return True
    normalized = context.version.strip().casefold()
    return any(
        normalized == row.casefold()
        or normalized.startswith(row.casefold() + ".")
        for row in entry.supported_energyplus_versions
    )


def _pattern_matches(patterns: tuple[str, ...], value: str | None) -> bool:
    '''在值缺失时保持 Provider 自身定位门禁，存在值时执行通配匹配。'''
    if not patterns or "*" in patterns or value is None:
        return True
    lowered = value.casefold()
    return any(fnmatchcase(lowered, pattern.casefold()) for pattern in patterns)


def entry_matches_root(
    entry: SupportEntry,
    root: DiagnosticRoot,
    context: CandidateContext,
) -> bool:
    '''按 family、版本、对象类型和字段角色执行生成前的确定性匹配。'''
    if entry.family not in {"*", root.family}:
        return False
    if not _version_matches(entry, context):
        return False
    if not _pattern_matches(entry.supported_object_types, root.object_type):
        return False
    field_role = root.metadata.get("field_role")
    if not _pattern_matches(
        entry.supported_field_roles,
        str(field_role) if isinstance(field_role, str) else None,
    ):
        return False
    if entry.entry_id == "extra_field_idd_safe_auto" and root.family != "extra_field":
        return False
    if entry.entry_id == "generic_schema_assisted" and root.family != "schema":
        return False
    return True


def _geometry_certificate(candidate: RepairCandidate) -> bool:
    '''确认 frozen graph reconstruction 候选携带完整且未放宽的证据。'''
    kinds = {row.kind for row in candidate.evidence}
    metadata = candidate.metadata
    support = metadata.get("independent_support_surface_ids", ())
    before = metadata.get("before_open_edges")
    after = metadata.get("after_open_edges")
    return bool(
        _GEOMETRY_EVIDENCE <= kinds
        and metadata.get("mechanism") == "unique_ring_graph_reconstruction"
        and metadata.get("automatic_policy") == "qualified_graph_invariants"
        and metadata.get("zone_closure_policy") == "strict_improvement"
        and metadata.get("minimum_independent_support_surfaces") == 2
        and isinstance(support, (tuple, list))
        and len(set(str(row) for row in support)) >= 2
        and isinstance(before, int)
        and not isinstance(before, bool)
        and isinstance(after, int)
        and not isinstance(after, bool)
        and after < before
    )


def entry_matches_candidate(
    entry: SupportEntry,
    root: DiagnosticRoot,
    candidate: RepairCandidate,
) -> bool:
    '''要求 Provider、family、有限操作和候选级证据同时满足登记项。'''
    if candidate.provider != entry.provider_name or candidate.root_id != root.root_id:
        return False
    if entry.family not in {"*", candidate.family, root.family}:
        return False
    operations = {row.kind.value for row in candidate.operations}
    if not operations or not operations <= set(entry.operation_allowlist):
        return False
    if entry.entry_id == "geometry_graph_reconstruct_safe_auto":
        return _geometry_certificate(candidate)
    if entry.entry_id == "extra_field_idd_safe_auto":
        return root.family == "extra_field" and operations == {"delete_field"}
    return True


def root_has_explicit_geometry_target(root: DiagnosticRoot) -> bool:
    '''判断 legacy geometry 是否至少有显式对象身份可供交互预览。'''
    if root.family != "geometry":
        return False
    if root.object_name:
        return True
    if root.metadata.get("object_index") is not None:
        return True
    message = canonical(root.message)
    return bool("surface" in message and any(row in message for row in ("name", "=")))


__all__ = [
    "entry_matches_candidate",
    "entry_matches_root",
    "root_has_explicit_geometry_target",
]
