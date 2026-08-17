"""Repair semantic pollution proven by an exact historical Transition lineage."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re
from types import MappingProxyType
from typing import Any, Sequence

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import (
    CandidateEvidence,
    DiagnosticRoot,
    RepairCandidate,
    RepairOperation,
)
from idfrepair.io.idf import canonical, changed_fields, parse_idf
from idfrepair.knowledge.idd import IDDSchema, parse_idd
from idfrepair.knowledge.provenance import semantic_multiset


_TRANSITION_LINEAGE_RUNTIME_TOKEN = object()


class _VerifiedTransitionLineage(Mapping[str, Any]):
    """Immutable in-process evidence accepted only through the internal channel."""

    __slots__ = ("_payload",)

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        token: object,
    ) -> None:
        if token is not _TRANSITION_LINEAGE_RUNTIME_TOKEN:
            raise ValueError("transition_lineage_runtime_token_invalid")
        object.__setattr__(
            self,
            "_payload",
            MappingProxyType(dict(payload)),
        )

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("verified_transition_lineage_is_immutable")

    def __getitem__(self, key: str) -> Any:
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)


def _verified_transition_lineage_from_runtime(
    payload: Mapping[str, Any],
) -> _VerifiedTransitionLineage:
    """Create evidence after the internal runner has verified copied artifacts."""
    return _VerifiedTransitionLineage(
        payload,
        token=_TRANSITION_LINEAGE_RUNTIME_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class TransitionYearPlan:
    operations: tuple[RepairOperation, ...]
    source_version: str
    target_version: str
    source_idd_sha256: str
    transition_executable_sha256: str
    source_sha256: str
    generated_sha256: str
    source_text_sha256: str
    generated_text_sha256: str
    transition_companion_tree_sha256: str


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _field_index(definition, name: str) -> int | None:  # type: ignore[no-untyped-def]
    matches = [
        field.index for field in definition.fields
        if canonical(field.name) == canonical(name)
    ]
    return matches[0] if len(matches) == 1 else None


def build_transition_year_plan(
    current_text: str,
    *,
    target_idd: IDDSchema,
    metadata: Mapping[str, Any],
) -> TransitionYearPlan | None:
    lineage = metadata.get("transition_lineage")
    if not isinstance(lineage, _VerifiedTransitionLineage):
        return None
    source_text = lineage.get("source_text")
    generated_text = lineage.get("generated_text")
    source_idd_text = lineage.get("source_idd_text")
    if (
        not isinstance(source_text, str)
        or not isinstance(generated_text, str)
        or not isinstance(source_idd_text, str)
        or lineage.get("verified") is not True
    ):
        return None
    source_idd = parse_idd(source_idd_text)
    verified_target_idd = parse_idd(target_idd.text)
    current = parse_idf(current_text)
    generated = parse_idf(generated_text)
    source = parse_idf(source_text)
    if semantic_multiset(current) != semantic_multiset(generated):
        return None
    if (
        canonical(source.version) == canonical(current.version)
        or canonical(source_idd.version) != canonical(source.version)
        or canonical(verified_target_idd.version) != canonical(current.version)
        or lineage.get("source_idd_sha256") != source_idd.sha256
        or lineage.get("target_idd_sha256") != verified_target_idd.sha256
    ):
        return None
    source_definition = source_idd.get("RunPeriod")
    target_definition = verified_target_idd.get("RunPeriod")
    if source_definition is None or target_definition is None:
        return None
    repeat_index = _field_index(
        source_definition, "Number of Times Runperiod to be Repeated",
    )
    start_year_index = _field_index(source_definition, "Start Year")
    begin_year_index = _field_index(target_definition, "Begin Year")
    end_year_index = _field_index(target_definition, "End Year")
    if None in {
        repeat_index, start_year_index, begin_year_index, end_year_index,
    }:
        return None
    source_rows = {
        canonical(obj.name): obj for obj in source.find_objects("RunPeriod")
    }
    current_rows = current.find_objects("RunPeriod")
    if (
        not current_rows
        or len(source_rows) != len(current_rows)
        or len(source_rows) != len(source.find_objects("RunPeriod"))
    ):
        return None
    operations: list[RepairOperation] = []
    for obj in current_rows:
        original = source_rows.get(canonical(obj.name))
        if original is None:
            return None
        repeat_value = (
            original.fields[repeat_index - 1].value
            if repeat_index <= len(original.fields)
            else source_definition.field_at(repeat_index).default or ""
        )
        start_year = (
            original.fields[start_year_index - 1].value.strip()
            if start_year_index <= len(original.fields) else ""
        )
        try:
            repeat_count = Decimal(repeat_value.strip())
        except InvalidOperation:
            return None
        if not repeat_count.is_finite() or repeat_count != Decimal(1) or start_year:
            return None
        for field_index, field_name in (
            (begin_year_index, "Begin Year"),
            (end_year_index, "End Year"),
        ):
            if field_index > len(obj.fields):
                return None
            value = obj.fields[field_index - 1].value
            if not value.strip():
                continue
            try:
                int(value)
            except ValueError:
                return None
            operations.append(RepairOperation(
                kind=OperationKind.REPLACE_FIELD,
                object_type=obj.object_type,
                object_name=obj.name or None,
                object_index=obj.index,
                field_index=field_index,
                field_name=field_name,
                old_value=value,
                new_value="",
            ))
    if not operations:
        return None
    required_hashes = (
        "source_sha256",
        "generated_sha256",
        "source_text_sha256",
        "generated_text_sha256",
        "transition_companion_tree_sha256",
        "transition_executable_sha256",
    )
    if any(not _is_sha256(lineage.get(key)) for key in required_hashes):
        return None
    source_text_sha256 = sha256(source_text.encode("utf-8")).hexdigest()
    generated_text_sha256 = sha256(generated_text.encode("utf-8")).hexdigest()
    if (
        lineage.get("source_text_sha256") != source_text_sha256
        or lineage.get("generated_text_sha256") != generated_text_sha256
    ):
        return None
    return TransitionYearPlan(
        operations=tuple(operations),
        source_version=source.version,
        target_version=current.version,
        source_idd_sha256=source_idd.sha256,
        transition_executable_sha256=str(
            lineage["transition_executable_sha256"]
        ),
        source_sha256=str(lineage["source_sha256"]),
        generated_sha256=str(lineage["generated_sha256"]),
        source_text_sha256=source_text_sha256,
        generated_text_sha256=generated_text_sha256,
        transition_companion_tree_sha256=str(
            lineage["transition_companion_tree_sha256"]
        ),
    )


def transition_lineage_root(
    current_text: str,
    *,
    target_idd: IDDSchema,
    metadata: Mapping[str, Any],
) -> DiagnosticRoot | None:
    plan = build_transition_year_plan(
        current_text, target_idd=target_idd, metadata=metadata,
    )
    if plan is None:
        return None
    payload = "|".join((
        "transition_semantics",
        plan.source_version,
        plan.target_version,
        plan.source_sha256,
        plan.generated_sha256,
        plan.source_text_sha256,
        plan.generated_text_sha256,
        plan.transition_companion_tree_sha256,
    ))
    return DiagnosticRoot(
        root_id=sha256(payload.encode("utf-8")).hexdigest()[:20],
        family="transition_semantics",
        message=(
            "Verified historical Transition lineage inserted RunPeriod years "
            "despite a single, yearless source repetition."
        ),
        severity="Severe",
        object_type="RunPeriod",
        metadata={
            "preflight_recovery_certificate": "transition_lineage_v1",
            "operation_count": len(plan.operations),
            "source_version": plan.source_version,
            "target_version": plan.target_version,
            "source_idd_sha256": plan.source_idd_sha256,
            "transition_executable_sha256": plan.transition_executable_sha256,
            "source_text_sha256": plan.source_text_sha256,
            "generated_text_sha256": plan.generated_text_sha256,
            "transition_companion_tree_sha256": (
                plan.transition_companion_tree_sha256
            ),
        },
    )


class TransitionLineageProvider(CandidateProvider):
    name = "transition_lineage"
    families = frozenset({"transition_semantics"})

    def generate(
        self, root: DiagnosticRoot, context: CandidateContext,
    ) -> Sequence[RepairCandidate]:
        plan = build_transition_year_plan(
            context.document.text,
            target_idd=context.idd,
            metadata=context.metadata,
        )
        if plan is None:
            return ()
        identity = candidate_identity(
            provider=self.name,
            root_id=root.root_id,
            input_sha256=context.input_sha256,
            operations=plan.operations,
        )
        return (RepairCandidate(
            candidate_id=identity,
            provider=self.name,
            root_id=root.root_id,
            family="transition_semantics",
            operations=plan.operations,
            evidence=(
                CandidateEvidence(
                    kind="source_idd_identity",
                    source="sealed_transition_lineage",
                    strength=1.0,
                    details={
                        "version": plan.source_version,
                        "sha256": plan.source_idd_sha256,
                    },
                ),
                CandidateEvidence(
                    kind="transition_executable_identity",
                    source="sealed_transition_lineage",
                    strength=1.0,
                    details={
                        "sha256": plan.transition_executable_sha256,
                        "source_sha256": plan.source_sha256,
                        "generated_sha256": plan.generated_sha256,
                        "source_text_sha256": plan.source_text_sha256,
                        "generated_text_sha256": plan.generated_text_sha256,
                        "transition_companion_tree_sha256": (
                            plan.transition_companion_tree_sha256
                        ),
                    },
                ),
                CandidateEvidence(
                    kind="transition_calendar_semantics",
                    source="source_RunPeriod_and_target_IDD",
                    strength=1.0,
                    details={"operation_count": len(plan.operations)},
                ),
            ),
            risk=RiskLevel.LOW,
            confidence=1.0,
            input_sha256=context.input_sha256,
            idd_sha256=context.idd_sha256,
            version=context.version,
            metadata={
                "historical_mechanism": "transition_runperiod_year_cleanup",
                "source_sha256": plan.source_sha256,
                "generated_sha256": plan.generated_sha256,
            },
        ),)

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        plan = build_transition_year_plan(
            before, target_idd=context.idd, metadata=context.metadata,
        )
        reasons = []
        if plan is None or candidate.operations != plan.operations:
            reasons.append("transition_lineage_plan_identity_mismatch")
        expected = tuple(
            (
                operation.object_index,
                operation.field_index,
                operation.old_value,
                operation.new_value,
            )
            for operation in candidate.operations
        )
        changes = changed_fields(before, after)
        if changes != expected:
            reasons.append("transition_lineage_patch_scope_changed")
        if any(
            operation.object_type != "RunPeriod"
            or operation.field_name not in {"Begin Year", "End Year"}
            or operation.new_value != ""
            for operation in candidate.operations
        ):
            reasons.append("transition_lineage_operation_outside_calendar_scope")
        return not reasons, tuple(reasons), {
            "changes": changes,
            "mechanism": "transition_runperiod_year_cleanup",
        }


__all__ = [
    "TransitionLineageProvider",
    "TransitionYearPlan",
    "build_transition_year_plan",
    "transition_lineage_root",
]
