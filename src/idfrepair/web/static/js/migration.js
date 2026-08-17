function normalizedVersion(value) {
  const parts = String(value || '').trim().replace(/^v/i, '').split('.');
  while (parts.length && Number(parts.at(-1)) === 0) parts.pop();
  return parts.join('.');
}

export function deriveMigrationState(sourceVersion, targets = [], preferredRuntimeId = null) {
  const source = normalizedVersion(sourceVersion);
  const matching = targets.find((row) => normalizedVersion(row.version) === source);
  const preferred = targets.find((row) => row.runtime_id === preferredRuntimeId);
  const selected = preferred || matching || targets[0] || null;
  return {
    sourceVersion: source,
    selectedRuntimeId: selected?.runtime_id || null,
    targetVersion: normalizedVersion(selected?.version),
    canCreateCopy: selected?.available === true,
    reason: selected?.reason || (selected?.available ? null : 'unavailable'),
    stepCount: Number(selected?.step_count || 0),
    steps: Array.isArray(selected?.steps) ? selected.steps : [],
    target: selected,
  };
}

export function summarizeMigrationReport(report = {}) {
  const idd = report.target_idd_validation || {};
  const simulation = report.energyplus_validation || {};
  return {
    safeCopy: report.original_preserved === true && report.creates_copy !== false,
    targetVersion: normalizedVersion(report.target_version),
    stepCount: Number(report.transition_step_count || 0),
    iddValid: idd.valid === true,
    iddIssueCount: Number(idd.issue_count || 0),
    simulationRan: simulation.status && simulation.status !== 'NOT_RUN',
    simulationPassed: simulation.status === 'PASSED',
    simulationStatus: simulation.status || 'NOT_RUN',
    warnings: Array.isArray(report.warnings) ? report.warnings : [],
    changes: report.changed_object_summary || {},
  };
}

if (typeof window !== 'undefined') {
  window.IDFRepairMigration = {
    deriveMigrationState,
    summarizeMigrationReport,
  };
}
