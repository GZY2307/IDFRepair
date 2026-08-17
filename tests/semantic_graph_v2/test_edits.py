"""验证 typed semantic edits 的 loss-aware 编译与冲突守卫。"""

from __future__ import annotations

import pytest

from idfrepair.io.idf import parse_idf
from idfrepair.semantic_graph_v2.edits import (
    FieldEdit,
    RelationStatePrecondition,
    SemanticEdit,
    SemanticEditConflict,
    SemanticEditKind,
    apply_semantic_edits,
)


TEXT = """! unrelated formatting stays byte-identical
Branch,
  Main Branch,  !- Name
  ,             !- Pressure Drop Curve Name
  Fan:One, Fan A, N0, N1,
  Fan:Two, Fan B, N1, N2;
"""


def _field_edit(field, new_value: str) -> FieldEdit:  # type: ignore[no-untyped-def]
    obj = parse_idf(TEXT).objects[0]
    return FieldEdit(
        object_index=obj.index,
        object_type=obj.object_type,
        object_name=obj.name,
        field_index=field.index,
        field_name=f"field {field.index}",
        old_value=field.value,
        new_value=new_value,
    )


def test_composite_reorder_is_one_semantic_edit_with_guarded_fields() -> None:
    obj = parse_idf(TEXT).objects[0]
    replacements = tuple(
        _field_edit(obj.fields[index - 1], value)
        for index, value in (
            (3, "Fan:Two"), (4, "Fan B"), (5, "N1"), (6, "N2"),
            (7, "Fan:One"), (8, "Fan A"), (9, "N0"), (10, "N1"),
        )
        if obj.fields[index - 1].value != value
    )
    edit = SemanticEdit(
        edit_id="reorder:main",
        kind=SemanticEditKind.REORDER_PATH_MEMBERS,
        scope_ids=("branch-path:0",),
        relation_ids=("branch-path:object:0",),
        resolves_constraint_ids=("V2-BRANCH-CONTINUITY-003",),
        evidence=(("directed_order", "2|1"),),
        precondition_reads=("branch-path:0",),
        write_variables=("branch-path:0:order",),
        field_edits=replacements,
        semantic_signature="branch-order:object:0:2|1",
        relation_preconditions=(RelationStatePrecondition(
            variable_id="branch-path:0",
            expected_document_sha256=parse_idf(TEXT).sha256,
        ),),
    )

    repaired = apply_semantic_edits(TEXT, (edit,))

    assert edit.semantic_cost == 1
    assert len(edit.field_edits) >= 4
    assert "! unrelated formatting stays byte-identical" in repaired
    assert "Fan:Two, Fan B, N1, N2" in repaired
    assert "Fan:One, Fan A, N0, N1" in repaired


def test_conflicting_field_writes_are_rejected() -> None:
    obj = parse_idf(TEXT).objects[0]
    first = _field_edit(obj.fields[3], "Fan X")
    second = _field_edit(obj.fields[3], "Fan Y")
    common = dict(
        kind=SemanticEditKind.REPLACE_TYPED_REFERENCE,
        scope_ids=("branch-member:1",),
        relation_ids=("branch-path:object:0",),
        resolves_constraint_ids=("V2-BRANCH-TYPED-IDENTITY-001",),
        evidence=(),
        precondition_reads=(),
        write_variables=("field:object:0:field:4",),
    )
    edit_a = SemanticEdit(
        edit_id="a", field_edits=(first,), semantic_signature="a", **common,
    )
    edit_b = SemanticEdit(
        edit_id="b", field_edits=(second,), semantic_signature="b", **common,
    )

    with pytest.raises(SemanticEditConflict, match="conflicting_field_write"):
        apply_semantic_edits(TEXT, (edit_a, edit_b))


def test_old_value_and_object_identity_guards_prevent_stale_application() -> None:
    obj = parse_idf(TEXT).objects[0]
    stale = FieldEdit(
        object_index=0,
        object_type="Branch",
        object_name="Other Branch",
        field_index=4,
        field_name="Component 1 Name",
        old_value=obj.fields[3].value,
        new_value="Fan X",
    )
    edit = SemanticEdit(
        edit_id="stale",
        kind=SemanticEditKind.REPLACE_TYPED_REFERENCE,
        scope_ids=("branch-member:1",),
        relation_ids=("branch-path:object:0",),
        resolves_constraint_ids=("V2-BRANCH-TYPED-IDENTITY-001",),
        evidence=(),
        precondition_reads=(),
        write_variables=("field:object:0:field:4",),
        field_edits=(stale,),
        semantic_signature="stale",
    )

    with pytest.raises(SemanticEditConflict, match="object_name_identity_mismatch"):
        apply_semantic_edits(TEXT, (edit,))


def test_provenance_field_read_requires_a_materialized_value_precondition() -> None:
    obj = parse_idf(TEXT).objects[0]
    field_edit = _field_edit(obj.fields[3], "Fan X")

    with pytest.raises(ValueError, match="field_read_precondition_missing"):
        SemanticEdit(
            edit_id="unguarded",
            kind=SemanticEditKind.REPLACE_TYPED_REFERENCE,
            scope_ids=("branch-member:1",),
            relation_ids=("branch-path:object:0",),
            resolves_constraint_ids=("V2-BRANCH-TYPED-IDENTITY-001",),
            evidence=(),
            precondition_reads=("field:object:0:field:4",),
            write_variables=("field:object:0:field:4",),
            field_edits=(field_edit,),
            semantic_signature="unguarded",
        )


def test_relation_read_requires_a_materialized_snapshot_precondition() -> None:
    obj = parse_idf(TEXT).objects[0]
    field_edit = _field_edit(obj.fields[3], "Fan X")

    with pytest.raises(ValueError, match="relation_read_precondition_missing"):
        SemanticEdit(
            edit_id="unguarded-relation",
            kind=SemanticEditKind.REPLACE_TYPED_REFERENCE,
            scope_ids=("branch-member:1",),
            relation_ids=("branch-path:object:0",),
            resolves_constraint_ids=("V2-BRANCH-TYPED-IDENTITY-001",),
            evidence=(),
            precondition_reads=("branch-path:0",),
            write_variables=("field:object:0:field:4",),
            field_edits=(field_edit,),
            semantic_signature="unguarded-relation",
        )
