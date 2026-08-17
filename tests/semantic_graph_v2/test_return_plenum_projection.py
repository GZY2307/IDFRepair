"""Official ReturnPlenum main-flow boundary contract."""

from __future__ import annotations

from .compound_fixtures import compound_model, projection_named


def test_return_plenum_excludes_zone_and_induced_nodes_from_merge_projection() -> None:
    model = compound_model()
    projection = projection_named(model, "Return Plenum")
    transition = projection.transitions[0]

    assert [port.node_name for port in transition.inlet_ports] == [
        "R In 1", "R In 2",
    ]
    assert [port.node_name for port in transition.outlet_ports] == ["R Out"]
    projected = {
        port.node_name for port in (*transition.inlet_ports, *transition.outlet_ports)
    }
    assert projected.isdisjoint({"Return Zone Node", "Induced Nodes"})
    assert {"Return Zone Node", "Induced Nodes"}.issubset({
        field.raw_value for field in model.unsupported_port_fields
    })
