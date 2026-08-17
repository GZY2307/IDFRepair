"""验证 canonical IR 的 provenance、order 与 snapshot-local identity。"""

from __future__ import annotations

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from idfrepair.semantic_graph_v2.ir import (
    BranchMember,
    BranchPath,
    ModelIR,
    object_ref_from_idf,
)


IDD = parse_idd(r"""!IDD_Version 24.1.0
Fan:Test,
 A1, \field Name
 A2, \field Air Inlet Node Name
 A3; \field Air Outlet Node Name
Branch,
 A1, \field Name
 A2, \field Pressure Drop Curve Name
 A3, \field Component 1 Object Type
     \begin-extensible
 A4, \field Component 1 Name
 A5, \field Component 1 Inlet Node Name
 A6; \field Component 1 Outlet Node Name
     \extensible:4
""")


def test_object_and_field_refs_preserve_source_provenance() -> None:
    document = parse_idf("Fan:Test, Supply Fan , Inlet Node, Outlet Node;\n")
    source = document.objects[0]
    ref = object_ref_from_idf(source, IDD)

    assert ref.object_id == "object:0"
    assert ref.raw_object_type == "Fan:Test"
    assert ref.normalized_object_type == "fan:test"
    assert ref.raw_name == "Supply Fan"
    assert ref.normalized_name == "supply fan"
    assert document.text[ref.start:ref.end] == source.raw

    name = ref.fields[0]
    assert name.field_token == "A1"
    assert name.field_name == "Name"
    assert name.raw_value == "Supply Fan"
    assert name.normalized_value == "supply fan"
    assert document.text[name.start:name.end].strip() == "Supply Fan"


def test_extensible_ordinal_uses_begin_extensible_field() -> None:
    document = parse_idf(
        "Branch,Main,,Fan:Test,Fan A,A0,A1,Fan:Test,Fan B,A1,A2;\n"
    )
    ref = object_ref_from_idf(document.objects[0], IDD)

    assert [field.extensible_ordinal for field in ref.fields[2:6]] == [1, 1, 1, 1]
    assert [field.extensible_ordinal for field in ref.fields[6:10]] == [2, 2, 2, 2]


def test_relation_order_and_model_queries_are_tuple_backed() -> None:
    document = parse_idf(
        "Branch,Main,,Fan:Test,Fan A,A0,A1,Fan:Test,Fan B,A1,A2;\n"
    )
    branch_ref = object_ref_from_idf(document.objects[0], IDD)
    first = BranchMember(
        ordinal=1,
        type_field=branch_ref.fields[2],
        name_field=branch_ref.fields[3],
        inlet_field=branch_ref.fields[4],
        outlet_field=branch_ref.fields[5],
    )
    second = BranchMember(
        ordinal=2,
        type_field=branch_ref.fields[6],
        name_field=branch_ref.fields[7],
        inlet_field=branch_ref.fields[8],
        outlet_field=branch_ref.fields[9],
    )
    branch = BranchPath(
        relation_id="branch:0",
        object_ref=branch_ref,
        members=(first, second),
    )
    model = ModelIR(
        schema_version="idfrepair.semantic-graph-v2.ir.v1",
        document_sha256=document.sha256,
        declared_version=document.version,
        idd_version=IDD.version,
        idd_sha256=IDD.sha256,
        objects=(branch_ref,),
        branches=(branch,),
    )

    assert isinstance(model.objects, tuple)
    assert isinstance(model.branches[0].members, tuple)
    assert model.objects_of_type("BRANCH") == (branch_ref,)
    assert model.resolve_identity("Branch", "Main") == (branch_ref,)
    assert model.relation("branch:0") is branch

