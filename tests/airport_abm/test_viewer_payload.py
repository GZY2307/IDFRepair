from __future__ import annotations

import json
from pathlib import Path

from idfrepair.analysis.airport_abm.model import AgentClass
from idfrepair.analysis.airport_abm.source import SourceSpace
from idfrepair.analysis.airport_abm.visualization import build_viewer_payload


def _series(value: float) -> list[float]:
    return [value] * 96


def _classes(**values: float) -> dict[str, list[float]]:
    return {
        agent_class.value: _series(values.get(agent_class.value, 0.0))
        for agent_class in AgentClass
    }


def _space(
    name: str,
    function: str,
    *,
    design_people: float | None,
) -> SourceSpace:
    return SourceSpace(
        name=name,
        thermal_zone=f"zone-{name}",
        region="north",
        function=function,
        source_function=function,
        original_space_type="fixture",
        area_m2=100.0,
        people_m2_per_person=(10.0 if design_people is not None else None),
        source_design_people=design_people,
        public_air_loop="North-VAV",
        office_doas=None,
        zone_hvac=None,
    )


def test_viewer_payload_has_five_classes_flow_evidence_and_no_coordinates() -> None:
    spaces = (
        _space("entry", "departure_entry", design_people=10.0),
        _space("gate", "domestic_waiting", design_people=10.0),
        _space("restroom", "restroom", design_people=None),
    )
    detail = {
        "schema_version": "idfrepair.airport-abm-seed-detail.v3",
        "scenario_id": "MORNING_BANK",
        "seed": 40015,
        "interval_minutes": 15,
        "interval_labels": [f"step-{index}" for index in range(96)],
        "space_counts": {
            "entry": _series(2.0),
            "gate": _series(2.0),
            "restroom": _series(0.0),
        },
        "class_counts": {
            "entry": _classes(DOMESTIC_DEPARTURE=2.0),
            "gate": _classes(DOMESTIC_DEPARTURE=2.0),
            "restroom": _classes(),
        },
        "class_space_flows": [
            {
                "from": "entry",
                "to": "gate",
                "classes": _classes(DOMESTIC_DEPARTURE=2.0),
            }
        ],
    }
    access = {
        "passenger_edges": [
            {
                "from": "entry",
                "to": "gate",
                "roles": ["DOMESTIC_DEPARTURE"],
                "routable": True,
                "evidence_label": "STRONG_ACCESS_EDGE",
                "evidence_layer": "A_EXPLICIT_DOOR",
                "evidence_ref": "fixture:entry-gate-door",
                "abstraction_flag": False,
                "scenario_condition": None,
                "door_instances": ["door-entry-gate"],
            }
        ],
        "staff_edges": [],
    }

    payload = build_viewer_payload(spaces=spaces, detail=detail, access=access)

    assert payload["schema_version"] == "idfrepair.airport-abm-viewer.v3"
    assert payload["agent_classes"] == [member.value for member in AgentClass]
    assert payload["space_count"] == 3
    assert payload["spaces"]["restroom"]["bem_people_supported"] is False
    assert payload["spaces"]["restroom"]["design_people"] is None
    assert payload["spaces"]["entry"]["public_air_loop"] == "North-VAV"
    assert payload["load_data_available"] is False
    assert "heating_kw" not in payload["spaces"]["entry"]
    assert "centroid_x_m" not in json.dumps(payload)
    assert payload["flows"] == [
        {
            "from_function": "departure_entry",
            "to_function": "domestic_waiting",
            "evidence_label": "STRONG_ACCESS_EDGE",
            "counts": _series(2.0),
            "class_counts": _classes(DOMESTIC_DEPARTURE=2.0),
        }
    ]
    assert payload["space_edge_flows"] == [
        {
            "from_node": "entry",
            "to_node": "gate",
            "from_space_name": "entry",
            "to_space_name": "gate",
            "from_function": "departure_entry",
            "to_function": "domestic_waiting",
            "evidence_layer": "A_EXPLICIT_DOOR",
            "evidence_label": "STRONG_ACCESS_EDGE",
            "evidence_ref": "fixture:entry-gate-door",
            "abstraction_flag": False,
            "scenario_condition": None,
            "door_instances": ["door-entry-gate"],
            "roles": ["DOMESTIC_DEPARTURE"],
            "off_model_boundary": False,
            "boundary_direction": None,
            "counts": _series(2.0),
            "class_counts": _classes(DOMESTIC_DEPARTURE=2.0),
        }
    ]


