from __future__ import annotations

import pytest

from idfrepair.analysis.airport_abm.capacity_audit import (
    CapacityObservation,
    summarize_capacity_reference,
)


def _observation(
    name: str,
    function: str,
    values: tuple[float, ...],
) -> CapacityObservation:
    return CapacityObservation(
        scenario_id="BASELINE_SPREAD",
        seed=40015,
        space_name=name,
        function=function,
        region="north",
        hvac_group="N-VAV",
        source_design_people=10.0,
        occupant_counts=values,
    )


def test_capacity_summary_counts_strict_thresholds_and_interpolated_quantiles() -> None:
    rows = summarize_capacity_reference(
        (
            _observation("gate-a", "domestic_waiting", (0.0, 10.0, 20.0, 30.0)),
            _observation("gate-b", "domestic_waiting", (5.0, 15.0, 25.0, 35.0)),
        )
    )
    whole = next(
        row
        for row in rows
        if row.dimension == "whole_model" and row.group == "whole_model"
    )

    assert whole.spaces_supported == 2
    assert whole.space_time_intervals == 8
    assert whole.spaces_over_1 == 2
    assert whole.ratio_over_1_count == 5
    assert whole.ratio_over_1_percent == pytest.approx(62.5)
    assert whole.ratio_over_1_5_count == 4
    assert whole.ratio_over_2_count == 3
    assert whole.p50 == pytest.approx(1.75)
    assert whole.maximum == 3.5


def test_capacity_summary_keeps_function_region_and_hvac_denominators_separate() -> None:
    rows = summarize_capacity_reference(
        (
            _observation("gate", "domestic_waiting", (10.0, 20.0)),
            _observation("shop", "commercial", (0.0, 5.0)),
        )
    )

    function_rows = {
        row.group: row for row in rows if row.dimension == "function"
    }
    assert function_rows["domestic_waiting"].space_time_intervals == 2
    assert function_rows["domestic_waiting"].ratio_over_1_count == 1
    assert function_rows["commercial"].space_time_intervals == 2
    assert function_rows["commercial"].ratio_over_1_count == 0
    assert sum(row.dimension == "region" for row in rows) == 1
    assert sum(row.dimension == "hvac_group" for row in rows) == 1


def test_capacity_summary_rejects_missing_or_nonpositive_design_reference() -> None:
    with pytest.raises(ValueError, match="design People"):
        CapacityObservation(
            scenario_id="SOURCE_STATIC",
            seed=None,
            space_name="bad",
            function="central_hall",
            region="central",
            hvac_group="C-VAV",
            source_design_people=0.0,
            occupant_counts=(1.0,),
        )


def test_public_capacity_rows_alias_source_hvac_group_names() -> None:
    from scripts.airport_abm.generate_v31_occupancy_reports import (
        public_capacity_rows,
    )

    rows = summarize_capacity_reference(
        (
            _observation("gate", "domestic_waiting", (10.0, 20.0)),
            CapacityObservation(
                scenario_id="BASELINE_SPREAD",
                seed=40015,
                space_name="shop",
                function="commercial",
                region="north",
                hvac_group="PRIVATE-SYSTEM-B",
                source_design_people=10.0,
                occupant_counts=(0.0, 5.0),
            ),
        )
    )

    public = public_capacity_rows(rows)
    hvac_names = {
        row["group"] for row in public if row["dimension"] == "hvac_group"
    }
    function_names = {
        row["group"] for row in public if row["dimension"] == "function"
    }

    assert hvac_names == {"hvac_group_01", "hvac_group_02"}
    assert function_names == {"commercial", "domestic_waiting"}
