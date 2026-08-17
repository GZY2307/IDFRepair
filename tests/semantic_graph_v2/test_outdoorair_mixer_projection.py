"""Official OutdoorAir:Mixer coupled-stream projection contract."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.ir import FlowTopologyForm, FlowTraversalRole

from .compound_fixtures import compound_model, projection_named


def test_outdoorair_mixer_keeps_primary_and_relief_interfaces() -> None:
    projection = projection_named(compound_model(), "OA Mixer")

    assert projection.topology_form is FlowTopologyForm.COUPLED_MULTI_STREAM
    primary, relief = projection.transitions
    assert primary.traversal_role is FlowTraversalRole.PRIMARY
    assert primary.stream == "outdoor_to_mixed"
    assert [port.node_name for port in primary.inlet_ports] == ["Outdoor Air"]
    assert [port.node_name for port in primary.outlet_ports] == ["Mixed Air"]
    assert relief.traversal_role is FlowTraversalRole.AUXILIARY
    assert relief.stream == "return_to_relief"
    assert [port.node_name for port in relief.inlet_ports] == ["Return Air"]
    assert [port.node_name for port in relief.outlet_ports] == ["Relief Air"]
