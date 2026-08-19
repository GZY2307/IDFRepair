from idfrepair.analysis.airport_abm.fixed_sizing import evaluate_people_only_derivative


def test_people_only_derivative_requires_common_controls_and_protected_inventory() -> None:
    passed = evaluate_people_only_derivative(
        source_unchanged=True,
        people_schedule_only=True,
        protected_inventory_equal=True,
        common_operation_controls_equal=True,
        dcv_equal=True,
        ideal_loads_added=0,
    )
    failed = evaluate_people_only_derivative(
        source_unchanged=True,
        people_schedule_only=True,
        protected_inventory_equal=True,
        common_operation_controls_equal=False,
        dcv_equal=True,
        ideal_loads_added=0,
    )

    assert passed.status == "PASS_PEOPLE_SCHEDULE_ONLY"
    assert passed.reasons == ()
    assert failed.status == "FAIL_PROTECTED_OBJECT_DIFF"
    assert failed.reasons == ("operation_controls_differ",)
