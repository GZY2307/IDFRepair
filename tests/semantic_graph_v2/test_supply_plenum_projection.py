"""Official SupplyPlenum main-flow boundary contract."""

from __future__ import annotations

from .compound_fixtures import compound_model, projection_named


def test_supply_plenum_excludes_zone_node_from_split_projection() -> None:
    model = compound_model()
    projection = projection_named(model, "Supply Plenum")
    transition = projection.transitions[0]

    assert [port.node_name for port in transition.inlet_ports] == ["P In"]
    assert [port.node_name for port in transition.outlet_ports] == [
        "P Out 1", "P Out 2",
    ]
    assert "Supply Zone Node" not in {
        port.node_name for port in model.ports_for(projection.object_ref.object_id)
    }
    assert any(
        field.raw_value == "Supply Zone Node"
        for field in model.unsupported_port_fields
    )
