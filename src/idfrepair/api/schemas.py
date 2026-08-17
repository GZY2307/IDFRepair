"""HTTP request and response schemas."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnswerRequest(StrictModel):
    question_id: str
    value: Any


class BatchAnswerRequest(StrictModel):
    question_id: str
    value: Any


class BatchRetryRequest(StrictModel):
    record_ids: list[str] = Field(min_length=1)
    runtime_id: str | None = None
    mode: str | None = None


class SettingsChildRequest(StrictModel):
    mode: str
    runtime_id: str | None = None


class AuditRequest(StrictModel):
    checks: list[str] | None = None
    geometry_tolerance_m: float = Field(default=0.05, ge=1e-8, le=0.05)


class ExperimentalPreviewRequest(StrictModel):
    mechanisms: list[str] | None = None
    snap_absolute_m: float = Field(default=0.05, ge=1e-8, le=0.05)
    snap_relative: float = Field(default=0.001, ge=1e-10, le=0.001)


class ModelPreflightRequest(StrictModel):
    checks: list[str] | None = None
    tolerance_m: float = Field(default=0.05, ge=1e-8, le=0.05)


class ModelPreflightIssue(StrictModel):
    """Complete, uncapped issue artifact returned by model preflight."""

    issue_id: str
    kind: str
    title: str
    explanation: str
    surface_refs: list[str]
    space_refs: list[str]
    before: dict[str, Any]
    after: dict[str, Any]
    locator: dict[str, Any]
    safe_to_apply: bool
    blocking_reasons: list[str]


def _preflight_object_identity(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"object_index", "object_type", "object_name"}
        and isinstance(value.get("object_index"), int)
        and isinstance(value.get("object_type"), str)
        and bool(value.get("object_type"))
        and isinstance(value.get("object_name"), str)
        and bool(value.get("object_name"))
    )


class ModelPreflightReport(StrictModel):
    schema_version: str
    derived_copy_only: bool
    original_input_changed: bool
    input_sha256: str
    tolerance_m: float
    checked_rules: list[str]
    summary: dict[str, Any]
    repair_plans: list[dict[str, Any]]
    issues: list[ModelPreflightIssue]
    audit: dict[str, Any]

    @model_validator(mode="after")
    def validate_plan_identity_contracts(self) -> Self:
        relationship_kinds = {
            "reciprocal_surface_pair", "split_and_pair", "resegment_and_pair",
        }
        for plan in self.repair_plans:
            kind = str(plan.get("kind") or "")
            if kind in relationship_kinds:
                if "construction_source_surface_id" not in plan:
                    raise ValueError("construction_source_surface_id_missing")
                source_id = plan.get("construction_source_surface_id")
                construction_after = plan.get("construction_after")
                surface_ids = plan.get("surface_ids")
                if not isinstance(surface_ids, list) or any(
                    not isinstance(value, str) for value in surface_ids
                ):
                    raise ValueError("construction_source_surface_ids_invalid")
                if source_id is None:
                    continue
                if not construction_after:
                    raise ValueError("construction_source_surface_unexpected")
                if not isinstance(source_id, str) or source_id not in surface_ids:
                    raise ValueError("construction_source_surface_not_participant")
                continue
            if kind != "canonicalize_air_boundary":
                continue
            canonical_identity = plan.get("canonical_object_identity")
            duplicate_identities = plan.get("duplicate_object_identities")
            remove_identities = plan.get("remove_object_identities")
            if (
                not _preflight_object_identity(canonical_identity)
                or canonical_identity["object_type"] != "Construction:AirBoundary"
            ):
                raise ValueError("air_boundary_canonical_identity_invalid")
            if (
                not isinstance(duplicate_identities, list)
                or not isinstance(remove_identities, list)
                or duplicate_identities != remove_identities
                or any(
                    not _preflight_object_identity(row)
                    or row["object_type"] != "Construction:AirBoundary"
                    for row in duplicate_identities
                )
            ):
                raise ValueError("air_boundary_remove_identity_invalid")
            if canonical_identity["object_index"] != plan.get("canonical_object_index"):
                raise ValueError("air_boundary_canonical_identity_mismatch")
            if canonical_identity["object_name"] != plan.get("canonical_name"):
                raise ValueError("air_boundary_canonical_identity_mismatch")
            if [row["object_index"] for row in duplicate_identities] != plan.get(
                "duplicate_object_indices"
            ):
                raise ValueError("air_boundary_remove_identity_mismatch")
            if [row["object_name"] for row in duplicate_identities] != plan.get(
                "duplicate_names"
            ):
                raise ValueError("air_boundary_remove_identity_mismatch")
            for rewrite in plan.get("reference_rewrites", ()):
                if not isinstance(rewrite, dict):
                    raise ValueError("air_boundary_reference_identity_invalid")
                identity = rewrite.get("before_target_identity")
                if (
                    not _preflight_object_identity(identity)
                    or identity["object_type"] not in {
                        "Construction", "Construction:AirBoundary",
                    }
                    or identity["object_index"] != rewrite.get("target_object_index")
                    or identity["object_name"] != rewrite.get("before")
                ):
                    raise ValueError("air_boundary_reference_identity_mismatch")
        return self


class MigrationRequest(StrictModel):
    """Create an official Transition-produced copy for one target runtime."""

    target_runtime_id: str
    run_energyplus: bool = False


class SessionCreated(StrictModel):
    session_id: str
    status: str | None
    message: dict[str, Any] = Field(default_factory=dict)
    production_enabled: bool = False


class SessionSummary(StrictModel):
    session_id: str
    input_name: str
    input_sha256: str
    mode: str
    status: str | None
    questions: list[dict[str, Any]]
    production_enabled: bool = False
    automatic_repair_release_authorized: bool = False
    archived: bool = False
    lifecycle_status: str
    candidate_attempt_count: int = 0
    completed_round_count: int = 0
    committed_candidate_count: int = 0
    created_at: str
    initial_issue_count: int = 0
    remaining_issue_count: int = 0
    actionable_issue_count: int = 0
    related_diagnostic_count: int = 0
    has_renderable_questions: bool = False
    output_changed: bool = False
    model_call_count: int = 0
    model_component_status: dict[str, Any] = Field(default_factory=dict)
    release_profile_id: str = "idfrepair.research_release.v1"
    repair_memory_component_status: dict[str, Any] = Field(default_factory=dict)
    root_support: list[dict[str, Any]] = Field(default_factory=list)
    selected_rule_set_id: str = "default"
    support_coverage_summary: dict[str, Any] = Field(default_factory=dict)
    support_registry_sha256: str
    updated_at: str
    rule_save_available: bool = False
    rule_save_candidates: list[dict[str, Any]] = Field(default_factory=list)
    rule_save_scope_choices: list[str] = Field(default_factory=list)
    message: dict[str, Any] = Field(default_factory=dict)
    source_type: str = "IDF"
    source_input_name: str | None = None
    osm_bridge_status: str | None = None
    osm_writeback_status: str | None = None
    idf_download_url: str | None = None
    osm_download_url: str | None = None
    osm_writeback_report_url: str | None = None
    preflight_status: str | None = None
    preflight_parent_session_id: str | None = None
    preflight_child_session_id: str | None = None
    preflight_summary: dict[str, Any] | None = None
    batch_id: str | None = None
    energyplus_version: str | None = None
    last_completed_action: str | None = None


class RuleSetRequest(StrictModel):
    '''限制网页可创建的规则集字段。'''

    rule_set_id: str | None = None
    name_zh: str
    name_en: str
    description_zh: str = ""
    description_en: str = ""


class RuleSaveRequest(StrictModel):
    '''限制已验证会话可保存的规则身份和作用域。'''

    candidate_id: str
    scope: str
    name_zh: str
    name_en: str
    global_authorized: bool = False
