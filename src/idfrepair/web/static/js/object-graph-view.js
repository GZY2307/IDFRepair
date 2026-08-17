const SVG_NS = 'http://www.w3.org/2000/svg';
const MAX_NODES = 30;
const LANE_ORDER = Object.freeze({incoming: 0, current: 1, outgoing: 2});
const STATE_COPY = Object.freeze({
  'zh-CN': {
    selected: '当前对象', valid_reference: '有效引用', missing_reference: '缺失引用',
    candidate: '建议修改涉及', blocked: '被安全规则阻止'
  },
  en: {
    selected: 'Current object', valid_reference: 'Valid reference', missing_reference: 'Missing reference',
    candidate: 'In suggested change', blocked: 'Blocked by safety rule'
  }
});
const RELATION_COPY = Object.freeze({
  'zh-CN': {
    incoming: '谁引用当前对象', current: '当前对象', outgoing: '当前对象引用谁',
    references: '通过字段“{field}”引用', missingType: '未找到的目标对象',
    listTitle: '逐条引用关系（箭头方向就是引用方向）'
  },
  en: {
    incoming: 'References current object', current: 'Current object', outgoing: 'Referenced by current object',
    references: 'references through “{field}”', missingType: 'Missing target object',
    listTitle: 'Reference list (arrow direction is reference direction)'
  }
});

function compact(value) {
  return String(value ?? '').trim();
}

function graphStateLabel(kind, locale = 'zh-CN') {
  const language = locale === 'en' ? 'en' : 'zh-CN';
  return STATE_COPY[language][compact(kind)] || compact(kind) || STATE_COPY[language].valid_reference;
}

function short(value, limit = 28) {
  const text = compact(value);
  return text.length > limit ? `${text.slice(0, Math.max(1, limit - 1))}…` : text;
}

function graphEdgeDescription(edge, payload = {}, locale = 'zh-CN') {
  const language = locale === 'en' ? 'en' : 'zh-CN';
  const copy = RELATION_COPY[language];
  const nodes = new Map((payload.nodes || []).map((row) => [row.node_id, row]));
  const source = nodes.get(edge.source) || {};
  const target = nodes.get(edge.target) || {};
  const sourceType = compact(source.object_type) || copy.missingType;
  const targetType = compact(target.object_type) || copy.missingType;
  const sourceLabel = compact(source.object_name || source.label) || '—';
  const targetLabel = compact(target.object_name || target.label) || '—';
  const relation = copy.references.replace('{field}', compact(edge.field_name) || `#${edge.field_index || '—'}`);
  return `${sourceType} · ${sourceLabel} — ${relation} → ${targetType} · ${targetLabel}`;
}

function fullNodeLabel(node = {}, locale = 'zh-CN') {
  const language = locale === 'en' ? 'en' : 'zh-CN';
  const type = compact(node.object_type) || RELATION_COPY[language].missingType;
  const label = compact(node.object_name || node.label) || '—';
  return `${type} · ${label}`;
}

function lanesFor(payload, nodes) {
  const selected = compact(payload.selected_node_id);
  const lanes = new Map([[selected, 'current']]);
  const edges = [...(payload.edges || [])].sort((left, right) =>
    `${left.source}|${left.target}`.localeCompare(`${right.source}|${right.target}`)
  );
  for (const edge of edges) {
    if (edge.target === selected) lanes.set(edge.source, 'incoming');
    if (edge.source === selected) lanes.set(edge.target, 'outgoing');
  }
  for (let pass = 0; pass < 2; pass += 1) {
    for (const edge of edges) {
      if (lanes.has(edge.source) && !lanes.has(edge.target)) lanes.set(edge.target, lanes.get(edge.source));
      if (lanes.has(edge.target) && !lanes.has(edge.source)) lanes.set(edge.source, lanes.get(edge.target));
    }
  }
  for (const row of nodes) {
    if (!lanes.has(row.node_id)) lanes.set(row.node_id, row.kind === 'selected' ? 'current' : 'outgoing');
  }
  return lanes;
}

