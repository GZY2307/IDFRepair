"""Build the one public, stage-free report used by every interface."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from idfrepair.capabilities.release_profile import (
    EXPECTED_SUPPORT_REGISTRY_SHA256,
    RELEASE_PROFILE_ID,
)
from idfrepair.capabilities.reporting import (
    component_statuses,
    empty_registry_audit,
    support_coverage_summary,
)
from idfrepair.config import EngineConfig
from idfrepair.domain.models import RepairOutcome, UserAnswer, to_primitive
from idfrepair.diagnostics.clusters import (
    build_issue_clusters,
    has_renderable_questions,
)
from idfrepair.reporting.explanations import explain_status
from idfrepair.reporting.schema import REPORT_SCHEMA_VERSION, validate_report
from idfrepair.reporting.text_fidelity import analyze_text_fidelity
from idfrepair.presentation.diagnostics import (
    diagnostic_presentation,
    support_reason_presentation,
)


def _diagnostic(row: Any) -> dict[str, Any]:
    return {
        **to_primitive(row),
        "presentation": diagnostic_presentation(row),
    }


def _attempt(row: Any) -> dict[str, Any]:
    candidate = row.candidate
    return {
        "accepted": row.accepted,
        "candidate_id": row.candidate_id,
        "candidate_metadata": to_primitive(candidate.metadata),
        "energyplus_result": to_primitive(row.energyplus_result),
        "evidence": to_primitive(candidate.evidence),
        "family": candidate.family,
        "patch": to_primitive(candidate.operations),
        "provider": candidate.provider,
        "rank": row.rank,
        "rejection_reason": row.rejection_reason,
        "root_id": row.root_id,
        "score": to_primitive(candidate.score),
        "semantic_result": to_primitive(row.semantic_result),
        "state_sha256": row.state_sha256,
        "static_result": to_primitive(row.static_result),
        "transition_result": to_primitive(row.transition_result),
    }


def build_session_report(
    *,
    session_id: str,
    input_name: str,
    input_text: str,
    outcome: RepairOutcome,
    configuration: EngineConfig,
    runtime_identity: Mapping[str, Any] | None = None,
    user_answers: Iterable[UserAnswer] = (),
    model_calls: Iterable[Mapping[str, Any]] = (),
    tool_calls: Iterable[Mapping[str, Any]] = (),
    support_registry_audit: Mapping[str, Any] | None = None,
    preprocessing: Mapping[str, Any] | None = None,
    input_had_utf8_bom: bool = False,
    output_has_utf8_bom: bool = False,
) -> dict[str, Any]:
    input_bytes = input_text.encode("utf-8")
    output_bytes = outcome.output_text.encode("utf-8")
    retrieval_rows = []
    for attempt in outcome.attempts:
        retrieval = attempt.candidate.metadata.get("retrieval")
        if retrieval:
            retrieval_rows.append({
                "candidate_id": attempt.candidate_id,
                **to_primitive(retrieval),
            })
    raw_err = []
    if outcome.initial_energyplus_diagnostics:
        raw_err.append(outcome.initial_energyplus_diagnostics)
    for attempt in outcome.attempts:
        result = attempt.energyplus_result
        if result is not None and result.diagnostics and result.diagnostics not in raw_err:
            raw_err.append(result.diagnostics)
    registry_audit = dict(support_registry_audit or empty_registry_audit())
    if registry_audit.get("support_registry_sha256") != EXPECTED_SUPPORT_REGISTRY_SHA256:
        raise ValueError("invalid_support_registry_audit_identity")
    root_support = [
        dict(row) for row in registry_audit.get("root_support", ())
        if isinstance(row, Mapping)
    ]
    known_roots = {str(row.get("root_id")) for row in root_support}
    for root in (*outcome.initial_diagnostics, *outcome.final_diagnostics):
        if root.root_id in known_roots:
            continue
        known_roots.add(root.root_id)
        root_support.append({
            "root_id": root.root_id,
            "family": root.family,
            "support_status": "unsupported",
            "support_entry_id": None,
            "support_reason": "root_not_reached_by_registry",
            "required_evidence": [],
            "user_input_conditions": [],
            "provider_allowed": False,
        })
    components = component_statuses()
    report = {
        "automatic_repair_release_authorized": False,
        "backtracks": outcome.backtracks,
        "candidate_attempts": [_attempt(row) for row in outcome.attempts],
        "committed_candidates": [row.candidate.candidate_id for row in outcome.committed_rounds],
        "configuration": configuration.to_dict(),
        "energyplus_runs": outcome.energyplus_runs,
        "final_diagnostics": [_diagnostic(row) for row in outcome.final_diagnostics],
        "final_status": outcome.status.value,
        "input_identity": {
            "bytes": len(input_bytes),
            "name": input_name,
            "sha256": sha256(input_bytes).hexdigest(),
        },
        "initial_energyplus_err": outcome.initial_energyplus_diagnostics,
        "initial_diagnostics": [_diagnostic(row) for row in outcome.initial_diagnostics],
        "limitations": list(outcome.limitations),
        "model_calls": [to_primitive(row) for row in (*outcome.model_calls, *model_calls)],
        "model_component_status": components["model_component_status"],
        "model_product_integration_authorized": False,
        "model_retraining_authorized": False,
        "output_identity": {
            "bytes": len(output_bytes),
            "sha256": sha256(output_bytes).hexdigest(),
        },
        "production_enabled": False,
        "preprocessing": dict(preprocessing or {
            "required": False,
            "used": False,
            "object_types": [],
            "artifact_available": False,
            "artifact_name": None,
            "artifact_sha256": None,
            "main_idf_preserves_templates": True,
        }),
        "provider_invocation_audit": registry_audit,
        "raw_energyplus_err": raw_err,
        "rejected_candidates": list(outcome.rejected_candidates),
        "retrieval": {
            "candidate_records": retrieval_rows,
            "retrieved_case_ids": sorted({
                case_id for row in retrieval_rows
                for case_id in row.get("retrieved_case_ids", [])
            }),
        },
        "rollback_reason": outcome.rollback_reason,
        "root_support": [
            {
                **row,
                "support_presentation": support_reason_presentation(
                    str(row.get("support_reason") or "")
                ),
            }
            for row in root_support
        ],
        "rounds": [to_primitive(row) for row in outcome.committed_rounds],
        "runtime_identity": dict(runtime_identity or {}),
        "schema_version": REPORT_SCHEMA_VERSION,
        "session_id": session_id,
        "status_explanation": explain_status(outcome.status),
        "support_coverage_summary": support_coverage_summary(root_support),
        "support_registry_sha256": EXPECTED_SUPPORT_REGISTRY_SHA256,
        "text_fidelity": analyze_text_fidelity(
            input_text,
            outcome.output_text,
            operation_groups=tuple(
                tuple(round_.candidate.operations) for round_ in outcome.committed_rounds
            ),
            input_had_utf8_bom=input_had_utf8_bom,
            output_has_utf8_bom=output_has_utf8_bom,
        ),
        "release_profile_id": RELEASE_PROFILE_ID,
        "repair_memory_component_status": components["repair_memory_component_status"],
        "repair_memory_release_authorized": False,
        "final_external_evaluation_authorized": False,
        "tool_calls": [to_primitive(row) for row in (*outcome.tool_calls, *tool_calls)],
        "user_answers": to_primitive(tuple(user_answers)),
        "user_questions": to_primitive(outcome.questions),
    }
    clusters = build_issue_clusters(report)
    final_clusters = build_issue_clusters({
        **report,
        "initial_diagnostics": report["final_diagnostics"],
        "final_diagnostics": report["final_diagnostics"],
        "rounds": [],
    })
    report.update({
        "issue_clusters": list(clusters),
        "actionable_issue_count": len(final_clusters),
        "related_diagnostic_count": sum(
            len(cluster["related_diagnostics"]) for cluster in clusters
        ),
        "has_renderable_questions": has_renderable_questions(report),
        "issue_category_counts": {
            family: sum(
                cluster["root"].get("family") == family for cluster in final_clusters
            )
            for family in sorted({
                str(cluster["root"].get("family") or "unknown")
                for cluster in final_clusters
            })
        },
    })
    violations = validate_report(report)
    if violations:
        raise ValueError("invalid_session_report:" + ";".join(violations))
    return report


def write_session_report(path: Path, report: Mapping[str, Any]) -> None:
    violations = validate_report(report)
    if violations:
        raise ValueError("invalid_session_report:" + ";".join(violations))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
