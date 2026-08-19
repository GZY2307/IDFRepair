from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path("src/idfrepair/web/static")


def test_v3_state_validates_classes_density_flow_and_chart_filtering() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for viewer state tests")
    module = (ROOT / "occupancy-viewer-state.js").resolve()
    script = f"""
const state = require({json.dumps(str(module))});
const zeros = Array(96).fill(0);
const dep = Array.from({{length: 96}}, (_, index) => index);
const staff = Array.from({{length: 96}}, (_, index) => 95 - index);
const labels = Array.from({{length: 96}}, (_, index) => {{
  const start = index * 15;
  const end = start + 15;
  const clock = value => `${{String(Math.floor(value / 60)).padStart(2, '0')}}:${{String(value % 60).padStart(2, '0')}}`;
  return `${{clock(start)}}–${{clock(end)}}`;
}});
const payload = state.validatePayload({{
  schema_version: 'idfrepair.airport-abm-viewer.v3',
  scenario_id: 'MORNING_BANK', period_id: 'representative-day', minutes_per_step: 15,
  timestamps: labels,
  agent_classes: ['DOMESTIC_DEPARTURE', 'DOMESTIC_ARRIVAL', 'DOMESTIC_TRANSFER', 'INTERNATIONAL_ARRIVAL', 'STAFF'],
  semantics: {{method: 'directed_discrete_event_abm', measured_flow_claim: false,
    walking_trajectory_claim: false, controlled_parameters: true}},
  load_data_available: true,
  spaces: {{
    gate: {{source_space_name: 'gate', zone_name: 'zone-gate', function: 'domestic_waiting',
      region: 'northeast_pier', floor_area_m2: 100, design_people: 50,
      bem_people_supported: true, occupancy: dep.map((value, i) => value + staff[i]),
      class_counts: {{DOMESTIC_DEPARTURE: dep, DOMESTIC_ARRIVAL: zeros,
        DOMESTIC_TRANSFER: zeros, INTERNATIONAL_ARRIVAL: zeros, STAFF: staff}},
      heating_kw: zeros, cooling_kw: zeros}},
    restroom: {{source_space_name: 'restroom', zone_name: 'zone-restroom', function: 'restroom',
      region: 'northeast_pier', floor_area_m2: 20, design_people: null,
      bem_people_supported: false, occupancy: staff,
      class_counts: {{DOMESTIC_DEPARTURE: zeros, DOMESTIC_ARRIVAL: zeros,
        DOMESTIC_TRANSFER: zeros, INTERNATIONAL_ARRIVAL: zeros, STAFF: staff}},
      heating_kw: zeros, cooling_kw: zeros}}
  }},
  flows: [{{from_function: 'departure_entry', to_function: 'domestic_waiting',
    evidence_label: 'functional route abstraction', counts: dep,
    class_counts: {{DOMESTIC_DEPARTURE: dep, DOMESTIC_ARRIVAL: zeros,
      DOMESTIC_TRANSFER: zeros, INTERNATIONAL_ARRIVAL: zeros, STAFF: zeros}}}}],
  space_edge_flows: [{{from_node: 'entry', to_node: 'gate',
    from_space_name: 'gate', to_space_name: 'restroom',
    from_function: 'departure_entry', to_function: 'domestic_waiting',
    evidence_layer: 'B_FUNCTIONAL_PROCESS', evidence_label: 'functional route abstraction',
    evidence_ref: 'fixture:directed-edge', abstraction_flag: true,
    scenario_condition: null, door_instances: [], roles: ['DOMESTIC_DEPARTURE'],
    off_model_boundary: false, counts: dep,
    class_counts: {{DOMESTIC_DEPARTURE: dep, DOMESTIC_ARRIVAL: zeros,
      DOMESTIC_TRANSFER: zeros, INTERNATIONAL_ARRIVAL: zeros, STAFF: zeros}}}}]
}});
if (!payload.is_v3 || payload.historical_demo) throw new Error('v3 identity');
if (state.metricValue(payload.spaces.gate, 10, 'count', 'DOMESTIC_DEPARTURE') !== 10) throw new Error('class count');
if (state.metricValue(payload.spaces.gate, 10, 'density', 'DOMESTIC_DEPARTURE') !== 0.1) throw new Error('class density');
if (state.metricValue(payload.spaces.restroom, 10, 'capacity', 'ALL') !== 0) throw new Error('flow-only capacity');
const totals = state.timelineTotals(payload, 'DOMESTIC_DEPARTURE');
if (totals.occupancy[20] !== 20) throw new Error('filtered timeline');
const flow = state.flowSnapshot(payload, 20, 'DOMESTIC_DEPARTURE');
if (flow.length !== 1 || flow[0].count !== 20 || flow[0].evidence_label !== 'functional route abstraction') throw new Error(JSON.stringify(flow));
const edgeFlow = state.edgeFlowSnapshot(payload, 20, 'DOMESTIC_DEPARTURE');
if (edgeFlow.length !== 1 || edgeFlow[0].count !== 20 || edgeFlow[0].from_space_name !== 'gate' ||
    edgeFlow[0].to_space_name !== 'restroom' || !edgeFlow[0].abstraction_flag) throw new Error(JSON.stringify(edgeFlow));
const details = state.spaceDetails(payload, 'gate', 20, 'density', 'DOMESTIC_DEPARTURE');
if (details.function !== 'domestic_waiting' || details.agent_class_counts.DOMESTIC_DEPARTURE !== 20 ||
    details.measured_flow_claim !== false || details.historical_demo) throw new Error(JSON.stringify(details));
const overloaded = {{...payload.spaces.gate, occupancy: Array(96).fill(60),
  class_counts: {{...payload.spaces.gate.class_counts, DOMESTIC_DEPARTURE: Array(96).fill(60), STAFF: zeros}}}};
if (state.colorForMetric(overloaded, 0, 'density', 999, 'ALL') !== '#c63d36') throw new Error('overload color');
const whole = state.wholeModelDetails(payload, 20, 'DOMESTIC_DEPARTURE');
if (whole.current_people !== 20 || whole.space_count !== 2 || !whole.load_data_available) throw new Error(JSON.stringify(whole));
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def test_v2_payload_remains_historical_and_is_not_promoted_to_v3_route_data() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for viewer state tests")
    module = (ROOT / "occupancy-viewer-state.js").resolve()
    legacy_test = Path("tests/occupancy_room_aware/test_viewer_state.py").read_text()
    assert "idfrepair.room-aware-viewer.v2" in legacy_test
    script = f"""
