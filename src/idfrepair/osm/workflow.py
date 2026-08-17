"""Pure report projections for the transactional OSM child workflow."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Any

from idfrepair.api.schemas import ModelPreflightReport
from idfrepair.io.idf import parse_idf, text_sha256
from idfrepair.osm.protocol import (
    OSMChildVerificationReport,
    OSMWorkflowReport,
)
from idfrepair.osm.writeback import build_osm_patch


def _normalized_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def build_osm_execution_authority(
    authoritative_preflight: Mapping[str, Any],
    authoritative_forward_report: Mapping[str, Any],
    attempted_patch: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project one fresh, exact-authorized execution authority from a full attempt."""

    fresh_attempt = build_osm_patch(
        authoritative_preflight, authoritative_forward_report,
    )
    if _normalized_json(fresh_attempt) != _normalized_json(attempted_patch):
        raise ValueError("osm_attempt_patch_authority_mismatch")
    patch_preflight = fresh_attempt.get("preflight")
    authorized = (
        patch_preflight.get("authorized_plans")
        if isinstance(patch_preflight, Mapping) else None
    )
    plans = authoritative_preflight.get("repair_plans")
    issues = authoritative_preflight.get("issues")
    if (
        not isinstance(authorized, list)
        or not isinstance(plans, list)
        or not isinstance(issues, list)
    ):
        raise ValueError("osm_execution_authority_invalid")
    plan_by_id: dict[str, Mapping[str, Any]] = {}
    for plan in plans:
        if not isinstance(plan, Mapping) or not isinstance(plan.get("plan_id"), str):
            raise ValueError("osm_execution_source_plan_invalid")
        plan_id = str(plan["plan_id"])
        if plan_id in plan_by_id:
            raise ValueError("osm_execution_source_plan_duplicate")
        plan_by_id[plan_id] = plan
    issue_by_id: dict[str, Mapping[str, Any]] = {}
    for issue in issues:
        if not isinstance(issue, Mapping) or not isinstance(issue.get("issue_id"), str):
            raise ValueError("osm_execution_source_issue_invalid")
        issue_id = str(issue["issue_id"])
        if issue_id in issue_by_id:
            raise ValueError("osm_execution_source_issue_duplicate")
        issue_by_id[issue_id] = issue

    selected_plans: list[dict[str, Any]] = []
    selected_issues: list[dict[str, Any]] = []
    for ref in authorized:
        if not isinstance(ref, Mapping) or set(ref) != {"plan_id", "plan_sha256"}:
            raise ValueError("osm_execution_authorized_ref_invalid")
        plan_id = ref.get("plan_id")
        plan_hash = ref.get("plan_sha256")
        if not isinstance(plan_id, str) or plan_id not in plan_by_id:
            raise ValueError("osm_execution_authorized_plan_unknown")
        plan = plan_by_id[plan_id]
        expected_hash = sha256(_normalized_json(plan).encode("utf-8")).hexdigest()
        if plan_hash != expected_hash:
            raise ValueError("osm_execution_authorized_plan_hash_mismatch")
        issue = issue_by_id.get(plan_id)
        if issue is None:
            raise ValueError("osm_execution_authorized_issue_missing")
        selected_plans.append(deepcopy(dict(plan)))
        selected_issues.append(deepcopy(dict(issue)))

    execution_preflight = deepcopy(dict(authoritative_preflight))
    execution_preflight["repair_plans"] = selected_plans
    execution_preflight["issues"] = selected_issues
    summary = deepcopy(dict(execution_preflight.get("summary") or {}))
    summary.update({
        "issue_count": len(selected_issues),
        "direct_pair_repairs": sum(
            row.get("kind") == "reciprocal_surface_pair" for row in selected_plans
        ),
        "split_group_repairs": sum(
            row.get("kind") == "split_and_pair" for row in selected_plans
        ),
        "resegmented_overlap_repairs": sum(
            row.get("kind") == "resegment_and_pair" for row in selected_plans
        ),
        "air_wall_context_repairs": sum(
            row.get("kind") == "canonicalize_air_boundary"
            or bool(row.get("air_wall_context"))
            for row in selected_plans
        ),
        "safe_repairs": sum(
            row.get("safe_to_apply") is True for row in selected_plans
        ),
        "review_only_repairs": sum(
            row.get("safe_to_apply") is not True for row in selected_plans
        ),
    })
    execution_preflight["summary"] = summary

    ModelPreflightReport.model_validate(execution_preflight)
    execution_patch = build_osm_patch(
        execution_preflight, authoritative_forward_report,
    )
    counts = execution_patch.get("counts")
    execution_refs = execution_patch.get("preflight", {}).get("authorized_plans")
    if (
        not isinstance(counts, Mapping)
        or counts.get("plans_considered") != len(selected_plans)
        or counts.get("plans_authorized") != len(selected_plans)
        or counts.get("plans_rejected") != 0
        or execution_patch.get("rejected_plans") != []
        or _normalized_json(execution_refs) != _normalized_json(authorized)
    ):
        raise ValueError("osm_execution_patch_authority_mismatch")
    return execution_preflight, execution_patch


