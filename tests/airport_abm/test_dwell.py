from __future__ import annotations

import importlib
import random

import pytest


@pytest.mark.parametrize(
    "spec",
    [
        {"kind": "uniform", "minimum": 5, "maximum": 15},
        {"kind": "triangular", "minimum": 5, "maximum": 15, "mode": 9},
        {"kind": "truncated_normal", "minimum": 5, "maximum": 15, "mean": 10, "sd": 4},
        {"kind": "truncated_lognormal", "minimum": 5, "maximum": 15, "mean": 2.2, "sd": 0.4},
        {"kind": "empirical", "minimum": 5, "maximum": 15, "empirical": [5, 8, 15]},
    ],
)
def test_stochastic_dwell_is_bounded_and_seed_reproducible(spec: dict[str, object]) -> None:
    module = importlib.import_module("idfrepair.analysis.airport_abm.dwell")
    dwell = module.DwellSpec(**spec)

    first_rng = random.Random(40015)
    first = [module.sample_dwell(dwell, first_rng) for _ in range(20)]
    second_rng = random.Random(40015)
    second = [module.sample_dwell(dwell, second_rng) for _ in range(20)]

    assert first == second
    assert all(5 <= value <= 15 for value in first)


def test_deterministic_dwell_returns_the_registered_value() -> None:
    module = importlib.import_module("idfrepair.analysis.airport_abm.dwell")
    dwell = module.DwellSpec(
        kind="deterministic", minimum=7.5, maximum=7.5, value=7.5
    )

    assert module.sample_dwell(dwell, random.Random(1)) == 7.5


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"kind": "uniform", "minimum": 10, "maximum": 5}, "bounds"),
        ({"kind": "triangular", "minimum": 5, "maximum": 10, "mode": 11}, "mode"),
        ({"kind": "truncated_normal", "minimum": 5, "maximum": 10, "mean": 7}, "sd"),
        ({"kind": "empirical", "minimum": 5, "maximum": 10, "empirical": []}, "empirical"),
        ({"kind": "unknown", "minimum": 5, "maximum": 10}, "kind"),
    ],
)
def test_invalid_dwell_spec_fails_closed(kwargs: dict[str, object], match: str) -> None:
    module = importlib.import_module("idfrepair.analysis.airport_abm.dwell")

    with pytest.raises(ValueError, match=match):
        module.DwellSpec(**kwargs)
