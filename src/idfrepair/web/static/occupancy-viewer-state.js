'use strict';

(function occupancyViewerStateFactory(root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.IDFRepairOccupancyState = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  const SCHEMA = 'idfrepair.room-aware-viewer.v2';
  const CATEGORIES = Object.freeze([
    'terminal_hall', 'office', 'commerce_retail', 'dining', 'restroom', 'breakroom'
  ]);
  const CATEGORY_COLORS = Object.freeze({
    terminal_hall: '#2878c8',
    office: '#64748b',
    commerce_retail: '#d68b00',
    dining: '#d94f45',
    restroom: '#8a5bbd',
    breakroom: '#21936f'
  });
  const METRICS = Object.freeze(['count', 'density', 'capacity']);
  const GRADIENT_STOPS = Object.freeze([
    [0.00, '#f3f7f6'],
    [0.18, '#c7e8df'],
    [0.42, '#61b7a8'],
    [0.68, '#f0b74d'],
    [1.00, '#c63d36']
  ]);

  function finite(value) {
    return Number.isFinite(Number(value));
  }

  function finiteSeries(values, length, identity) {
    if (!Array.isArray(values) || values.length !== length) {
      throw new Error(`occupancy_series_length_invalid:${identity}`);
    }
    const result = values.map(Number);
    if (result.some((value) => !Number.isFinite(value) || value < 0)) {
      throw new Error(`occupancy_series_value_invalid:${identity}`);
    }
    return Object.freeze(result);
  }

  function validatePayload(input) {
    if (!input || input.schema_version !== SCHEMA) throw new Error('occupancy_payload_schema_invalid');
    if (!String(input.scenario_id || '').trim() || !String(input.period_id || '').trim()) {
      throw new Error('occupancy_payload_identity_missing');
    }
    const minutes = Number(input.minutes_per_step);
    if (!Number.isInteger(minutes) || minutes <= 0 || 60 % minutes !== 0) {
      throw new Error('occupancy_payload_timestep_invalid');
    }
    if (!Array.isArray(input.timestamps) || input.timestamps.length !== 96) {
      throw new Error('occupancy_payload_timestamps_invalid');
    }
    if (!Array.isArray(input.interval_start_times) || input.interval_start_times.length !== 96 ||
        !Array.isArray(input.interval_end_times) || input.interval_end_times.length !== 96 ||
        !Array.isArray(input.interval_labels) || input.interval_labels.length !== 96 ||
        !Array.isArray(input.energyplus_timestamps) || input.energyplus_timestamps.length !== 96) {
      throw new Error('occupancy_payload_interval_metadata_invalid');
    }
    if (input.timestamps.some((value, index) => String(value) !== String(input.interval_labels[index]))) {
      throw new Error('occupancy_payload_timestamp_label_mismatch');
    }
    const rawSpaces = input.spaces && typeof input.spaces === 'object' ? input.spaces : {};
    const names = Object.keys(rawSpaces);
    if (!names.length || Number(input.space_count ?? names.length) !== names.length) {
      throw new Error('occupancy_payload_space_count_mismatch');
    }
    const normalizedSpaces = {};
    const canonicalNames = new Set();
    const flow = input.flow && typeof input.flow === 'object' ? input.flow : null;
    const entranceSpaces = flow ? flow.entrance_spaces : [];
    if (flow && (
      !Array.isArray(entranceSpaces) || entranceSpaces.length !== 2 ||
      !entranceSpaces.includes('z-u-hall-2') || !entranceSpaces.includes('z-u-hall-3') ||
      flow.phase_semantics !== 'controlled_occupancy_response_not_travel_time' ||
      flow.walking_route_claim !== false || flow.measured_flow_claim !== false
    )) {
      throw new Error('occupancy_payload_flow_metadata_invalid');
    }
    names.sort((a, b) => a.localeCompare(b)).forEach((name) => {
      const key = String(name).trim().toLowerCase();
      if (!key || canonicalNames.has(key)) throw new Error(`occupancy_payload_space_duplicate:${name}`);
      canonicalNames.add(key);
      const row = rawSpaces[name] || {};
      if (!CATEGORIES.includes(row.category)) throw new Error(`occupancy_payload_category_invalid:${name}`);
      const area = Number(row.floor_area_m2);
      const design = Number(row.design_people);
      if (!finite(area) || area <= 0 || !finite(design) || design <= 0) {
        throw new Error(`occupancy_payload_capacity_invalid:${name}`);
      }
      if (flow) {
        const phaseSteps = Number(row.flow_phase_steps);
        const phaseMinutes = Number(row.flow_phase_minutes);
        const hops = Number(row.adjacency_hops);
        if (!entranceSpaces.includes(row.nearest_entrance_space) ||
            !Number.isInteger(phaseSteps) || phaseSteps < 0 || phaseSteps > 3 ||
            phaseMinutes !== phaseSteps * minutes || !Number.isInteger(hops) || hops < 0 ||
            ((row.category === 'office' || row.category === 'breakroom') && phaseSteps !== 0) ||
            (Boolean(row.is_flow_entrance) !== entranceSpaces.includes(name)) ||
            (row.is_flow_entrance && (phaseSteps !== 0 || hops !== 0 || row.nearest_entrance_space !== name))) {
          throw new Error(`occupancy_payload_flow_space_invalid:${name}`);
        }
      }
      normalizedSpaces[name] = Object.freeze({
        ...row,
        source_space_name: String(row.source_space_name || name),
        zone_name: String(row.zone_name || ''),
        floor_area_m2: area,
        design_people: design,
        conflict: Boolean(row.conflict || row.metadata_status === 'SOURCE_METADATA_CONFLICT'),
        occupancy: finiteSeries(row.occupancy, 96, `${name}:occupancy`),
        heating_kw: finiteSeries(row.heating_kw, 96, `${name}:heating_kw`),
        cooling_kw: finiteSeries(row.cooling_kw, 96, `${name}:cooling_kw`)
      });
    });
    return Object.freeze({
      ...input,
      minutes_per_step: minutes,
      space_count: names.length,
      timestamps: Object.freeze(input.timestamps.map(String)),
      interval_start_times: Object.freeze(input.interval_start_times.map(String)),
      interval_end_times: Object.freeze(input.interval_end_times.map(String)),
      interval_labels: Object.freeze(input.interval_labels.map(String)),
      energyplus_timestamps: Object.freeze(input.energyplus_timestamps.map(String)),
      spaces: Object.freeze(normalizedSpaces)
    });
  }

  function timeIndexFromClock(clock, minutesPerStep = 15) {
    const match = /^(\d{1,2}):(\d{2})$/.exec(String(clock || '').trim());
    if (!match) throw new Error(`occupancy_clock_invalid:${clock}`);
    const hour = Number(match[1]);
    const minute = Number(match[2]);
    if (hour < 0 || hour > 23 || minute < 0 || minute >= 60 || minute % minutesPerStep) {
      throw new Error(`occupancy_clock_invalid:${clock}`);
    }
    return (hour * 60 + minute) / minutesPerStep;
  }

  function stepIndex(current, delta, length = 96) {
    const size = Math.max(1, Number(length) || 1);
    return ((Number(current) + Number(delta)) % size + size) % size;
  }

  function metricValue(space, timeIndex, metric = 'density') {
    if (!space || !METRICS.includes(metric)) throw new Error(`occupancy_metric_invalid:${metric}`);
    const count = Number(space.occupancy[timeIndex]);
    if (metric === 'count') return count;
    if (metric === 'density') return count / Number(space.floor_area_m2);
    return 100 * count / Number(space.design_people);
  }

  function hexToRgb(hex) {
    const value = parseInt(String(hex).replace('#', ''), 16);
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
  }

  function rgbToHex(rgb) {
    return `#${rgb.map((value) => Math.round(value).toString(16).padStart(2, '0')).join('')}`;
  }

  function colorForNormalized(value) {
    const normalized = Math.max(0, Math.min(1, Number(value) || 0));
    let left = GRADIENT_STOPS[0];
    let right = GRADIENT_STOPS.at(-1);
    for (let index = 1; index < GRADIENT_STOPS.length; index += 1) {
      if (normalized <= GRADIENT_STOPS[index][0]) {
        left = GRADIENT_STOPS[index - 1];
        right = GRADIENT_STOPS[index];
        break;
      }
    }
    const span = right[0] - left[0] || 1;
    const weight = (normalized - left[0]) / span;
    const leftRgb = hexToRgb(left[1]);
    const rightRgb = hexToRgb(right[1]);
    return rgbToHex(leftRgb.map((channel, index) => (
      channel + (rightRgb[index] - channel) * weight
    )));
  }

  function maximumMetric(payload, timeIndex, metric = 'density') {
    return Math.max(
      0,
      ...Object.values(payload.spaces).map((space) => metricValue(space, timeIndex, metric))
    );
  }

  function colorForMetric(space, timeIndex, metric, maximum) {
    const value = metricValue(space, timeIndex, metric);
    return colorForNormalized(maximum > 0 ? value / maximum : 0);
  }

  function spaceDetails(payload, spaceName, timeIndex, metric = 'density') {
    const space = payload.spaces[spaceName];
    if (!space) throw new Error(`occupancy_space_unknown:${spaceName}`);
    return Object.freeze({
      source_space_name: space.source_space_name,
      zone_name: space.zone_name,
      category: space.category,
      conflict: space.conflict,
      metadata_status: space.metadata_status,
      nearest_entrance_space: space.nearest_entrance_space,
      adjacency_hops: space.adjacency_hops,
      flow_distance_band: space.flow_distance_band,
      flow_phase_steps: space.flow_phase_steps,
      flow_phase_minutes: space.flow_phase_minutes,
      is_flow_entrance: Boolean(space.is_flow_entrance),
      phase_basis: space.phase_basis,
      scenario_id: payload.scenario_id,
      period_id: payload.period_id,
      time: payload.timestamps[timeIndex],
      time_index: timeIndex,
      current_people: space.occupancy[timeIndex],
      density_people_m2: space.occupancy[timeIndex] / space.floor_area_m2,
      capacity_percent: 100 * space.occupancy[timeIndex] / space.design_people,
      metric,
      metric_value: metricValue(space, timeIndex, metric),
      heating_kw: space.heating_kw[timeIndex],
      cooling_kw: space.cooling_kw[timeIndex]
    });
  }

  function timelineTotals(payload) {
    const totals = {
      occupancy: Array(96).fill(0),
      heating_kw: Array(96).fill(0),
      cooling_kw: Array(96).fill(0)
    };
    Object.values(payload.spaces).forEach((space) => {
      for (let index = 0; index < 96; index += 1) {
        totals.occupancy[index] += space.occupancy[index];
        totals.heating_kw[index] += space.heating_kw[index];
        totals.cooling_kw[index] += space.cooling_kw[index];
      }
    });
    return Object.freeze({
      occupancy: Object.freeze(totals.occupancy),
      heating_kw: Object.freeze(totals.heating_kw),
      cooling_kw: Object.freeze(totals.cooling_kw)
    });
  }

  return Object.freeze({
    SCHEMA,
    CATEGORIES,
    CATEGORY_COLORS,
    GRADIENT_STOPS,
    METRICS,
    colorForMetric,
    colorForNormalized,
    maximumMetric,
    metricValue,
    spaceDetails,
    stepIndex,
    timeIndexFromClock,
    timelineTotals,
    validatePayload
  });
});
