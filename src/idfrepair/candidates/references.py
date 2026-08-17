"""IDD object-list reference candidates."""

from __future__ import annotations

from collections import defaultdict

from idfrepair.candidates.base import CandidateContext, CandidateProvider, candidate_identity
from idfrepair.candidates.finite_keys import _project_case
from idfrepair.candidates.schema import _unique_typo
from idfrepair.diagnostics.semantic_preflight import bounded_unique_choice
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import CandidateEvidence, RepairCandidate, RepairOperation
from idfrepair.io.idf import canonical, changed_fields


class ReferenceProvider(CandidateProvider):
    name = "object_reference"
    families = frozenset({"object_reference", "schema", "reference"})

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        reference_names: dict[str, set[str]] = defaultdict(set)
        for obj in context.document.objects:
            definition = context.idd.get(obj.object_type)
            if definition is None:
                continue
            for field in definition.fields:
                for reference in field.references:
                    if field.index <= len(obj.fields) and obj.fields[field.index - 1].value:
                        reference_names[canonical(reference)].add(obj.fields[field.index - 1].value)
        if root.metadata.get("semantic_issue") is True:
            if root.metadata.get("recoverability") != "RECOVERABLE":
                return ()
            object_index = root.metadata.get("object_index")
            field_index = root.metadata.get("field_index")
            if not isinstance(object_index, int) or not isinstance(field_index, int):
                return ()
            if not 0 <= object_index < len(context.document.objects):
                return ()
            obj = context.document.objects[object_index]
            definition = context.idd.get(obj.object_type)
            field_def = definition.field_at(field_index) if definition else None
            if (
                field_def is None
                or not field_def.object_lists
                or field_index > len(obj.fields)
                or field_def.role == "schedule_reference"
            ):
                return ()
            field = obj.fields[field_index - 1]
            choices = tuple(sorted({
                value
                for object_list in field_def.object_lists
                for value in reference_names.get(canonical(object_list), set())
            }, key=canonical))
            selected = bounded_unique_choice(field.value, choices)
            if selected is None or selected[0] != root.metadata.get("bounded_candidate"):
                return ()
            operation = RepairOperation(
                kind=OperationKind.RENAME_REFERENCE,
                object_type=obj.object_type,
                object_name=obj.name or None,
                object_index=obj.index,
                field_index=field.index,
                field_name=field_def.name,
                old_value=field.value,
                new_value=_project_case(field.value, selected[0]),
                metadata={"semantic_issue_id": root.root_id},
            )
            identity = candidate_identity(
                provider=self.name,
                root_id=root.root_id,
                input_sha256=context.input_sha256,
                operations=(operation,),
            )
            return (RepairCandidate(
                candidate_id=identity,
                provider=self.name,
                root_id=root.root_id,
                family="object_reference",
                operations=(operation,),
                evidence=(
                    CandidateEvidence(
                        kind="current_idd_object_list",
                        source="Energy+.idd_object_graph",
                        strength=1.0,
                        details={
                            "choice_count": len(choices),
                            "field_role": field_def.role,
                            "object_lists": field_def.object_lists,
                        },
                    ),
                    CandidateEvidence(
                        kind="unique_bounded_typo",
                        source="whole_file_semantic_preflight",
                        strength=1.0,
                        details={"edit_distance": selected[1]},
                    ),
                ),
                risk=RiskLevel.LOW,
                confidence=0.99,
                input_sha256=context.input_sha256,
                idd_sha256=context.idd_sha256,
                version=context.version,
                metadata={
                    "mechanism": "current_idd_object_list_unique_typo",
                    "no_competing_solution": True,
                },
            ),)
        rows = []
        diagnostic = canonical(context.diagnostics_text)
        for obj in context.document.objects:
            definition = context.idd.get(obj.object_type)
            if definition is None:
                continue
            for field in obj.fields:
                field_def = definition.field_at(field.index)
                if field_def is None or not field_def.object_lists or not field.value:
                    continue
                choices = sorted({
                    value
                    for object_list in field_def.object_lists
                    for value in reference_names.get(canonical(object_list), set())
                })
                if not choices or any(canonical(field.value) == canonical(value) for value in choices):
                    continue
                if canonical(field.value) not in diagnostic:
                    continue
                proposed = _unique_typo(field.value, choices)
                if proposed is None:
                    continue
                operation = RepairOperation(
                    kind=OperationKind.RENAME_REFERENCE,
                    object_type=obj.object_type,
                    object_name=obj.name or None,
                    object_index=obj.index,
                    field_index=field.index,
                    field_name=field_def.name,
                    old_value=field.value,
                    new_value=proposed,
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
                    family=root.family,
                    operations=(operation,),
                    evidence=(CandidateEvidence(
                        kind="idd_object_list",
                        source="object_graph",
                        strength=0.9,
                        details={"choice_count": len(choices), "field_role": field_def.role},
                    ),),
                    risk=RiskLevel.LOW,
                    confidence=0.9,
                    input_sha256=context.input_sha256,
                    idd_sha256=context.idd_sha256,
                    version=context.version,
                ))
        return tuple(rows)

    def validate_semantics(self, before, after, candidate, context):  # type: ignore[no-untyped-def]
        operation = candidate.operations[0]
        changes = changed_fields(before, after)
        expected = ((
            operation.object_index,
            operation.field_index,
            operation.old_value,
            operation.new_value,
        ),)
        passed = changes == expected
        return passed, (() if passed else ("reference_patch_scope_changed",)), {"changes": changes}
