"""RDD-bound typo repair for Output objects."""

from __future__ import annotations

from hashlib import sha256
import json

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import CandidateEvidence, RepairCandidate, RepairOperation
from idfrepair.io.idf import canonical, changed_fields
from idfrepair.knowledge.rdd import unique_variable_match


def _unique_rdd_match(faulty: str, choices: tuple[str, ...]) -> tuple[str, int] | None:
    return unique_variable_match(faulty, choices)


def _runtime_binding(context: CandidateContext) -> tuple[bool, dict[str, object]]:
    identity = context.runtime_identity
    runtime_version = str(identity.get("energyplus_version") or "")
    runtime_idd = str(identity.get("idd_sha256") or "")
    executable_sha = str(identity.get("energyplus_executable_sha256") or "")
    details: dict[str, object] = {
        "energyplus_version": runtime_version,
        "energyplus_executable_sha256": executable_sha,
        "idd_sha256": runtime_idd,
        "rdd_sha256": context.rdd.sha256,
        "input_sha256": context.input_sha256,
    }
    return bool(
        runtime_version
        and canonical(runtime_version) == canonical(context.version)
        and runtime_idd == context.idd_sha256
        and executable_sha
        and context.rdd.text.strip()
    ), details


def _context_sha(obj, variable_field_index: int, root) -> str:  # type: ignore[no-untyped-def]
    payload = {
        "fields": [
            (field.index, field.value)
            for field in obj.fields if field.index != variable_field_index
        ],
        "frequency": root.metadata.get("frequency"),
        "key_value": root.metadata.get("key_value"),
        "object_index": obj.index,
        "object_type": canonical(obj.object_type),
        "variable_field_index": variable_field_index,
    }
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class OutputProvider(CandidateProvider):
    name = "rdd_output"
    families = frozenset({"output_variable"})

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        choices = context.rdd.variable_names
        runtime_valid, runtime_details = _runtime_binding(context)
        if not choices or not runtime_valid or root.metadata.get("ambiguous_output_target_count"):
            return ()
        rows = []
        diagnostics = canonical(context.diagnostics_text)
        for obj in context.document.objects:
            if not canonical(obj.object_type).startswith("output:"):
                continue
            definition = context.idd.get(obj.object_type)
            if definition is None:
                continue
            for field in obj.fields:
                field_def = definition.field_at(field.index)
                if field_def is None or field_def.role != "output_variable":
                    continue
                bound_index = root.metadata.get("object_index")
                bound_field = root.metadata.get("field_index")
                if isinstance(bound_index, int) and obj.index != bound_index:
                    continue
                if isinstance(bound_field, int) and field.index != bound_field:
                    continue
                bound_variable = root.metadata.get("variable_name")
                if isinstance(bound_variable, str) and canonical(field.value) != canonical(bound_variable):
                    continue
                if (
                    root.metadata.get("semantic_issue") is not True
                    and canonical(field.value) not in diagnostics
                ):
                    continue
                selected = _unique_rdd_match(field.value, choices)
                if selected is None:
                    continue
                proposed, distance = selected
                bounded = root.metadata.get("bounded_candidate")
                if (
                    root.metadata.get("semantic_issue") is True
                    and (
                        root.metadata.get("recoverability") != "RECOVERABLE"
                        or not isinstance(bounded, str)
                        or canonical(proposed) != canonical(bounded)
                    )
                ):
                    continue
                operation = RepairOperation(
                    kind=OperationKind.REPLACE_FIELD,
                    object_type=obj.object_type,
                    object_name=obj.name or None,
                    object_index=obj.index,
                    field_index=field.index,
                    field_name=field_def.name,
                    old_value=field.value,
                    new_value=proposed,
                    metadata={
                        "output_context_sha256": _context_sha(obj, field.index, root),
                        "key_value": root.metadata.get("key_value"),
                        "frequency": root.metadata.get("frequency"),
                    },
                )
                identity = candidate_identity(
                    provider=self.name,
                    root_id=root.root_id,
                    input_sha256=context.input_sha256,
                    operations=(operation,),
                )
                rows.append(RepairCandidate(
                    candidate_id=identity,
                    provider=self.name,
                    root_id=root.root_id,
                    family="output_variable",
                    operations=(operation,),
                    evidence=(
                        CandidateEvidence(
                            kind="version_bound_rdd",
                            source="eplusout.rdd",
                            strength=1.0,
                            details={**runtime_details, "name_count": len(choices)},
                        ),
                        CandidateEvidence(
                            kind="unique_typo",
                            source="bounded_edit_distance",
                            strength=0.95,
                            details={"edit_distance": distance},
                        ),
                        CandidateEvidence(
                            kind="output_subtype_field_binding",
                            source="current_version_Energy+.idd",
                            strength=1.0,
                            details={
                                "object_type": obj.object_type,
                                "field_index": field.index,
                                "field_name": field_def.name,
                                "key_value": root.metadata.get("key_value"),
                                "frequency": root.metadata.get("frequency"),
                            },
                        ),
                    ),
                    risk=RiskLevel.LOW,
                    confidence=0.96,
                    input_sha256=context.input_sha256,
                    idd_sha256=context.idd_sha256,
                    version=context.version,
                    metadata={
                        "mechanism": "version_bound_rdd_unique_typo",
                        "runtime_binding": runtime_details,
                        "opposed_semantic_term_exclusion": True,
                    },
                ))
        return tuple(rows) if len(rows) == 1 else ()

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        operation = candidate.operations[0]
        changes = changed_fields(before, after)
        expected = ((operation.object_index, operation.field_index, operation.old_value, operation.new_value),)
        exists = context.rdd.contains(operation.new_value or "")
        runtime_valid, runtime_details = _runtime_binding(context)
        reasons = []
        if changes != expected:
            reasons.append("output_patch_scope_changed")
        if not exists:
            reasons.append("replacement_not_in_bound_rdd")
        if not runtime_valid:
            reasons.append("rdd_runtime_identity_not_bound")
        if operation.object_index is None or operation.object_index >= len(context.document.objects):
            reasons.append("output_target_missing")
            context_matches = False
        else:
            obj = context.document.objects[operation.object_index]
            context_matches = operation.metadata.get("output_context_sha256") == _context_sha(
                obj, operation.field_index or 0, type("RootView", (), {"metadata": operation.metadata})(),
            )
            if not context_matches:
                reasons.append("output_key_frequency_context_changed")
        return not reasons, tuple(reasons), {
            "changes": changes,
            "rdd_contains": exists,
            "runtime_binding_valid": runtime_valid,
            "runtime_binding": runtime_details,
            "output_context_matches": context_matches,
        }
