from __future__ import annotations

import importlib


def _fixture():
    model = importlib.import_module("idfrepair.analysis.airport_abm.model")
    source = importlib.import_module("idfrepair.analysis.airport_abm.source")
    spaces = (
        source.SourceSpace("entry", "z-entry", "central", "departure_entry", "departure_entry", "Hall", 10, 1, 10, "VAV", None, None),
        source.SourceSpace("central", "z-central", "central", "central_hall", "central_hall", "Hall", 10, 1, 10, "VAV", None, None),
        source.SourceSpace("gate-small", "z-g1", "east", "domestic_waiting", "domestic_waiting", "Hall", 10, 10, 1, "VAV", None, None),
        source.SourceSpace("gate-large", "z-g2", "east", "domestic_waiting", "domestic_waiting", "Hall", 90, 10, 9, "VAV", None, None),
        source.SourceSpace("bag", "z-bag", "central", "baggage_claim", "baggage_claim", "Hall", 10, 1, 10, "VAV", None, None),
        source.SourceSpace("exit", "z-exit", "central", "arrival_exit", "arrival_exit", "Hall", 10, 1, 10, "VAV", None, None),
        source.SourceSpace("intl-gate", "z-ig", "south", "international_arrival", "international_arrival", "Hall", 10, 1, 10, "VAV", None, None),
        source.SourceSpace("intl-hall", "z-ih", "south", "international_hall", "international_hall", "Hall", 10, 1, 10, "VAV", None, None),
        source.SourceSpace("transfer", "z-t", "south", "transfer", "transfer", "Hall", 10, 1, 10, "VAV", None, None),
        source.SourceSpace("office", "z-o", "east", "office", "office", "Office", 10, 1, 10, None, "DOAS", "FCU"),
        source.SourceSpace("break", "z-br", "east", "breakroom", "staff_breakroom", "Office", 10, 1, 10, None, "DOAS", "FCU"),
        source.SourceSpace("shop", "z-shop", "east", "commercial", "general_commercial", "Retail", 10, 1, 10, "VAV", None, None),
    )
    groups = {
        "departure_entries": ("entry",),
        "central_public": ("central",),
        "ne_gates": (),
        "nw_gates": (),
        "se_gates": ("gate-small", "gate-large"),
        "sw_gates": (),
        "ne_concourse": (),
        "nw_concourse": (),
        "domestic_gates": ("gate-small", "gate-large"),
        "baggage_claim": ("bag",),
        "arrival_exits": ("exit",),
        "international_arrival": ("intl-gate",),
        "international_hall": ("intl-hall",),
        "international_transfer": ("transfer",),
        "offices": ("office",),
        "staff_breakrooms": ("break",),
    }
    return model, spaces, groups


def test_gate_assignment_is_seeded_and_weighted_by_source_design_people() -> None:
    model, spaces, groups = _fixture()
    module = importlib.import_module("idfrepair.analysis.airport_abm.flight_bank")
    counts = {agent_class: 0 for agent_class in model.AgentClass}
    counts[model.AgentClass.DOMESTIC_DEPARTURE] = 1000
    parameters = module.ControlledParameters(detour_probability=0)

    plans = module.build_daily_plans(
        spaces=spaces,
        groups=groups,
        door_detours={},
        counts=counts,
        parameters=parameters,
        seed=40015,
    )

    gates = [
        stop.location
        for plan in plans
        for stop in plan.stops
        if stop.stage == "gate_wait"
    ]
    assert gates.count("gate-large") > 800
    assert gates.count("gate-small") < 200
    assert plans == module.build_daily_plans(
        spaces=spaces,
        groups=groups,
        door_detours={},
        counts=counts,
        parameters=parameters,
        seed=40015,
    )


def test_all_five_classes_follow_declared_process_endpoints() -> None:
    model, spaces, groups = _fixture()
    module = importlib.import_module("idfrepair.analysis.airport_abm.flight_bank")
    counts = {agent_class: 1 for agent_class in model.AgentClass}

    plans = module.build_daily_plans(
        spaces=spaces,
        groups=groups,
        door_detours={},
        counts=counts,
        parameters=module.ControlledParameters(detour_probability=0),
        seed=40015,
    )
    by_class = {plan.agent_class: plan for plan in plans}

    assert by_class[model.AgentClass.DOMESTIC_DEPARTURE].stops[0].location == "entry"
    assert by_class[model.AgentClass.DOMESTIC_DEPARTURE].terminal_state == "BOARDING"
    arrival_locations = [stop.location for stop in by_class[model.AgentClass.DOMESTIC_ARRIVAL].stops]
    assert arrival_locations.index("bag") < arrival_locations.index("exit")
    transfer_locations = [stop.location for stop in by_class[model.AgentClass.DOMESTIC_TRANSFER].stops]
    assert "bag" not in transfer_locations
    international_locations = [stop.location for stop in by_class[model.AgentClass.INTERNATIONAL_ARRIVAL].stops]
    assert "bag" not in international_locations
    assert by_class[model.AgentClass.INTERNATIONAL_ARRIVAL].terminal_state == "OFF_MODEL_LEVEL1_IMMIGRATION"
    assert by_class[model.AgentClass.STAFF].terminal_state == "STAFF_EXIT_BOUNDARY"


