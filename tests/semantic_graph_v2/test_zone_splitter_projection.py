"""Official ZoneSplitter projection contract."""

from __future__ import annotations

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from idfrepair.semantic_graph_v2 import build_model_ir
from idfrepair.semantic_graph_v2.ir import ProjectionApplicability

from .compound_fixtures import (
    COMPOUND_IDD_24_TEXT,
    compound_model,
    projection_named,
)


def test_zone_splitter_projection_includes_all_actual_outlets() -> None:
    model = compound_model()
    projection = projection_named(model, "Splitter 1")

    transition = projection.transitions[0]
    assert [port.node_name for port in transition.inlet_ports] == ["S In"]
    assert [port.node_name for port in transition.outlet_ports] == [
        "S Out 1", "S Out 2", "S Out 3",
    ]
    assert {port.field_ref.field_index for port in transition.outlet_ports} == {3, 4, 5}
    assert projection.rule_version == "24.1"


def test_zone_splitter_projection_is_independently_version_bound_for_22_1() -> None:
    projection = projection_named(compound_model("22.1.0"), "Splitter 1")

    assert projection.rule_version == "22.1"
    assert "e22_1" in projection.rule_id


def test_zone_splitter_blank_or_duplicate_outlet_never_claims_complete() -> None:
    idd = parse_idd(COMPOUND_IDD_24_TEXT)
    blank = build_model_ir(
        parse_idf("AirLoopHVAC:ZoneSplitter,S1,In,O1,,O3;"), idd,
    )
    duplicate = build_model_ir(
        parse_idf("AirLoopHVAC:ZoneSplitter,S1,In,O1,O1;"), idd,
    )

    blank_projection = projection_named(blank, "S1")
    duplicate_projection = projection_named(duplicate, "S1")
    assert blank_projection.complete is False
    assert duplicate_projection.complete is False
    assert blank_projection.applicability is (
        ProjectionApplicability.INCOMPLETE_MISSING_PORT
    )
    assert "blank_extensible_port" in blank_projection.issues
    assert "duplicate_projected_node" in duplicate_projection.issues


def test_zone_splitter_without_any_outlet_is_retained_as_incomplete() -> None:
    model = build_model_ir(
        parse_idf("AirLoopHVAC:ZoneSplitter,S1,In;"),
        parse_idd(COMPOUND_IDD_24_TEXT),
    )
    projection = projection_named(model, "S1")

    assert projection.complete is False
    assert projection.transitions[0].outlet_ports == ()
