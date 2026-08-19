from idfrepair.analysis.airport_abm.capacity_audit import CapacityObservation
from idfrepair.analysis.airport_abm.schedule_compiler import counts_to_fractions


def test_people_schedule_and_capacity_ratio_preserve_values_above_one() -> None:
    fractions = counts_to_fractions(
        {"gate": (0.0, 10.0, 25.0)},
        source_design_capacity={"gate": 10.0},
    )
    observation = CapacityObservation(
        scenario_id="BASELINE_SPREAD",
        seed=40015,
        space_name="gate",
        function="domestic_waiting",
        region="north",
        hvac_group="N-VAV",
        source_design_people=10.0,
        occupant_counts=(0.0, 10.0, 25.0),
    )

    assert fractions["gate"] == (0.0, 1.0, 2.5)
    assert observation.ratios == (0.0, 1.0, 2.5)