function layoutObjectGraph(payload = {}, options = {}) {
  const width = Math.max(480, Number(options.width || 720));
  const selectedId = compact(payload.selected_node_id);
  const sourceNodes = [...(payload.nodes || [])].sort((left, right) => {
    if (left.node_id === selectedId) return -1;
    if (right.node_id === selectedId) return 1;
    return `${left.label}|${left.node_id}`.localeCompare(`${right.label}|${right.node_id}`);
  }).slice(0, MAX_NODES);
  const included = new Set(sourceNodes.map((row) => row.node_id));
  const lanes = lanesFor(payload, sourceNodes);
  const sorted = sourceNodes.map((row) => ({...row, lane: lanes.get(row.node_id)})).sort((left, right) => {
    const lane = (LANE_ORDER[left.lane] ?? 9) - (LANE_ORDER[right.lane] ?? 9);
    if (lane) return lane;
    return `${left.depth}|${left.label}|${left.node_id}`.localeCompare(`${right.depth}|${right.label}|${right.node_id}`);
  });
  const perLane = new Map();
  for (const row of sorted) {
    if (!perLane.has(row.lane)) perLane.set(row.lane, []);
    perLane.get(row.lane).push(row);
  }
  const maxRows = Math.max(1, ...[...perLane.values()].map((rows) => rows.length));
  const height = Math.max(340, 128 + maxRows * 92);
  const xByLane = {incoming: width * .17, current: width * .5, outgoing: width * .83};
  const nodes = sorted.map((row) => {
    const rows = perLane.get(row.lane);
    const index = rows.indexOf(row);
    const usableHeight = height - 64;
    const spacing = usableHeight / (rows.length + 1);
    const outward = Number(row.depth || 1) > 1 ? (row.lane === 'incoming' ? -28 : row.lane === 'outgoing' ? 28 : 0) : 0;
    return {...row, x: Math.round(xByLane[row.lane] + outward), y: Math.round(48 + spacing * (index + 1))};
  });
  const byId = new Map(nodes.map((row) => [row.node_id, row]));
  const edges = [...(payload.edges || [])].filter((edge) => included.has(edge.source) && included.has(edge.target))
    .sort((left, right) => `${left.source}|${left.field_index}|${left.target}`.localeCompare(`${right.source}|${right.field_index}|${right.target}`))
    .map((edge, index) => ({
      ...edge,
      badge: String(index + 1),
      sourceNode: byId.get(edge.source),
      targetNode: byId.get(edge.target)
    }));
  const parallelGroups = new Map();
  for (const edge of edges) {
    const key = `${edge.source}|${edge.target}`;
    if (!parallelGroups.has(key)) parallelGroups.set(key, []);
    parallelGroups.get(key).push(edge);
  }
  for (const group of parallelGroups.values()) {
    group.forEach((edge, index) => {
      edge.parallelIndex = index;
      edge.parallelCount = group.length;
    });
  }
  return {width, height, nodes, edges, truncated: Boolean(payload.truncated || (payload.nodes || []).length > MAX_NODES)};
}

function relationshipRows(payload = {}, options = {}) {
  const locale = options.locale === 'en' ? 'en' : 'zh-CN';
  const layout = options.layout || layoutObjectGraph(payload, {width: options.width});
  return layout.edges.map((edge) => {
    const source = fullNodeLabel(edge.sourceNode, locale);
    const target = fullNodeLabel(edge.targetNode, locale);
    const field = compact(edge.field_name) || `#${edge.field_index || '—'}`;
    const state = compact(edge.state) || 'valid';
    return Object.freeze({
      badge: edge.badge,
      source,
      field,
      target,
      state,
      sourceNode: edge.sourceNode,
      targetNode: edge.targetNode,
      text: `${source} — ${field} → ${target}`
    });
  });
}

function svgNode(documentRef, tag, attrs = {}, text) {
  const item = documentRef.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => item.setAttribute(key, String(value)));
  if (text !== undefined) item.textContent = String(text);
  return item;
}

