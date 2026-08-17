"""Generic multi-circuit projection role contract."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.ir import FlowTopologyForm, FlowTraversalRole

from .compound_fixtures import compound_model, projection_named


def test_multi_circuit_projection_keeps_primary_and_auxiliary_separate() -> None:
    projection = projection_named(compound_model(), "HX SensLat")

    assert projection.topology_form is FlowTopologyForm.MULTI_CIRCUIT
    assert [row.traversal_role for row in projection.transitions] == [
        FlowTraversalRole.PRIMARY,
        FlowTraversalRole.AUXILIARY,
    ]
    assert projection.transitions[0].stream == "supply"
    assert projection.transitions[1].stream == "exhaust"