def summarize_osm_patch_rejections(
    patch: Mapping[str, Any], *, record_limit: int = 200,
) -> dict[str, Any]:
    """Keep complete rejection counts and a bounded stable record sample."""

    rejected = patch.get("rejected_plans")
    if not isinstance(rejected, list) or any(
        not isinstance(row, Mapping) for row in rejected
    ):
        raise ValueError("osm_patch_rejections_invalid")
    reason_counts = Counter(str(row.get("reason") or "") for row in rejected)
    return {
        "count": len(rejected),
        "reason_counts": dict(sorted(reason_counts.items())),
        "records": [deepcopy(dict(row)) for row in rejected[:record_limit]],
        "records_truncated": len(rejected) > record_limit,
    }


@dataclass(frozen=True, slots=True)
class OSMExecutionAuthority:
    authoritative_preflight: dict[str, Any]
    attempted_patch: dict[str, Any]
    execution_preflight: dict[str, Any]
    execution_patch: dict[str, Any]
    writeback_status: str
    coverage: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OSMVerifiedEvidence:
    repaired_osm: bytes
    patcher_report: dict[str, Any]
    source_audit: dict[str, Any]
    child_audit: dict[str, Any]
    verification_report: dict[str, Any]
    forward_report: dict[str, Any]
    forward_idf: bytes
    post_preflight: dict[str, Any]


class OSMChildVerificationFailed(ValueError):
    """A stable workflow failure that retains bounded independent evidence."""

    def __init__(self, verification_report: Mapping[str, Any]) -> None:
        super().__init__("openstudio_child_verification_failed")
        self.verification_report = _bounded_failed_verification(
            verification_report
        )