function renderObjectGraph(container, payload, options = {}) {
  const documentRef = options.documentRef || globalThis.document;
  const locale = options.locale === 'en' ? 'en' : 'zh-CN';
  const layout = layoutObjectGraph(payload, {width: options.width});
  container.replaceChildren();
  const relationCopy = RELATION_COPY[locale];
  const svg = svgNode(documentRef, 'svg', {
    viewBox: `0 0 ${layout.width} ${layout.height}`,
    role: 'group',
    'aria-label': relationCopy.listTitle
  });
  const defs = svgNode(documentRef, 'defs');
  for (const [id, className] of [['graph-arrow-valid', 'valid'], ['graph-arrow-missing', 'missing']]) {
    const marker = svgNode(documentRef, 'marker', {
      id, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse'
    });
    marker.append(svgNode(documentRef, 'path', {d: 'M 0 0 L 10 5 L 0 10 z', class: `graph-arrow ${className}`}));
    defs.append(marker);
  }
  svg.append(defs);
  const laneHeading = svgNode(documentRef, 'g', {class: 'graph-lane-headings'});
  for (const [lane, x] of Object.entries({incoming: layout.width * .17, current: layout.width * .5, outgoing: layout.width * .83})) {
    laneHeading.append(svgNode(documentRef, 'text', {x, y: 24, 'text-anchor': 'middle'}, relationCopy[lane]));
  }
  svg.append(laneHeading);
  const edgeLayer = svgNode(documentRef, 'g', {class: 'graph-edges'});
  for (const edge of layout.edges) {
    const dx = edge.targetNode.x - edge.sourceNode.x;
    const dy = edge.targetNode.y - edge.sourceNode.y;
    const horizontal = Math.abs(dx) >= Math.abs(dy);
    const direction = horizontal ? Math.sign(dx || 1) : Math.sign(dy || 1);
    const coordinates = horizontal
      ? {x1: edge.sourceNode.x + direction * 94, y1: edge.sourceNode.y, x2: edge.targetNode.x - direction * 94, y2: edge.targetNode.y}
      : {x1: edge.sourceNode.x, y1: edge.sourceNode.y + direction * 36, x2: edge.targetNode.x, y2: edge.targetNode.y - direction * 36};
    const state = edge.state || 'valid';
    const parallelOffset = (edge.parallelIndex - (edge.parallelCount - 1) / 2) * 18;
    const badgeX = (coordinates.x1 + coordinates.x2) / 2 + (horizontal ? 0 : parallelOffset);
    const badgeY = (coordinates.y1 + coordinates.y2) / 2 + (horizontal ? parallelOffset : 0);
    edgeLayer.append(
      svgNode(documentRef, 'line', {
        ...coordinates,
        class: `graph-edge state-${state}`,
        'marker-end': `url(#graph-arrow-${state === 'missing' ? 'missing' : 'valid'})`
      }),
      svgNode(documentRef, 'circle', {
        cx: badgeX,
        cy: badgeY,
        r: 9,
        class: `graph-edge-badge-background state-${state}`,
        'aria-hidden': 'true'
      }),
      svgNode(documentRef, 'text', {
        x: badgeX,
        y: badgeY + 3,
        'text-anchor': 'middle',
        class: 'graph-edge-badge',
        'aria-hidden': 'true'
      }, edge.badge)
    );
  }
  svg.append(edgeLayer);
  const nodeLayer = svgNode(documentRef, 'g', {class: 'graph-nodes'});
  for (const row of layout.nodes) {
    const state = graphStateLabel(row.kind, locale);
    const group = svgNode(documentRef, 'g', {
      class: `graph-node kind-${row.kind}`,
      transform: `translate(${row.x} ${row.y})`, role: 'button', tabindex: '0',
      'aria-label': `${state}: ${row.label}`
    });
    group.append(
      svgNode(documentRef, 'rect', {x: -92, y: -35, width: 184, height: 70, rx: 8}),
      svgNode(documentRef, 'text', {x: 0, y: -13, 'text-anchor': 'middle', class: 'graph-node-type'}, short(row.object_type || relationCopy.missingType, 26)),
      svgNode(documentRef, 'text', {x: 0, y: 5, 'text-anchor': 'middle', class: 'graph-node-label'}, short(row.label, 26)),
      svgNode(documentRef, 'text', {x: 0, y: 22, 'text-anchor': 'middle', class: 'graph-node-state'}, state)
    );
    if (typeof options.onSelect === 'function') {
      const select = () => options.onSelect(row);
      group.addEventListener('click', select);
      group.addEventListener('keydown', (event) => {
        if (!['Enter', ' '].includes(event.key)) return;
        event.preventDefault();
        select();
      });
    }
    nodeLayer.append(group);
  }
  svg.append(nodeLayer);
  container.append(svg);
  if (layout.edges.length) {
    const relationships = relationshipRows(payload, {layout, locale});
    const list = documentRef.createElement('section');
    list.className = 'graph-reference-list';
    const heading = documentRef.createElement('strong');
    heading.textContent = relationCopy.listTitle;
    list.append(heading);
    const rows = documentRef.createElement('ul');
    for (const relationship of relationships) {
      const row = documentRef.createElement('li');
      row.className = relationship.state === 'missing' ? 'state-missing' : 'state-valid';
      const source = documentRef.createElement('button');
      source.type = 'button';
      source.textContent = relationship.source;
      source.setAttribute('aria-label', relationship.source);
      const field = documentRef.createElement('span');
      field.textContent = ` — ${relationship.field} → `;
      const target = documentRef.createElement('button');
      target.type = 'button';
      target.textContent = relationship.target;
      target.setAttribute('aria-label', relationship.target);
      if (typeof options.onSelect === 'function') {
        source.addEventListener('click', () => options.onSelect(relationship.sourceNode));
        target.addEventListener('click', () => options.onSelect(relationship.targetNode));
      }
      row.append(source, field, target);
      rows.append(row);
    }
    list.append(rows);
    container.append(list);
  }
  return layout;
}

const api = Object.freeze({graphStateLabel, graphEdgeDescription, layoutObjectGraph, relationshipRows, renderObjectGraph});
globalThis.IDFRepairObjectGraph = api;

export {graphStateLabel, graphEdgeDescription, layoutObjectGraph, relationshipRows, renderObjectGraph};
