"""Canonical IR contracts shared by direct and compound projections."""

from __future__ import annotations

from dataclasses import replace

import pytest

from idfrepair.io.idf import parse_idf
from idfrepair.knowledge.idd import parse_idd
from idfrepair.semantic_graph_v2 import build_model_ir
from idfrepair.semantic_graph_v2.ir import (
    FlowTopologyForm,
    FlowTraversalRole,
    ProjectionApplicability,
)

from .compound_fixtures import (
    COMPOUND_IDD_22_TEXT,
    compound_model,
    projection_named,
)


def test_direct_projection_is_additive_above_atomic_port_evidence() -> None:
    model = compound_model()
    direct = projection_named(model, "Direct Fan")

    assert direct.topology_form is FlowTopologyForm.DIRECT
    assert direct.applicability is ProjectionApplicability.SUPPORTED_COMPLETE
    assert direct.complete is True
    assert direct.object_ref.start >= 0
    assert len(direct.transitions) == 1
    transition = direct.transitions[0]
    assert transition.object_ref is direct.object_ref
    assert transition.traversal_role is FlowTraversalRole.PRIMARY
    assert [port.node_name for port in transition.inlet_ports] == ["D In"]
    assert [port.node_name for port in transition.outlet_ports] == ["D Out"]
    assert transition.rule_id
    assert transition.rule_version == "24.1"
    assert model.projections_for(direct.object_ref.object_id) == (direct,)


def test_complete_transition_rejects_empty_cross_object_or_duplicate_evidence() -> None:
    model = compound_model()
    direct = projection_named(model, "Direct Fan")
    transition = direct.transitions[0]
    foreign = projection_named(model, "Splitter 1").transitions[0].inlet_ports[0]

    with pytest.raises(ValueError, match="complete_flow_transition_cardinality"):
        replace(transition, inlet_ports=())
    with pytest.raises(ValueError, match="flow_transition_cross_object_port"):
        replace(transition, inlet_ports=(foreign,))
    with pytest.raises(ValueError, match="flow_transition_duplicate_port"):
        replace(
            transition,
            inlet_ports=(transition.inlet_ports[0], transition.inlet_ports[0]),
        )


def test_complete_projection_rejects_topology_or_state_mismatch() -> None:
    model = compound_model()
    split = projection_named(model, "Splitter 1")
    multi = projection_named(model, "HX SensLat")

    with pytest.raises(ValueError, match="complete_flow_projection_topology"):
        replace(multi, transitions=(multi.transitions[0],))
    incomplete = replace(
        split.transitions[0],
        applicability=ProjectionApplicability.INCOMPLETE_MISSING_PORT,
    )
    with pytest.raises(ValueError, match="complete_flow_projection_transition"):
        replace(split, transitions=(incomplete,))
    with pytest.raises(ValueError, match="flow_projection_rule_version_mismatch"):
        replace(split, rule_version="22.1")


def test_document_idd_version_mismatch_blocks_compound_projection() -> None:
    model = build_model_ir(
        parse_idf(
            "Version,24.1;\n"
            "AirLoopHVAC:ZoneSplitter,S1,In,O1,O2;\n"
        ),
        parse_idd(COMPOUND_IDD_22_TEXT),
    )

    assert model.flow_projections == ()
    assert "document_idd_version_mismatch:24.1:22.1" in model.extraction_issues
