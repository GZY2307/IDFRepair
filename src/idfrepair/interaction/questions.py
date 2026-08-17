"""Question construction for non-identifiable repair intent."""

from __future__ import annotations

from uuid import uuid4

from idfrepair.candidates.base import CandidateContext
from idfrepair.domain.enums import QuestionType
from idfrepair.domain.models import DiagnosticRoot, RepairCandidate, UserQuestion, to_primitive
from idfrepair.io.idf import canonical


def question_for_candidates(
    root: DiagnosticRoot,
    candidates: tuple[RepairCandidate, ...],
) -> UserQuestion:
    if root.family == "reference_schedule":
        question_type = QuestionType.CHOOSE_REFERENCE
        prompt = "Choose the intended Schedule reference. The answer will still be validated."
    elif root.family == "version_migration":
        question_type = QuestionType.CONFIRM_VERSION
        prompt = "Confirm the intended EnergyPlus target version."
    elif root.family == "geometry":
        question_type = QuestionType.CONFIRM_GEOMETRY
        prompt = "Confirm the intended polygon topology."
    elif candidates:
        question_type = QuestionType.CHOOSE_CANDIDATE
        prompt = "Choose a candidate to validate, or decline all candidates."
    else:
        question_type = QuestionType.SELECT_REPAIR_FAMILY
        prompt = "Select the intended repair family or leave the input unchanged."
    choices = tuple({
        "candidate_id": candidate.candidate_id,
        "confidence": candidate.confidence,
        "evidence": to_primitive(candidate.evidence),
        "family": candidate.family,
        "operations": to_primitive(candidate.operations),
        "provider": candidate.provider,
        "risk": candidate.risk.value,
    } for candidate in candidates)
    return UserQuestion(
        question_id=uuid4().hex,
        question_type=question_type,
        root_id=root.root_id,
        prompt=prompt,
        choices=choices,
        metadata={"candidate_count": len(candidates)},
    )


def external_file_question(root: DiagnosticRoot, path: str) -> UserQuestion:
    return UserQuestion(
        question_id=uuid4().hex,
        question_type=QuestionType.PROVIDE_EXTERNAL_FILE,
        root_id=root.root_id,
        prompt=f"Provide the required external file: {path}",
        metadata={"relative_path": path},
    )


def field_value_question(
    root: DiagnosticRoot,
    *,
    object_type: str,
    object_name: str | None,
    object_index: int,
    field_index: int,
    field_name: str | None,
    current_value: str,
) -> UserQuestion:
    """Ask for one field value while binding the answer to an exact target."""
    return UserQuestion(
        question_id=uuid4().hex,
        question_type=QuestionType.ENTER_FIELD_VALUE,
        root_id=root.root_id,
        prompt="Enter the intended field value. It will still pass all validation gates.",
        metadata={
            "current_value": current_value,
            "field_index": field_index,
            "field_name": field_name,
            "object_index": object_index,
            "object_name": object_name,
            "object_type": object_type,
            "operation": "replace_field",
        },
    )


def object_question(
    root: DiagnosticRoot,
    choices: tuple[dict[str, object], ...],
) -> UserQuestion:
    return UserQuestion(
        question_id=uuid4().hex,
        question_type=QuestionType.CHOOSE_OBJECT,
        root_id=root.root_id,
        prompt="Choose the intended target object.",
        choices=choices,
        metadata={"choice_count": len(choices)},
    )


def question_for_context(
    root: DiagnosticRoot,
    candidates: tuple[RepairCandidate, ...],
    context: CandidateContext,
) -> UserQuestion | None:
    '''按错误语义构造专用问题；无法有限绑定时退回错误类型选择。'''
    if candidates:
        return question_for_candidates(root, candidates)
    if root.family == "external_dependency":
        raw_path = root.metadata.get("relative_path") or root.object_name
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None
        path = raw_path.strip()
        return external_file_question(root, path)
    field_index = root.metadata.get("field_index")
    matches = tuple(
        obj for obj in context.document.objects
        if root.object_type and canonical(obj.object_type) == canonical(root.object_type)
        and (not root.object_name or canonical(obj.name) == canonical(root.object_name))
    )
    if len(matches) > 1:
        choices = tuple({
            "label": f"{obj.object_type}: {obj.name or '#' + str(obj.index)}",
            "value": {
                "object_index": obj.index,
                "object_name": obj.name or None,
                "object_type": obj.object_type,
            },
        } for obj in matches[:50])
        return object_question(root, choices)
    if len(matches) == 1 and isinstance(field_index, int):
        obj = matches[0]
        if 1 <= field_index <= len(obj.fields):
            definition = context.idd.get(obj.object_type)
            field_definition = definition.field_at(field_index) if definition else None
            return field_value_question(
                root,
                object_type=obj.object_type,
                object_name=obj.name or None,
                object_index=obj.index,
                field_index=field_index,
                field_name=field_definition.name if field_definition else None,
                current_value=obj.fields[field_index - 1].value,
            )
    return question_for_candidates(root, candidates)
