"""Official air-to-air heat-exchanger circuit projections."""

from __future__ import annotations

from idfrepair.semantic_graph_v2.ir import FlowTopologyForm

from .compound_fixtures import compound_model, projection_named


def test_sensible_latent_hx_uses_supply_and_exhaust_circuits() -> None:
    projection = projection_named(compound_model(), "HX SensLat")

    assert projection.topology_form is FlowTopologyForm.MULTI_CIRCUIT
    supply, exhaust = projection.transitions
    assert [port.node_name for port in supply.inlet_ports] == ["HX Supply In"]
    assert [port.node_name for port in supply.outlet_ports] == ["HX Supply Out"]
    assert [port.node_name for port in exhaust.inlet_ports] == ["HX Exhaust In"]
    assert [port.node_name for port in exhaust.outlet_ports] == ["HX Exhaust Out"]


def test_sensible_latent_hx_is_bound_to_real_22_1_and_24_1_field_layouts() -> None:
    old = projection_named(compound_model("22.1.0"), "HX SensLat")
    current = projection_named(compound_model("24.1.0"), "HX SensLat")

    assert old.transitions[0].inlet_ports[0].field_ref.field_index == 12
    assert current.transitions[0].inlet_ports[0].field_ref.field_index == 8
    assert old.rule_version == "22.1"
    assert current.rule_version == "24.1"


def test_flat_plate_hx_uses_supply_and_secondary_circuits() -> None:
    projection = projection_named(compound_model(), "HX Flat")

    assert projection.topology_form is FlowTopologyForm.MULTI_CIRCUIT
    supply, secondary = projection.transitions
    assert supply.stream == "supply"
    assert secondary.stream == "secondary"
    assert [port.node_name for port in supply.inlet_ports] == ["FP Supply In"]
    assert [port.node_name for port in supply.outlet_ports] == ["FP Supply Out"]
    assert [port.node_name for port in secondary.inlet_ports] == ["FP Secondary In"]
    assert [port.node_name for port in secondary.outlet_ports] == [
        "FP Secondary Out",
    ]
