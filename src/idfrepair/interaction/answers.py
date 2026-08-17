"""Compile user answers into standard candidates without bypassing gates."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from idfrepair.candidates.base import CandidateContext, candidate_identity
from idfrepair.domain.enums import OperationKind, Provenance, QuestionType, RiskLevel
from idfrepair.domain.errors import SessionStateError
from idfrepair.domain.models import (
    CandidateEvidence,
    RepairCandidate,
    RepairOperation,
    UserAnswer,
    UserQuestion,
)


def answer_to_candidate(
    question: UserQuestion,
    answer: UserAnswer,
    candidates: tuple[RepairCandidate, ...],
    context: CandidateContext | None = None,
) -> RepairCandidate | None:
    if answer.question_id != question.question_id:
        raise SessionStateError("answer_question_identity_mismatch")
    if answer.value is None or (
        isinstance(answer.value, str) and answer.value in {"", "decline", "abort"}
    ):
        return None
    if question.question_type in {
        QuestionType.CHOOSE_CANDIDATE,
        QuestionType.CHOOSE_REFERENCE,
        QuestionType.CONFIRM_GEOMETRY,
        QuestionType.CONFIRM_VERSION,
    }:
        candidate_id = answer.value.get("candidate_id") if isinstance(answer.value, Mapping) else answer.value
        matches = [candidate for candidate in candidates if candidate.candidate_id == candidate_id]
        if len(matches) != 1:
            raise SessionStateError("selected_candidate_not_found")
        return replace(
            matches[0],
            requires_user_confirmation=False,
            provenance=Provenance.USER_SELECTED,
            metadata={**dict(matches[0].metadata), "user_question_id": question.question_id},
        )
    if question.question_type is QuestionType.ENTER_FIELD_VALUE:
        if context is None:
            raise SessionStateError("field_answer_requires_candidate_context")
        value = answer.value.get("value") if isinstance(answer.value, Mapping) else answer.value
        if not isinstance(value, (str, int, float, bool)):
            raise SessionStateError("field_answer_must_be_scalar")
        metadata = question.metadata
        try:
            kind = OperationKind(str(metadata.get("operation", "replace_field")))
            object_index = int(metadata["object_index"])
            field_index = int(metadata["field_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionStateError("field_question_target_invalid") from exc
        if kind not in {
            OperationKind.REPLACE_FIELD,
            OperationKind.RENAME_REFERENCE,
            OperationKind.UPDATE_VERSION,
        }:
            raise SessionStateError("field_question_operation_forbidden")
        operation = RepairOperation(
            kind=kind,
            object_type=str(metadata["object_type"]),
            object_name=str(metadata["object_name"]) if metadata.get("object_name") is not None else None,
            object_index=object_index,
            field_index=field_index,
            field_name=str(metadata["field_name"]) if metadata.get("field_name") is not None else None,
            old_value=str(metadata.get("current_value", "")),
            new_value=str(value),
        )
        identity = candidate_identity(
            provider="user_input",
            root_id=question.root_id,
            input_sha256=context.input_sha256,
            operations=(operation,),
        )
        return RepairCandidate(
            candidate_id=identity,
            provider="user_input",
            root_id=question.root_id,
            family=str(question.metadata.get("family", "schema")),
            operations=(operation,),
            evidence=(CandidateEvidence(
                kind="user_supplied_value",
                source=question.question_id,
                strength=1.0,
            ),),
            risk=RiskLevel.MEDIUM,
            confidence=1.0,
            input_sha256=context.input_sha256,
            idd_sha256=context.idd_sha256,
            version=context.version,
            requires_user_confirmation=False,
            provenance=Provenance.USER_SUPPLIED,
            metadata={"user_question_id": question.question_id},
        )
    raise SessionStateError("answer_requires_specialized_compiler")