def test_viewer_payload_preserves_distinct_space_edges_for_same_function_pair() -> None:
    spaces = (
        _space("entry-a", "departure_entry", design_people=10.0),
        _space("entry-b", "departure_entry", design_people=10.0),
        _space("gate-a", "domestic_waiting", design_people=10.0),
        _space("gate-b", "domestic_waiting", design_people=10.0),
    )
    detail = {
        "schema_version": "idfrepair.airport-abm-seed-detail.v3",
        "scenario_id": "BASELINE_SPREAD",
        "seed": 40015,
        "interval_minutes": 15,
        "interval_labels": [f"step-{index}" for index in range(96)],
        "space_counts": {space.name: _series(0.0) for space in spaces},
        "class_counts": {space.name: _classes() for space in spaces},
        "class_space_flows": [
            {"from": "entry-a", "to": "gate-a", "classes": _classes(DOMESTIC_DEPARTURE=2.0)},
            {"from": "entry-b", "to": "gate-b", "classes": _classes(DOMESTIC_DEPARTURE=3.0)},
        ],
    }
    access = {
        "passenger_edges": [
            {
                "from": source,
                "to": target,
                "roles": ["DOMESTIC_DEPARTURE"],
                "routable": True,
                "evidence_layer": "B_FUNCTIONAL_PROCESS",
                "evidence_label": "functional route abstraction",
                "evidence_ref": f"fixture:{source}:{target}",
                "abstraction_flag": True,
                "scenario_condition": None,
                "door_instances": [],
            }
            for source, target in (("entry-a", "gate-a"), ("entry-b", "gate-b"))
        ],
        "staff_edges": [],
    }

    payload = build_viewer_payload(spaces=spaces, detail=detail, access=access)

    assert [(row["from_node"], row["to_node"]) for row in payload["space_edge_flows"]] == [
        ("entry-a", "gate-a"),
        ("entry-b", "gate-b"),
    ]
    assert [row["counts"][0] for row in payload["space_edge_flows"]] == [2.0, 3.0]


def test_viewer_payload_marks_virtual_source_as_incoming_boundary() -> None:
    spaces = (_space("office", "office", design_people=10.0),)
    detail = {
        "schema_version": "idfrepair.airport-abm-seed-detail.v3",
        "scenario_id": "BASELINE_SPREAD",
        "seed": 40015,
        "interval_minutes": 15,
        "interval_labels": [f"step-{index}" for index in range(96)],
        "space_counts": {"office": _series(0.0)},
        "class_counts": {"office": _classes()},
        "class_space_flows": [
            {"from": "STAFF_ENTRY_BOUNDARY", "to": "office", "classes": _classes(STAFF=1.0)}
        ],
    }
    access = {
        "nodes": [
            {"name": "STAFF_ENTRY_BOUNDARY", "function": "staff_boundary", "is_virtual": True}
        ],
        "passenger_edges": [],
        "staff_edges": [
            {
                "from": "STAFF_ENTRY_BOUNDARY",
                "to": "office",
                "roles": ["STAFF"],
                "routable": True,
                "evidence_layer": "B_FUNCTIONAL_PROCESS",
                "evidence_label": "functional route abstraction",
                "evidence_ref": "fixture:staff-entry",
                "abstraction_flag": True,
                "scenario_condition": None,
                "door_instances": [],
            }
        ],
    }

    payload = build_viewer_payload(spaces=spaces, detail=detail, access=access)

    edge = payload["space_edge_flows"][0]
    assert edge["from_space_name"] is None
    assert edge["to_space_name"] == "office"
    assert edge["off_model_boundary"] is True
    assert edge["boundary_direction"] == "incoming"


def test_viewer_payload_rejects_missing_space_counts() -> None:
    spaces = (_space("entry", "departure_entry", design_people=10.0),)
    detail = {
        "schema_version": "idfrepair.airport-abm-seed-detail.v3",
        "scenario_id": "BASELINE_SPREAD",
        "seed": 40015,
        "interval_minutes": 15,
        "interval_labels": [f"step-{index}" for index in range(96)],
        "space_counts": {},
        "class_counts": {},
        "class_space_flows": [],
    }

    try:
        build_viewer_payload(
            spaces=spaces,
            detail=detail,
            access={"passenger_edges": [], "staff_edges": []},
        )
    except ValueError as exc:
        assert str(exc) == "viewer payload is missing Space data: entry"
    else:
        raise AssertionError("missing Space data must fail closed")


def test_viewer_payload_requires_complete_paired_energy_when_loaded() -> None:
    spaces = (_space("entry", "departure_entry", design_people=10.0),)
    detail = {
        "schema_version": "idfrepair.airport-abm-seed-detail.v3",
        "scenario_id": "BASELINE_SPREAD",
        "seed": 40015,
        "interval_minutes": 15,
        "interval_labels": [f"step-{index}" for index in range(96)],
        "space_counts": {"entry": _series(1.0)},
        "class_counts": {"entry": _classes(DOMESTIC_DEPARTURE=1.0)},
        "class_space_flows": [],
    }
    payload = build_viewer_payload(
        spaces=spaces,
        detail=detail,
        access={"passenger_edges": [], "staff_edges": []},
        energy_by_space={
            "entry": {"heating_kw": _series(2.0), "cooling_kw": _series(3.0)}
        },
    )
    assert payload["load_data_available"] is True
    assert payload["spaces"]["entry"]["heating_kw"] == _series(2.0)

    try:
        build_viewer_payload(
            spaces=spaces,
            detail=detail,
            access={"passenger_edges": [], "staff_edges": []},
            energy_by_space={"entry": {"heating_kw": _series(2.0)}},
        )
    except ValueError as exc:
        assert "cooling_kw" in str(exc)
    else:
        raise AssertionError("partial energy coverage must fail closed")
