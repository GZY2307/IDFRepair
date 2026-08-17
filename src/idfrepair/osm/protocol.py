"""Frozen, companion-bound protocols for transactional OSM child reports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Any


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_]+(?::[A-Za-z0-9_]+){0,3}$")
_VERIFICATION_KEYS = {
    "schema_version", "status", "independent_verifier",
    "reopened_repaired_osm", "repaired_osm_sha256", "repaired_idf_sha256",
    "post_forward_idf_sha256", "post_forward_report_complete",
    "strict_validity_error_multiset_not_worsened",
    "authorized_safe_plan_count", "remaining_targeted_safe_issue_count",
    "mapped_surface_geometry_and_adjacency_match",
    "non_target_surface_fingerprints_unchanged",
    "simulation_semantic_equivalence_claimed", "failure_reasons",
    "failure_reasons_truncated",
}
_WORKFLOW_SUCCESS_KEYS = {
    "schema_version", "status", "osm_writeback_status", "failure",
    "parent_session_id", "child_session_id", "source_osm_sha256",
    "repaired_osm_sha256", "repaired_idf_sha256", "source_osm_modified",
    "repaired_osm_available", "patch_counts", "execution_patch_counts",
    "preflight_rejection_summary", "idf_osm_semantic_equivalence_claimed",
    "coverage", "writeback_counts", "verification", "simulation",
    "non_writebacks", "non_writeback_count",
}
_WORKFLOW_FAILURE_KEYS = {
    "schema_version", "status", "failure", "parent_session_id",
    "child_session_id", "source_osm_modified", "repaired_osm_available",
    "verification", "simulation", "non_writebacks", "non_writeback_count",
}
_PATCH_COUNT_KEYS = {
    "plans_considered", "plans_authorized", "plans_rejected", "operations",
}
_WRITEBACK_COUNT_KEYS = {
    "operations_requested", "operations_applied", "generated_surfaces",
    "removed_air_boundaries",
}


def _normalized_json(value: object) -> str | None:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError):
        return None


def _count(value: object, *, maximum: int = 1_000_000) -> int | None:
    if type(value) is int and 0 <= value <= maximum:
        return value
    return None


def _exact_counts(value: object, keys: set[str]) -> dict[str, int] | None:
    if not isinstance(value, Mapping) or set(value) != keys:
        return None
    result = {key: _count(value.get(key)) for key in keys}
    if any(item is None for item in result.values()):
        return None
    return {key: int(item) for key, item in result.items()}


def _sha(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _session_id(value: object) -> bool:
    return type(value) is str and _SESSION_ID.fullmatch(value) is not None


def _bounded_detail(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if type(value) is int:
        return -(10**9) <= value <= 10**9
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, str):
        return len(value) <= 240 and "/" not in value and "\\" not in value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return len(value) <= 20 and all(
            isinstance(item, str)
            and len(item) <= 160
            and "/" not in item
            and "\\" not in item
            for item in value
        )
    return False


def _verification_reasons(value: object, *, failed: bool) -> bool:
    if (
        not isinstance(value, list)
        or len(value) > 50
        or (failed and not value)
        or (not failed and bool(value))
    ):
        return False
    seen: set[str] = set()
    for row in value:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"code", "details"}
            or not isinstance(row.get("code"), str)
            or not 0 < len(row["code"]) <= 160
            or _TOKEN.fullmatch(row["code"]) is None
            or not isinstance(row.get("details"), Mapping)
            or len(row["details"]) > 30
            or any(
                not isinstance(key, str)
                or not 0 < len(key) <= 80
                or _TOKEN.fullmatch(key) is None
                or not _bounded_detail(item)
                for key, item in row["details"].items()
            )
        ):
            return False
        token = _normalized_json(row)
        if token is None or len(token) > 4_000 or token in seen:
            return False
        seen.add(token)
    return True


@dataclass(frozen=True, slots=True)
class OSMChildVerificationReport:
    """An immutable exact verification report."""

    _canonical: str

    @classmethod
    def from_mapping(
        cls,
        value: object,
        *,
        expected_repaired_osm_sha256: str,
        expected_repaired_idf_sha256: str,
        expected_post_forward_idf_sha256: str,
        expected_authorized_safe_plan_count: int,
    ) -> OSMChildVerificationReport | None:
        if not isinstance(value, Mapping) or set(value) != _VERIFICATION_KEYS:
            return None
        status = value.get("status")
        failed = status == "FAILED"
        authorized = _count(value.get("authorized_safe_plan_count"))
        remaining = _count(value.get("remaining_targeted_safe_issue_count"))
        if (
            value.get("schema_version")
            != "idfrepair.osm-child-verification.v1"
            or status not in {"VERIFIED", "FAILED"}
            or value.get("independent_verifier")
            != "OpenStudioBridge.verify_repaired"
            or value.get("reopened_repaired_osm") is not True
            or not all(
                _sha(value.get(key))
                for key in (
                    "repaired_osm_sha256", "repaired_idf_sha256",
                    "post_forward_idf_sha256",
                )
            )
            or value.get("repaired_osm_sha256")
            != expected_repaired_osm_sha256
            or value.get("repaired_idf_sha256")
            != expected_repaired_idf_sha256
            or value.get("post_forward_idf_sha256")
            != expected_post_forward_idf_sha256
            or not all(
                isinstance(value.get(key), bool)
                for key in (
                    "post_forward_report_complete",
                    "strict_validity_error_multiset_not_worsened",
                    "mapped_surface_geometry_and_adjacency_match",
                    "non_target_surface_fingerprints_unchanged",
                    "simulation_semantic_equivalence_claimed",
                    "failure_reasons_truncated",
                )
            )
            or authorized != expected_authorized_safe_plan_count
            or remaining is None
            or value.get("simulation_semantic_equivalence_claimed") is not False
            or not _verification_reasons(value.get("failure_reasons"), failed=failed)
        ):
            return None
        if not failed and (
            remaining != 0
            or value.get("post_forward_report_complete") is not True
            or value.get("strict_validity_error_multiset_not_worsened") is not True
            or value.get("mapped_surface_geometry_and_adjacency_match") is not True
            or value.get("non_target_surface_fingerprints_unchanged") is not True
            or value.get("failure_reasons_truncated") is not False
        ):
            return None
        canonical = _normalized_json(value)
        return cls(canonical) if canonical is not None else None

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical)


def _simulation(value: object, *, success: bool) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "status", "simulation_ran", "passed", "semantic_equivalence_claimed",
    } or value.get("semantic_equivalence_claimed") is not False:
        return False
    state = (
        value.get("status"), value.get("simulation_ran"), value.get("passed"),
    )
    successful = {
        ("VALIDATED_WITHOUT_SIMULATION", False, None),
        ("VALIDATED_WITH_SIMULATION", True, True),
    }
    failures = successful | {
        ("NOT_RUN", False, None),
        ("FAILED", True, False),
    }
    return state in (successful if success else failures)


def _plan_sets(
    authoritative_preflight: object,
    attempted_patch: object,
    execution_patch: object,
) -> tuple[dict[str, Mapping[str, Any]], set[str], set[str]] | None:
    if not all(isinstance(row, Mapping) for row in (
        authoritative_preflight, attempted_patch, execution_patch,
    )):
        return None
    plans = authoritative_preflight.get("repair_plans")
    attempted_refs = attempted_patch.get("preflight")
    execution_refs = execution_patch.get("preflight")
    attempted_authorized = (
        attempted_refs.get("authorized_plans")
        if isinstance(attempted_refs, Mapping) else None
    )
    execution_authorized = (
        execution_refs.get("authorized_plans")
        if isinstance(execution_refs, Mapping) else None
    )
    if not all(isinstance(rows, list) for rows in (
        plans, attempted_authorized, execution_authorized,
    )):
        return None
    by_id: dict[str, Mapping[str, Any]] = {}
    for plan in plans:
        if (
            not isinstance(plan, Mapping)
            or not isinstance(plan.get("plan_id"), str)
            or not plan["plan_id"]
            or plan["plan_id"] in by_id
            or not isinstance(plan.get("safe_to_apply"), bool)
        ):
            return None
        by_id[plan["plan_id"]] = plan

    def refs(rows: list[object]) -> set[str] | None:
        result: set[str] = set()
        for row in rows:
            if (
                not isinstance(row, Mapping)
                or set(row) != {"plan_id", "plan_sha256"}
                or not isinstance(row.get("plan_id"), str)
                or row["plan_id"] in result
                or row["plan_id"] not in by_id
                or not _sha(row.get("plan_sha256"))
            ):
                return None
            result.add(row["plan_id"])
        return result

    attempted_ids = refs(attempted_authorized)
    execution_ids = refs(execution_authorized)
    safe = {plan_id for plan_id, row in by_id.items() if row["safe_to_apply"]}
    if (
        attempted_ids is None
        or execution_ids is None
        or attempted_ids != execution_ids
        or not attempted_ids <= safe
    ):
        return None
    return by_id, safe, attempted_ids


def _patch_contract(
    attempted_patch: Mapping[str, Any],
    execution_patch: Mapping[str, Any],
    *,
    plan_ids: set[str],
    eligible: set[str],
) -> tuple[dict[str, int], dict[str, int], list[Mapping[str, Any]]] | None:
    attempt_counts = _exact_counts(attempted_patch.get("counts"), _PATCH_COUNT_KEYS)
    execution_counts = _exact_counts(execution_patch.get("counts"), _PATCH_COUNT_KEYS)
    attempt_ops = attempted_patch.get("operations")
    execution_ops = execution_patch.get("operations")
    rejected = attempted_patch.get("rejected_plans")
    execution_rejected = execution_patch.get("rejected_plans")
    if (
        attempt_counts is None
        or execution_counts is None
        or not isinstance(attempt_ops, list)
        or not isinstance(execution_ops, list)
        or _normalized_json(attempt_ops) != _normalized_json(execution_ops)
        or not isinstance(rejected, list)
        or execution_rejected != []
    ):
        return None
    rejected_ids: set[str] = set()
    for row in rejected:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"plan_id", "kind", "reason"}
            or not isinstance(row.get("plan_id"), str)
            or row["plan_id"] in rejected_ids
            or row["plan_id"] not in plan_ids
            or not isinstance(row.get("kind"), str)
            or not isinstance(row.get("reason"), str)
            or _TOKEN.fullmatch(row["reason"]) is None
        ):
            return None
        rejected_ids.add(row["plan_id"])
    if (
        rejected_ids != plan_ids - eligible
        or attempt_counts != {
            "plans_considered": len(plan_ids),
            "plans_authorized": len(eligible),
            "plans_rejected": len(rejected),
            "operations": len(attempt_ops),
        }
        or execution_counts != {
            "plans_considered": len(eligible),
            "plans_authorized": len(eligible),
            "plans_rejected": 0,
            "operations": len(execution_ops),
        }
    ):
        return None
    return attempt_counts, execution_counts, rejected


def _coverage(
    value: object,
    plans: Mapping[str, Mapping[str, Any]],
    safe: set[str],
    eligible: set[str],
) -> bool:
    keys = {
        "safe_idf_plan_count", "osm_eligible_plan_count", "idf_only_plan_count",
        "review_only_plan_count", "idf_only_records",
        "idf_only_records_truncated",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        return False
    idf_only = safe - eligible
    records = [
        {
            "plan_id": plan_id,
            "kind": str(plans[plan_id].get("kind") or "")[:64],
            "status": "IDF_ONLY_NOT_WRITTEN",
            "reason": "exact_typed_mapping_unavailable",
        }
        for plan_id in sorted(idf_only)
    ]
    return dict(value) == {
        "safe_idf_plan_count": len(safe),
        "osm_eligible_plan_count": len(eligible),
        "idf_only_plan_count": len(idf_only),
        "review_only_plan_count": len(plans) - len(safe),
        "idf_only_records": records[:200],
        "idf_only_records_truncated": len(records) > 200,
    }


def _rejection_summary(value: object, rejected: list[Mapping[str, Any]]) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "count", "reason_counts", "records", "records_truncated",
    }:
        return False
    reasons = dict(sorted(Counter(row["reason"] for row in rejected).items()))
    return dict(value) == {
        "count": len(rejected),
        "reason_counts": reasons,
        "records": [dict(row) for row in rejected[:200]],
        "records_truncated": len(rejected) > 200,
    }


def _generic_failed_verification(value: object, reason: str) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"status", "failure_reasons"}
        and value.get("status") == "FAILED"
        and value.get("failure_reasons") == [{
            "code": "OSM_WRITEBACK_FAILED", "reason": reason,
        }]
    )


@dataclass(frozen=True, slots=True)
class OSMWorkflowReport:
    """An immutable workflow marker bound to every authoritative companion."""

    _canonical: str

    @classmethod
    def from_mapping(
        cls,
        value: object,
        *,
        authoritative_preflight: object,
        attempted_patch: object,
        execution_patch: object,
        patcher_report: object,
        expected_parent_session_id: str,
        expected_child_session_id: str,
        source_osm: bytes | None,
        repaired_osm: bytes | None,
        repaired_idf: bytes | None,
        post_forward_idf: bytes | None,
    ) -> OSMWorkflowReport | None:
        if (
            not isinstance(value, Mapping)
            or value.get("schema_version") != "idfrepair.osm-workflow.v1"
            or value.get("status") not in {"VERIFIED", "FAILED"}
            or value.get("parent_session_id") != expected_parent_session_id
            or value.get("child_session_id") != expected_child_session_id
            or not _session_id(expected_parent_session_id)
            or not _session_id(expected_child_session_id)
            or value.get("source_osm_modified") is not False
            or value.get("non_writebacks") != []
            or value.get("non_writeback_count") != 0
        ):
            return None
        if value["status"] == "FAILED":
            if (
                set(value) != _WORKFLOW_FAILURE_KEYS
                or value.get("repaired_osm_available") is not False
                or repaired_osm is not None
                or not isinstance(value.get("failure"), Mapping)
                or set(value["failure"]) != {"code", "reason"}
                or value["failure"].get("code") != "OSM_WRITEBACK_FAILED"
                or not isinstance(value["failure"].get("reason"), str)
                or _TOKEN.fullmatch(value["failure"]["reason"]) is None
                or not _simulation(value.get("simulation"), success=False)
            ):
                return None
            reason = value["failure"]["reason"]
            verification = value.get("verification")
            if not _generic_failed_verification(verification, reason):
                if not isinstance(verification, Mapping):
                    return None
                repaired_sha = verification.get("repaired_osm_sha256")
                repaired_idf_sha = verification.get("repaired_idf_sha256")
                post_idf_sha = verification.get("post_forward_idf_sha256")
                authorized = verification.get("authorized_safe_plan_count")
                if (
                    not all(_sha(item) for item in (
                        repaired_sha, repaired_idf_sha, post_idf_sha,
                    ))
                    or _count(authorized) is None
                    or OSMChildVerificationReport.from_mapping(
                        verification,
                        expected_repaired_osm_sha256=repaired_sha,
                        expected_repaired_idf_sha256=repaired_idf_sha,
                        expected_post_forward_idf_sha256=post_idf_sha,
                        expected_authorized_safe_plan_count=authorized,
                    ) is None
                ):
                    return None
            canonical = _normalized_json(value)
            return cls(canonical) if canonical is not None else None

        if (
            set(value) != _WORKFLOW_SUCCESS_KEYS
            or value.get("failure") is not None
            or value.get("repaired_osm_available") is not True
            or value.get("idf_osm_semantic_equivalence_claimed") is not False
            or not all(isinstance(item, bytes) for item in (
                source_osm, repaired_osm, repaired_idf, post_forward_idf,
            ))
            or value.get("source_osm_sha256") != sha256(source_osm).hexdigest()
            or value.get("repaired_osm_sha256") != sha256(repaired_osm).hexdigest()
            or value.get("repaired_idf_sha256") != sha256(repaired_idf).hexdigest()
            or not _simulation(value.get("simulation"), success=True)
        ):
            return None
        plan_sets = _plan_sets(
            authoritative_preflight, attempted_patch, execution_patch,
        )
        if plan_sets is None or not isinstance(patcher_report, Mapping):
            return None
        plans, safe, eligible = plan_sets
        patch_contract = _patch_contract(
            attempted_patch, execution_patch,
            plan_ids=set(plans), eligible=eligible,
        )
        writeback_counts = _exact_counts(
            patcher_report.get("counts"), _WRITEBACK_COUNT_KEYS,
        )
        if patch_contract is None or writeback_counts is None:
            return None
        attempt_counts, execution_counts, rejected = patch_contract
        verification = OSMChildVerificationReport.from_mapping(
            value.get("verification"),
            expected_repaired_osm_sha256=sha256(repaired_osm).hexdigest(),
            expected_repaired_idf_sha256=sha256(repaired_idf).hexdigest(),
            expected_post_forward_idf_sha256=sha256(post_forward_idf).hexdigest(),
            expected_authorized_safe_plan_count=len(eligible),
        )
        expected_status = (
            "OSM_WRITEBACK_PARTIAL"
            if safe - eligible else "OSM_WRITEBACK_VERIFIED"
        )
        if (
            value.get("osm_writeback_status") != expected_status
            or dict(value.get("patch_counts") or {}) != attempt_counts
            or dict(value.get("execution_patch_counts") or {}) != execution_counts
            or not _rejection_summary(
                value.get("preflight_rejection_summary"), rejected,
            )
            or not _coverage(value.get("coverage"), plans, safe, eligible)
            or dict(value.get("writeback_counts") or {}) != writeback_counts
            or patcher_report.get("source_sha256") != sha256(source_osm).hexdigest()
            or patcher_report.get("repaired_sha256") != sha256(repaired_osm).hexdigest()
            or writeback_counts["operations_requested"]
            != execution_counts["operations"]
            or writeback_counts["operations_applied"]
            != execution_counts["operations"]
            or verification is None
        ):
            return None
        canonical = _normalized_json(value)
        return cls(canonical) if canonical is not None else None

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical)


__all__ = ["OSMChildVerificationReport", "OSMWorkflowReport"]
