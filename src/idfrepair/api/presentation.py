'''构造只读、可向后兼容的 Web/API 展示元数据。'''

from __future__ import annotations

from typing import Any, Mapping

from idfrepair.diagnostics.clusters import (
    build_issue_clusters,
    has_renderable_questions,
)


def capability_display_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    '''解释能力边界，不复制或替代 capability matching。'''
    model = payload.get("model_component_status", {})
    memory = payload.get("repair_memory_component_status", {})
    counts = payload.get("status_counts", {})
    return {
        "product": {
            "name": "IDFRepair",
            "workbench": "EnergyPlus IDF Repair Workbench",
        },
        "registry_counts": dict(counts) if isinstance(counts, Mapping) else {},
        "version_matching": {
            "safe_auto_policy": "runtime-bound-exact",
            "declared_registry_versions_are_decisive": False,
            "runtime_assets": [
                "EnergyPlus executable",
                "bound IDD",
                "RDD when required",
            ],
        },
        "release_boundaries": {
            "production_enabled": bool(payload.get("production_enabled", False)),
            "automatic_repair_release_authorized": bool(
                payload.get("automatic_repair_release_authorized", False)
            ),
            "model_enabled": bool(
                model.get("model_enabled", False)
                if isinstance(model, Mapping) else False
            ),
            "repair_memory_candidate_generation_enabled": bool(
                memory.get("candidate_generation_enabled", False)
                if isinstance(memory, Mapping) else False
            ),
        },
    }


def session_display_metadata(
    outcome: Mapping[str, Any], *, input_sha256: str,
) -> dict[str, Any]:
    '''从持久 outcome 派生单文件身份和计数，不制造评估指标。'''
    initial = outcome.get("initial_diagnostics", ())
    final = outcome.get("final_diagnostics", ())
    committed = outcome.get("committed_rounds", ())
    output_sha256 = outcome.get("output_sha256")
    initial_clusters = build_issue_clusters(outcome)
    final_clusters = build_issue_clusters({
        **outcome,
        "initial_diagnostics": final,
        "final_diagnostics": final,
        "rounds": (),
        "committed_rounds": (),
    })
    return {
        "initial_issue_count": len(initial) if isinstance(initial, (list, tuple)) else 0,
        "remaining_issue_count": len(final) if isinstance(final, (list, tuple)) else 0,
        "actionable_issue_count": len(final_clusters),
        "related_diagnostic_count": sum(
            len(cluster["related_diagnostics"]) for cluster in initial_clusters
        ),
        "has_renderable_questions": has_renderable_questions(outcome),
        "committed_candidate_count": (
            len(committed) if isinstance(committed, (list, tuple)) else 0
        ),
        "output_changed": bool(
            output_sha256 and str(output_sha256) != input_sha256
        ),
    }


__all__ = ["capability_display_metadata", "session_display_metadata"]
