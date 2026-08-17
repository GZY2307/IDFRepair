const KIND_ORDER = Object.freeze({energyplus: 0, audit: 1, experimental: 2, osm: 3});
const SEVERITY_ORDER = Object.freeze({error: 0, severe: 0, fatal: 0, warning: 1, review: 2, info: 3});

function compact(value) {
  return String(value ?? '').trim();
}

function unique(values = []) {
  return [...new Set(values.map(compact).filter(Boolean))];
}

function diagnosticTarget(root = {}) {
  const metadata = root?.metadata && typeof root.metadata === 'object' ? root.metadata : {};
  const target = metadata?.target && typeof metadata.target === 'object' ? metadata.target : metadata;
  return {
    object_index: Number.isInteger(target.object_index) ? target.object_index : null,
    field_index: Number.isInteger(target.field_index) ? target.field_index : null,
    object_type: compact(target.object_type || root.object_type),
    object_name: compact(target.object_name || root.object_name)
  };
}

function diagnosticLocator(root = {}, roots = []) {
  const target = diagnosticTarget(root);
  if (Number.isInteger(target.object_index)) return target;
  if (!target.object_type || !target.object_name) return target;
  const identity = `${target.object_type.toLowerCase()}\u0000${target.object_name.toLowerCase()}`;
  const matches = roots.map(diagnosticTarget).filter((candidate) => (
    Number.isInteger(candidate.object_index)
      && `${candidate.object_type.toLowerCase()}\u0000${candidate.object_name.toLowerCase()}` === identity
  ));
  const indices = unique(matches.map((candidate) => candidate.object_index));
  return indices.length === 1 ? {...target, object_index: Number(indices[0])} : target;
}

function preflightIssueRows(report = {}) {
  const issues = Array.isArray(report?.issues) ? report.issues : [];
  return issues.map((source, index) => {
    const locator = source?.locator && typeof source.locator === 'object' ? source.locator : {};
    const surfaces = Array.isArray(locator.surfaces) ? locator.surfaces : [];
    const target = surfaces[0] || {};
    const paired = surfaces.slice(1);
    const safe = source?.safe_to_apply === true;
    const excludedCandidate = !safe && compact(source?.kind) === 'vertex_snap';
    const modelWide = compact(source?.kind) === 'canonicalize_air_boundary' && surfaces.length > 1;
    return {
      ...source,
      id: compact(source?.issue_id || `preflight-${index}`),
      root_id: compact(source?.issue_id || `preflight-${index}`),
      kind: 'audit',
      preflight_kind: compact(source?.kind || 'geometry_review'),
      rule_id: compact(source?.kind || 'geometry_review'),
      family: 'geometry',
      source: 'preflight',
      severity: safe ? 'warning' : 'review',
      support_status: safe ? 'safe-auto' : (excludedCandidate ? 'evidence' : 'review'),
      status: safe ? 'SAFE_TO_APPLY' : 'REVIEW_ONLY',
      title: compact(source?.title || source?.kind || source?.issue_id),
      summary: compact(source?.explanation),
      action: '',
      object_index: Number.isInteger(target.object_index) ? target.object_index : null,
      object_type: compact(target.object_type),
      object_name: modelWide ? '' : compact(target.name),
      paired_object_name: modelWide ? '' : compact(paired[0]?.name),
      surface_names: modelWide ? [] : unique(surfaces.map((row) => row?.name)),
      zone: modelWide ? '' : compact(target.space_name || target.zone_name || source?.space_refs?.[0]),
      locator_scope: modelWide ? 'global' : 'local',
      affected_surface_count: surfaces.length,
      locator_action: modelWide ? 'global' : 'locate',
      evidence_signature: compact(source?.kind || source?.issue_id || `preflight-${index}`)
    };
  });
}

function locatorVertices(surfaces, field) {
  return surfaces.flatMap((surface) => {
    const vertices = surface?.[field];
    if (!Array.isArray(vertices)) return [];
    return [{
      surface_id: compact(surface.surface_id),
      name: compact(surface.name),
      vertices
    }];
  });
}

function issueSurfaceNames(issue = {}) {
  if (issue?.locator_scope === 'global') return [];
  const locatorSurfaces = Array.isArray(issue?.locator?.surfaces) ? issue.locator.surfaces : [];
  const names = locatorSurfaces.map((surface) => surface?.name);
  if (!names.length) {
    names.push(...(Array.isArray(issue.surface_names) ? issue.surface_names : []));
    names.push(issue.object_name, issue.paired_object_name);
  }
  return unique(names);
}

function issueLocatorMessage(issue = {}, _groupRows = []) {
  const surfaces = issue?.locator_scope === 'global'
    ? []
    : (Array.isArray(issue?.locator?.surfaces) ? issue.locator.surfaces : []);
  const names = issueSurfaceNames(issue);
  return Object.freeze({
    issue_id: compact(issue.issue_id || issue.id || issue.root_id),
    kind: compact(issue.preflight_kind || issue.kind),
    target_surface_names: Object.freeze(names.slice(0, 1)),
    paired_surface_names: Object.freeze(names.slice(1)),
    // Display groups can contain thousands of distant findings. They are never
    // camera targets; a locator is bounded to the selected issue's evidence.
    group_surface_names: Object.freeze([]),
    before_vertices: Object.freeze(locatorVertices(surfaces, 'before_world_vertices')),
    after_vertices: Object.freeze(locatorVertices(surfaces, 'after_world_vertices')),
    status: compact(issue.status || (issue.safe_to_apply === true ? 'SAFE_TO_APPLY' : 'REVIEW_ONLY'))
  });
}

