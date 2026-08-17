'use strict';

((root, factory) => {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.IDFRepairViewerIssueState = api;
})(typeof globalThis === 'object' ? globalThis : this, () => {
  function canonical(value) {
    return String(value || '').trim().replace(/^['"]|['"]$/g, '').toLowerCase();
  }

  function uniqueNames(values, excluded = new Set()) {
    const seen = new Set(excluded);
    const names = [];
    for (const value of Array.isArray(values) ? values : []) {
      const key = canonical(value);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      names.push(String(value).trim());
    }
    return {names, seen};
  }

  function nameValues(input, ...keys) {
    return keys.flatMap((key) => {
      const value = input?.[key];
      if (Array.isArray(value)) return value;
      return value === undefined || value === null ? [] : [value];
    });
  }

  function normalizePolygons(values, role) {
    return Object.freeze((Array.isArray(values) ? values : []).flatMap((row) => {
      const vertices = (Array.isArray(row?.vertices) ? row.vertices : []).flatMap((vertex) => {
        if (!Array.isArray(vertex) || vertex.length < 3) return [];
        const point = vertex.slice(0, 3).map(Number);
        return point.every(Number.isFinite) ? [Object.freeze(point)] : [];
      });
      if (vertices.length < 3) return [];
      return [Object.freeze({
        surfaceId: String(row?.surfaceId || row?.surface_id || '').trim(),
        name: String(row?.name || '').trim(),
        role,
        vertices: Object.freeze(vertices)
      })];
    }));
  }

  function normalizeRoleLabels(input = {}) {
    const labels = input.roleLabels && typeof input.roleLabels === 'object'
      ? input.roleLabels
      : input.role_labels && typeof input.role_labels === 'object'
        ? input.role_labels
        : {};
    return Object.freeze(Object.fromEntries(
      ['target', 'paired', 'group', 'neutral', 'before', 'after']
        .map((role) => [role, String(labels[role] || '').trim()])
    ));
  }

  function normalizeIssueMode(input = {}) {
    const target = uniqueNames(nameValues(input, 'targetNames', 'target_surface_names', 'target'));
    const paired = uniqueNames(nameValues(input, 'pairedNames', 'paired_surface_names', 'paired'), target.seen);
    const group = uniqueNames(nameValues(input, 'groupNames', 'group_surface_names', 'group'), paired.seen);
    const beforePolygons = normalizePolygons(input.beforePolygons || input.before_vertices, 'before');
    const afterPolygons = normalizePolygons(input.afterPolygons || input.after_vertices, 'after');
    return Object.freeze({
      issueId: String(input.issueId || input.issue_id || '').trim(),
      kind: String(input.kind || '').trim(),
      status: String(input.status || '').trim(),
      title: String(input.title || '').trim(),
      severity: String(input.severity || 'review').trim().toLowerCase(),
      scopeLabel: String(input.scopeLabel || '').trim(),
      targetNames: Object.freeze(target.names),
      pairedNames: Object.freeze(paired.names),
      groupNames: Object.freeze(group.names),
      targetKeys: Object.freeze(target.names.map(canonical)),
      pairedKeys: Object.freeze(paired.names.map(canonical)),
      groupKeys: Object.freeze(group.names.map(canonical)),
      beforePolygons,
      afterPolygons,
      roleLabels: normalizeRoleLabels(input)
    });
  }

  function roleForSurface(name, mode) {
    const key = canonical(name);
    if (!mode || !key) return 'neutral';
    if (mode.targetKeys.includes(key)) return 'target';
    if (mode.pairedKeys.includes(key)) return 'paired';
    if (mode.groupKeys.includes(key)) return 'group';
    return 'neutral';
  }

  return Object.freeze({normalizeIssueMode, roleForSurface});
});
