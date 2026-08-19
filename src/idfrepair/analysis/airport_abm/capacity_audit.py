"""BEM design-occupancy reference envelopes for Airport Occupancy V3.1."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Iterable

from .reporting import quantile


@dataclass(frozen=True, slots=True)
class CapacityObservation:
    scenario_id: str
    seed: int | None
    space_name: str
    function: str
    region: str
    hvac_group: str
    source_design_people: float
    occupant_counts: tuple[float, ...]

    def __post_init__(self) -> None:
        text_values = (
            self.scenario_id,
            self.space_name,
            self.function,
            self.region,
            self.hvac_group,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("capacity observation labels must not be empty")
        if self.seed is not None and self.seed <= 0:
            raise ValueError("capacity observation seed must be positive")
        if (
            not math.isfinite(self.source_design_people)
            or self.source_design_people <= 0
        ):
            raise ValueError("source design People reference must be finite and positive")
        if not self.occupant_counts:
            raise ValueError("capacity observation requires occupant counts")
        if any(
            not math.isfinite(float(value)) or float(value) < 0
            for value in self.occupant_counts
        ):
            raise ValueError("occupant counts must be finite and non-negative")

    @property
    def ratios(self) -> tuple[float, ...]:
        return tuple(
            float(value) / self.source_design_people for value in self.occupant_counts
        )


@dataclass(frozen=True, slots=True)
class CapacitySummary:
    scenario_id: str
    dimension: str
    group: str
    seeds: int
    spaces_supported: int
    space_time_intervals: int
    spaces_over_1: int
    ratio_over_1_count: int
    ratio_over_1_percent: float
    ratio_over_1_5_count: int
    ratio_over_1_5_percent: float
    ratio_over_2_count: int
    ratio_over_2_percent: float
    p50: float
    p90: float
    p95: float
    p99: float
    maximum: float


def summarize_capacity_reference(
    observations: Iterable[CapacityObservation],
) -> tuple[CapacitySummary, ...]:
    items = tuple(observations)
    if not items:
        raise ValueError("capacity audit requires at least one observation")
    grouped: dict[
        tuple[str, str, str], list[CapacityObservation]
    ] = defaultdict(list)
    for item in items:
        for dimension, group in (
            ("whole_model", "whole_model"),
            ("function", item.function),
            ("region", item.region),
            ("hvac_group", item.hvac_group),
        ):
            grouped[(item.scenario_id, dimension, group)].append(item)

    output: list[CapacitySummary] = []
    for (scenario_id, dimension, group), members in sorted(grouped.items()):
        ratios = tuple(value for item in members for value in item.ratios)
        interval_count = len(ratios)
        if interval_count <= 0:  # guarded by CapacityObservation, kept fail-closed
            raise ValueError("capacity audit group contains no intervals")

        def count_over(threshold: float) -> int:
            return sum(value > threshold for value in ratios)

        over_1 = count_over(1.0)
        over_1_5 = count_over(1.5)
        over_2 = count_over(2.0)
        by_space: dict[str, list[float]] = defaultdict(list)
        for item in members:
            by_space[item.space_name].extend(item.ratios)
        output.append(
            CapacitySummary(
                scenario_id=scenario_id,
                dimension=dimension,
                group=group,
                seeds=len({item.seed for item in members}),
                spaces_supported=len(by_space),
                space_time_intervals=interval_count,
                spaces_over_1=sum(
                    any(value > 1.0 for value in values)
                    for values in by_space.values()
                ),
                ratio_over_1_count=over_1,
                ratio_over_1_percent=over_1 / interval_count * 100.0,
                ratio_over_1_5_count=over_1_5,
                ratio_over_1_5_percent=over_1_5 / interval_count * 100.0,
                ratio_over_2_count=over_2,
                ratio_over_2_percent=over_2 / interval_count * 100.0,
                p50=quantile(ratios, 0.50),
                p90=quantile(ratios, 0.90),
                p95=quantile(ratios, 0.95),
                p99=quantile(ratios, 0.99),
                maximum=max(ratios),
            )
        )
    return tuple(output)
