"""Generic split projection cardinality contract."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.ir import FlowTopologyForm

from .compound_fixtures import compound_model, projection_named


def test_split_projection_retains_one_to_many_cardinality() -> None:
    projection = projection_named(compound_model(), "Splitter 1")

    assert projection.topology_form is FlowTopologyForm.SPLIT
    transition = projection.transitions[0]
    assert len(transition.inlet_ports) == 1
    assert len(transition.outlet_ports) == 3
