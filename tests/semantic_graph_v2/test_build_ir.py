"""验证 canonical builder 一次性物化复用的 HVAC relations。"""

from __future__ import annotations

from idfrepair.semantic_graph_v2 import build_model_ir
from idfrepair.semantic_graph_v2.ir import IdentityStatus, LoopSideKind


def test_build_ir_materializes_ordered_branch_members(ir_document, ir_idd) -> None:  # type: ignore[no-untyped-def]
    model = build_model_ir(ir_document, ir_idd)
    branch = next(row for row in model.branches if row.object_ref.raw_name == "Air Branch")

    assert [member.ordinal for member in branch.members] == [1, 2]
    assert [member.object_name for member in branch.members] == ["Fan A", "Fan B"]
    assert [member.inlet_node for member in branch.members] == ["A0", "A1"]
    assert [member.outlet_node for member in branch.members] == ["A1", "A2"]


def test_connector_set_and_order_views_remain_distinct(ir_document, ir_idd) -> None:  # type: ignore[no-untyped-def]
    model = build_model_ir(ir_document, ir_idd)
    pair = model.connector_pairs[0]

    assert pair.splitter is not None and pair.mixer is not None
    assert pair.splitter.parallel_branch_names == ("p1", "p2")
    assert pair.mixer.parallel_branch_names == ("p2", "p1")
    assert pair.splitter.parallel_branch_set == pair.mixer.parallel_branch_set
    branch_list = model.branch_lists[0]
    assert branch_list.normalized_members == ("si", "p2", "p1", "so")


def test_loop_air_and_oa_ownership_relations_are_materialized(ir_document, ir_idd) -> None:  # type: ignore[no-untyped-def]
    model = build_model_ir(ir_document, ir_idd)

    assert len(model.loop_sides) == 1
    assert model.loop_sides[0].side is LoopSideKind.SUPPLY
    assert model.loop_sides[0].branch_list_field.raw_value == "BL1"
    assert model.loop_sides[0].connector_list_field.raw_value == "CL1"
    assert [member.object_name for member in model.air_paths[0].members] == ["ZS1"]
    assert [member.object_name for member in model.equipment_paths[0].members] == [
        "OA Mixer",
    ]


def test_zone_declared_reference_and_inferred_evidence_are_separate(ir_document, ir_idd) -> None:  # type: ignore[no-untyped-def]
    model = build_model_ir(ir_document, ir_idd)
    relation = model.zone_relations[0]

    assert relation.declared_list_field.raw_value == "Wrong Equipment"
    assert relation.declared_list_ref is not None
    assert relation.declared_list_ref.raw_name == "Wrong Equipment"
    assert relation.ranked_list_evidence[0].candidate_id.endswith("object:24")
    assert relation.ranked_list_evidence[0].score == 2
    assert model.zone_equipment_lists[0].members[0].cooling_sequence_field is not None
    assert model.zone_equipment_lists[0].members[0].heating_sequence_field is not None


def test_identities_retain_resolution_multiplicity(ir_document, ir_idd) -> None:  # type: ignore[no-untyped-def]
    model = build_model_ir(ir_document, ir_idd)
    identity = next(
        row for row in model.identities
        if row.normalized_object_type == "fan:constantvolume"
        and row.normalized_object_name == "fan a"
    )

    assert identity.status is IdentityStatus.RESOLVED
    assert identity.object_ids == ("object:1",)


def test_controller_ownership_is_retained_as_detect_only_fact(ir_document, ir_idd) -> None:  # type: ignore[no-untyped-def]
    model = build_model_ir(ir_document, ir_idd)
    relation = model.controller_relations[0]

    assert relation.owner_ref.raw_name == "Main Air Loop"
    assert relation.controller_list_ref is not None
    assert [member.object_name for member in relation.members] == ["Water Controller"]
