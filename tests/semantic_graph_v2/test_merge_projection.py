"""Generic merge projection cardinality contract."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.ir import FlowTopologyForm

from .compound_fixtures import compound_model, projection_named


def test_merge_projection_retains_many_to_one_cardinality() -> None:
    projection = projection_named(compound_model(), "Mixer 1")

    assert projection.topology_form is FlowTopologyForm.MERGE
    transition = projection.transitions[0]
    assert len(transition.inlet_ports) == 3
    assert len(transition.outlet_ports) == 1
