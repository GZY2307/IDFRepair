"""Dependency-free validation for the public session report contract."""

from __future__ import annotations

from typing import Any, Mapping


REPORT_SCHEMA_VERSION = "1.0"
REQUIRED_REPORT_KEYS = frozenset({
    "automatic_repair_release_authorized",
    "backtracks",
    "candidate_attempts",
    "committed_candidates",
    "configuration",
    "energyplus_runs",
    "final_diagnostics",
    "final_status",
    "input_identity",
    "initial_diagnostics",
    "limitations",
    "model_calls",
    "model_component_status",
    "output_identity",
    "production_enabled",
    "provider_invocation_audit",
    "raw_energyplus_err",
    "rejected_candidates",
    "release_profile_id",
    "repair_memory_component_status",
    "retrieval",
    "rollback_reason",
    "root_support",
    "rounds",
    "runtime_identity",
    "schema_version",
    "session_id",
    "support_coverage_summary",
    "support_registry_sha256",
    "text_fidelity",
    "tool_calls",
    "user_answers",
    "user_questions",
})


def validate_report(report: Mapping[str, Any]) -> tuple[str, ...]:
    """Return contract violations; an empty tuple means the report is valid."""
    reasons: list[str] = []
    missing = sorted(REQUIRED_REPORT_KEYS - set(report))
    if missing:
        reasons.append("missing_keys:" + ",".join(missing))
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        reasons.append("unsupported_schema_version")
    if report.get("production_enabled") is not False:
        reasons.append("production_must_remain_disabled")
    if report.get("automatic_repair_release_authorized") is not False:
        reasons.append("automatic_release_must_remain_disabled")
    if not isinstance(report.get("candidate_attempts", []), list):
        reasons.append("candidate_attempts_must_be_array")
    if not isinstance(report.get("rounds", []), list):
        reasons.append("rounds_must_be_array")
    if "issue_clusters" in report and not isinstance(report.get("issue_clusters"), list):
        reasons.append("issue_clusters_must_be_array")
    for key in ("actionable_issue_count", "related_diagnostic_count"):
        if key not in report:
            continue
        value = report.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            reasons.append(f"{key}_must_be_nonnegative_integer")
    if (
        "has_renderable_questions" in report
        and not isinstance(report.get("has_renderable_questions"), bool)
    ):
        reasons.append("has_renderable_questions_must_be_boolean")
    if report.get("release_profile_id") != "idfrepair.research_release.v1":
        reasons.append("release_profile_id_invalid")
    registry_sha = report.get("support_registry_sha256")
    if not isinstance(registry_sha, str) or len(registry_sha) != 64:
        reasons.append("support_registry_sha256_invalid")
    if not isinstance(report.get("root_support"), list):
        reasons.append("root_support_must_be_array")
    if not isinstance(report.get("support_coverage_summary"), Mapping):
        reasons.append("support_coverage_summary_must_be_object")
    text_fidelity = report.get("text_fidelity")
    if not isinstance(text_fidelity, Mapping):
        reasons.append("text_fidelity_must_be_object")
    elif text_fidelity.get("utf8_bom_policy") != "preserve-input":
        reasons.append("text_fidelity_bom_policy_invalid")
    if not isinstance(report.get("provider_invocation_audit"), Mapping):
        reasons.append("provider_invocation_audit_must_be_object")
    model_status = report.get("model_component_status")
    if not isinstance(model_status, Mapping) or model_status.get("model_enabled") is not False:
        reasons.append("model_component_must_remain_disabled")
    memory_status = report.get("repair_memory_component_status")
    if (
        not isinstance(memory_status, Mapping)
        or memory_status.get("candidate_generation_enabled") is not False
    ):
        reasons.append("repair_memory_candidate_generation_must_remain_disabled")
    for index, attempt in enumerate(report.get("candidate_attempts", [])):
        required = {
            "accepted", "candidate_id", "energyplus_result", "evidence", "patch",
            "rank", "rejection_reason", "root_id", "score", "semantic_result",
            "state_sha256", "static_result", "transition_result",
        }
        if not isinstance(attempt, Mapping):
            reasons.append(f"candidate_attempt_not_object:{index}")
            continue
        absent = sorted(required - set(attempt))
        if absent:
            reasons.append(f"candidate_attempt_missing_keys:{index}:" + ",".join(absent))
    return tuple(reasons)
