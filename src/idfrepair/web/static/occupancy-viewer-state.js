'use strict';

(function occupancyViewerStateFactory(root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.IDFRepairOccupancyState = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  const V2_SCHEMA = 'idfrepair.room-aware-viewer.v2';
  const V3_SCHEMA = 'idfrepair.airport-abm-viewer.v3';
  const SCHEMA = V2_SCHEMA;
  const SCHEMAS = Object.freeze([V2_SCHEMA, V3_SCHEMA]);
  const V3_AGENT_CLASSES = Object.freeze([
    'DOMESTIC_DEPARTURE',
    'DOMESTIC_ARRIVAL',
    'DOMESTIC_TRANSFER',
    'INTERNATIONAL_ARRIVAL',
    'STAFF'
  ]);
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
  const FUNCTION_COLORS = Object.freeze({
    departure_entry: '#23806f', arrival_exit: '#4f7ec9', baggage_claim: '#8e67bd',
    central_hall: '#3c91a3', concourse: '#53a65b', domestic_waiting: '#2c78c5',
    international_arrival: '#7a5bc4', international_hall: '#9b63b6', transfer: '#7056a5',
    commercial: '#d68b00', restaurant: '#d94f45', office: '#64748b',
    breakroom: '#21936f', restroom: '#8a5bbd', info: '#7b8581'
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

  function validateV3Payload(input) {
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
    if (!Array.isArray(input.agent_classes) || input.agent_classes.length !== V3_AGENT_CLASSES.length ||
        input.agent_classes.some((value, index) => value !== V3_AGENT_CLASSES[index])) {
      throw new Error('occupancy_payload_agent_classes_invalid');
    }
    const semantics = input.semantics && typeof input.semantics === 'object' ? input.semantics : {};
    if (semantics.method !== 'directed_discrete_event_abm' || semantics.measured_flow_claim !== false ||
        semantics.walking_trajectory_claim !== false || semantics.controlled_parameters !== true) {
      throw new Error('occupancy_payload_v3_semantics_invalid');
    }
    const loadDataAvailable = input.load_data_available === true;
    const rawSpaces = input.spaces && typeof input.spaces === 'object' ? input.spaces : {};
    const names = Object.keys(rawSpaces);
    if (!names.length || Number(input.space_count ?? names.length) !== names.length) {
      throw new Error('occupancy_payload_space_count_mismatch');
    }
    const normalizedSpaces = {};
    const canonicalNames = new Set();
    names.sort((a, b) => a.localeCompare(b)).forEach((name) => {
      const key = String(name).trim().toLowerCase();
      if (!key || canonicalNames.has(key)) throw new Error(`occupancy_payload_space_duplicate:${name}`);
      canonicalNames.add(key);
      const row = rawSpaces[name] || {};
      const area = Number(row.floor_area_m2);
      if (!finite(area) || area <= 0 || !String(row.function || '').trim() || !String(row.region || '').trim()) {
        throw new Error(`occupancy_payload_v3_space_invalid:${name}`);
      }
      const supported = row.bem_people_supported === true;
      const design = row.design_people === null || row.design_people === undefined
        ? null : Number(row.design_people);
      if ((supported && (!finite(design) || design <= 0)) || (!supported && design !== null && design !== 0)) {
        throw new Error(`occupancy_payload_capacity_invalid:${name}`);
      }
      const occupancy = finiteSeries(row.occupancy, 96, `${name}:occupancy`);
      const classCounts = {};
      V3_AGENT_CLASSES.forEach((agentClass) => {
        classCounts[agentClass] = finiteSeries(
          row.class_counts?.[agentClass], 96, `${name}:${agentClass}`
        );
      });
      for (let index = 0; index < 96; index += 1) {
        const total = V3_AGENT_CLASSES.reduce((sum, agentClass) => sum + classCounts[agentClass][index], 0);
        if (Math.abs(total - occupancy[index]) > 1e-5) {
          throw new Error(`occupancy_payload_v3_class_reconciliation:${name}:${index}`);
        }
      }
      normalizedSpaces[name] = Object.freeze({
        ...row,
        source_space_name: String(row.source_space_name || name),
        zone_name: String(row.zone_name || ''),
        function: String(row.function),
        category: String(row.function),
        region: String(row.region),
        floor_area_m2: area,
        design_people: supported ? design : null,
        bem_people_supported: supported,
        conflict: false,
        occupancy,
        class_counts: Object.freeze(classCounts),
        heating_kw: loadDataAvailable
          ? finiteSeries(row.heating_kw, 96, `${name}:heating_kw`) : null,
        cooling_kw: loadDataAvailable
          ? finiteSeries(row.cooling_kw, 96, `${name}:cooling_kw`) : null
      });
    });
    const flows = (Array.isArray(input.flows) ? input.flows : []).map((row, flowIndex) => {
      if (!String(row.from_function || '').trim() || !String(row.to_function || '').trim() ||
          !String(row.evidence_label || '').trim()) {
        throw new Error(`occupancy_payload_v3_flow_invalid:${flowIndex}`);
      }
      const counts = finiteSeries(row.counts, 96, `flow:${flowIndex}:counts`);
      const classCounts = {};
      V3_AGENT_CLASSES.forEach((agentClass) => {
        classCounts[agentClass] = finiteSeries(
          row.class_counts?.[agentClass], 96, `flow:${flowIndex}:${agentClass}`
        );
      });
      for (let index = 0; index < 96; index += 1) {
        const total = V3_AGENT_CLASSES.reduce((sum, agentClass) => sum + classCounts[agentClass][index], 0);
        if (Math.abs(total - counts[index]) > 1e-5) {
          throw new Error(`occupancy_payload_v3_flow_reconciliation:${flowIndex}:${index}`);
        }
      }
      return Object.freeze({...row, counts, class_counts: Object.freeze(classCounts)});
    });
    const knownSpaceNames = new Set(
      Object.values(normalizedSpaces).map((space) => space.source_space_name.toLowerCase())
    );
    const spaceEdgeFlows = (Array.isArray(input.space_edge_flows) ? input.space_edge_flows : [])
      .map((row, edgeIndex) => {
        const fromNode = String(row.from_node || '').trim();
        const toNode = String(row.to_node || '').trim();
        const fromSpace = row.from_space_name === null || row.from_space_name === undefined
          ? null : String(row.from_space_name).trim();
        const toSpace = row.to_space_name === null || row.to_space_name === undefined
          ? null : String(row.to_space_name).trim();
        const fromFunction = String(row.from_function || '').trim();
        const toFunction = String(row.to_function || '').trim();
        const layer = String(row.evidence_layer || '').trim();
        const label = String(row.evidence_label || '').trim();
        const reference = String(row.evidence_ref || '').trim();
        const abstraction = row.abstraction_flag;
        const offModel = row.off_model_boundary === true;
        const boundaryDirection = row.boundary_direction === null || row.boundary_direction === undefined
          ? null : String(row.boundary_direction).trim();
        const doors = Array.isArray(row.door_instances)
          ? row.door_instances.map((value) => String(value).trim()) : [];
        const roles = Array.isArray(row.roles)
          ? row.roles.map((value) => String(value).trim()) : [];
        const modelEndpointCount = Number(Boolean(fromSpace)) + Number(Boolean(toSpace));
        if (!fromNode || !toNode || !fromFunction || !toFunction ||
            !['A_EXPLICIT_DOOR', 'B_FUNCTIONAL_PROCESS'].includes(layer) ||
            !label || !reference || typeof abstraction !== 'boolean' ||
            (fromSpace && !knownSpaceNames.has(fromSpace.toLowerCase())) ||
            (toSpace && !knownSpaceNames.has(toSpace.toLowerCase())) ||
            (!offModel && (modelEndpointCount !== 2 || boundaryDirection !== null)) ||
            (offModel && modelEndpointCount !== 1) ||
            (boundaryDirection === 'incoming' && (fromSpace !== null || toSpace === null)) ||
            (boundaryDirection === 'outgoing' && (fromSpace === null || toSpace !== null)) ||
            (offModel && !['incoming', 'outgoing'].includes(boundaryDirection)) ||
            doors.some((value) => !value) ||
            !roles.length || roles.some((role) => !V3_AGENT_CLASSES.includes(role)) ||
            (layer === 'A_EXPLICIT_DOOR' && (abstraction || !doors.length)) ||
            (layer === 'B_FUNCTIONAL_PROCESS' && !abstraction)) {
          throw new Error(`occupancy_payload_v3_space_edge_invalid:${edgeIndex}`);
        }
        const counts = finiteSeries(row.counts, 96, `space-edge:${edgeIndex}:counts`);
        const classCounts = {};
        V3_AGENT_CLASSES.forEach((agentClass) => {
          classCounts[agentClass] = finiteSeries(
            row.class_counts?.[agentClass], 96, `space-edge:${edgeIndex}:${agentClass}`
          );
          if (!roles.includes(agentClass) && classCounts[agentClass].some((value) => value > 0)) {
            throw new Error(`occupancy_payload_v3_space_edge_role_mismatch:${edgeIndex}:${agentClass}`);
          }
        });
        for (let index = 0; index < 96; index += 1) {
          const total = V3_AGENT_CLASSES.reduce(
            (sum, agentClass) => sum + classCounts[agentClass][index], 0
          );
          if (Math.abs(total - counts[index]) > 1e-5) {
            throw new Error(`occupancy_payload_v3_space_edge_reconciliation:${edgeIndex}:${index}`);
          }
        }
        return Object.freeze({
          ...row,
          from_node: fromNode,
          to_node: toNode,
          from_space_name: fromSpace,
          to_space_name: toSpace,
          from_function: fromFunction,
          to_function: toFunction,
          evidence_layer: layer,
          evidence_label: label,
          evidence_ref: reference,
          abstraction_flag: abstraction,
          off_model_boundary: offModel,
          boundary_direction: boundaryDirection,
          door_instances: Object.freeze(doors),
          roles: Object.freeze(roles),
          counts,
          class_counts: Object.freeze(classCounts)
        });
      });
    return Object.freeze({
      ...input,
      is_v3: true,
      historical_demo: false,
      load_data_available: loadDataAvailable,
      minutes_per_step: minutes,
      space_count: names.length,
      timestamps: Object.freeze(input.timestamps.map(String)),
      interval_labels: Object.freeze(input.timestamps.map(String)),
      spaces: Object.freeze(normalizedSpaces),
      flows: Object.freeze(flows),
      space_edge_flows: Object.freeze(spaceEdgeFlows),
      functions: Object.freeze([...new Set(Object.values(normalizedSpaces).map((space) => space.function))].sort())
    });
  }

  function validatePayload(input) {
    if (!input || !SCHEMAS.includes(input.schema_version)) throw new Error('occupancy_payload_schema_invalid');
    if (input.schema_version === V3_SCHEMA) return validateV3Payload(input);
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
    const canonicalEntrances = Array.isArray(entranceSpaces)
      ? entranceSpaces.map((name) => String(name).trim().toLowerCase())
      : [];
    if (flow && (
      !Array.isArray(entranceSpaces) || entranceSpaces.length !== 2 ||
      canonicalEntrances.some((name) => !name) || new Set(canonicalEntrances).size !== 2 ||
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
      is_v3: false,
      historical_demo: true,
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

  function countForClass(space, timeIndex, agentClass = 'ALL') {
    if (agentClass === 'ALL' || !space.class_counts) return Number(space.occupancy[timeIndex]);
    if (!V3_AGENT_CLASSES.includes(agentClass)) throw new Error(`occupancy_agent_class_invalid:${agentClass}`);
    return Number(space.class_counts[agentClass][timeIndex]);
  }

  function metricValue(space, timeIndex, metric = 'density', agentClass = 'ALL') {
    if (!space || !METRICS.includes(metric)) throw new Error(`occupancy_metric_invalid:${metric}`);
    const count = countForClass(space, timeIndex, agentClass);
    if (metric === 'count') return count;
    if (metric === 'density') return count / Number(space.floor_area_m2);
    if (!space.design_people) return 0;
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

  function maximumMetric(payload, timeIndex, metric = 'density', agentClass = 'ALL') {
    return Math.max(
      0,
      ...Object.values(payload.spaces).map((space) => metricValue(space, timeIndex, metric, agentClass))
    );
  }

  function colorForMetric(space, timeIndex, metric, maximum, agentClass = 'ALL') {
    const value = metricValue(space, timeIndex, metric, agentClass);
    if (space.design_people) {
      const utilization = countForClass(space, timeIndex, agentClass) / Number(space.design_people);
      if (utilization > 1) return '#c63d36';
      if (metric === 'capacity') return colorForNormalized(utilization * 0.68);
    }
    return colorForNormalized(maximum > 0 ? value / maximum : 0);
  }

  function spaceDetails(payload, spaceName, timeIndex, metric = 'density', agentClass = 'ALL') {
    const space = payload.spaces[spaceName];
    if (!space) throw new Error(`occupancy_space_unknown:${spaceName}`);
    const currentPeople = countForClass(space, timeIndex, agentClass);
    const classSnapshot = Object.freeze(Object.fromEntries(
      V3_AGENT_CLASSES.map((name) => [name, Number(space.class_counts?.[name]?.[timeIndex] || 0)])
    ));
    return Object.freeze({
      source_space_name: space.source_space_name,
      zone_name: space.zone_name,
      category: space.category,
      function: space.function || space.category,
      region: space.region || '',
      public_air_loop: space.public_air_loop || '',
      office_doas: space.office_doas || '',
      zone_hvac: space.zone_hvac || '',
      bem_people_supported: space.bem_people_supported !== false,
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
      current_people: currentPeople,
      density_people_m2: currentPeople / space.floor_area_m2,
      capacity_percent: space.design_people ? 100 * currentPeople / space.design_people : null,
      active_agent_class: agentClass,
      agent_class_counts: classSnapshot,
      measured_flow_claim: payload.semantics?.measured_flow_claim ?? false,
      historical_demo: Boolean(payload.historical_demo),
      metric,
      metric_value: metricValue(space, timeIndex, metric, agentClass),
      load_data_available: payload.load_data_available !== false,
      heating_kw: space.heating_kw ? space.heating_kw[timeIndex] : null,
      cooling_kw: space.cooling_kw ? space.cooling_kw[timeIndex] : null
    });
  }

  function wholeModelDetails(payload, timeIndex, agentClass = 'ALL') {
    const spaces = Object.values(payload.spaces);
    const currentPeople = spaces.reduce(
      (sum, space) => sum + countForClass(space, timeIndex, agentClass), 0
    );
    const floorArea = spaces.reduce((sum, space) => sum + Number(space.floor_area_m2), 0);
    const designPeople = spaces.reduce(
      (sum, space) => sum + (space.design_people ? Number(space.design_people) : 0), 0
    );
    const loadAvailable = payload.load_data_available !== false;
    return Object.freeze({
      whole_model: true,
      space_count: spaces.length,
      scenario_id: payload.scenario_id,
      period_id: payload.period_id,
      time: payload.timestamps[timeIndex],
      time_index: timeIndex,
      current_people: currentPeople,
      floor_area_m2: floorArea,
      density_people_m2: floorArea > 0 ? currentPeople / floorArea : 0,
      design_people: designPeople,
      capacity_percent: designPeople > 0 ? 100 * currentPeople / designPeople : null,
      active_agent_class: agentClass,
      load_data_available: loadAvailable,
      heating_kw: loadAvailable
        ? spaces.reduce((sum, space) => sum + Number(space.heating_kw[timeIndex]), 0) : null,
      cooling_kw: loadAvailable
        ? spaces.reduce((sum, space) => sum + Number(space.cooling_kw[timeIndex]), 0) : null,
      active_flow_count: flowSnapshot(payload, timeIndex, agentClass)
        .reduce((sum, flow) => sum + flow.count, 0)
    });
  }

  function timelineTotals(payload, agentClass = 'ALL') {
    const loadAvailable = payload.load_data_available !== false;
    const totals = {
      occupancy: Array(96).fill(0),
      heating_kw: loadAvailable ? Array(96).fill(0) : null,
      cooling_kw: loadAvailable ? Array(96).fill(0) : null
    };
    Object.values(payload.spaces).forEach((space) => {
      for (let index = 0; index < 96; index += 1) {
        totals.occupancy[index] += countForClass(space, index, agentClass);
        if (loadAvailable) {
          totals.heating_kw[index] += space.heating_kw[index];
          totals.cooling_kw[index] += space.cooling_kw[index];
        }
      }
    });
    return Object.freeze({
      occupancy: Object.freeze(totals.occupancy),
      heating_kw: totals.heating_kw ? Object.freeze(totals.heating_kw) : null,
      cooling_kw: totals.cooling_kw ? Object.freeze(totals.cooling_kw) : null,
      load_data_available: loadAvailable
    });
  }

  function flowSnapshot(payload, timeIndex, agentClass = 'ALL') {
    if (!payload?.is_v3) return Object.freeze([]);
    return Object.freeze(payload.flows.map((flow) => Object.freeze({
      from_function: flow.from_function,
      to_function: flow.to_function,
      evidence_label: flow.evidence_label,
      count: agentClass === 'ALL'
        ? Number(flow.counts[timeIndex])
        : Number(flow.class_counts[agentClass]?.[timeIndex] || 0)
    })).filter((flow) => flow.count > 0));
  }

  function edgeFlowSnapshot(payload, timeIndex, agentClass = 'ALL') {
    if (!payload?.is_v3) return Object.freeze([]);
    return Object.freeze((payload.space_edge_flows || []).map((flow) => Object.freeze({
      from_node: flow.from_node,
      to_node: flow.to_node,
      from_space_name: flow.from_space_name,
      to_space_name: flow.to_space_name,
      from_function: flow.from_function,
      to_function: flow.to_function,
      evidence_layer: flow.evidence_layer,
      evidence_label: flow.evidence_label,
      evidence_ref: flow.evidence_ref,
      abstraction_flag: flow.abstraction_flag,
      scenario_condition: flow.scenario_condition,
      door_instances: flow.door_instances,
      off_model_boundary: flow.off_model_boundary,
      boundary_direction: flow.boundary_direction,
      count: agentClass === 'ALL'
        ? Number(flow.counts[timeIndex])
        : Number(flow.class_counts[agentClass]?.[timeIndex] || 0)
    })).filter((flow) => flow.count > 0));
  }

  return Object.freeze({
    SCHEMA,
    SCHEMAS,
    V2_SCHEMA,
    V3_SCHEMA,
    V3_AGENT_CLASSES,
    CATEGORIES,
    CATEGORY_COLORS,
    FUNCTION_COLORS,
    GRADIENT_STOPS,
    METRICS,
    colorForMetric,
    colorForNormalized,
    edgeFlowSnapshot,
    flowSnapshot,
    maximumMetric,
    metricValue,
    spaceDetails,
    stepIndex,
    timeIndexFromClock,
    timelineTotals,
    wholeModelDetails,
    validatePayload
  });
});