const state = require({json.dumps(str(module))});
if (!state.SCHEMAS.includes('idfrepair.room-aware-viewer.v2') ||
    !state.SCHEMAS.includes('idfrepair.airport-abm-viewer.v3')) throw new Error('schemas');
if (state.V3_AGENT_CLASSES.length !== 5) throw new Error('classes');
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def test_v2_flow_metadata_accepts_generic_self_consistent_entrance_names() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for viewer state tests")
    module = (ROOT / "occupancy-viewer-state.js").resolve()
    script = f"""
const state = require({json.dumps(str(module))});
const zeros = Array(96).fill(0);
const labels = Array.from({{length: 96}}, (_, index) => String(index));
const makeSpace = name => ({{
  source_space_name: name, zone_name: name + '-zone', category: 'terminal_hall',
  floor_area_m2: 10, design_people: 5, occupancy: zeros,
  heating_kw: zeros, cooling_kw: zeros, flow_phase_steps: 0,
  flow_phase_minutes: 0, adjacency_hops: 0, nearest_entrance_space: name,
  is_flow_entrance: true
}});
const payload = state.validatePayload({{
  schema_version: 'idfrepair.room-aware-viewer.v2', scenario_id: 'HISTORICAL_FIXTURE',
  period_id: 'fixture-day', minutes_per_step: 15, timestamps: labels,
  interval_start_times: labels, interval_end_times: labels, interval_labels: labels,
  energyplus_timestamps: labels, space_count: 2,
  flow: {{entrance_spaces: ['entry-alpha', 'entry-beta'],
    phase_semantics: 'controlled_occupancy_response_not_travel_time',
    walking_route_claim: false, measured_flow_claim: false}},
  spaces: {{'entry-alpha': makeSpace('entry-alpha'), 'entry-beta': makeSpace('entry-beta')}}
}});
if (payload.is_v3 || !payload.historical_demo || payload.space_count !== 2) throw new Error('legacy fixture');
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def test_v3_dom_contract_keeps_controls_compact_and_chart_scrubbable() -> None:
    html = (ROOT / "epshape-viewer.html").read_text()
    viewer = (ROOT / "epshape-viewer.js").read_text()
    style = (ROOT / "epshape-viewer.css").read_text()
    local = (ROOT / "occupancy-local.html").read_text()

    for identity in (
        "occupancy-class-filters",
        "occupancy-flow-toggle",
        "occupancy-flow-layer",
        "occupancy-controls-toggle",
        "occupancy-details-toggle",
        "occupancy-details-drag-handle",
        "occupancy-details-close",
        "occupancy-detail-hvac",
        "occupancy-timeline-chart",
        "occupancy-time",
    ):
        assert f'id="{identity}"' in html
    for value in (
        "ALL",
        "DOMESTIC_DEPARTURE",
        "DOMESTIC_ARRIVAL",
        "DOMESTIC_TRANSFER",
        "INTERNATIONAL_ARRIVAL",
        "STAFF",
    ):
        assert f'data-agent-class="{value}"' in html
    chart = html[html.index('class="occupancy-chart-control"'):]
    assert chart.index('id="occupancy-timeline-chart"') < chart.index('id="occupancy-time"')
    assert "renderOccupancyFlowArrows" in viewer
    assert 'id="occupancy-timeline-heating"' in html
    assert 'id="occupancy-timeline-cooling"' in html
    assert "wholeModelDetails" in viewer
    assert "renderOccupancyDetails(mesh ? mesh.userData.roomKey : null)" in viewer
    assert "未加载真实 EnergyPlus 负荷" in viewer
    assert "[...occupancyState.edgeFlowSnapshot(" in viewer
    assert "flow.abstraction_flag" in viewer
    assert "details.public_air_loop" in viewer
    assert "occupancyRoomAnchor" in viewer
    assert "occupancyFunctionAnchor" not in viewer
    assert ".slice(0, 24)" not in viewer
    assert "depthTest = false" in viewer
    assert "clampOccupancyDetailsPosition" in viewer
    assert "setPointerCapture" in viewer
    assert "occupancyDetailsDismissed" in viewer
    assert "occupancyControlsMinimized" in viewer
    assert "child.traverse((object) =>" in viewer
    assert "disposedGeometries" in viewer
    assert "occupancyClassButtons.forEach" in viewer
    assert "occupancyFlowToggle.addEventListener" in viewer
    assert "occupancyClassFilters.hidden = !currentOccupancy.is_v3" in viewer
    assert "occupancyFlowLayer.hidden = !currentOccupancy.is_v3" in viewer
    assert ".occupancy-class-filters" in style
    assert ".occupancy-flow-toggle" in style
    assert ".occupancy-controls.minimized" in style
    assert ".occupancy-details-drag-handle" in style
    assert "304 个 Space" not in local
    assert "304 Spaces" not in local
    assert "optional JSON" not in local
    assert "可选 JSON" not in local
