"""Official ZoneMixer projection contract."""

from __future__ import annotations

from .compound_fixtures import compound_model, projection_named


def test_zone_mixer_projection_includes_all_actual_inlets() -> None:
    projection = projection_named(compound_model(), "Mixer 1")
    transition = projection.transitions[0]

    assert [port.node_name for port in transition.inlet_ports] == [
        "M In 1", "M In 2", "M In 3",
    ]
    assert [port.node_name for port in transition.outlet_ports] == ["M Out"]
