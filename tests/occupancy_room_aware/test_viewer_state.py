"""Pure-JS room-aware viewer state and integration contracts."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_viewer_state_validates_metrics_timeline_colors_and_details() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for occupancy viewer-state contracts")
    module = Path(
        "src/idfrepair/web/static/occupancy-viewer-state.js"
    ).resolve()
    script = f"""
const state = require({json.dumps(str(module))});
const valuesA = Array.from({{length: 96}}, (_, i) => i / 10);
const valuesB = Array.from({{length: 96}}, (_, i) => (95 - i) / 20);
const starts = Array.from({{length: 96}}, (_, i) => `${{String(Math.floor(i / 4)).padStart(2, '0')}}:${{String((i % 4) * 15).padStart(2, '0')}}`);
const ends = Array.from({{length: 96}}, (_, i) => `${{String(Math.floor((i + 1) * 15 / 60)).padStart(2, '0')}}:${{String((i + 1) * 15 % 60).padStart(2, '0')}}`);
const labels = starts.map((value, i) => `${{value}}–${{ends[i]}}`);
const payload = state.validatePayload({{
  schema_version: 'idfrepair.room-aware-viewer.v2',
  scenario_id: 'baseline_r', period_id: 'winter', minutes_per_step: 15,
  flow: {{entrance_spaces: ['z-u-hall-2', 'z-u-hall-3'],
    phase_semantics: 'controlled_occupancy_response_not_travel_time',
    walking_route_claim: false, measured_flow_claim: false}},
  timestamp_semantics: 'interval_start_to_end; EnergyPlus timestamp is interval end',
  timestamps: labels,
  interval_start_times: starts,
  interval_end_times: ends,
  interval_labels: labels,
  energyplus_timestamps: ends.map(value => `01/15  ${{value}}:00`),
  spaces: {{
    'hall-1': {{category: 'terminal_hall', floor_area_m2: 100, design_people: 10,
      nearest_entrance_space: 'z-u-hall-2', adjacency_hops: 2,
      flow_distance_band: 1, flow_phase_steps: 1, flow_phase_minutes: 15,
      is_flow_entrance: false, phase_basis: 'public_dynamic_adjacency_tercile',
      metadata_status: 'SOURCE_METADATA_CONSISTENT', occupancy: valuesA,
      heating_kw: valuesA.map(v => v * 2), cooling_kw: valuesA.map(v => v * 3)}},
    'office-1': {{category: 'office', floor_area_m2: 20, design_people: 5,
      nearest_entrance_space: 'z-u-hall-3', adjacency_hops: 4,
      flow_distance_band: 2, flow_phase_steps: 0, flow_phase_minutes: 0,
      is_flow_entrance: false, phase_basis: 'staff_fixed_not_entrance_delayed',
      metadata_status: 'SOURCE_METADATA_CONFLICT', occupancy: valuesB,
      heating_kw: valuesB.map(v => v), cooling_kw: valuesB.map(v => v * 4)}}
  }}
}});
if (payload.space_count !== 2 || payload.timestamps.length !== 96) throw new Error('payload');
if (payload.timestamps[24] !== '06:00–06:15' || payload.energyplus_timestamps[24] !== '01/15  06:15:00') throw new Error('interval');
if (state.timeIndexFromClock('06:00', 15) !== 24 || state.timeIndexFromClock('21:00', 15) !== 84) throw new Error('clock');
if (state.metricValue(payload.spaces['hall-1'], 10, 'count') !== 1) throw new Error('count');
if (state.metricValue(payload.spaces['hall-1'], 10, 'density') !== 0.01) throw new Error('density');
if (state.metricValue(payload.spaces['hall-1'], 10, 'capacity') !== 10) throw new Error('capacity');
if (state.stepIndex(95, 1, 96) !== 0 || state.stepIndex(0, -1, 96) !== 95) throw new Error('step');
const low = state.colorForNormalized(0);
const high = state.colorForNormalized(1);
if (!/^#[0-9a-f]{{6}}$/i.test(low) || low === high) throw new Error('colors');
const details = state.spaceDetails(payload, 'office-1', 20, 'density');
if (!details.conflict || details.category !== 'office' || details.current_people !== valuesB[20] ||
    details.heating_kw !== valuesB[20] || details.cooling_kw !== valuesB[20] * 4 ||
    details.nearest_entrance_space !== 'z-u-hall-3' || details.flow_phase_minutes !== 0) throw new Error(JSON.stringify(details));
const totals = state.timelineTotals(payload);
if (totals.occupancy.length !== 96 || totals.heating_kw[10] !== valuesA[10] * 2 + valuesB[10]) throw new Error('timeline');
"""
    subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)


def test_viewer_integrates_room_function_and_occupancy_controls() -> None:
    root = Path("src/idfrepair/web/static")
    index = (root / "index.html").read_text(encoding="utf-8")
    html = (root / "epshape-viewer.html").read_text(encoding="utf-8")
    viewer = (root / "epshape-viewer.js").read_text(encoding="utf-8")
    bridge = (root / "viewer-bridge.js").read_text(encoding="utf-8")
    style = (root / "epshape-viewer.css").read_text(encoding="utf-8")

    for identity in (
        "occupancy-controls",
        "occupancy-play",
        "occupancy-time",
        "occupancy-time-label",
        "occupancy-metric",
        "occupancy-timeline-chart",
        "occupancy-details",
    ):
        assert f'id="{identity}"' in html
    assert 'value="roomFunction"' in html
    assert 'value="occupancy"' in html
    assert "/static/occupancy-viewer-state.js" in html
    assert "idfrepair:viewer-occupancy" in viewer
    assert "loadOccupancy" in bridge
    assert "pendingOccupancy" in bridge
    assert ".occupancy-controls" in style
    assert ".occupancy-gradient" in style
    assert ".occupancy-details" in style
    assert 'class="occupancy-chart-control"' in html
    chart_start = html.index('class="occupancy-chart-control"')
    chart_end = html.index("</label>", chart_start)
    assert chart_start < html.index('id="occupancy-timeline-chart"') < chart_end
    assert chart_start < html.index('id="occupancy-time"') < chart_end
    assert ".occupancy-chart-control input" in style
    assert "function scrubOccupancyTimeline" in viewer
    assert "occupancyTimeInput.addEventListener('pointermove'" in viewer
    assert 'id="occupancy-detail-flow"' in html
    assert 'id="occupancy-detail-phase"' in html
    for identity in (
        "occupancy-payload-file",
        "occupancy-payload-clear",
        "occupancy-payload-status",
    ):
        assert f'id="{identity}"' in index
    assert "occupancy_payload_invalid" in viewer
    assert "if (container) observer.observe(container);" in viewer
    session_actions = index[index.index('class="session-bar-actions"'):index.index("</section>", index.index('class="session-bar-actions"'))]
    assert session_actions.index('id="open-session-settings"') < session_actions.index('id="occupancy-payload-file"')
    main_identity = index[index.index('class="main-view-identity"'):index.index("</div>", index.index('class="main-view-identity"'))]
    assert "occupancy-payload-file" not in main_identity


def test_demo_bridge_loads_and_clears_local_occupancy_layer() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for demo occupancy bridge contracts")
    module = Path("src/idfrepair/web/static/viewer-bridge.js").resolve()
    script = f"""
(async () => {{
  const posted = [];
  const windowListeners = {{}};
  const inputListeners = {{}};
  const clearListeners = {{}};
  const iframeWindow = {{postMessage(message, origin) {{ posted.push({{message, origin}}); }}}};
  const iframe = {{contentWindow: iframeWindow, addEventListener() {{}}}};
  const fileInput = {{addEventListener() {{}}, files: []}};
  const occupancyInput = {{
    files: [], value: '',
    addEventListener(type, listener) {{ inputListeners[type] = listener; }}
  }};
  const occupancyClear = {{
    disabled: true,
    addEventListener(type, listener) {{ clearListeners[type] = listener; }}
  }};
  const occupancyStatus = {{textContent: '', hidden: true}};
  const elements = {{
    '#model-viewer': iframe,
    '#idf-file': fileInput,
    '#occupancy-payload-file': occupancyInput,
    '#occupancy-payload-clear': occupancyClear,
    '#occupancy-payload-status': occupancyStatus
  }};
  global.CustomEvent = class CustomEvent {{ constructor(type, init) {{ this.type = type; this.detail = init?.detail; }} }};
  global.document = {{
    documentElement: {{lang: 'zh-CN'}},
    querySelector(selector) {{ return elements[selector] || null; }}
  }};
  global.window = {{
    location: {{origin: 'https://demo.local'}},
    addEventListener(type, listener) {{ windowListeners[type] = listener; }},
    dispatchEvent() {{}},
    requestAnimationFrame(callback) {{ callback(); }}
  }};
  require({json.dumps(str(module))});
  windowListeners.message({{
    source: iframeWindow, origin: window.location.origin,
    data: {{type: 'idfrepair:viewer-ready'}}
  }});
  posted.length = 0;
  occupancyInput.files = [{{
    name: 'room-aware.json',
    async text() {{ return JSON.stringify({{schema_version: 'idfrepair.room-aware-viewer.v2'}}); }}
  }}];
  await inputListeners.change();
  const load = posted.at(-1)?.message;
  if (load?.type !== 'idfrepair:viewer-occupancy' ||
      load?.payload?.schema_version !== 'idfrepair.room-aware-viewer.v2') {{
    throw new Error(`occupancy payload not forwarded: ${{JSON.stringify(load)}}`);
  }}
  windowListeners.message({{
    source: iframeWindow, origin: window.location.origin,
    data: {{type: 'idfrepair:viewer-occupancy-ready', spaceCount: 304,
      scenarioId: 'baseline_r', periodId: 'winter'}}
  }});
  if (!occupancyStatus.hidden || occupancyStatus.textContent !== '' || occupancyClear.disabled) {{
    throw new Error(`ready state should be compact: ${{JSON.stringify(occupancyStatus)}}`);
  }}
  clearListeners.click();
  const cleared = posted.at(-1)?.message;
  if (cleared?.type !== 'idfrepair:viewer-occupancy' || cleared.payload !== null ||
      !occupancyClear.disabled || occupancyInput.value !== '') {{
    throw new Error(`clear state invalid: ${{JSON.stringify(cleared)}}`);
  }}
  occupancyInput.files = [{{name: 'bad.json', async text() {{ return '{{'; }}}}];
  await inputListeners.change();
  if (occupancyStatus.hidden || !occupancyStatus.textContent.includes('失败')) {{
    throw new Error(`invalid JSON not reported: ${{occupancyStatus.textContent}}`);
  }}
}})().catch((error) => {{ console.error(error); process.exit(1); }});
"""
    subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)


def test_local_viewer_shell_allows_file_controls_to_shrink_on_mobile() -> None:
    html = Path("src/idfrepair/web/static/occupancy-local.html").read_text(
        encoding="utf-8"
    )

    assert "header { min-width: 0;" in html
    assert "label { min-width: 0;" in html
    assert 'input[type="file"] { width: min(230px, 100%); min-width: 0;' in html
    assert "iframe { min-width: 0;" in html
