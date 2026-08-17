const INTERNAL_TERMS = ['root', 'candidate', 'gate', 'idd'];
const OPERATION_STAGES = Object.freeze([
  'PREPARING',
  'CHECKING_MODEL',
  'APPLYING_IDF',
  'WRITING_OSM',
  'VERIFYING_OSM',
  'DIAGNOSING',
  'REPAIRING',
  'FINAL_VALIDATION'
]);

function deriveOperationProgress(input = {}) {
  const requested = String(input.stage || 'PREPARING').toUpperCase();
  const stage = OPERATION_STAGES.includes(requested) ? requested : 'PREPARING';
  const completed = Number(input.completed);
  const total = Number(input.total);
  const determinate = Number.isFinite(completed) && Number.isFinite(total)
    && completed >= 0 && total > 0 && completed <= total;
  return Object.freeze({
    stage,
    stageIndex: OPERATION_STAGES.indexOf(stage),
    stageCount: OPERATION_STAGES.length,
    determinate,
    value: determinate ? completed : null,
    max: determinate ? total : null
  });
}

function deriveReadinessState(readiness = {}, session = {}) {
  const checks = Array.isArray(readiness?.checks) ? readiness.checks : [];
  const weather = checks.find((row) => row?.check_id === 'weather') || null;
  const weatherMissing = weather?.status === 'MISSING';
  const eligible = Boolean(session.sessionId)
    && String(session.lifecycleStatus || 'CREATED') === 'CREATED'
    && !session.reportStatus;
  const canDiagnose = eligible && readiness?.overall_status === 'READY';
  return Object.freeze({
    overallStatus: String(readiness?.overall_status || 'UNKNOWN'),
    weatherStatus: String(weather?.status || 'UNKNOWN'),
    weatherMissing,
    showWeatherDrop: eligible && weatherMissing,
    canAttachWeather: eligible && weatherMissing,
    canDiagnose,
    diagnosisRequiresClick: Boolean(session.sessionId),
    autoDiagnose: false
  });
}

function derivePreflightCounts(report = {}) {
  const summary = report?.summary && typeof report.summary === 'object' ? report.summary : {};
  const issues = Array.isArray(report?.issues) ? report.issues : null;
  const safe = Number(summary.safe_repairs || 0);
  if (issues) {
    return Object.freeze({
      safe,
      review: issues.filter((row) => row?.safe_to_apply !== true && row?.kind !== 'vertex_snap').length,
      excluded: issues.filter((row) => row?.safe_to_apply !== true && row?.kind === 'vertex_snap').length,
      detailsReady: true
    });
  }
  const review = Number(summary.confirmed_review_repairs);
  const excluded = Number(summary.excluded_candidate_repairs);
  const splitAvailable = Number.isFinite(review) && review >= 0
    && Number.isFinite(excluded) && excluded >= 0;
  return Object.freeze({
    safe,
    review: splitAvailable ? review : null,
    excluded: splitAvailable ? excluded : null,
    detailsReady: splitAvailable
  });
}

function deriveSettingsHandoff(input = {}) {
  const sessionId = String(input.sessionId || '');
  const changed = String(input.currentMode || '') !== String(input.desiredMode || '')
    || String(input.currentRuntimeId || '') !== String(input.desiredRuntimeId || '');
  const pristine = String(input.lifecycleStatus || 'CREATED') === 'CREATED'
    && !input.status;
  const request = Boolean(sessionId && changed);
  return Object.freeze({
    request,
    strategy: request
      ? (pristine ? 'update-in-place' : 'create-linked-child')
      : 'none',
    keepSessionId: request && pristine,
    preserveParentHistory: true,
    autoRun: false,
    endpoint: sessionId
      ? `/api/sessions/${encodeURIComponent(sessionId)}/settings-child`
      : null
  });
}

function deriveWorkbenchState(input = {}) {
  const loaded = Boolean(input.hasFile || input.sessionId);
  return {
    mode: loaded ? 'loaded' : 'empty',
    showSetup: !loaded,
    showSessionBar: loaded,
    showWorkbench: loaded,
    settingsDrawer: loaded && Boolean(input.settingsOpen),
    runConsoleOpen: String(input.status || '').toUpperCase() === 'PROCESS_FAILED'
  };
}

function noviceCopyAudit(values = []) {
  const findings = [];
  values.forEach((value, index) => {
    const text = String(value || '').trim();
    const lower = text.toLowerCase();
    for (const term of INTERNAL_TERMS) {
      const match = lower.match(new RegExp(`\\b${term}\\b`));
      if (!match) continue;
      const following = text.slice((match.index || 0) + term.length).trimStart();
      if (following.includes('(') || following.includes('（')) continue;
      findings.push({index, term, text});
    }
  });
  return findings;
}

function applyWorkbenchState(documentRef, input = {}) {
  const next = deriveWorkbenchState(input);
  const repair = documentRef.querySelector('#repair-panel');
  repair?.classList.toggle('workbench-empty', next.mode === 'empty');
  repair?.classList.toggle('workbench-loaded', next.mode === 'loaded');
  documentRef.querySelector('#session-bar')?.classList.toggle('hidden', !next.showSessionBar);
  documentRef.querySelector('#issue-navigator')?.classList.toggle('hidden', !next.showWorkbench);
  documentRef.querySelector('#main-workbench-view')?.classList.toggle('hidden', !next.showWorkbench);
  documentRef.querySelector('#context-inspector')?.classList.toggle('hidden', !next.showWorkbench);
  documentRef.querySelector('.upload-rail')?.classList.toggle('settings-open', next.settingsDrawer);
  const consoleNode = documentRef.querySelector('#run-console');
  if (consoleNode && next.runConsoleOpen) consoleNode.open = true;
  return next;
}

const api = {
  OPERATION_STAGES,
  applyWorkbenchState,
  deriveOperationProgress,
  derivePreflightCounts,
  deriveReadinessState,
  deriveSettingsHandoff,
  deriveWorkbenchState,
  noviceCopyAudit
};
globalThis.IDFRepairSessionWorkbench = api;

export {
  OPERATION_STAGES,
  applyWorkbenchState,
  deriveOperationProgress,
  derivePreflightCounts,
  deriveReadinessState,
  deriveSettingsHandoff,
  deriveWorkbenchState,
  noviceCopyAudit
};
