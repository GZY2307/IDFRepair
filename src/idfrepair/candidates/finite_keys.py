'''
为当前版本 IDD 的有限 key 字段生成唯一 typo 修复候选。

FiniteKeyProvider.generate(): 仅接受字段绑定的 recoverable SemanticIssue。
'''

from __future__ import annotations

from idfrepair.candidates.base import (
    CandidateContext,
    CandidateProvider,
    candidate_identity,
)
from idfrepair.diagnostics.semantic_preflight import bounded_unique_choice
from idfrepair.domain.enums import OperationKind, RiskLevel
from idfrepair.domain.models import (
    CandidateEvidence,
    RepairCandidate,
    RepairOperation,
)
from idfrepair.io.idf import canonical, changed_fields


def _project_case(faulty: str, selected: str) -> str:
    '''沿最短编辑对齐继承原字段大小写，同时保留插入字符的 IDD 风格。'''
    left = faulty.casefold()
    right = selected.casefold()
    if len(left) == len(right):
        differing = [
            index
            for index, (source, target) in enumerate(zip(left, right))
            if source != target
        ]
        if (
            len(differing) == 2
            and differing[1] == differing[0] + 1
            and left[differing[0]] == right[differing[1]]
            and left[differing[1]] == right[differing[0]]
        ):
            projected = list(faulty)
            projected[differing[0]], projected[differing[1]] = (
                projected[differing[1]],
                projected[differing[0]],
            )
            return "".join(projected)
    # A single surviving letter is not enough evidence for a whole-token case
    # convention.  In that case the exact current-version IDD spelling wins.
    if len(faulty) >= 2 and faulty.isupper():
        return selected.upper()
    # Lowercase surviving text is only evidence for characters that align to
    # it.  A deleted leading letter may carry an independent case convention
    # (for example an uppercase material-name prefix), so defer lowercase
    # projection to the edit alignment below.
    table = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for row in range(len(left) + 1):
        table[row][0] = row
    for column in range(len(right) + 1):
        table[0][column] = column
    for row in range(1, len(left) + 1):
        for column in range(1, len(right) + 1):
            table[row][column] = min(
                table[row - 1][column] + 1,
                table[row][column - 1] + 1,
                table[row - 1][column - 1]
                + int(left[row - 1] != right[column - 1]),
            )
    aligned: dict[int, int] = {}
    row = len(left)
    column = len(right)
    while row or column:
        if row and column and table[row][column] == (
            table[row - 1][column - 1]
            + int(left[row - 1] != right[column - 1])
        ):
            aligned[column - 1] = row - 1
            row -= 1
            column -= 1
        elif column and table[row][column] == table[row][column - 1] + 1:
            column -= 1
        else:
            row -= 1
    projected = list(selected)
    for selected_index, faulty_index in aligned.items():
        character = projected[selected_index]
        source = faulty[faulty_index]
        if character.isalpha() and source.isalpha():
            projected[selected_index] = (
                character.upper() if source.isupper() else character.lower()
            )
    for selected_index, character in enumerate(projected):
        if selected_index in aligned or not character.isalpha():
            continue
        token_start = selected_index
        token_end = selected_index + 1
        while token_start and selected[token_start - 1].isalnum():
            token_start -= 1
        while token_end < len(selected) and selected[token_end].isalnum():
            token_end += 1
        inherited = [
            faulty[source_index]
            for target_index, source_index in aligned.items()
            if token_start <= target_index < token_end
            and faulty[source_index].isalpha()
        ]
        # At least two surviving letters are required before inferring the case
        # of a deleted character.  This keeps N -> No bound to the IDD spelling.
        if len(inherited) < 2:
            continue
        left_source = next((
            faulty[aligned[index]]
            for index in range(selected_index - 1, token_start - 1, -1)
            if index in aligned and faulty[aligned[index]].isalpha()
        ), None)
        right_source = next((
            faulty[aligned[index]]
            for index in range(selected_index + 1, token_end)
            if index in aligned and faulty[aligned[index]].isalpha()
        ), None)
        if all(source.isupper() for source in inherited):
            projected[selected_index] = character.upper()
        elif all(source.islower() for source in inherited):
            projected[selected_index] = character.lower()
        elif (
            (left_source is not None and left_source.islower())
            or (right_source is not None and right_source.islower())
        ):
            projected[selected_index] = character.lower()
    return "".join(projected)


class FiniteKeyProvider(CandidateProvider):
    '''只修复 IDD 明确列举且唯一最近的有限 key。'''

    name = "finite_key"
    families = frozenset({"finite_key"})

    def generate(self, root, context):  # type: ignore[no-untyped-def]
        if (
            root.metadata.get("semantic_issue") is not True
            or root.metadata.get("recoverability") != "RECOVERABLE"
        ):
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
        if field_def is None or not field_def.keys or field_index > len(obj.fields):
            return ()
        field = obj.fields[field_index - 1]
        selected = bounded_unique_choice(field.value, field_def.keys)
        if selected is None or selected[0] != root.metadata.get("bounded_candidate"):
            return ()
        operation = RepairOperation(
            kind=OperationKind.REPLACE_FIELD,
            object_type=obj.object_type,
            object_name=obj.name or None,
            object_index=obj.index,
            field_index=field.index,
            field_name=field_def.name,
            old_value=field.value,
            new_value=_project_case(field.value, selected[0]),
            metadata={
                "finite_key_count": len(field_def.keys),
                "semantic_issue_id": root.root_id,
            },
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
            family="finite_key",
            operations=(operation,),
            evidence=(
                CandidateEvidence(
                    kind="current_version_idd_finite_key",
                    source="Energy+.idd",
                    strength=1.0,
                    details={"keys": field_def.keys},
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
                "continuous_numeric_forbidden": True,
                "mechanism": "current_idd_finite_key_unique_typo",
            },
        ),)

    def validate_semantics(
        self,
        before: str,
        after: str,
        candidate: RepairCandidate,
        context: CandidateContext,
    ):  # type: ignore[no-untyped-def]
        operation = candidate.operations[0]
        changes = changed_fields(before, after)
        expected = ((
            operation.object_index,
            operation.field_index,
            operation.old_value,
            operation.new_value,
        ),)
        definition = context.idd.get(operation.object_type or "")
        field_def = (
            definition.field_at(operation.field_index or 0) if definition else None
        )
        legal = bool(
            field_def is not None
            and any(
                canonical(operation.new_value or "") == canonical(key)
                for key in field_def.keys
            )
        )
        reasons = []
        if changes != expected:
            reasons.append("finite_key_patch_scope_changed")
        if not legal:
            reasons.append("finite_key_not_in_bound_idd")
        return not reasons, tuple(reasons), {
            "changes": changes,
            "current_idd_key_legal": legal,
        }


__all__ = ["FiniteKeyProvider"]
