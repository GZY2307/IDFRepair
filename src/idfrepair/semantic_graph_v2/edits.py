"""定义、编译并 loss-aware 应用 V2 typed semantic edits。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from idfrepair.io.idf import canonical, parse_idf
from idfrepair.semantic_graph_v2.ir import FieldRef


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class SemanticEditKind(_StringEnum):
    REPLACE_TYPED_REFERENCE = "REPLACE_TYPED_REFERENCE"
    REPLACE_ENDPOINT = "REPLACE_ENDPOINT"
    REPLACE_ORDERED_MEMBER = "REPLACE_ORDERED_MEMBER"
    REORDER_PATH_MEMBERS = "REORDER_PATH_MEMBERS"
    REPLACE_LOOP_SIDE_REFERENCE = "REPLACE_LOOP_SIDE_REFERENCE"
    REPLACE_CONNECTOR_MEMBER = "REPLACE_CONNECTOR_MEMBER"


class SemanticEditConflict(ValueError):
    """表示一组 semantic edits 无法安全编译到同一个 source snapshot。"""


@dataclass(frozen=True, slots=True)
class FieldEdit:
    object_index: int
    object_type: str
    object_name: str
    field_index: int
    field_name: str
    old_value: str
    new_value: str

    @property
    def field_id(self) -> str:
        return f"object:{self.object_index}:field:{self.field_index}"


@dataclass(frozen=True, slots=True)
class FieldValuePrecondition:
    """绑定 candidate 读取过的 provenance field 及其 before value。"""

    object_index: int
    object_type: str
    object_name: str
    field_index: int
    field_name: str
    expected_value: str

    @property
    def field_id(self) -> str:
        return f"object:{self.object_index}:field:{self.field_index}"


@dataclass(frozen=True, slots=True)
class RelationStatePrecondition:
    """把非字段 relation/factor read 绑定到 candidate 的 before snapshot。"""

    variable_id: str
    expected_document_sha256: str


@dataclass(frozen=True, slots=True)
class SemanticEdit:
    """一个语义动作；复合 reorder 的多字段 patch 仍计成本 1。"""

    edit_id: str
    kind: SemanticEditKind
    scope_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    resolves_constraint_ids: tuple[str, ...]
    evidence: tuple[tuple[str, str], ...]
    precondition_reads: tuple[str, ...]
    write_variables: tuple[str, ...]
    field_edits: tuple[FieldEdit, ...]
    semantic_signature: str
    field_preconditions: tuple[FieldValuePrecondition, ...] = ()
    relation_preconditions: tuple[RelationStatePrecondition, ...] = ()
    semantic_cost: int = 1

    def __post_init__(self) -> None:
        if self.semantic_cost != 1:
            raise ValueError("semantic_cost_must_equal_one")
        if not self.field_edits:
            raise ValueError("semantic_edit_has_no_field_edits")
        guarded = {
            f"field:{precondition.field_id}"
            for precondition in self.field_preconditions
        }
        provenance_reads = {
            variable for variable in self.precondition_reads
            if variable.startswith("field:object:") and ":field:" in variable
        }
        if provenance_reads - guarded:
            raise ValueError("field_read_precondition_missing")
        guarded_relations = {
            precondition.variable_id
            for precondition in self.relation_preconditions
        }
        relation_reads = set(self.precondition_reads) - provenance_reads
        if relation_reads - guarded_relations:
            raise ValueError("relation_read_precondition_missing")

    @property
    def field_cost(self) -> int:
        return len({field.field_id for field in self.field_edits})


def compile_field_edit(field: FieldRef, new_value: str) -> FieldEdit:
    """将 provenance FieldRef 编译为 exact old-value-guarded replacement。"""

    if canonical(new_value) == field.normalized_value:
        raise ValueError("field_edit_is_semantic_noop")
    return FieldEdit(
        object_index=field.object_index,
        object_type=field.object_type,
        object_name=field.object_name,
        field_index=field.field_index,
        field_name=field.field_name,
        old_value=field.raw_value,
        new_value=new_value,
    )


def make_semantic_edit(
    *,
    kind: SemanticEditKind,
    scope_ids: tuple[str, ...],
    relation_ids: tuple[str, ...],
    resolves_constraint_ids: tuple[str, ...],
    evidence: tuple[tuple[str, str], ...],
    precondition_reads: tuple[str, ...],
    write_variables: tuple[str, ...],
    field_edits: tuple[FieldEdit, ...],
    semantic_signature: str,
    field_preconditions: tuple[FieldValuePrecondition, ...] = (),
    relation_preconditions: tuple[RelationStatePrecondition, ...] = (),
) -> SemanticEdit:
    """构造稳定、去顺序歧义的 semantic edit identity。"""

    signature = semantic_signature.strip()
    if not signature:
        raise ValueError("semantic_signature_missing")
    return SemanticEdit(
        edit_id=f"edit:{kind.value.casefold()}:{signature}",
        kind=kind,
        scope_ids=tuple(sorted(set(scope_ids))),
        relation_ids=tuple(sorted(set(relation_ids))),
        resolves_constraint_ids=tuple(sorted(set(resolves_constraint_ids))),
        evidence=tuple(sorted(set(evidence))),
        precondition_reads=tuple(sorted(set(precondition_reads))),
        write_variables=tuple(sorted(set(write_variables))),
        field_edits=tuple(sorted(
            field_edits, key=lambda row: (row.object_index, row.field_index)
        )),
        semantic_signature=signature,
        field_preconditions=tuple(sorted(
            set(field_preconditions),
            key=lambda row: (row.object_index, row.field_index),
        )),
        relation_preconditions=tuple(sorted(
            set(relation_preconditions), key=lambda row: row.variable_id,
        )),
    )


def _validate_preconditions(document, edits: tuple[SemanticEdit, ...]) -> None:  # type: ignore[no-untyped-def]
    selected_fields: dict[tuple[int, int], FieldValuePrecondition] = {}
    for edit in edits:
        for precondition in edit.field_preconditions:
            key = (precondition.object_index, precondition.field_index)
            prior = selected_fields.get(key)
            if prior is not None and prior != precondition:
                raise SemanticEditConflict(
                    f"conflicting_field_precondition:{precondition.field_id}"
                )
            selected_fields[key] = precondition

    for (object_index, field_index), precondition in selected_fields.items():
        if not 0 <= object_index < len(document.objects):
            raise SemanticEditConflict("field_precondition_object_out_of_range")
        obj = document.objects[object_index]
        if canonical(obj.object_type) != canonical(precondition.object_type):
            raise SemanticEditConflict("field_precondition_object_type_mismatch")
        if canonical(obj.name) != canonical(precondition.object_name):
            raise SemanticEditConflict("field_precondition_object_name_mismatch")
        if not 1 <= field_index <= len(obj.fields):
            raise SemanticEditConflict("field_precondition_index_out_of_range")
        if obj.fields[field_index - 1].value != precondition.expected_value:
            raise SemanticEditConflict(
                f"field_precondition_value_mismatch:{precondition.field_id}"
            )

    for edit in edits:
        for precondition in edit.relation_preconditions:
            if document.sha256 != precondition.expected_document_sha256:
                raise SemanticEditConflict(
                    "relation_precondition_snapshot_mismatch:"
                    f"{precondition.variable_id}"
                )


def apply_semantic_edits(text: str, edits: tuple[SemanticEdit, ...]) -> str:
    """在原 snapshot 上原子应用 edits，保留所有未触及 bytes。"""

    document = parse_idf(text)
    _validate_preconditions(document, edits)
    selected: dict[tuple[int, int], FieldEdit] = {}
    for edit in edits:
        for field_edit in edit.field_edits:
            key = (field_edit.object_index, field_edit.field_index)
            prior = selected.get(key)
            if prior is not None:
                if (
                    prior.new_value != field_edit.new_value
                    or prior.old_value != field_edit.old_value
                ):
                    raise SemanticEditConflict(
                        f"conflicting_field_write:{field_edit.field_id}"
                    )
                continue
            selected[key] = field_edit

    replacements: list[tuple[int, int, str]] = []
    for (object_index, field_index), field_edit in selected.items():
        if not 0 <= object_index < len(document.objects):
            raise SemanticEditConflict("object_index_out_of_range")
        obj = document.objects[object_index]
        if canonical(obj.object_type) != canonical(field_edit.object_type):
            raise SemanticEditConflict("object_type_identity_mismatch")
        if canonical(obj.name) != canonical(field_edit.object_name):
            raise SemanticEditConflict("object_name_identity_mismatch")
        if not 1 <= field_index <= len(obj.fields):
            raise SemanticEditConflict("field_index_out_of_range")
        field = obj.fields[field_index - 1]
        if field.value != field_edit.old_value:
            raise SemanticEditConflict("field_old_value_mismatch")
        if field_edit.new_value == field.value:
            raise SemanticEditConflict("field_replacement_is_noop")
        replacements.append((field.start, field.end, field_edit.new_value))

    repaired = text
    for start, end, value in sorted(replacements, reverse=True):
        repaired = repaired[:start] + value + repaired[end:]
    return repaired


__all__ = [
    "FieldEdit",
    "FieldValuePrecondition",
    "RelationStatePrecondition",
    "SemanticEdit",
    "SemanticEditConflict",
    "SemanticEditKind",
    "apply_semantic_edits",
    "compile_field_edit",
    "make_semantic_edit",
]