def test_detour_returns_to_anchor_and_reallocates_instead_of_adding_wait_time() -> None:
    model, spaces, groups = _fixture()
    module = importlib.import_module("idfrepair.analysis.airport_abm.flight_bank")
    counts = {agent_class: 0 for agent_class in model.AgentClass}
    counts[model.AgentClass.DOMESTIC_DEPARTURE] = 1
    parameters = module.ControlledParameters(
        detour_probability=1,
        departure_wait_minimum=90,
        departure_wait_maximum=90,
        detour_minutes=15,
    )

    plan = module.build_daily_plans(
        spaces=spaces,
        groups=groups,
        door_detours={"gate-small": ("shop",), "gate-large": ("shop",)},
        counts=counts,
        parameters=parameters,
        seed=40015,
    )[0]

    locations = [stop.location for stop in plan.stops]
    detour_index = locations.index("shop")
    assert locations[detour_index - 1] == locations[detour_index + 1]
    assert plan.stops[detour_index].detour_anchor == locations[detour_index - 1]
    gate_budget = sum(
        stop.dwell.value
        for stop in plan.stops
        if stop.stage in {"gate_anchor", "discretionary_detour", "gate_wait"}
    )
    assert gate_budget == 90


def test_timing_scenarios_change_only_passenger_spawn_times() -> None:
    model, spaces, groups = _fixture()
    module = importlib.import_module("idfrepair.analysis.airport_abm.flight_bank")
    counts = {agent_class: 1 for agent_class in model.AgentClass}
    base = module.build_daily_plans(
        spaces=spaces,
        groups=groups,
        door_detours={},
        counts=counts,
        parameters=module.ControlledParameters(detour_probability=0),
        seed=40015,
    )

    morning = module.retime_plans(base, "MORNING_BANK", seed=40015)
    evening = module.retime_plans(base, "EVENING_BANK", seed=40015)

    for original, early, late in zip(base, morning, evening):
        assert original.agent_id == early.agent_id == late.agent_id
        assert original.stops == early.stops == late.stops
        if original.agent_class is model.AgentClass.STAFF:
            assert original.spawn_minute == early.spawn_minute == late.spawn_minute
        else:
            assert 0 <= early.spawn_minute < 1440
            assert 0 <= late.spawn_minute < 1440


def test_baseline_and_banked_passenger_plans_keep_controlled_night_support() -> None:
    model, spaces, groups = _fixture()
    module = importlib.import_module("idfrepair.analysis.airport_abm.flight_bank")
    counts = {agent_class: 400 for agent_class in model.AgentClass}
    counts[model.AgentClass.STAFF] = 0
    base = module.build_daily_plans(
        spaces=spaces,
        groups=groups,
        door_detours={},
        counts=counts,
        parameters=module.ControlledParameters(detour_probability=0),
        seed=40015,
    )
    morning = module.retime_plans(base, "MORNING_BANK", seed=40015)

    for plans in (base, morning):
        for agent_class in (
            model.AgentClass.DOMESTIC_DEPARTURE,
            model.AgentClass.DOMESTIC_ARRIVAL,
            model.AgentClass.DOMESTIC_TRANSFER,
            model.AgentClass.INTERNATIONAL_ARRIVAL,
        ):
            spawns = [p.spawn_minute for p in plans if p.agent_class is agent_class]
            assert any(value < 300 or value >= 1260 for value in spawns)
            assert any(300 <= value < 1260 for value in spawns)


def test_passenger_volume_does_not_change_staff_plans() -> None:
    model, spaces, groups = _fixture()
    module = importlib.import_module("idfrepair.analysis.airport_abm.flight_bank")
    groups = dict(groups)
    groups["offices"] = ("office", "break")
    small = {agent_class: 1 for agent_class in model.AgentClass}
    small[model.AgentClass.STAFF] = 20
    large = dict(small)
    large[model.AgentClass.DOMESTIC_DEPARTURE] = 20
    parameters = module.ControlledParameters(
        detour_probability=0, staff_break_probability=0.5
    )

    small_plans = module.build_daily_plans(
        spaces=spaces,
        groups=groups,
        door_detours={},
        counts=small,
        parameters=parameters,
        seed=40015,
    )
    large_plans = module.build_daily_plans(
        spaces=spaces,
        groups=groups,
        door_detours={},
        counts=large,
        parameters=parameters,
        seed=40015,
    )

    small_staff = [
        plan for plan in small_plans if plan.agent_class is model.AgentClass.STAFF
    ]
    large_staff = [
        plan for plan in large_plans if plan.agent_class is model.AgentClass.STAFF
    ]
    assert small_staff == large_staff
