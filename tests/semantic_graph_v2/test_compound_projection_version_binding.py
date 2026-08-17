"""Compound rule identity follows the exact audited IDD version."""

from __future__ import annotations

from .compound_fixtures import compound_model, projection_named


def test_sensible_latent_projection_keeps_token_identity_across_real_layouts() -> None:
    old = projection_named(compound_model("22.1.0"), "HX SensLat")
    current = projection_named(compound_model("24.1.0"), "HX SensLat")
    old_port = old.transitions[0].inlet_ports[0]
    current_port = current.transitions[0].inlet_ports[0]

    assert old.rule_id != current.rule_id
    assert old.rule_version == old_port.rule_version == "22.1"
    assert current.rule_version == current_port.rule_version == "24.1"
    assert old_port.field_ref.field_token == current_port.field_ref.field_token == "A3"
    assert old_port.field_ref.field_index == 12
    assert current_port.field_ref.field_index == 8