def _bounded_failed_verification(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    scalar_keys = (
        "schema_version", "status", "independent_verifier",
        "reopened_repaired_osm", "repaired_osm_sha256",
        "repaired_idf_sha256", "post_forward_idf_sha256",
        "post_forward_report_complete",
        "strict_validity_error_multiset_not_worsened",
        "authorized_safe_plan_count", "remaining_targeted_safe_issue_count",
        "mapped_surface_geometry_and_adjacency_match",
        "non_target_surface_fingerprints_unchanged",
        "simulation_semantic_equivalence_claimed",
    )
    bounded = {
        key: value for key in scalar_keys
        if isinstance((value := report.get(key)), (str, bool, int, float))
        or value is None
    }
    raw_reasons = report.get("failure_reasons")
    reason_rows = raw_reasons if isinstance(raw_reasons, list) else []
    reasons: list[dict[str, Any]] = []
    for row in reason_rows[:50]:
        if not isinstance(row, Mapping):
            continue
        code = str(row.get("code") or "")[:160]
        details = row.get("details")
        bounded_details: dict[str, Any] = {}
        if isinstance(details, Mapping):
            for key, value in list(sorted(details.items()))[:30]:
                if isinstance(value, str):
                    bounded_details[str(key)[:80]] = value[:240]
                elif isinstance(value, (bool, int, float)) or value is None:
                    bounded_details[str(key)[:80]] = value
                elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    bounded_details[str(key)[:80]] = [
                        str(item)[:160] for item in value[:20]
                    ]
        reasons.append({"code": code, "details": bounded_details})
    bounded["failure_reasons"] = reasons
    bounded["failure_reasons_truncated"] = bool(
        report.get("failure_reasons_truncated") or len(reason_rows) > 50
    )
    return bounded


def prepare_osm_execution(
    authoritative_preflight: Mapping[str, Any],
    authoritative_forward_report: Mapping[str, Any],
) -> OSMExecutionAuthority:
    attempted_patch = build_osm_patch(
        authoritative_preflight, authoritative_forward_report,
    )
    execution_preflight, execution_patch = build_osm_execution_authority(
        authoritative_preflight,
        authoritative_forward_report,
        attempted_patch,
    )
    writeback_status, coverage = project_osm_writeback_coverage(
        authoritative_preflight, execution_patch,
    )
    return OSMExecutionAuthority(
        authoritative_preflight=deepcopy(dict(authoritative_preflight)),
        attempted_patch=attempted_patch,
        execution_preflight=execution_preflight,
        execution_patch=execution_patch,
        writeback_status=writeback_status,
        coverage=coverage,
    )


def execute_osm_writeback_verification(
    adapter: Any,
    temporary_root: Path,
    *,
    source_bytes: bytes,
    source_name: str,
    repaired_idf: bytes,
    idd_text: str,
    authority: OSMExecutionAuthority,
    authoritative_forward_report: Mapping[str, Any],
) -> OSMVerifiedEvidence:
    with tempfile.TemporaryDirectory(
        prefix="idfrepair-osm-child-", dir=temporary_root,
    ) as directory:
        writeback = adapter.apply_patch(
            source_bytes,
            source_name,
            authority.execution_patch,
            Path(directory) / "patch",
            authoritative_preflight=authority.execution_preflight,
            authoritative_forward_report=authoritative_forward_report,
        )
        if not hasattr(adapter, "verify_repaired"):
            raise ValueError("openstudio_child_verifier_unavailable")
        verification = adapter.verify_repaired(
            writeback.repaired_osm,
            source_name,
            Path(directory) / "verify",
            source_osm=source_bytes,
            source_audit=writeback.source_audit,
            writeback_child_audit=writeback.child_audit,
            repaired_idf=repaired_idf,
            idd_text=idd_text,
            authoritative_preflight=authority.execution_preflight,
            authoritative_forward_report=authoritative_forward_report,
            patch=authority.execution_patch,
            writeback_report=writeback.report,
        )
    verification_report = dict(verification.report)
    execution_counts = authority.execution_patch.get("counts")
    authorized_count = (
        execution_counts.get("plans_authorized")
        if isinstance(execution_counts, Mapping) else None
    )
    parsed_verification = (
        OSMChildVerificationReport.from_mapping(
            verification_report,
            expected_repaired_osm_sha256=sha256(
                writeback.repaired_osm
            ).hexdigest(),
            expected_repaired_idf_sha256=sha256(repaired_idf).hexdigest(),
            expected_post_forward_idf_sha256=sha256(
                verification.forward_idf
            ).hexdigest(),
            expected_authorized_safe_plan_count=authorized_count,
        )
        if type(authorized_count) is int else None
    )
    if parsed_verification is None:
        raise ValueError("openstudio_child_verification_report_invalid")
    verification_report = parsed_verification.as_dict()
    if (
        verification_report.get("status") != "VERIFIED"
        or verification_report.get("independent_verifier")
        != "OpenStudioBridge.verify_repaired"
    ):
        if (
            verification_report.get("status") == "FAILED"
            and verification_report.get("independent_verifier")
            == "OpenStudioBridge.verify_repaired"
        ):
            raise OSMChildVerificationFailed(verification_report)
        raise ValueError("openstudio_child_verification_failed")
    return OSMVerifiedEvidence(
        repaired_osm=bytes(writeback.repaired_osm),
        patcher_report=dict(writeback.report),
        source_audit=dict(writeback.source_audit),
        child_audit=dict(writeback.child_audit),
        verification_report=verification_report,
        forward_report=dict(verification.forward_report),
        forward_idf=bytes(verification.forward_idf),
        post_preflight=dict(verification.preflight_report),
    )


def validate_osm_simulation(
    repaired_idf: bytes,
    *,
    weather_ready: bool,
    run_final: Any,
) -> dict[str, Any]:
    repaired_text = repaired_idf.decode("utf-8-sig")
    has_design_day = any(
        obj.object_type.casefold() == "sizingperiod:designday"
        for obj in parse_idf(repaired_text).objects
    )
    if not weather_ready and not has_design_day:
        return {
            "status": "VALIDATED_WITHOUT_SIMULATION",
            "simulation_ran": False,
            "passed": None,
            "semantic_equivalence_claimed": False,
        }
    try:
        final_result = run_final(repaired_text)
    except Exception as exc:
        raise ValueError("osm_child_final_simulation_failed") from exc
    final_passed = bool(
        final_result.passed
        and final_result.returncode == 0
        and final_result.severe_count == 0
        and final_result.fatal_count == 0
        and not final_result.process_failure
        and not final_result.timed_out
        and final_result.input_sha256 == text_sha256(repaired_text)
    )
    if not final_passed:
        raise ValueError("osm_child_final_simulation_failed")
    return {
        "status": "VALIDATED_WITH_SIMULATION",
        "simulation_ran": True,
        "passed": True,
        "semantic_equivalence_claimed": False,
    }


def build_verified_osm_workflow_report(
    *,
    parent_session_id: str,
    child_session_id: str,
    source_bytes: bytes,
    repaired_idf: bytes,
    authority: OSMExecutionAuthority,
    evidence: OSMVerifiedEvidence,
    simulation: Mapping[str, Any],
) -> dict[str, Any]:
    report = {
        "schema_version": "idfrepair.osm-workflow.v1",
        "status": "VERIFIED",
        "osm_writeback_status": authority.writeback_status,
        "failure": None,
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "source_osm_sha256": sha256(source_bytes).hexdigest(),
        "repaired_osm_sha256": sha256(evidence.repaired_osm).hexdigest(),
        "repaired_idf_sha256": sha256(repaired_idf).hexdigest(),
        "source_osm_modified": False,
        "repaired_osm_available": True,
        "patch_counts": dict(authority.attempted_patch["counts"]),
        "execution_patch_counts": dict(authority.execution_patch["counts"]),
        "preflight_rejection_summary": summarize_osm_patch_rejections(
            authority.attempted_patch,
        ),
        "idf_osm_semantic_equivalence_claimed": False,
        "coverage": authority.coverage,
        "writeback_counts": dict(evidence.patcher_report.get("counts") or {}),
        "verification": evidence.verification_report,
        "simulation": dict(simulation),
        "non_writebacks": [],
        "non_writeback_count": 0,
    }
    parsed = OSMWorkflowReport.from_mapping(
        report,
        authoritative_preflight=authority.authoritative_preflight,
        attempted_patch=authority.attempted_patch,
        execution_patch=authority.execution_patch,
        patcher_report=evidence.patcher_report,
        expected_parent_session_id=parent_session_id,
        expected_child_session_id=child_session_id,
        source_osm=source_bytes,
        repaired_osm=evidence.repaired_osm,
        repaired_idf=repaired_idf,
        post_forward_idf=evidence.forward_idf,
    )
    if parsed is None:
        raise ValueError("osm_workflow_report_invalid")
    return parsed.as_dict()


def build_failed_osm_workflow_report(
    *,
    parent_session_id: str,
    child_session_id: str,
    reason: str,
    simulation: Mapping[str, Any] | None = None,
    verification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "schema_version": "idfrepair.osm-workflow.v1",
        "status": "FAILED",
        "failure": {"code": "OSM_WRITEBACK_FAILED", "reason": reason},
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "source_osm_modified": False,
        "repaired_osm_available": False,
        "verification": dict(verification or {
            "status": "FAILED",
            "failure_reasons": [{
                "code": "OSM_WRITEBACK_FAILED", "reason": reason,
            }],
        }),
        "simulation": dict(simulation or {
            "status": "NOT_RUN",
            "simulation_ran": False,
            "passed": None,
            "semantic_equivalence_claimed": False,
        }),
        "non_writebacks": [],
        "non_writeback_count": 0,
    }
    parsed = OSMWorkflowReport.from_mapping(
        report,
        authoritative_preflight={},
        attempted_patch={},
        execution_patch={},
        patcher_report={},
        expected_parent_session_id=parent_session_id,
        expected_child_session_id=child_session_id,
        source_osm=None,
        repaired_osm=None,
        repaired_idf=None,
        post_forward_idf=None,
    )
    if parsed is None:
        raise ValueError("osm_failed_workflow_report_invalid")
    return parsed.as_dict()


def project_osm_writeback_coverage(
    authoritative_preflight: Mapping[str, Any],
    execution_patch: Mapping[str, Any],
    *,
    record_limit: int = 200,
) -> tuple[str, dict[str, Any]]:
    """Classify exact OSM coverage without treating review-only plans as IDF-only."""

    raw_plans = authoritative_preflight.get("repair_plans")
    patch_preflight = execution_patch.get("preflight")
    raw_refs = (
        patch_preflight.get("authorized_plans")
        if isinstance(patch_preflight, Mapping) else None
    )
    if (
        not isinstance(raw_plans, Sequence)
        or isinstance(raw_plans, (str, bytes))
        or not isinstance(raw_refs, Sequence)
        or isinstance(raw_refs, (str, bytes))
        or record_limit < 0
    ):
        raise ValueError("osm_writeback_coverage_authority_invalid")

    plans: dict[str, Mapping[str, Any]] = {}
    safe_ids: set[str] = set()
    for row in raw_plans:
        if not isinstance(row, Mapping) or not isinstance(row.get("plan_id"), str):
            raise ValueError("osm_writeback_coverage_plan_invalid")
        plan_id = str(row["plan_id"])
        if plan_id in plans:
            raise ValueError("osm_writeback_coverage_plan_duplicate")
        plans[plan_id] = row
        if row.get("safe_to_apply") is True:
            safe_ids.add(plan_id)

    eligible_ids: set[str] = set()
    for row in raw_refs:
        if not isinstance(row, Mapping) or not isinstance(row.get("plan_id"), str):
            raise ValueError("osm_writeback_coverage_ref_invalid")
        plan_id = str(row["plan_id"])
        if plan_id in eligible_ids:
            raise ValueError("osm_writeback_coverage_ref_duplicate")
        eligible_ids.add(plan_id)
    if not eligible_ids <= safe_ids:
        raise ValueError("osm_writeback_coverage_eligible_not_safe")

    idf_only_ids = safe_ids - eligible_ids
    records = [
        {
            "plan_id": plan_id,
            "kind": str(plans[plan_id].get("kind") or "")[:64],
            "status": "IDF_ONLY_NOT_WRITTEN",
            "reason": "exact_typed_mapping_unavailable",
        }
        for plan_id in sorted(idf_only_ids)
    ]
    status = (
        "OSM_WRITEBACK_PARTIAL"
        if idf_only_ids else "OSM_WRITEBACK_VERIFIED"
    )
    return status, {
        "safe_idf_plan_count": len(safe_ids),
        "osm_eligible_plan_count": len(eligible_ids),
        "idf_only_plan_count": len(idf_only_ids),
        "review_only_plan_count": len(plans) - len(safe_ids),
        "idf_only_records": records[:record_limit],
        "idf_only_records_truncated": len(records) > record_limit,
    }


def compile_committed_osm_operations(
    committed_rounds: Iterable[Mapping[str, Any]],
    forward_report: Mapping[str, Any],
    *,
    output_text: str | None = None,
) -> dict[str, Any]:
    """Classify journaled IDF operations without inspecting a text diff."""

    del output_text
    mapping_contract = str(forward_report.get("mapping_contract") or "")
    non_writebacks: list[dict[str, Any]] = []
    committed_count = 0
    for round_row in committed_rounds:
        if not isinstance(round_row, Mapping):
            continue
        candidate = round_row.get("candidate")
        if not isinstance(candidate, Mapping):
            continue
        operations = candidate.get("operations")
        if not isinstance(operations, Sequence) or isinstance(
            operations, (str, bytes),
        ):
            continue
        for operation_index, operation in enumerate(operations):
            if not isinstance(operation, Mapping):
                continue
            committed_count += 1
            non_writebacks.append({
                "round_index": int(round_row.get("round_index") or 0),
                "candidate_id": str(candidate.get("candidate_id") or "")[:160],
                "operation_index": operation_index,
                "kind": str(operation.get("kind") or "")[:80],
                "status": "IDF_ONLY_NOT_WRITTEN",
                "reason": "exact_typed_mapping_unavailable",
            })
    return {
        "schema_version": "idfrepair.committed-osm-operations.v1",
        "mapping_contract": (
            mapping_contract
            if mapping_contract == "exact-source-handle-typed-surface-v2"
            else "exact-source-handle-typed-surface-v2"
        ),
        "operations": [],
        "non_writebacks": non_writebacks,
        "counts": {
            "committed": committed_count,
            "written": 0,
            "idf_only": len(non_writebacks),
        },
    }


__all__ = [
    "OSMChildVerificationFailed",
    "OSMExecutionAuthority",
    "OSMVerifiedEvidence",
    "build_osm_execution_authority",
    "build_failed_osm_workflow_report",
    "build_verified_osm_workflow_report",
    "compile_committed_osm_operations",
    "execute_osm_writeback_verification",
    "prepare_osm_execution",
    "project_osm_writeback_coverage",
    "summarize_osm_patch_rejections",
    "validate_osm_simulation",
]