function locationScope(row) {
  return compact(
    row.zone || row.zone_name || row.story || row.building_story || row.elevation_group
      || row.surface?.zone || row.surface?.story || row.surface?.space || ''
  );
}

function issueCategories(row) {
  const kind = compact(row.kind || 'energyplus').toLowerCase();
  const support = compact(row.support_status).toLowerCase();
  const categories = new Set([kind === 'energyplus' ? 'energyplus' : kind]);
  if (support === 'safe-auto' || row.safe_to_repair === true) categories.add('safe');
  if (support === 'interactive' || row.needs_input === true) categories.add('input');
  if (support === 'review' || row.status === 'REVIEW_ONLY') categories.add('review');
  if (support === 'evidence') {
    categories.delete('review');
    categories.add('evidence');
  }
  if (['unsupported', 'disabled'].includes(support) || row.unsupported === true) {
    categories.add('unsupported');
  }
  return [...categories].sort();
}

function normalizedIssue(row, index = 0) {
  const kind = compact(row.kind || 'energyplus').toLowerCase();
  const severity = compact(row.severity || (kind === 'energyplus' ? 'error' : 'review')).toLowerCase();
  const id = compact(row.id || row.root_id || row.finding_id || row.preview_id || `issue-${index}`);
  const objectName = compact(row.object_name || row.surface?.name || row.name);
  const pairedName = compact(row.paired_surface?.name);
  const zone = locationScope(row);
  const title = compact(row.title || row.presentation?.title || row.message || row.message_id || row.rule_id || id);
  const evidenceSignature = compact(
    row.evidence_signature || row.evidence_group || row.evidence_type
      || row.support_entry_id || row.message_id || row.rule_id || row.family || 'unclassified'
  );
  const rule = compact(row.rule_id || row.family || row.message_id || 'unclassified');
  return {
    ...row,
    id,
    kind,
    severity,
    title,
    zone,
    object_name: objectName,
    paired_object_name: pairedName,
    evidence_signature: evidenceSignature,
    categories: issueCategories({...row, kind})
  };
}

function groupKey(row) {
  return [row.kind, row.rule_id || row.family || 'unclassified', row.severity, row.evidence_signature]
    .map((value) => encodeURIComponent(compact(value).toLowerCase()))
    .join('|');
}

function compareIssues(left, right) {
  return [left.zone, left.object_name, left.paired_object_name, left.id]
    .join('|').localeCompare([right.zone, right.object_name, right.paired_object_name, right.id].join('|'));
}

function compareGroups(left, right) {
  const kindDelta = (KIND_ORDER[left.kind] ?? 99) - (KIND_ORDER[right.kind] ?? 99);
  if (kindDelta) return kindDelta;
  const severityDelta = (SEVERITY_ORDER[left.severity] ?? 99) - (SEVERITY_ORDER[right.severity] ?? 99);
  if (severityDelta) return severityDelta;
  return `${left.title}|${left.key}`.localeCompare(`${right.title}|${right.key}`);
}

function groupIssues(rows = []) {
  const groups = new Map();
  rows.forEach((source, index) => {
    const row = normalizedIssue(source, index);
    const key = groupKey(row);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        kind: row.kind,
        severity: row.severity,
        title: row.title,
        zone: row.zone,
        evidence_signature: row.evidence_signature,
        categories: new Set(),
        zones: new Set(),
        rows: []
      });
    }
    const group = groups.get(key);
    row.categories.forEach((category) => group.categories.add(category));
    if (row.zone) group.zones.add(row.zone);
    group.rows.push(row);
  });
  return [...groups.values()].map((group) => ({
    ...group,
    categories: [...group.categories].sort(),
    zone: group.zones.size === 1 ? [...group.zones][0] : '',
    zone_count: group.zones.size,
    zones: [...group.zones].sort(),
    rows: group.rows.sort(compareIssues),
    count: group.rows.length
  })).sort(compareGroups);
}

function issueHaystack(row) {
  return [
    row.title, row.summary, row.action, row.rule_id, row.family, row.message_id,
    row.object_type, row.object_name, row.field_name, row.zone, row.story,
    row.paired_object_name, row.surface?.space, row.surface?.construction,
    row.surface?.boundary_condition
  ].map(compact).join(' ').toLowerCase();
}

function filterIssues(groups = [], query = '', category = 'all') {
  const needle = compact(query).toLowerCase();
  const selected = compact(category || 'all').toLowerCase();
  return groups.flatMap((group) => {
    const rows = group.rows.filter((row) => {
      if (selected !== 'all' && !row.categories.includes(selected)) return false;
      return !needle || issueHaystack(row).includes(needle);
    });
    return rows.length ? [{...group, rows, count: rows.length}] : [];
  });
}

function categoryCounts(rows = []) {
  const counts = {all: rows.length, energyplus: 0, safe: 0, review: 0, evidence: 0, input: 0, unsupported: 0, audit: 0, experimental: 0, osm: 0};
  rows.forEach((row) => {
    issueCategories(row).forEach((category) => {
      counts[category] = (counts[category] || 0) + 1;
    });
  });
  return counts;
}

const api = Object.freeze({
  categoryCounts,
  diagnosticLocator,
  filterIssues,
  groupIssues,
  issueCategories,
  issueLocatorMessage,
  normalizedIssue,
  preflightIssueRows
});
globalThis.IDFRepairIssueNavigator = api;

export {
  categoryCounts,
  diagnosticLocator,
  filterIssues,
  groupIssues,
  issueCategories,
  issueLocatorMessage,
  normalizedIssue,
  preflightIssueRows
};
