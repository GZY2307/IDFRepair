"""Seeded, bounded dwell-time distributions for the discrete-event ABM."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Sequence


_KINDS = {
    "deterministic",
    "uniform",
    "triangular",
    "truncated_normal",
    "truncated_lognormal",
    "empirical",
}


@dataclass(frozen=True, slots=True)
class DwellSpec:
    kind: str
    minimum: float
    maximum: float
    value: float | None = None
    mode: float | None = None
    mean: float | None = None
    sd: float | None = None
    empirical: Sequence[float] = ()

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"unknown dwell kind: {self.kind}")
        if self.minimum < 0 or self.maximum < self.minimum:
            raise ValueError("invalid dwell bounds")
        object.__setattr__(self, "empirical", tuple(self.empirical))
        if self.kind == "deterministic":
            if self.value is None or not self.minimum <= self.value <= self.maximum:
                raise ValueError("deterministic value must be within bounds")
        elif self.kind == "triangular":
            if self.mode is None or not self.minimum <= self.mode <= self.maximum:
                raise ValueError("triangular mode must be within bounds")
        elif self.kind in {"truncated_normal", "truncated_lognormal"}:
            if self.mean is None:
                raise ValueError("mean is required")
            if self.sd is None or self.sd <= 0:
                raise ValueError("sd must be positive")
        elif self.kind == "empirical":
            if not self.empirical:
                raise ValueError("empirical values must not be empty")
            if any(
                value < self.minimum or value > self.maximum
                for value in self.empirical
            ):
                raise ValueError("empirical value lies outside bounds")


def _rejection_sample(
    draw,
    minimum: float,
    maximum: float,
    *,
    attempts: int = 100_000,
) -> float:
    for _ in range(attempts):
        value = float(draw())
        if minimum <= value <= maximum:
            return value
    raise RuntimeError("bounded dwell sampler could not draw within bounds")


def sample_dwell(spec: DwellSpec, rng: random.Random) -> float:
    if spec.kind == "deterministic":
        return float(spec.value)
    if spec.kind == "uniform":
        return rng.uniform(spec.minimum, spec.maximum)
    if spec.kind == "triangular":
        return rng.triangular(spec.minimum, spec.maximum, spec.mode)
    if spec.kind == "truncated_normal":
        return _rejection_sample(
            lambda: rng.normalvariate(spec.mean, spec.sd),
            spec.minimum,
            spec.maximum,
        )
    if spec.kind == "truncated_lognormal":
        return _rejection_sample(
            lambda: rng.lognormvariate(spec.mean, spec.sd),
            spec.minimum,
            spec.maximum,
        )
    if spec.kind == "empirical":
        return float(rng.choice(spec.empirical))
    raise AssertionError("validated dwell kind is unreachable")
