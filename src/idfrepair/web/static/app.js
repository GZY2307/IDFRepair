import './workflow-state.js?v=20260811v5';
import './batch-state.js?v=20260811v5';
import './js/batch-workbench.js?v=20260811v5';
import './viewer-bridge.js?v=20260818occ5';
import './js/session-workbench.js?v=20260812v4';
import './js/issue-navigator.js?v=20260812v4';
import './js/inspector.js?v=20260812v4';
import './js/source-view.js?v=20260811v5';
import './js/object-graph-view.js?v=20260811v5';
import './js/osm-tools.js?v=20260811v6';
import './js/migration.js?v=20260811v5';

'use strict';

const REPAIR_FAMILIES = [
  'extra_field', 'syntax', 'reference_schedule', 'output_variable', 'geometry',
  'schema', 'version_migration', 'ems', 'hvac_reference', 'external_dependency'
];

const state = {
  locale: localStorage.getItem('idfrepair.locale') || 'zh-CN',
  messages: {},
  sessionId: null,
  activeModelFile: null,
  summary: null,
  report: null,
  capabilities: null,
  sessions: [],
  historyBatches: [],
  rules: [],
  ruleSets: [],
  editingRuleId: null,
  rootDetails: [],
  selectedRootId: null,
  selectedAttemptId: null,
  inputRevision: 0,
  runtimes: [],
  selectedRuntimeId: null,
  busy: null,
  lastCompletedAction: null,
  outputReady: false,
  batchEntries: [],
  batchId: null,
  batchSnapshot: null,
  batchRecords: [],
  batchPollTimer: null,
  batchPollGeneration: 0,
  batchRecordContext: null,
  batchPreparationExpanded: true,
  batchSelectedRecordIds: new Set(),
  batchRetrySettingsDirty: false,
  auditReport: null,
  auditSurfaceFilter: null,
  selectedAuditFindingId: null,
  auditRenderLimit: 200,
  auditBusy: false,
  experimentalReport: null,
  experimentalSurfaceFilter: null,
  selectedExperimentalPreviewId: null,
  experimentalRenderLimit: 100,
  experimentalBusy: false,
  experimentalResultsExpanded: true,
  preflightReport: null,
  preflightApplication: null,
  preflightBusy: false,
  preflightStatus: null,
  osmCapability: null,
  osmResult: null,
  osmReport: null,
  osmBusy: false,
  osmMappingQuery: '',
  osmMappingLimit: 50,
  osmValidityLimit: 50,
  runReadiness: null,
  readinessGeneration: 0,
  readinessLoading: false,
  readinessFailed: false,
  weatherUploadBusy: false,
  sourceKind: 'idf',
  previousIdfMode: 'safe-auto',
  settingsOpen: false,
  issueCategory: 'all',
  issueQuery: '',
  issueGroupLimits: new Map(),
  selectedIssueId: null,
  contextRequestRevision: 0,
  sourceContext: null,
  fieldContext: null,
  objectContext: null,
  migrationCapability: null,
  migrationReport: null,
  migrationBusy: false,
  migrationSessionId: null,
  migrationTargetRuntimeId: null,
  settingsHandoffBusy: false,
  settingsHandoffQueued: false
};

const $ = (selector) => document.querySelector(selector);
const statusBox = $('#status');
const questionBox = $('#questions');
const reportBox = $('#report');
const rawErrBox = $('#raw-err');
const roundsBox = $('#rounds');
const attemptsBox = $('#attempts');
const primaryActionButtons = [...document.querySelectorAll('.primary-workflow-action')];
const cancelButton = $('#cancel-current');
const downloadLink = $('#download');
const expandedDownloadLink = $('#download-expanded');
const preprocessingSummaryBox = $('#preprocessing-summary');
const ruleSaveBox = $('#rule-save');
const supportSummaryBox = $('#support-summary');
const rootSupportBox = $('#root-support');
const diagnosisSummaryBox = $('#diagnosis-summary');
const candidateInspectorBox = $('#candidate-inspector');
const validationGatesBox = $('#validation-gates');
const resultSummaryBox = $('#result-summary');
const viewerSelectionBox = $('#viewer-selection-details');
const runProgressBox = $('#run-progress');
const runProgressLabel = $('#run-progress-label');
const runElapsed = $('#run-elapsed');
const runProgressBar = $('#run-progress-bar');
let runProgressTimer = null;
let runProgressHideTimer = null;

function primaryActionState() {
  const mode = new FormData($('#session-form')).get('mode') || 'safe-auto';
  const activeFile = state.activeModelFile || (state.sourceKind === 'osm'
    ? $('#osm-file')?.files?.[0]
    : $('#idf-file')?.files?.[0]);
  const hasFile = Boolean(activeFile || state.sessionId);
  if (state.sourceKind === 'osm') {
    if (!hasFile) {
      return {action: 'choose-file', labelKey: 'actions.choose_file', disabled: false};
    }
    if (!state.osmCapability?.diagnostic_bridge_available) {
      return {action: 'osm-unavailable', labelKey: 'osm.unavailable', disabled: true};
    }
    if (!state.selectedRuntimeId) {
      return {action: 'runtime-required', labelKey: 'actions.runtime_required', disabled: true};
    }
    if (state.busy || state.osmBusy) {
      return {action: 'busy', labelKey: 'osm.running', disabled: true};
    }
    if (state.outputReady && state.sessionId) {
      return {action: 'download', labelKey: 'osm.download_derived', disabled: false};
    }
    if (!state.sessionId) {
      return {action: 'import-osm', labelKey: 'osm.run', disabled: false};
    }
    const preflightStatus = state.preflightStatus || state.summary?.preflight_status;
    const safeRepairs = Number(
      state.preflightReport?.summary?.safe_repairs
      ?? state.summary?.preflight_summary?.safe_repairs
      ?? 0
    );
    if (!['CHECKED', 'APPLIED'].includes(preflightStatus)) {
      return {action: 'run-preflight', labelKey: 'preflight.focus', disabled: state.preflightBusy};
    }
    if (preflightStatus === 'CHECKED' && safeRepairs > 0) {
      return {action: 'apply-preflight', labelKey: 'preflight.apply_action', disabled: state.preflightBusy};
    }
    return {action: 'diagnose', labelKey: 'actions.diagnose', disabled: false};
  }
  const workflow = window.IDFRepairWorkflow.derivePrimaryAction({
    hasFile,
    runtimeReady: Boolean(state.selectedRuntimeId),
    busy: state.busy,
    sessionId: state.sessionId,
    lastCompletedAction: state.lastCompletedAction,
    mode,
    reportStatus: state.report?.final_status || state.summary?.status || null,
    outputReady: state.outputReady
  });
  if (workflow.action !== 'diagnose' || !state.sessionId || !window.IDFRepairSessionWorkbench) {
    return workflow;
  }
  if (!state.runReadiness) {
    return state.readinessFailed
      ? {action: 'retry-readiness', labelKey: 'readiness.retry', disabled: false}
      : {action: 'check-readiness', labelKey: 'readiness.checking', disabled: true};
  }
  const readiness = window.IDFRepairSessionWorkbench.deriveReadinessState(
    state.runReadiness,
    {
      sessionId: state.sessionId,
      lifecycleStatus: state.summary?.lifecycle_status,
      reportStatus: state.summary?.status
    }
  );
  if (readiness.showWeatherDrop) {
    return {action: 'focus-weather', labelKey: 'readiness.attach', disabled: false};
  }
  return workflow;
}

function detectOpenStudioModelText(text) {
  return /^\s*OS:(?:Version|Surface|SubSurface|Space|ThermalZone|BuildingStory)\s*,/im
    .test(String(text || ''));
}

function detectSourceKind(fileOrName, text = '') {
  const name = typeof fileOrName === 'string' ? fileOrName : fileOrName?.name || '';
  if (detectOpenStudioModelText(text)) return 'osm';
  if (/\.osm$/i.test(name)) return 'osm';
  if (/\.idf$/i.test(name)) return 'idf';
  return 'unknown';
}

function syncSourceKindUi({restoreIdfMode = true} = {}) {
  const isOsm = state.sourceKind === 'osm';
  const bridge = $('#osm-bridge');
  bridge.classList.toggle('hidden', !isOsm && !state.osmReport);
  if (isOsm) bridge.open = true;
  $('#session-form').dataset.sourceKind = state.sourceKind;
  const modes = [...document.querySelectorAll('input[name="mode"]')];
  if (isOsm) {
    const checked = modes.find((input) => input.checked);
    if (checked && checked.value !== 'analyze-only') state.previousIdfMode = checked.value;
    const analyzeOnly = modes.find((input) => input.value === 'analyze-only');
    if (analyzeOnly) analyzeOnly.checked = true;
  } else if (restoreIdfMode) {
    const previous = modes.find((input) => input.value === state.previousIdfMode);
    if (previous) previous.checked = true;
  }
  modes.forEach((input) => { input.disabled = isOsm; });
  $('.mode-fieldset').classList.toggle('source-locked', isOsm);
  if (isOsm && state.osmCapability?.energyplus_version) {
    const runtimeId = window.IDFRepairBatch?.runtimeIdForVersion(
      state.osmCapability.energyplus_version, state.runtimes
    );
    if (runtimeId) state.selectedRuntimeId = runtimeId;
  }
  const runtime = $('#runtime-select');
  if (runtime) runtime.disabled = isOsm || state.runtimes.length === 0;
  renderMigrationAssistant();
}

function setSourceKind(kind, options = {}) {
  state.sourceKind = kind === 'osm' ? 'osm' : 'idf';
  syncSourceKindUi(options);
  if (state.runtimes.length) renderRuntimeOptions();
}

function updatePrimaryAction() {
  const current = primaryActionState();
  for (const button of primaryActionButtons) {
    button.dataset.action = current.action;
    button.textContent = t(current.labelKey);
    button.disabled = current.disabled;
    button.setAttribute('aria-busy', String(current.action === 'busy'));
  }
  $('#repair-panel').classList.toggle('no-input', !state.activeModelFile
    && !$('#idf-file').files?.[0] && !$('#osm-file')?.files?.[0] && !state.sessionId);
  updateSessionWorkbench();
  updateAuditAction();
  updateExperimentalAction();
  updateModelPreflightAction();
  updateOsmAction();
}

function updateSessionWorkbench() {
  const activeFile = state.activeModelFile || (state.sourceKind === 'osm'
    ? $('#osm-file')?.files?.[0]
    : $('#idf-file')?.files?.[0]);
  window.IDFRepairSessionWorkbench?.applyWorkbenchState(document, {
    hasFile: Boolean(activeFile),
    sessionId: state.sessionId,
    settingsOpen: state.settingsOpen,
    status: state.report?.final_status || state.summary?.status || null
  });
  const sourceName = state.summary?.source_input_name
    || state.summary?.input_name
    || activeFile?.name
    || t('workbench.no_file');
  $('#session-file-name').textContent = sourceName;
  $('#session-file-name').title = sourceName;
  const version = state.osmReport?.derived_idf_version || state.summary?.energyplus_version || '—';
  $('#session-idf-version').textContent = `IDF ${version}`;
  $('#session-runtime-version').textContent = `EnergyPlus ${state.summary?.energyplus_version || '—'}`;
  const mode = state.summary?.mode || new FormData($('#session-form')).get('mode') || 'safe-auto';
  $('#session-mode-label').textContent = t(`tokens.modes.${mode}`);
  const status = state.report?.final_status || state.summary?.status || '';
  const statusText = status
    ? t(`workbench.statuses.${status}`)
    : t('workbench.not_started');
  $('#session-status-label').textContent = statusText.startsWith('workbench.statuses.')
    ? (renderMessage(state.summary?.message) || status)
    : statusText;
  $('#session-download').disabled = !state.outputReady;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function lookup(path) {
  return path.split('.').reduce((value, key) => value && value[key], state.messages);
}

function t(path, params = {}) {
  let value = lookup(path);
  if (typeof value !== 'string') return path;
  for (const [key, item] of Object.entries(params)) {
    value = value.replaceAll(`{${key}}`, String(item));
  }
  return value;
}

function renderMessage(row) {
  if (!row || typeof row !== 'object') return '';
  const rawToken = String(row.params?.raw || row.raw_message || '').trim();
  const tokenKey = `messages.error_tokens.${rawToken}`;
  const tokenText = t(tokenKey);
  if (rawToken && tokenText !== tokenKey) return tokenText;
  const translated = t(`messages.${row.message_id}`, {...(row.params || {}), raw: row.raw_message});
  return translated.startsWith('messages.') ? row.raw_message : translated;
}

function localizedDiagnostic(row) {
  const presentation = row?.presentation || {};
  const locale = state.locale === 'en' ? 'en' : 'zh-CN';
  return {
    title: presentation.title?.[locale] || t('presentation.unknown_title'),
    summary: presentation.summary?.[locale] || t('presentation.unknown_summary'),
    action: presentation.action?.[locale] || t('presentation.unknown_action'),
    raw: presentation.raw_message || row?.message || ''
  };
}

function localizedSupportReason(row) {
  const locale = state.locale === 'en' ? 'en' : 'zh-CN';
  return row?.support_presentation?.text?.[locale]
    || (row?.support_reason ? localizedReasonText(row.support_reason) : '')
    || t('diagnosis.unmatched');
}

function localizedReasonText(reason) {
  const raw = String(reason ?? '').trim();
  if (!raw) return t('candidate.unavailable');
  return raw.split(/[;,]/).map((part) => part.trim()).filter(Boolean).map((token) => {
    const count = token.match(/^(severe|fatal|warning)=(\d+)$/i);
    if (count) return t(`candidate.reason_counts.${count[1].toLowerCase()}`, {count: count[2]});
    const errorTokenKey = `messages.error_tokens.${token}`;
    const errorTokenText = t(errorTokenKey);
    if (errorTokenText !== errorTokenKey) return errorTokenText;
    const key = `candidate.reasons.${token}`;
    const translated = t(key);
    return translated === key ? t('candidate.reason_fallback') : translated;
  }).join(state.locale === 'en' ? '; ' : '；');
}

function localizedCandidateToken(group, value) {
  if (value === true || value === false) return t(`candidate.booleans.${value}`);
  const raw = String(value ?? '').trim();
  if (!raw) return t('candidate.unavailable');
  const key = `candidate.${group}.${raw.toLowerCase().replaceAll('-', '_')}`;
  const translated = t(key);
  return translated === key ? t('candidate.technical_value') : translated;
}

function localizedFamily(value) {
  const raw = String(value || 'unknown').trim().toLowerCase();
  const key = `tokens.families.${raw}`;
  const translated = t(key);
  return translated === key ? t('tokens.families.unknown') : translated;
}

function localizedProvider(value) {
  return localizedCandidateToken('providers', value);
}

function localizedResultStatus(value) {
  const key = `result.statuses.${String(value || '').toUpperCase()}`;
  const translated = t(key);
  return translated === key ? t('result.status_unresolved') : translated;
}

function localizedQualificationText(attempt, candidate, metadata) {
  if (attempt?.accepted === true || ['safe-auto', 'assisted'].includes(metadata?.support_status)) {
    return t(attempt?.accepted === true ? 'candidate.qualification_accepted' : 'candidate.qualification_eligible');
  }
  const raw = metadata?.qualification_reason || metadata?.qualification || '';
  return raw ? localizedReasonText(raw) : t('candidate.qualification_unavailable');
}

function diagnosticWorkbenchIssues() {
  const questions = new Map((state.summary?.questions || []).map((question) => [question.root_id, question]));
  const roots = state.rootDetails.map((root) => {
    const target = questions.get(root.root_id)?.metadata?.target || questions.get(root.root_id)?.metadata || {};
    return {
      ...root,
      metadata: {
        ...(root.metadata || {}),
        object_index: root.metadata?.object_index ?? target.object_index ?? null,
        field_index: root.metadata?.field_index ?? target.field_index ?? null,
        object_type: root.metadata?.object_type || target.object_type || '',
        object_name: root.metadata?.object_name || target.object_name || ''
      }
    };
  });
  return roots.map((root) => {
    const presentation = localizedDiagnostic(root);
    const question = questions.get(root.root_id) || null;
    const locator = window.IDFRepairIssueNavigator.diagnosticLocator(root, roots);
    return {
      ...root,
      id: root.root_id,
      kind: 'energyplus',
      rule_id: root.family || root.support_entry_id || root.root_id,
      title: presentation.title,
      summary: presentation.summary,
      action: presentation.action,
      severity: String(root.severity || 'error').toLowerCase(),
      object_index: locator.object_index,
      field_index: locator.field_index,
      object_type: locator.object_type,
      object_name: locator.object_name,
      question,
      raw_message: presentation.raw,
      evidence_signature: root.signatures?.join('|') || root.support_entry_id || root.family
    };
  });
}

function auditEvidenceSignature(finding) {
  const evidence = finding.evidence || {};
  const categorical = [
    evidence.signal,
    Array.isArray(evidence.failed_checks) ? [...evidence.failed_checks].sort().join(',') : '',
    Array.isArray(evidence.mismatches) ? [...evidence.mismatches].sort().join(',') : '',
    Number.isFinite(evidence.target_count) ? `target-count:${evidence.target_count}` : ''
  ].filter(Boolean);
  return [finding.rule_id, ...categorical].join('|');
}

function auditWorkbenchIssues() {
  return (state.auditReport?.findings || []).map((finding) => {
    const copy = auditRuleText(finding);
    return {
      ...finding,
      id: finding.finding_id,
      kind: 'audit',
      title: copy.title,
      summary: copy.summary,
      action: t('workbench.audit_next'),
      object_index: finding.surface?.object_index ?? null,
      object_type: finding.surface?.object_type,
      object_name: finding.surface?.name,
      zone: finding.surface?.zone || finding.surface?.space,
      paired_object_name: finding.paired_surface?.name,
      surface_names: [finding.surface?.name, finding.paired_surface?.name].filter(Boolean),
      evidence_signature: auditEvidenceSignature(finding)
    };
  });
}

function experimentalWorkbenchIssues() {
  return experimentalPreviewRows().map((preview) => {
    const mechanism = experimentalMechanismCopy(preview.mechanism_id);
    return {
      ...preview,
      id: preview.preview_id,
      kind: 'experimental',
      rule_id: preview.mechanism_id,
      severity: 'review',
      title: mechanism.name,
      summary: t('workbench.experimental_summary'),
      action: t('workbench.experimental_next'),
      object_index: preview.surface?.object_index ?? null,
      object_type: preview.surface?.object_type,
      object_name: preview.surface?.name,
      zone: preview.surface?.zone || preview.surface?.space,
      paired_object_name: preview.paired_surface?.name,
      surface_names: [preview.surface?.name, preview.paired_surface?.name].filter(Boolean),
      evidence_signature: preview.preview_kind || preview.mechanism_id
    };
  });
}

function questionOnlyWorkbenchIssues(existingRows) {
  const roots = new Set(existingRows.map((row) => row.root_id || row.id));
  return (state.summary?.questions || []).filter((question) => !roots.has(question.root_id)).map((question) => {
    const target = question.metadata?.target || question.metadata || {};
    return {
      id: `question:${question.question_id}`,
      root_id: question.root_id,
      kind: 'energyplus',
      rule_id: question.question_type,
      severity: 'error',
      support_status: 'interactive',
      title: t(`tokens.questions.${question.question_type}`),
      summary: t(`question_prompts.${question.question_type}`),
      action: t('workbench.answer_next'),
      object_type: target.object_type,
      object_name: target.object_name,
      field_name: target.field_name,
      object_index: target.object_index ?? null,
      field_index: target.field_index ?? null,
      question,
      evidence_signature: question.question_type
    };
  });
}

function workbenchIssueRows() {
  const diagnostics = diagnosticWorkbenchIssues();
  const preflightRows = window.IDFRepairIssueNavigator
    .preflightIssueRows(state.preflightReport).map(localizePreflightIssue);
  return [
    ...diagnostics,
    ...questionOnlyWorkbenchIssues(diagnostics),
    ...preflightRows,
    ...(preflightRows.length ? [] : auditWorkbenchIssues()),
    ...experimentalWorkbenchIssues()
  ];
}

function localizePreflightIssue(issue) {
  const kindKey = `preflight.issue_kinds.${issue.preflight_kind}`;
  const title = t(kindKey);
  const status = issue.safe_to_apply ? 'safe' : 'review';
  const summaryKey = `preflight.issue_copy.${issue.preflight_kind}.${status}`;
  const nextKey = `preflight.issue_copy.${issue.preflight_kind}.${status}_next`;
  const summary = t(summaryKey);
  const next = t(nextKey);
  return {
    ...issue,
    title: title === kindKey ? issue.title : title,
    summary: summary === summaryKey ? t(`preflight.issue_copy.geometry_review.${status}`) : summary,
    action: next === nextKey ? t(`preflight.issue_copy.geometry_review.${status}_next`) : next
  };
}

function issueSeverityText(issue) {
  if (issue.preflight_kind) {
    if (issue.support_status === 'evidence') return t('preflight.status_evidence');
    return t(issue.safe_to_apply ? 'preflight.status_safe' : 'preflight.status_review');
  }
  if (issue.kind === 'audit') {
    return window.IDFRepairInspector.auditSeverityLabel(issue.severity, state.locale);
  }
  if (issue.kind === 'experimental') return t('workbench.preview_only');
  return t(`support.statuses.${issue.support_status || 'unsupported'}`);
}

function issueKindText(issue) {
  if (!issue.preflight_kind) return '';
  const key = `preflight.issue_kinds.${issue.preflight_kind}`;
  const translated = t(key);
  return translated === key ? issue.preflight_kind.replaceAll('_', ' ') : translated;
}

function renderIssueNavigator() {
  const box = $('#issue-groups');
  if (!box || !window.IDFRepairIssueNavigator) return;
  const rows = workbenchIssueRows();
  const counts = window.IDFRepairIssueNavigator.categoryCounts(rows);
  const groups = window.IDFRepairIssueNavigator.groupIssues(rows);
  const visible = window.IDFRepairIssueNavigator.filterIssues(
    groups, state.issueQuery, state.issueCategory
  );
  $('#issue-count').textContent = String(rows.length);
  document.querySelectorAll('[data-issue-category]').forEach((button) => {
    const category = button.dataset.issueCategory;
    button.classList.toggle('active', category === state.issueCategory);
    button.setAttribute('aria-selected', String(category === state.issueCategory));
    const count = button.querySelector('strong');
    if (count) count.textContent = String(counts[category] || 0);
  });
  box.replaceChildren();
  if (!visible.length) {
    box.append(element('p', 'empty-copy', rows.length
      ? t('workbench.issue_no_match')
      : t('workbench.issue_empty')));
    return;
  }
  for (const group of visible) {
    const details = element('details', 'issue-group');
    const selected = group.rows.some((row) => row.id === state.selectedIssueId);
    details.open = selected || group.count === 1;
    const summary = element('summary', 'issue-group-summary');
    const copy = element('span', 'issue-group-copy');
    const location = group.zone_count > 1
      ? t('workbench.issue_zones', {count: group.zone_count})
      : group.zone;
    copy.append(
      element('strong', '', group.title),
      element('small', '', [location, issueSeverityText(group.rows[0])].filter(Boolean).join(' · '))
    );
    summary.append(copy, element('span', 'issue-group-count', t('workbench.issue_count', {count: group.count})));
    const list = element('div', 'issue-group-rows');
    const selectedIndex = group.rows.findIndex((row) => row.id === state.selectedIssueId);
    const defaultLimit = state.issueQuery ? 50 : 20;
    const limit = Math.max(
      state.issueGroupLimits.get(group.key) || defaultLimit,
      selectedIndex >= 0 ? selectedIndex + 1 : 0
    );
    const displayedRows = group.rows.slice(0, limit);
    for (const issue of displayedRows) {
      const button = element('button', 'issue-row');
      button.type = 'button';
      button.dataset.issueId = issue.id;
      const active = issue.id === state.selectedIssueId;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
      const location = issue.locator_scope === 'global'
        ? t('workbench.global_scope_count', {count: issue.affected_surface_count || 0})
        : ([issue.zone, issue.paired_object_name, issue.field_name]
          .filter(Boolean).join(' · ') || t('workbench.file_level'));
      const kind = issueKindText(issue);
      const locateLabel = issue.locator_scope === 'global'
        ? t('workbench.global_scope')
        : t('workbench.locate');
      button.append(
        element('span', `issue-severity severity-${issue.severity}`, issueSeverityText(issue)),
        element('strong', '', issue.object_name || issue.field_name || issue.title),
        element('small', '', [kind, location].filter(Boolean).join(' · ')),
        element('span', 'issue-row-locate', locateLabel)
      );
      button.addEventListener('click', () => selectWorkbenchIssue(issue.id));
      list.append(button);
    }
    if (displayedRows.length < group.rows.length) {
      const more = element('button', 'quiet-button issue-group-more', t('workbench.issue_show_more', {
        shown: displayedRows.length,
        total: group.rows.length
      }));
      more.type = 'button';
      more.addEventListener('click', () => {
        state.issueGroupLimits.set(group.key, displayedRows.length + 50);
        renderIssueNavigator();
      });
      list.append(more);
    }
    details.append(summary, list);
    box.append(details);
  }
}

function renderIssueInspector(issue) {
  const box = $('#issue-inspector-copy');
  if (!box || !window.IDFRepairInspector) return;
  box.replaceChildren();
  const candidateDetails = document.querySelector('.inspector-candidate-details');
  candidateDetails?.classList.toggle('hidden', !issue || issue.kind !== 'energyplus');
  if (!issue) {
    box.append(element('p', 'empty-copy', t('workbench.inspector_empty')));
    syncInspectorQuestionVisibility(null);
    return;
  }
  const copy = window.IDFRepairInspector.issueExplanation(issue, {locale: state.locale});
  const header = element('div', 'issue-inspector-heading');
  header.append(
    element('span', `issue-severity severity-${issue.severity}`, issueSeverityText(issue)),
    element('strong', '', copy.what)
  );
  const explanations = element('dl', 'issue-explanations');
  for (const [key, value] of [
    ['where', copy.where], ['importance', copy.importance], ['next', copy.next]
  ]) {
    const row = element('div');
    row.append(element('dt', '', t(`workbench.explanation.${key}`)), element('dd', '', value));
    explanations.append(row);
  }
  const technical = element('details', 'issue-technical');
  technical.append(
    element('summary', '', t('workbench.technical_evidence')),
    element('pre', '', JSON.stringify(copy.technical, null, 2))
  );
  box.append(header, explanations, technical);
  syncInspectorQuestionVisibility(issue);
}

function syncInspectorQuestionVisibility(issue) {
  if (!questionBox) return;
  const selectedRoot = issue?.root_id || (issue?.kind === 'energyplus' ? issue?.id : null);
  let visible = 0;
  questionBox.querySelectorAll(':scope > .question').forEach((card) => {
    const show = Boolean(selectedRoot && card.dataset.rootId === selectedRoot);
    card.classList.toggle('hidden', !show);
    if (show) visible += 1;
  });
  questionBox.querySelectorAll(':scope > .question-boundary').forEach((boundary) => {
    boundary.classList.toggle('hidden', visible === 0);
  });
  questionBox.classList.toggle('hidden', visible === 0);
}

function showWorkbenchIssueInViewer(issue) {
  if (!issue) {
    window.IDFRepairViewer?.showIssue(null);
    return;
  }
  const targetName = issue.object_name || issue.surface?.name || issue.surface_names?.[0] || '';
  const pairedName = issue.paired_object_name || issue.paired_surface?.name || '';
  const scopeLabel = [
    issue.zone || issue.surface?.zone || issue.surface?.space,
    issue.story || issue.building_story || issue.elevation_group || issue.surface?.story
  ].filter(Boolean).join(' · ');
  const locatorMessage = window.IDFRepairIssueNavigator.issueLocatorMessage(issue);
  const viewerIssue = {
    title: issue.title || issue.rule_id || issue.family || '',
    severity: issue.severity || 'review',
    scopeLabel,
    targetNames: targetName ? [targetName] : [],
    pairedNames: pairedName ? [pairedName] : [],
    groupNames: [],
    ...locatorMessage
  };
  window.IDFRepairViewer?.showIssue(viewerIssue);
  const viewerFrame = $('#model-viewer');
  viewerFrame?.contentWindow?.postMessage(
    {type: 'idfrepair:viewer-issue-mode', issue: viewerIssue},
    window.location.origin
  );
}

function selectWorkbenchIssue(issueId, {view = null} = {}) {
  const issue = workbenchIssueRows().find((row) => row.id === issueId);
  if (!issue) return;
  state.selectedIssueId = issueId;
  if (issue.kind === 'audit') selectAuditFinding(issue.finding_id, {syncWorkbench: false});
  else if (issue.kind === 'experimental') selectExperimentalPreview(issue.preview_id, {syncWorkbench: false});
  else if (issue.root_id) selectRoot(issue.root_id, {syncWorkbench: false});
  if (view) switchMainView(view);
  else if (issue.preflight_kind) switchMainView('3d');
  showWorkbenchIssueInViewer(issue);
  renderIssueNavigator();
  renderIssueInspector(issue);
  loadIssueContexts(issue, {autoSwitch: !view});
}

function switchMainView(view, {focus = false} = {}) {
  const panelId = String(view).startsWith('main-view-') ? String(view) : `main-view-${view}`;
  const tabs = [...document.querySelectorAll('#main-view-tabs [role="tab"]')];
  for (const tab of tabs) {
    const selected = tab.getAttribute('aria-controls') === panelId;
    tab.classList.toggle('active', selected);
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    document.getElementById(tab.getAttribute('aria-controls'))?.classList.toggle('hidden', !selected);
    document.getElementById(tab.getAttribute('aria-controls'))?.classList.toggle('active', selected);
    if (selected && focus) tab.focus({preventScroll: true});
  }
}

function preferredIssueView(issue) {
  if (!issue) return '3d';
  if (issue.kind === 'audit' || issue.kind === 'experimental' || issue.family === 'geometry') return '3d';
  if (/reference|schedule/i.test(`${issue.family || ''} ${issue.rule_id || ''}`)) return 'graph';
  if (Number.isInteger(issue.field_index)) return 'source';
  return '3d';
}

function clearIssueContexts(message = null) {
  state.contextRequestRevision += 1;
  state.sourceContext = null;
  state.fieldContext = null;
  state.objectContext = null;
  $('#source-context-view').replaceChildren();
  $('#object-graph-view').replaceChildren();
  $('#source-view-empty').classList.remove('hidden');
  $('#graph-view-empty').classList.remove('hidden');
  $('#source-location').textContent = message || '';
  $('#copy-source-context').disabled = true;
  renderIddFieldInspector(null);
}

function renderIddFieldInspector(payload) {
  const box = $('#idd-field-inspector');
  if (!box) return;
  box.replaceChildren();
  if (!payload) {
    box.classList.add('hidden');
    return;
  }
  const field = window.IDFRepairSourceView.iddFieldPresentation(payload, state.locale);
  box.append(
    element('h4', '', t('workbench.idd_title')),
    element('p', 'idd-intro', t('workbench.idd_intro')),
    element('p', field.available ? 'idd-available' : 'idd-unavailable', field.explanation)
  );
  const facts = element('dl', 'idd-field-facts');
  const range = [
    field.minimum === null ? null : `≥ ${field.minimum}`,
    field.maximum === null ? null : `≤ ${field.maximum}`
  ].filter(Boolean).join(' · ');
  const rows = [
    ['field', field.fieldName || `#${payload.field_index}`],
    ['current', field.currentValue || '—'],
    ['type', field.dataType],
    ['required', field.required],
    ['default', field.defaultValue ?? '—'],
    ['units', field.units || '—'],
    ['range', range || '—'],
    ['allowed', field.allowed.length ? field.allowed.join(' · ') : '—']
  ];
  for (const [key, value] of rows) {
    const row = element('div');
    row.append(element('dt', '', t(`workbench.idd_fields.${key}`)), element('dd', '', String(value)));
    facts.append(row);
  }
  const raw = element('details', 'idd-raw');
  raw.append(
    element('summary', '', t('workbench.idd_raw')),
    element('pre', '', JSON.stringify(field.raw, null, 2))
  );
  box.append(facts, raw);
  box.classList.remove('hidden');
}

function contextError(target, message) {
  target.replaceChildren(element('p', 'context-error', message));
}

async function loadIssueContexts(issue, {autoSwitch = true} = {}) {
  const rawObjectIndex = issue?.object_index;
  const objectIndex = rawObjectIndex === null || rawObjectIndex === undefined || rawObjectIndex === ''
    ? null
    : Number(rawObjectIndex);
  const rawFieldIndex = issue?.field_index;
  const fieldIndex = rawFieldIndex === null || rawFieldIndex === undefined || rawFieldIndex === ''
    ? null
    : Number(rawFieldIndex);
  if (!state.sessionId || !Number.isInteger(objectIndex)) {
    clearIssueContexts(t('workbench.context_unavailable'));
    if (autoSwitch) switchMainView(preferredIssueView(issue));
    return;
  }
  const revision = ++state.contextRequestRevision;
  state.sourceContext = null;
  state.fieldContext = null;
  state.objectContext = null;
  $('#source-view-empty').classList.add('hidden');
  $('#graph-view-empty').classList.add('hidden');
  contextError($('#source-context-view'), t('workbench.context_loading'));
  contextError($('#object-graph-view'), t('workbench.context_loading'));
  $('#copy-source-context').disabled = true;
  renderIddFieldInspector(null);
  const base = `/api/sessions/${encodeURIComponent(state.sessionId)}`;
  const sourceParams = new URLSearchParams({object_index: objectIndex, before_lines: 2, after_lines: 2});
  if (Number.isInteger(fieldIndex) && fieldIndex > 0) sourceParams.set('field_index', fieldIndex);
  const requests = [
    request(`${base}/source-context?${sourceParams}`),
    Number.isInteger(fieldIndex) && fieldIndex > 0
      ? request(`${base}/field-context?${new URLSearchParams({object_index: objectIndex, field_index: fieldIndex})}`)
      : Promise.resolve(null),
    request(`${base}/object-context?${new URLSearchParams({object_index: objectIndex, depth: 1, limit: 30})}`)
  ];
  const [sourceResult, fieldResult, graphResult] = await Promise.allSettled(requests);
  if (revision !== state.contextRequestRevision) return;
  if (sourceResult.status === 'fulfilled') {
    state.sourceContext = sourceResult.value;
    window.IDFRepairSourceView.renderSourceContext($('#source-context-view'), sourceResult.value, {
      errorText: t('workbench.context_unavailable')
    });
    $('#source-location').textContent = t('workbench.source_location', {
      start: sourceResult.value.context_line_start,
      end: sourceResult.value.context_line_end
    });
    $('#copy-source-context').disabled = false;
  } else {
    contextError($('#source-context-view'), t('workbench.context_failed'));
  }
  if (fieldResult.status === 'fulfilled' && fieldResult.value) {
    state.fieldContext = fieldResult.value;
    renderIddFieldInspector(fieldResult.value);
  }
  if (graphResult.status === 'fulfilled') {
    state.objectContext = graphResult.value;
    const layout = window.IDFRepairObjectGraph.renderObjectGraph(
      $('#object-graph-view'), graphResult.value, {
        locale: state.locale,
        onSelect: (node) => {
          if (!Number.isInteger(node.object_index)) return;
          loadIssueContexts({...issue, object_index: node.object_index, field_index: null}, {autoSwitch: false});
        }
      }
    );
    if (layout.truncated) {
      $('#object-graph-view').append(element('p', 'graph-truncated', t('workbench.graph_truncated')));
    }
  } else {
    contextError($('#object-graph-view'), t('workbench.context_failed'));
  }
  if (autoSwitch) switchMainView(preferredIssueView(issue));
}

function visibleWorkbenchIssues() {
  const groups = window.IDFRepairIssueNavigator.groupIssues(workbenchIssueRows());
  return window.IDFRepairIssueNavigator.filterIssues(groups, state.issueQuery, state.issueCategory)
    .flatMap((group) => group.rows);
}

function selectAdjacentIssue(direction) {
  const rows = visibleWorkbenchIssues();
  if (!rows.length) return;
  const current = rows.findIndex((row) => row.id === state.selectedIssueId);
  const next = current < 0
    ? 0
    : (current + direction + rows.length) % rows.length;
  selectWorkbenchIssue(rows[next].id, {view: 'source'});
}

async function loadLocale(locale) {
  const response = await fetch(`/locales/${locale}.json?v=20260818occ5`, {cache: 'no-store'});
  if (!response.ok) throw new Error(`locale_load_failed:${locale}`);
  state.messages = await response.json();
  state.locale = locale;
  localStorage.setItem('idfrepair.locale', locale);
  document.documentElement.lang = locale;
  $('#language').value = locale;
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  document.querySelectorAll('[data-i18n-aria-label]').forEach((node) => {
    node.setAttribute('aria-label', t(node.dataset.i18nAriaLabel));
  });
  document.querySelectorAll('[data-i18n-title]').forEach((node) => {
    node.setAttribute('title', t(node.dataset.i18nTitle));
  });
  window.IDFRepairViewer?.setLocale(locale);
  if (state.summary) setStatus(state.summary);
  if (state.report) renderReport(state.report);
  else renderValidation(null);
  if (state.capabilities) renderCapabilitySummary();
  renderSessionList();
  renderRuleList();
  populateRuleSets();
  renderRuntimeOptions();
  renderBatchPreview();
  renderBatchDashboard();
  renderAudit();
  renderExperimental();
  renderOsmBridge();
  renderMigrationAssistant();
  const selectedIssue = workbenchIssueRows().find((row) => row.id === state.selectedIssueId);
  if (selectedIssue) loadIssueContexts(selectedIssue, {autoSwitch: false});
  syncCollapsibleLabels();
  updatePrimaryAction();
  updateAuditAction();
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload;
    const error = new Error(renderMessage(detail) || detail.raw_message || response.statusText);
    error.payload = detail;
    throw error;
  }
  return payload;
}

function currentReadinessState() {
  return window.IDFRepairSessionWorkbench.deriveReadinessState(
    state.runReadiness || {},
    {
      sessionId: state.sessionId,
      lifecycleStatus: state.summary?.lifecycle_status,
      reportStatus: state.summary?.status
    }
  );
}

function renderReadiness() {
  const box = $('#readiness-blocker');
  if (!box || !window.IDFRepairSessionWorkbench) return;
  const readiness = currentReadinessState();
  box.classList.toggle('hidden', !readiness.showWeatherDrop);
  $('#readiness-status').textContent = readiness.weatherMissing
    ? t('readiness.weather_missing')
    : t('readiness.ready_explicit');
  $('#attach-session-weather').disabled = !readiness.canAttachWeather
    || state.weatherUploadBusy
    || !$('#session-epw-file')?.files?.[0];
  box.setAttribute('aria-busy', String(state.weatherUploadBusy));
}

async function refreshReadiness(sessionId = state.sessionId) {
  const generation = ++state.readinessGeneration;
  if (!sessionId) {
    state.runReadiness = null;
    state.readinessLoading = false;
    state.readinessFailed = false;
    renderReadiness();
    return null;
  }
  state.readinessLoading = true;
  state.readinessFailed = false;
  updatePrimaryAction();
  try {
    const readiness = await request(`/api/sessions/${encodeURIComponent(sessionId)}/readiness`);
    if (state.sessionId !== sessionId || state.readinessGeneration !== generation) return null;
    state.runReadiness = readiness;
    state.readinessLoading = false;
    state.readinessFailed = false;
    renderReadiness();
    updatePrimaryAction();
    return readiness;
  } catch (error) {
    if (state.sessionId === sessionId && state.readinessGeneration === generation) {
      state.runReadiness = null;
      state.readinessLoading = false;
      state.readinessFailed = true;
      renderReadiness();
      updatePrimaryAction();
      notice(error.message, true);
    }
    return null;
  }
}

async function attachSessionWeather() {
  const sessionId = state.sessionId;
  const file = $('#session-epw-file')?.files?.[0];
  if (!sessionId || !file || state.weatherUploadBusy) return;
  const generation = ++state.readinessGeneration;
  state.weatherUploadBusy = true;
  state.readinessLoading = false;
  state.readinessFailed = false;
  renderReadiness();
  try {
    const body = new FormData();
    body.set('file', file, file.name);
    const result = await request(
      `/api/sessions/${encodeURIComponent(sessionId)}/weather`,
      {method: 'POST', body}
    );
    if (state.sessionId !== sessionId || state.readinessGeneration !== generation) return;
    state.runReadiness = result.readiness;
    state.readinessFailed = false;
    $('#session-epw-file').value = '';
    $('#session-epw-name').textContent = result.filename || file.name;
    notice(t('readiness.attached_explicit'));
  } catch (error) {
    if (state.sessionId === sessionId) notice(error.message, true);
  } finally {
    if (state.sessionId === sessionId) {
      state.weatherUploadBusy = false;
      renderReadiness();
      updatePrimaryAction();
    }
  }
}

function renderRuntimeOptions() {
  const select = $('#runtime-select');
  const status = $('#runtime-status');
  if (!select || !status) return;
  let previous = state.selectedRuntimeId || localStorage.getItem('idfrepair.runtime_id');
  if (state.sourceKind === 'osm' && state.osmCapability?.energyplus_version) {
    previous = window.IDFRepairBatch?.runtimeIdForVersion(
      state.osmCapability.energyplus_version, state.runtimes
    ) || previous;
  }
  select.replaceChildren();
  for (const runtime of state.runtimes) {
    const option = element(
      'option',
      '',
      `EnergyPlus ${runtime.version}`
    );
    option.value = runtime.runtime_id;
    option.title = runtime.home;
    select.append(option);
  }
  const availableIds = new Set(state.runtimes.map((runtime) => runtime.runtime_id));
  state.selectedRuntimeId = availableIds.has(previous)
    ? previous
    : availableIds.has(select.dataset.defaultRuntimeId)
      ? select.dataset.defaultRuntimeId
      : state.runtimes.at(-1)?.runtime_id || null;
  select.value = state.selectedRuntimeId || '';
  select.disabled = state.runtimes.length === 0 || state.sourceKind === 'osm';
  const selected = state.runtimes.find((runtime) => runtime.runtime_id === state.selectedRuntimeId);
  if (selected) {
    localStorage.setItem('idfrepair.runtime_id', selected.runtime_id);
    status.textContent = t('form.runtime_ready', {
      version: selected.version,
      executable: selected.executable_name,
      count: state.runtimes.length
    });
  } else {
    localStorage.removeItem('idfrepair.runtime_id');
    status.textContent = t('form.runtime_none');
  }
  updatePrimaryAction();
  renderBatchRuntimeOptions();
}

function renderBatchRuntimeOptions() {
  const select = $('#batch-runtime-select');
  if (!select) return;
  const previous = select.value || state.selectedRuntimeId;
  select.replaceChildren();
  for (const runtime of state.runtimes) {
    const option = element('option', '', `EnergyPlus ${runtime.version}`);
    option.value = runtime.runtime_id;
    option.title = runtime.home;
    select.append(option);
  }
  const available = new Set(state.runtimes.map((runtime) => runtime.runtime_id));
  select.value = available.has(previous)
    ? previous
    : (state.selectedRuntimeId || state.runtimes.at(-1)?.runtime_id || '');
  select.disabled = state.runtimes.length === 0;
  selectBatchRuntimeForEntries();
  updateBatchStartState();
}

function selectSingleRuntimeByVersion(version) {
  if (!window.IDFRepairBatch || !version) return;
  const runtimeId = window.IDFRepairBatch.runtimeIdForVersion(version, state.runtimes);
  if (!runtimeId) return;
  state.selectedRuntimeId = runtimeId;
  renderRuntimeOptions();
}

function currentSessionRuntimeId() {
  return window.IDFRepairBatch?.runtimeIdForVersion(
    state.summary?.energyplus_version,
    state.runtimes
  ) || null;
}

async function handoffSessionSettings() {
  if (state.settingsHandoffBusy) {
    state.settingsHandoffQueued = true;
    return;
  }
  const desiredMode = new FormData($('#session-form')).get('mode') || 'safe-auto';
  const handoff = window.IDFRepairSessionWorkbench?.deriveSettingsHandoff({
    sessionId: state.sessionId,
    lifecycleStatus: state.summary?.lifecycle_status,
    status: state.summary?.status,
    currentMode: state.summary?.mode,
    desiredMode,
    currentRuntimeId: currentSessionRuntimeId(),
    desiredRuntimeId: state.selectedRuntimeId
  });
  if (!handoff?.request) return;
  state.settingsHandoffBusy = true;
  const parentSessionId = state.sessionId;
  try {
    const result = await request(handoff.endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode: desiredMode, runtime_id: state.selectedRuntimeId})
    });
    if (state.sessionId !== parentSessionId) return;
    if (result.created_child) {
      resetRepairViewForNewInput();
      setStatus(result.session);
      await loadSessionInputIntoViewer(
        `/api/sessions/${encodeURIComponent(result.session.session_id)}/input`,
        result.session.input_name
      );
    } else {
      setStatus(result.session);
    }
    await loadSessions();
    notice(result.created_child
      ? (state.locale === 'zh-CN'
        ? '基于上一会话创建新设置副本'
        : 'Created a new settings copy from the previous session')
      : (state.locale === 'zh-CN' ? '已更新当前会话设置' : 'Session settings updated'));
  } catch (error) {
    if (state.sessionId === parentSessionId) {
      if (state.summary) setStatus(state.summary);
      notice(error.message, true);
    }
  } finally {
    state.settingsHandoffBusy = false;
    if (state.settingsHandoffQueued) {
      state.settingsHandoffQueued = false;
      void handoffSessionSettings();
    }
  }
}

async function loadRuntimes(rescan = false) {
  const select = $('#runtime-select');
  const rescanButton = $('#rescan-runtimes');
  $('#runtime-status').textContent = t('form.runtime_loading');
  select.disabled = true;
  rescanButton.disabled = true;
  try {
    const payload = await request('/api/runtimes' + (rescan ? '/rescan' : ''), {
      method: rescan ? 'POST' : 'GET'
    });
    state.runtimes = payload.runtimes || [];
    select.dataset.defaultRuntimeId = payload.default_runtime_id || '';
    renderRuntimeOptions();
    if (rescan && state.sessionId && state.sourceKind === 'idf') {
      await loadMigrationCapability(state.sessionId, {force: true});
    }
  } catch (error) {
    state.runtimes = [];
    state.selectedRuntimeId = null;
    renderRuntimeOptions();
    notice(error.message, true);
  } finally {
    rescanButton.disabled = false;
  }
}

function migrationReasonText(reason) {
  const key = `migration.${reason || 'unavailable'}`;
  const value = t(key);
  return value.startsWith('migration.') ? t('migration.unavailable') : value;
}

function migrationFact(text, help = '') {
  const node = element('div', 'migration-result-fact');
  node.append(element('strong', '', text));
  if (help) node.append(element('small', '', help));
  return node;
}

function renderMigrationResult() {
  const result = $('#migration-result');
  const summaryBox = $('#migration-result-summary');
  const warnings = $('#migration-warnings');
  const warningList = $('#migration-warning-list');
  const download = $('#migration-download');
  const report = state.migrationReport;
  if (!report || !state.sessionId) {
    result.classList.add('hidden');
    summaryBox.replaceChildren();
    warningList.replaceChildren();
    warnings.classList.add('hidden');
    download.classList.add('hidden');
    download.removeAttribute('href');
    return;
  }
  const view = window.IDFRepairMigration?.summarizeMigrationReport(report) || {};
  const facts = element('div', 'migration-result-grid');
  facts.append(
    migrationFact(t('migration.original_preserved')),
    migrationFact(t('migration.steps_complete', {count: view.stepCount})),
    migrationFact(
      t(view.iddValid ? 'migration.idd_valid' : 'migration.idd_invalid', {
        count: view.iddIssueCount
      }),
      t('migration.idd_help')
    ),
    migrationFact(t(
      !view.simulationRan
        ? 'migration.simulation_not_run'
        : view.simulationPassed
          ? 'migration.simulation_passed'
          : 'migration.simulation_failed'
    )),
    migrationFact(t('migration.changes', {
      count: Number(view.changes?.changed_type_count || 0)
    }))
  );
  summaryBox.replaceChildren(facts);
  warningList.replaceChildren();
  for (const value of (view.warnings || []).slice(0, 100)) {
    warningList.append(element('li', '', String(value)));
  }
  warnings.classList.toggle('hidden', warningList.childElementCount === 0);
  download.href = `/api/sessions/${state.sessionId}/migrations/${report.migration_id}/download`;
  download.classList.remove('hidden');
  result.classList.remove('hidden');
}

function renderMigrationAssistant() {
  const assistant = $('#migration-assistant');
  if (!assistant) return;
  const source = $('#migration-source-version');
  const select = $('#migration-target-runtime');
  const status = $('#migration-capability');
  const run = $('#migration-run');
  const simulate = $('#migration-run-energyplus');
  const progress = $('#migration-progress');
  const pathDetails = $('#migration-path');
  const pathList = $('#migration-steps');
  const isOsm = state.sourceKind === 'osm';
  assistant.hidden = isOsm;
  if (isOsm) return;

  const capability = state.migrationCapability;
  source.textContent = capability?.source_version
    ? `${t('migration.source')} ${capability.source_version}`
    : `${t('migration.source')} —`;
  const previous = state.migrationTargetRuntimeId
    || select.value
    || capability?.matching_runtime_id
    || null;
  select.replaceChildren();
  for (const row of capability?.targets || []) {
    const option = element('option', '', `EnergyPlus ${row.version}`);
    option.value = row.runtime_id;
    option.title = row.available
      ? t('migration.available', {count: row.step_count})
      : migrationReasonText(row.reason);
    select.append(option);
  }
  const view = window.IDFRepairMigration?.deriveMigrationState(
    capability?.source_version,
    capability?.targets || [],
    previous
  ) || {canCreateCopy: false, reason: 'unavailable', selectedRuntimeId: null};
  state.migrationTargetRuntimeId = view.selectedRuntimeId;
  select.value = view.selectedRuntimeId || '';
  const pathWasOpen = pathDetails.open;
  pathList.replaceChildren();
  for (const step of view.steps || []) {
    pathList.append(element('li', '', t('migration.path_step', {
      source: step.source_version,
      target: step.target_version
    })));
  }
  pathDetails.classList.toggle('hidden', !view.canCreateCopy || !pathList.childElementCount);
  pathDetails.open = pathWasOpen && view.canCreateCopy;
  select.disabled = !capability || state.migrationBusy || !select.options.length;
  run.disabled = !view.canCreateCopy || state.migrationBusy || !state.sessionId;
  simulate.disabled = !view.canCreateCopy || state.migrationBusy || !state.sessionId;
  progress.hidden = !state.migrationBusy;
  run.textContent = t(state.migrationBusy ? 'migration.running_action' : 'migration.action');
  status.classList.toggle('ready', view.canCreateCopy && !state.migrationBusy);
  if (state.migrationBusy) {
    status.textContent = t('migration.running');
  } else if (!state.sessionId) {
    status.textContent = t('migration.no_session');
  } else if (!capability) {
    status.textContent = t('migration.loading');
  } else if (capability.error) {
    status.textContent = t('migration.unavailable');
  } else if (!(capability.targets || []).length) {
    status.textContent = t('migration.no_runtimes');
  } else if (view.canCreateCopy) {
    status.textContent = t('migration.available', {count: view.stepCount});
  } else {
    status.textContent = migrationReasonText(view.reason);
  }
  renderMigrationResult();
}

async function loadMigrationCapability(sessionId, {force = false} = {}) {
  if (!sessionId || state.sourceKind !== 'idf') {
    renderMigrationAssistant();
    return;
  }
  if (!force && state.migrationSessionId === sessionId && state.migrationCapability) {
    renderMigrationAssistant();
    return;
  }
  state.migrationSessionId = sessionId;
  state.migrationCapability = null;
  state.migrationReport = null;
  state.migrationTargetRuntimeId = null;
  renderMigrationAssistant();
  try {
    const payload = await request(`/api/sessions/${sessionId}/migration-capability`);
    if (state.sessionId !== sessionId || state.sourceKind !== 'idf') return;
    state.migrationCapability = payload;
    state.migrationTargetRuntimeId = payload.matching_runtime_id || null;
    renderMigrationAssistant();
  } catch (_error) {
    if (state.sessionId !== sessionId) return;
    state.migrationCapability = {source_version: '—', targets: [], error: true};
    renderMigrationAssistant();
  }
}

async function runMigrationCopy() {
  if (!state.sessionId || !state.migrationTargetRuntimeId || state.migrationBusy) return;
  const sessionId = state.sessionId;
  state.migrationBusy = true;
  state.migrationReport = null;
  renderMigrationAssistant();
  try {
    const report = await request(`/api/sessions/${sessionId}/migrations`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        target_runtime_id: state.migrationTargetRuntimeId,
        run_energyplus: $('#migration-run-energyplus').checked
      })
    });
    if (state.sessionId !== sessionId) return;
    state.migrationReport = report;
    notice(t('migration.complete'));
  } catch (_error) {
    if (state.sessionId === sessionId) notice(t('migration.error'), true);
  } finally {
    if (state.sessionId === sessionId) {
      state.migrationBusy = false;
      renderMigrationAssistant();
    }
  }
}

function notice(text, error = false) {
  const box = $('#notice');
  box.textContent = text;
  box.classList.toggle('error', error);
  box.classList.remove('hidden');
  window.setTimeout(() => box.classList.add('hidden'), 6000);
}

function elapsedText(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
  const seconds = String(totalSeconds % 60).padStart(2, '0');
  return `${minutes}:${seconds}`;
}

function setRunProgressStage(stage, counts = {}) {
  if (!runProgressBox || !window.IDFRepairSessionWorkbench) return;
  const progress = window.IDFRepairSessionWorkbench.deriveOperationProgress({stage, ...counts});
  runProgressBox.dataset.stage = progress.stage;
  runProgressLabel.textContent = t(`progress.stages.${progress.stage}`);
  if (progress.determinate) {
    runProgressBar.max = progress.max;
    runProgressBar.value = progress.value;
    runProgressBox.dataset.counts = `${progress.value}/${progress.max}`;
  } else {
    runProgressBar.removeAttribute('value');
    runProgressBar.removeAttribute('max');
    runProgressBox.removeAttribute('data-counts');
  }
}

function startRunProgress(action, stage = 'PREPARING', counts = {}) {
  if (!runProgressBox) return;
  window.clearInterval(runProgressTimer);
  window.clearTimeout(runProgressHideTimer);
  const started = Date.now();
  runProgressBox.hidden = false;
  runProgressBox.dataset.action = action;
  runProgressBox.classList.remove('failed', 'complete');
  setRunProgressStage(stage, counts);
  runElapsed.textContent = '00:00';
  $('#repair-panel').setAttribute('aria-busy', 'true');
  state.busy = action === 'run' ? 'repair' : action;
  updatePrimaryAction();
  runProgressTimer = window.setInterval(() => {
    runElapsed.textContent = elapsedText(Date.now() - started);
  }, 500);
}

function finishRunProgress(success) {
  if (!runProgressBox) return;
  window.clearInterval(runProgressTimer);
  runProgressTimer = null;
  runProgressBar.value = 1;
  runProgressBar.max = 1;
  runProgressBox.classList.add(success ? 'complete' : 'failed');
  runProgressLabel.textContent = t(success ? 'progress.complete' : 'progress.failed');
  $('#repair-panel').removeAttribute('aria-busy');
  state.busy = null;
  updatePrimaryAction();
  runProgressHideTimer = window.setTimeout(() => { runProgressBox.hidden = true; }, success ? 1200 : 3000);
}

function resetRepairViewForNewInput({clearViewerSelection = true} = {}) {
  state.inputRevision += 1;
  state.sessionId = null;
  state.activeModelFile = null;
  state.summary = null;
  state.report = null;
  state.rootDetails = [];
  state.selectedRootId = null;
  state.selectedAttemptId = null;
  state.busy = null;
  state.lastCompletedAction = null;
  state.outputReady = false;
  state.batchRecordContext = null;
  state.auditReport = null;
  state.auditSurfaceFilter = null;
  state.selectedAuditFindingId = null;
  state.auditRenderLimit = 200;
  state.auditBusy = false;
  state.experimentalReport = null;
  state.experimentalSurfaceFilter = null;
  state.selectedExperimentalPreviewId = null;
  state.experimentalRenderLimit = 100;
  state.experimentalBusy = false;
  state.experimentalResultsExpanded = true;
  state.preflightReport = null;
  state.preflightApplication = null;
  state.preflightBusy = false;
  state.preflightStatus = null;
  state.osmResult = null;
  state.osmReport = null;
  state.osmBusy = false;
  state.osmMappingQuery = '';
  state.osmMappingLimit = 50;
  state.osmValidityLimit = 50;
  state.runReadiness = null;
  state.readinessGeneration += 1;
  state.readinessLoading = false;
  state.readinessFailed = false;
  state.weatherUploadBusy = false;
  state.settingsOpen = false;
  state.issueCategory = 'all';
  state.issueQuery = '';
  state.issueGroupLimits = new Map();
  state.selectedIssueId = null;
  state.migrationCapability = null;
  state.migrationReport = null;
  state.migrationBusy = false;
  state.migrationSessionId = null;
  state.migrationTargetRuntimeId = null;
  $('#migration-run-energyplus').checked = false;
  const activeSource = $('#active-session-source');
  activeSource.classList.add('hidden');
  activeSource.replaceChildren();

  window.clearInterval(runProgressTimer);
  window.clearTimeout(runProgressHideTimer);
  runProgressTimer = null;
  runProgressHideTimer = null;
  runProgressBox.hidden = true;
  runProgressBox.classList.remove('failed', 'complete');
  runProgressBox.removeAttribute('data-action');
  runProgressBox.removeAttribute('data-stage');
  runProgressBox.removeAttribute('data-counts');
  runProgressLabel.textContent = t('progress.preparing');
  runElapsed.textContent = '00:00';
  runProgressBar.removeAttribute('value');
  $('#repair-panel').removeAttribute('aria-busy');
  $('#readiness-blocker').classList.add('hidden');
  $('#readiness-status').textContent = t('readiness.weather_missing');
  $('#session-epw-file').value = '';
  $('#session-epw-name').textContent = t('readiness.no_epw');
  $('#attach-session-weather').disabled = true;

  statusBox.textContent = t('session.none');
  questionBox.replaceChildren();
  supportSummaryBox.replaceChildren();
  rootSupportBox.replaceChildren();
  diagnosisSummaryBox.replaceChildren(element('p', 'empty-copy', t('repair.no_diagnosis')));
  candidateInspectorBox.replaceChildren(element('p', 'empty-copy', t('repair.no_candidate')));
  resultSummaryBox.replaceChildren(element('p', 'empty-copy', t('repair.no_result')));
  roundsBox.replaceChildren();
  attemptsBox.replaceChildren();
  renderValidation(null);
  rawErrBox.textContent = t('report.no_raw_err');
  reportBox.textContent = t('report.empty');
  document.querySelectorAll('.technical-details details').forEach((details) => { details.open = false; });
  ruleSaveBox.classList.add('hidden');
  downloadLink.classList.add('hidden');
  downloadLink.removeAttribute('href');
  downloadLink.textContent = t('actions.download');
  expandedDownloadLink.classList.add('hidden');
  expandedDownloadLink.removeAttribute('href');
  preprocessingSummaryBox.classList.add('hidden');
  preprocessingSummaryBox.replaceChildren();
  cancelButton.disabled = true;
  document.querySelectorAll('#workflow-steps li').forEach((step, index) => {
    step.classList.remove('active', 'complete');
    if (index === 0) step.classList.add('active');
  });
  $('#notice').classList.add('hidden');
  $('#audit-status').textContent = t('audit.empty');
  $('#audit-summary').replaceChildren();
  $('#audit-findings').replaceChildren();
  $('#audit-detail').replaceChildren();
  $('#audit-detail').classList.add('hidden');
  $('#audit-clear-surface').classList.add('hidden');
  $('#audit-load-more').classList.add('hidden');
  $('#experimental-status').textContent = t('experimental.empty');
  $('#experimental-summary').replaceChildren();
  $('#experimental-results').replaceChildren();
  $('#experimental-preview-detail').replaceChildren();
  $('#experimental-preview-detail').classList.add('hidden');
  $('#experimental-clear-surface').classList.add('hidden');
  $('#experimental-load-more').classList.add('hidden');
  renderModelPreflight();
  $('#osm-summary').replaceChildren();
  $('#osm-adaptation-facts').replaceChildren();
  $('#osm-adaptation-facts').classList.add('hidden');
  $('#osm-validity-section').classList.add('hidden');
  $('#osm-validity-errors').replaceChildren();
  $('#osm-mapping-section').classList.add('hidden');
  $('#osm-mappings').replaceChildren();
  $('#osm-mapping-summary').textContent = '';
  $('#osm-mapping-search').value = '';
  $('#osm-validity-more').classList.add('hidden');
  $('#osm-mapping-more').classList.add('hidden');
  resetOsmTimeline();
  $('#osm-downloads').classList.add('hidden');
  $('#osm-technical').classList.add('hidden');
  $('#osm-status').classList.remove('running');
  $('#osm-status').textContent = t('osm.ready');
  window.IDFRepairViewer?.focusRoots([]);
  window.IDFRepairViewer?.showIssue(null);
  if (clearViewerSelection) renderViewerSelection(null);
  $('#issue-search').value = '';
  renderIssueNavigator();
  renderIssueInspector(null);
  clearIssueContexts();
  renderMigrationAssistant();
  updatePrimaryAction();
  updateAuditAction();
}

function startNewInput() {
  resetRepairViewForNewInput();
  for (const selector of ['#idf-file', '#osm-file', '#epw-file', '#dependency-files']) {
    const input = $(selector);
    if (input) input.value = '';
  }
  $('#idf-file-name').textContent = t('form.idf_none');
  $('#osm-file-name').textContent = t('workbench.osm_none');
  $('#epw-file-name').textContent = t('form.epw_none');
  $('#dependency-file-name').textContent = t('form.dependencies_none');
  setSourceKind('idf');
  window.IDFRepairViewer?.clearModel();
  updatePrimaryAction();
  document.querySelector('[data-panel="repair-panel"]')?.click();
  $('#idf-file')?.focus({preventScroll: true});
  $('#session-form')?.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function setStatus(summary) {
  const openingDifferentSession = state.sessionId !== summary.session_id;
  if (openingDifferentSession) {
    state.runReadiness = null;
    state.readinessGeneration += 1;
    state.readinessLoading = false;
    state.readinessFailed = false;
  }
  state.summary = summary;
  state.sessionId = summary.session_id;
  if (summary.last_completed_action) {
    state.lastCompletedAction = summary.last_completed_action;
  } else if (openingDifferentSession) {
    state.lastCompletedAction = null;
  }
  const mode = document.querySelector(`input[name="mode"][value="${summary.mode}"]`);
  if (mode) mode.checked = true;
  if (summary.energyplus_version) selectSingleRuntimeByVersion(summary.energyplus_version);
  setSourceKind(summary.source_type === 'OSM' ? 'osm' : 'idf', {restoreIdfMode: false});
  state.preflightStatus = summary.preflight_status || ({
    PRECHECK_REQUIRED: 'REQUIRED',
    PRECHECKED: 'CHECKED',
    PREPROCESSING_APPLIED: 'APPLIED'
  }[summary.osm_bridge_status] || null);
  if (!state.preflightReport && summary.preflight_summary) {
    state.preflightReport = {summary: summary.preflight_summary, repair_plans: [], issues: null};
  }
  const sourceName = summary.source_input_name || summary.input_name || '—';
  const source = $('#active-session-source');
  source.replaceChildren(
    element('strong', '', t('sessions.current_session')),
    element('span', '', sourceName),
    element('small', '', t('sessions.settings_bound'))
  );
  source.classList.remove('hidden');
  const isOsmSource = summary.source_type === 'OSM';
  const fileLabel = isOsmSource ? $('#osm-file-name') : $('#idf-file-name');
  const sourceInput = isOsmSource ? $('#osm-file') : $('#idf-file');
  if (!sourceInput.files?.[0]) {
    fileLabel.textContent = sourceName;
    fileLabel.title = sourceName;
    fileLabel.removeAttribute('data-i18n');
  }
  if (isOsmSource && !$('#idf-file').files?.[0]) {
    $('#idf-file-name').textContent = t('form.idf_none');
    $('#idf-file-name').removeAttribute('title');
    $('#idf-file-name').dataset.i18n = 'form.idf_none';
  }
  statusBox.textContent = t('session.summary', {
    id: summary.session_id,
    status: renderMessage(summary.message) || summary.status || summary.lifecycle_status,
    mode: t(`tokens.modes.${summary.mode}`)
  });
  renderQuestions(summary.questions || []);
  renderSupport(
    summary.root_support || [],
    summary.support_coverage_summary || null,
    summary.status
  );
  renderRuleSave(summary);
  renderIssueNavigator();
  cancelButton.disabled = ['CANCELLED', 'ARCHIVED'].includes(summary.lifecycle_status);
  updatePrimaryAction();
  updateAuditAction();
  renderModelPreflight();
  void loadMigrationCapability(summary.session_id);
  void refreshReadiness(summary.session_id);
}

function formatRatio(metric) {
  if (!metric || !metric.denominator) return '—';
  const percentage = (100 * metric.numerator / metric.denominator).toFixed(1);
  return `${metric.numerator}/${metric.denominator} (${percentage}%)`;
}

function metricNode(label, value) {
  const node = element('div', 'metric');
  node.append(element('span', '', label), element('strong', '', value));
  return node;
}

function renderSupport(roots, coverage) {
  if (!supportSummaryBox || !rootSupportBox) return;
  const supportMetric = coverage?.support_coverage || {numerator: 0, denominator: roots.length};
  supportSummaryBox.replaceChildren(
    metricNode(t('support.coverage'), formatRatio(supportMetric)),
    metricNode(t('support.roots'), String(roots.length))
  );
  rootSupportBox.replaceChildren();
  for (const row of roots) {
    const card = element('div', `card ${row.provider_allowed ? 'accepted' : 'rejected'}`);
    const status = t(`support.statuses.${row.support_status}`);
    const reason = localizedSupportReason(row);
    const technical = element('details', 'support-technical');
    technical.append(
      element('summary', '', t('workbench.technical_evidence')),
      element('code', 'support-raw-token', row.support_presentation?.raw_token || row.support_reason || row.support_entry_id || '')
    );
    card.append(
      element('strong', '', `${localizedFamily(row.family)} · ${status}`),
      element('p', '', row.provider_allowed
        ? t('support.allowed')
        : t('support.blocked', {reason})),
      technical
    );
    rootSupportBox.append(card);
  }
}

function joinRootDetails(report) {
  const joined = new Map();
  const ensure = (rootId) => {
    const key = String(rootId || 'unidentified-root');
    if (!joined.has(key)) joined.set(key, {root_id: key, attempts: []});
    return joined.get(key);
  };
  for (const diagnostic of report.initial_diagnostics || []) {
    Object.assign(ensure(diagnostic.root_id), diagnostic, {present_initially: true});
  }
  for (const diagnostic of report.final_diagnostics || []) {
    const row = ensure(diagnostic.root_id);
    if (!row.message) Object.assign(row, diagnostic);
    row.present_finally = true;
    row.final_diagnostic = diagnostic;
  }
  for (const support of report.root_support || []) {
    Object.assign(ensure(support.root_id), support);
  }
  for (const attempt of report.candidate_attempts || []) {
    ensure(attempt.root_id).attempts.push(attempt);
  }
  return [...joined.values()];
}

function patchRows(patch) {
  return (Array.isArray(patch) ? patch : []).map((operation, index) => ({
    index: index + 1,
    kind: operation.kind || 'unknown',
    object: [operation.object_type, operation.object_name].filter(Boolean).join(' · ') || '—',
    field: operation.field_name || (operation.field_index === null || operation.field_index === undefined
      ? (operation.metadata?.line_number ? `line ${operation.metadata.line_number}` : '—')
      : `#${operation.field_index}`),
    oldValue: operation.old_value === null || operation.old_value === undefined ? '∅' : String(operation.old_value),
    newValue: operation.new_value === null || operation.new_value === undefined
      ? (operation.kind === 'insert_delimiter'
          ? String(operation.metadata?.delimiter || ';')
          : (operation.vertices?.length ? `${operation.vertices.length} vertices` : '∅'))
      : String(operation.new_value)
  }));
}

function validationState(result, gateKey) {
  if (result === null || result === undefined) return 'not-run';
  if (gateKey === 'energyplus' && (result.process_failure || result.timed_out)) return 'failed';
  if ((result.reasons || []).includes('not_run')) return 'not-run';
  if (result.passed === true) return 'passed';
  if (result.passed === false) return 'failed';
  return 'not-applicable';
}

function attemptGates(attempt) {
  const definitions = [
    ['static', attempt?.static_result],
    ['semantic', attempt?.semantic_result],
    ['energyplus', attempt?.energyplus_result],
    ['transition', attempt?.transition_result]
  ];
  let foundFailure = false;
  return definitions.map(([key, result]) => {
    const status = attempt ? validationState(result, key) : 'not-applicable';
    const firstFailure = status === 'failed' && !foundFailure;
    if (status === 'failed') foundFailure = true;
    const reasons = key === 'energyplus'
      ? [
          result?.process_failure ? 'process_failure' : null,
          result?.timed_out ? 'timed_out' : null,
          Number.isFinite(result?.severe_count) ? `severe=${result.severe_count}` : null,
          Number.isFinite(result?.fatal_count) ? `fatal=${result.fatal_count}` : null,
          Number.isFinite(result?.warning_count) ? `warning=${result.warning_count}` : null
        ].filter(Boolean)
      : (result?.reasons || []);
    return {key, result, status, firstFailure, reasons};
  });
}

function resultView(report) {
  const inputSha = report.input_identity?.sha256 || '';
  const outputSha = report.output_identity?.sha256 || '';
  const outputChanged = Boolean(inputSha && outputSha && inputSha !== outputSha);
  const committedCount = (report.committed_candidates || []).length;
  const repairedArtifact = report.final_status === 'REPAIRED' && outputChanged && committedCount > 0;
  const attempts = report.candidate_attempts || [];
  const lastAttempt = attempts[attempts.length - 1] || null;
  const gates = attemptGates(lastAttempt);
  return {
    status: report.final_status,
    initialIssueCount: (report.initial_diagnostics || []).length,
    remainingIssueCount: (report.final_diagnostics || []).length,
    committedCount,
    inputSha,
    outputSha,
    outputChanged,
    repairedArtifact,
    downloadKey: repairedArtifact ? 'actions.download_repaired' : 'actions.download_unchanged',
    semanticState: gates.find((gate) => gate.key === 'semantic')?.status || 'not-applicable',
    energyplusState: gates.find((gate) => gate.key === 'energyplus')?.status || 'not-applicable',
    energyplusRuns: report.energyplus_runs || 0,
    rollbackReason: report.rollback_reason || null
  };
}

function displayList(values) {
  return Array.isArray(values) && values.length ? values.join(' · ') : '—';
}

function localizedTechnicalList(values) {
  if (!Array.isArray(values) || !values.length) return '—';
  return values.map((value) => localizedCandidateToken('evidence_kinds', value)).join(' · ');
}

function renderDiagnosis(report) {
  const roots = joinRootDetails(report);
  const statusCount = (status) => roots.filter((root) => root.support_status === status).length;
  state.rootDetails = roots;
  renderIssueNavigator();
  diagnosisSummaryBox.replaceChildren();
  diagnosisSummaryBox.append(
    element('strong', 'diagnosis-title', roots.length ? t('diagnosis.title', {count: roots.length}) : t('diagnosis.none')),
    element('p', 'diagnosis-status', t(`result.statuses.${report.final_status}`))
  );
  supportSummaryBox.replaceChildren(
    metricNode(t('diagnosis.initial'), String((report.initial_diagnostics || []).length)),
    metricNode(t('diagnosis.remaining'), String((report.final_diagnostics || []).length)),
    metricNode(t('diagnosis.safe_auto'), String(statusCount('safe-auto'))),
    metricNode(t('diagnosis.assisted'), String(statusCount('assisted'))),
    metricNode(t('diagnosis.needs_input'), String(statusCount('interactive'))),
    metricNode(t('diagnosis.unsupported'), String(statusCount('unsupported'))),
    metricNode(t('support.coverage'), formatRatio(report.support_coverage_summary?.support_coverage))
  );

  rootSupportBox.replaceChildren();
  if (!roots.length) {
    state.selectedRootId = null;
    candidateInspectorBox.replaceChildren(element('p', 'empty-copy', t('candidate.none')));
    renderValidation(null);
    window.IDFRepairViewer?.focusRoots([]);
    window.IDFRepairViewer?.showIssue(null);
    renderIssueInspector(null);
    return;
  }

  roots.forEach((root, index) => {
    const card = element('article', 'root-card');
    card.dataset.rootId = root.root_id;
    const select = element('button', 'root-select');
    select.type = 'button';
    select.setAttribute('aria-pressed', 'false');
    const presentation = localizedDiagnostic(root);
    const heading = element('span', 'root-heading');
    heading.append(
      element('span', 'issue-number', String(index + 1)),
      element('strong', 'presentation-title', presentation.title)
    );
    const identity = [root.object_type, root.object_name, root.field_name].filter(Boolean).join(' · ') || root.root_id;
    const status = t(`support.statuses.${root.support_status || 'unsupported'}`);
    const providerText = root.provider_allowed ? t('diagnosis.provider_allowed') : t('diagnosis.provider_blocked');
    select.append(
      heading,
      element('span', 'diagnostic-summary', presentation.summary),
      element('span', 'diagnostic-action', `${t('presentation.next_step')}：${presentation.action}`),
      element('span', 'root-identity', identity),
      element('span', `support-badge support-${root.support_status || 'unsupported'}`, `${localizedFamily(root.family)} · ${status}`),
      element('span', 'root-reason', `${providerText} · ${localizedSupportReason(root)}`),
      element('span', 'root-evidence', `${t('diagnosis.required_evidence')}: ${localizedTechnicalList(root.required_evidence)}`),
      element('span', 'root-evidence', `${t('diagnosis.user_input')}: ${localizedTechnicalList(root.user_input_conditions)}`)
    );
    select.addEventListener('click', () => selectRoot(root.root_id));
    const raw = element('details', 'raw-diagnostic');
    raw.append(
      element('summary', '', t('presentation.raw')),
      element('code', '', presentation.raw)
    );
    card.append(select, raw);
    rootSupportBox.append(card);
  });

  const selected = roots.some((root) => root.root_id === state.selectedRootId)
    ? state.selectedRootId
    : roots[0].root_id;
  selectRoot(selected);
}

function committedCandidate(attempt) {
  for (const round of state.report?.rounds || []) {
    if (round.candidate?.candidate_id === attempt.candidate_id) return round.candidate;
  }
  return null;
}

function candidateFact(label, value) {
  const node = element('span', 'candidate-fact');
  node.append(element('small', '', label), element('strong', '', value ?? t('candidate.unavailable')));
  return node;
}

function renderPatch(patch) {
  const section = element('section', 'patch-section');
  section.append(element('h5', '', t('diff.title')));
  const rows = patchRows(patch);
  if (!rows.length) {
    section.append(element('p', 'empty-copy', t('diff.empty')));
    return section;
  }
  const table = element('div', 'diff-table');
  for (const row of rows) {
    const item = element('div', 'diff-row');
    item.append(
      element('span', 'diff-index', String(row.index)),
      element('span', 'diff-kind', localizedCandidateToken('operations', row.kind)),
      element('span', 'diff-target', `${row.object} · ${row.field}`),
      element('span', 'diff-before', `${t('diff.old_value')}: ${row.oldValue}`),
      element('span', 'diff-arrow', '→'),
      element('span', 'diff-after', `${t('diff.new_value')}: ${row.newValue}`)
    );
    table.append(item);
  }
  section.append(table);
  return section;
}

function renderEvidence(evidence) {
  const section = element('section', 'evidence-section');
  section.append(element('h5', '', t('candidate.evidence')));
  if (!evidence?.length) {
    section.append(element('p', 'empty-copy', t('candidate.unavailable')));
    return section;
  }
  const list = element('div', 'evidence-list');
  for (const row of evidence) {
    const item = element('div', 'evidence-item');
    item.append(
      element('strong', '', localizedCandidateToken('evidence_kinds', row.kind)),
      element('span', '', `${t('candidate.evidence_source')}: ${localizedCandidateToken('sources', row.source)}`),
      element('span', '', `${t('candidate.evidence_strength')}: ${localizedCandidateToken('strengths', row.strength)}`),
      element('code', 'evidence-details', JSON.stringify(row.details || {}))
    );
    list.append(item);
  }
  section.append(list);
  return section;
}

function selectAttempt(candidateId) {
  state.selectedAttemptId = candidateId;
  candidateInspectorBox.querySelectorAll('[data-candidate-id]').forEach((node) => {
    const active = node.dataset.candidateId === candidateId;
    node.classList.toggle('active', active);
    node.querySelector('.attempt-select')?.setAttribute('aria-pressed', String(active));
  });
  const attempt = (state.report?.candidate_attempts || []).find((row) => row.candidate_id === candidateId) || null;
  renderValidation(attempt);
}

function renderCandidateInspector(root) {
  candidateInspectorBox.replaceChildren();
  const header = element('div', 'inspector-heading');
  header.append(
    element('span', 'section-index', t('candidate.index')),
    element('h4', '', t('candidate.title'))
  );
  candidateInspectorBox.append(header, element('p', 'selected-root-message', localizedDiagnostic(root).title || root.root_id));
  const attempts = root.attempts || [];
  if (!attempts.length) {
    candidateInspectorBox.append(element('p', 'empty-copy', t('candidate.none')));
    state.selectedAttemptId = null;
    renderValidation(null);
    return;
  }

  const list = element('div', 'candidate-grid');
  attempts.forEach((attempt, index) => {
    const candidate = committedCandidate(attempt) || {};
    const metadata = attempt.candidate_metadata || {};
    const card = element('article', `candidate-card ${attempt.accepted ? 'accepted' : 'rejected'}`);
    card.dataset.candidateId = attempt.candidate_id;
    const select = element('button', 'attempt-select');
    select.type = 'button';
    select.setAttribute('aria-pressed', 'false');
    select.append(
      element('strong', '', `${localizedCandidateToken('providers', attempt.provider || candidate.provider)} · #${attempt.rank ?? index + 1}`),
      element('span', `pill ${attempt.accepted ? 'enabled' : 'disabled'}`, t(attempt.accepted ? 'candidate.accepted' : 'candidate.rejected'))
    );
    select.addEventListener('click', () => selectAttempt(attempt.candidate_id));
    const facts = element('div', 'candidate-facts');
    facts.append(
      candidateFact(t('candidate.score'), attempt.score?.total ?? attempt.score ?? null),
      candidateFact(t('candidate.confidence'), candidate.confidence ?? metadata.confidence ?? null),
      candidateFact(t('candidate.risk'), localizedCandidateToken('risks', candidate.risk ?? metadata.risk)),
      candidateFact(t('candidate.provenance'), localizedCandidateToken('provenances', candidate.provenance ?? metadata.provenance)),
      candidateFact(t('candidate.rollback'), localizedCandidateToken('booleans', candidate.rollback_supported ?? metadata.rollback_supported))
    );
    const qualification = metadata.qualification_reason || metadata.qualification || [
      metadata.support_entry_id,
      metadata.support_status,
      metadata.release_automatic_policy
    ].filter(Boolean).join(' · ') || null;
    card.append(select, facts);
    if (qualification) card.append(element('p', 'candidate-reason', `${t('candidate.qualification')}: ${localizedQualificationText(attempt, candidate, metadata)}`));
    if (attempt.rejection_reason) card.append(element(
      'p', 'candidate-reason rejection-copy',
      `${t('candidate.rejection')}: ${localizedReasonText(attempt.rejection_reason)}`
    ));
    if (qualification || attempt.rejection_reason) {
      const rawReasons = element('details', 'candidate-technical-reasons');
      rawReasons.append(
        element('summary', '', t('workbench.technical_evidence')),
        element('pre', '', JSON.stringify({qualification, rejection_reason: attempt.rejection_reason || null}, null, 2))
      );
      card.append(rawReasons);
    }
    card.append(renderPatch(attempt.patch), renderEvidence(attempt.evidence));
    card.append(element('p', 'candidate-continuation', index < attempts.length - 1 && !attempt.accepted
      ? t('candidate.continue')
      : t('candidate.exhausted')));
    list.append(card);
  });
  candidateInspectorBox.append(list);
  const selected = attempts.some((attempt) => attempt.candidate_id === state.selectedAttemptId)
    ? state.selectedAttemptId
    : attempts[0].candidate_id;
  selectAttempt(selected);
}

function selectRoot(rootId, {syncWorkbench = true} = {}) {
  const root = state.rootDetails.find((row) => row.root_id === rootId);
  if (!root) return;
  state.selectedRootId = rootId;
  if (syncWorkbench) state.selectedIssueId = rootId;
  rootSupportBox.querySelectorAll('[data-root-id]').forEach((node) => {
    const active = node.dataset.rootId === rootId;
    node.classList.toggle('active', active);
    node.querySelector('.root-select')?.setAttribute('aria-pressed', String(active));
  });
  renderCandidateInspector(root);
  window.IDFRepairViewer?.focusRoots([{
    ...root,
    localized_message: localizedDiagnostic(root).summary
  }]);
  if (syncWorkbench) {
    renderIssueNavigator();
    const issue = workbenchIssueRows().find((row) => row.id === rootId) || null;
    showWorkbenchIssueInViewer(issue);
    renderIssueInspector(issue);
    loadIssueContexts(issue);
  }
}

function renderValidation(attempt) {
  validationGatesBox.replaceChildren();
  for (const gate of attemptGates(attempt)) {
    const card = element('article', `gate ${gate.status}${gate.firstFailure ? ' first-failure' : ''}`);
    const icon = {passed: '✓', failed: '!', 'not-run': '–', 'not-applicable': '○'}[gate.status];
    const header = element('div', 'gate-heading');
    header.append(element('span', 'gate-icon', icon), element('strong', '', t(`validation.gates.${gate.key}`)));
    card.append(header, element('span', 'gate-state', t(`validation.states.${gate.status}`)));
    if (gate.firstFailure) card.append(element('small', 'first-failure-label', t('validation.first_failure')));
    if (gate.reasons.length) {
      card.append(element('small', 'gate-reasons', gate.reasons.map(localizedReasonText).join(' · ')));
      const rawReasons = element('details', 'gate-technical-reasons');
      rawReasons.append(
        element('summary', '', t('workbench.technical_evidence')),
        element('pre', '', JSON.stringify(gate.reasons, null, 2))
      );
      card.append(rawReasons);
    }
    validationGatesBox.append(card);
  }
}

function renderTrace(report) {
  roundsBox.replaceChildren();
  attemptsBox.replaceChildren();
  for (const round of report.rounds || []) {
    const card = element('article', 'trace-row accepted');
    card.append(
      element('strong', '', t('report.round', {
        index: round.round_index,
        family: localizedFamily(round.root?.family),
        provider: localizedProvider(round.candidate?.provider)
      })),
      element('code', '', round.candidate?.candidate_id || '—')
    );
    roundsBox.append(card);
  }
  for (const attempt of report.candidate_attempts || []) {
    const row = element('button', `trace-row ${attempt.accepted ? 'accepted' : 'rejected'}`);
    row.type = 'button';
    row.append(
      element('strong', '', `${localizedProvider(attempt.provider)} · #${attempt.rank}`),
      element('span', '', attempt.accepted
        ? t('candidate.accepted')
        : `${t('candidate.rejected')}: ${localizedReasonText(attempt.rejection_reason)}`)
    );
    row.addEventListener('click', () => {
      selectRoot(attempt.root_id);
      selectAttempt(attempt.candidate_id);
      validationGatesBox.scrollIntoView({behavior: 'smooth', block: 'center'});
    });
    attemptsBox.append(row);
  }
  if (!(report.candidate_attempts || []).length) renderValidation(null);
}

function shortHash(value) {
  return value ? `${value.slice(0, 10)}…${value.slice(-6)}` : '—';
}

function renderTextFidelity(report) {
  const fidelity = report.text_fidelity || {};
  const section = element('section', 'text-fidelity-summary');
  const header = element('header');
  header.append(
    element('strong', '', t('text_fidelity.title')),
    element(
      'span',
      `pill ${fidelity.proof_passed === true ? 'enabled' : 'disabled'}`,
      t(fidelity.proof_passed === true ? 'text_fidelity.proven' : 'text_fidelity.not_proven')
    )
  );
  section.append(header);
  const generated = fidelity.generated_field_comments || {};
  const facts = [
    [t('text_fidelity.unmodified_regions'), fidelity.unmodified_regions_preserved === true, ''],
    [
      t('text_fidelity.existing_comments'),
      fidelity.existing_comments_preserved === true,
      `${fidelity.existing_comment_count_after ?? '—'}/${fidelity.existing_comment_count_before ?? '—'}`
    ],
    [
      t('text_fidelity.generated_comments'),
      Number(generated.generated || 0) === Number(generated.eligible || 0),
      `${generated.generated ?? 0}/${generated.eligible ?? 0}`
    ],
    [t('text_fidelity.line_endings'), fidelity.line_ending_preserved === true, fidelity.line_ending_after || '—'],
    [
      t('text_fidelity.bom'),
      fidelity.utf8_bom_preserved === true,
      fidelity.utf8_bom_policy === 'preserve-input'
        ? t('text_fidelity.bom_preserve_input')
        : (fidelity.utf8_bom_policy || '—')
    ]
  ];
  const list = element('div', 'text-fidelity-facts');
  facts.forEach(([label, proven, detail]) => {
    const row = element('div', proven ? 'proven' : 'not-proven');
    row.append(
      element('span', 'fidelity-mark', proven ? '✓' : '—'),
      element('span', '', label),
      element('code', '', detail)
    );
    list.append(row);
  });
  const details = element('details', 'text-fidelity-details');
  details.append(
    element('summary', '', t('text_fidelity.technical_details')),
    element('pre', '', JSON.stringify(fidelity, null, 2))
  );
  section.append(list, details);
  return section;
}

function renderResult(report) {
  const view = resultView(report);
  resultSummaryBox.replaceChildren();
  const header = element('div', 'result-headline');
  header.append(
    element('span', `result-status status-${String(view.status || '').toLowerCase()}`, localizedResultStatus(view.status)),
    element('strong', '', localizedResultStatus(view.status))
  );
  const metrics = element('div', 'result-metrics');
  metrics.append(
    metricNode(t('result.initial_issues'), String(view.initialIssueCount)),
    metricNode(t('result.remaining_issues'), String(view.remainingIssueCount)),
    metricNode(t('result.commits'), String(view.committedCount))
  );
  const identity = element('div', `identity-line ${view.outputChanged ? 'changed' : 'unchanged'}`);
  identity.append(element('strong', '', view.outputChanged ? t('result.changed') : t('result.unchanged')));
  const gates = element('div', 'result-gate-summary');
  gates.append(
    element('span', '', `${t('result.semantic')}: ${t(`validation.states.${view.semanticState}`)}`),
    element('span', '', `${t('result.energyplus')}: ${t(`validation.states.${view.energyplusState}`)}`),
    element('span', '', t('result.runs', {count: view.energyplusRuns}))
  );
  resultSummaryBox.append(header, metrics, identity, gates, renderTextFidelity(report));
  if (view.rollbackReason) {
    resultSummaryBox.append(element('p', 'rollback-reason', `${t('result.rollback')}: ${view.rollbackReason}`));
  }
  downloadLink.textContent = t(view.downloadKey);
  downloadLink.href = `/api/sessions/${state.sessionId}/download`;
  downloadLink.classList.remove('hidden');
  const preprocessing = report.preprocessing || {};
  preprocessingSummaryBox.replaceChildren();
  preprocessingSummaryBox.classList.toggle('hidden', !preprocessing.required);
  if (preprocessing.required) {
    preprocessingSummaryBox.append(
      element('strong', '', t('preprocessing.title')),
      element('p', '', t(preprocessing.used ? 'preprocessing.used' : 'preprocessing.required_not_used')),
      element('p', '', t('preprocessing.objects', {
        objects: (preprocessing.object_types || []).join(' · ') || '—'
      })),
      element('small', '', t('preprocessing.templates_preserved'))
    );
  }
  expandedDownloadLink.classList.toggle('hidden', !preprocessing.artifact_available);
  if (preprocessing.artifact_available) {
    expandedDownloadLink.href = `/api/sessions/${state.sessionId}/expanded-input`;
  } else {
    expandedDownloadLink.removeAttribute('href');
  }
}

function renderViewerSelection(detail) {
  if (!viewerSelectionBox) return;
  viewerSelectionBox.replaceChildren();
  if (!detail) {
    viewerSelectionBox.append(element('p', 'empty-copy', t('viewer.details_empty')));
    return;
  }
  const fields = [
    ['name', detail.objectName],
    ['type', detail.objectType],
    ['surface_type', detail.surfaceType],
    ['construction', detail.construction],
    ['boundary', detail.boundary],
    ['zone', detail.zone],
    ['space', detail.space],
    ['space_type', detail.spaceType],
    [detail.storyIsInferred ? 'elevation_group' : 'story', detail.story],
    ['surface_count', detail.surfaceCount],
    ['window_count', detail.windowCount],
    ['shading_count', detail.shadingCount],
    ['room_count', detail.roomCount],
    [detail.storyCountIsInferred ? 'elevation_group_count' : 'story_count', detail.storyCount],
    ['dimensions', detail.dimensions],
    ['vertices', detail.vertexCount],
    ['normal', Array.isArray(detail.normal) ? detail.normal.map((value) => Number(value).toFixed(3)).join(', ') : detail.normal]
  ].filter(([, value]) => value !== null && value !== undefined && value !== '');
  const list = element('dl', 'selection-properties');
  for (const [key, value] of fields) {
    const row = element('div');
    row.append(element('dt', '', t(`viewer.fields.${key}`)), element('dd', '', String(value)));
    list.append(row);
  }
  viewerSelectionBox.append(list);
}

function renderRuleSave(summary) {
  if (!ruleSaveBox) return;
  ruleSaveBox.classList.toggle('hidden', !summary.rule_save_available);
  if (!summary.rule_save_available) return;
  const candidateSelect = $('#rule-save-candidate');
  candidateSelect.replaceChildren();
  for (const row of summary.rule_save_candidates || []) {
    const option = element('option', '', `${localizedFamily(row.family)} · ${localizedProvider(row.provider)}`);
    option.value = row.candidate_id;
    candidateSelect.append(option);
  }
  const scopeSelect = $('#rule-save-scope');
  scopeSelect.replaceChildren();
  for (const scope of summary.rule_save_scope_choices || []) {
    const option = element('option', '', t(`rule_save.scopes.${scope}`));
    option.value = scope;
    option.dataset.token = scope;
    scopeSelect.append(option);
  }
  $('#rule-save-name-zh').value ||= t('rule_save.default_name_zh');
  $('#rule-save-name-en').value ||= t('rule_save.default_name_en');
  $('#rule-save-global-row').classList.toggle('hidden', scopeSelect.value !== 'GLOBAL');
}

function questionTargetText(target = {}) {
  const identity = [target.object_type, target.object_name].filter(Boolean).join(' · ') || t('questions.unknown_target');
  const facts = [identity];
  if (target.object_index !== null && target.object_index !== undefined) {
    facts.push(t('questions.object_index', {index: target.object_index}));
  }
  if (target.field_name || target.field_index !== null && target.field_index !== undefined) {
    const field = target.field_name || t('questions.field_index', {index: target.field_index});
    facts.push(target.field_index === null || target.field_index === undefined
      ? field
      : `${field} [${target.field_index}]`);
  }
  if (target.line) facts.push(t('questions.line', {line: target.line}));
  return facts.join(' · ');
}

function questionChangeValue(change, side) {
  const value = change?.[`${side}_value`];
  if (value !== null && value !== undefined && value !== '') return String(value);
  if (side === 'new' && change?.vertices?.length) return JSON.stringify(change.vertices);
  if (side === 'new' && change?.object_text) return String(change.object_text);
  if (side === 'new' && change?.awaiting_input) return t('questions.awaiting_input');
  return '∅';
}

function renderQuestionContext(card, question) {
  const metadata = question.metadata || {};
  const contexts = question.metadata?.idf_contexts || [];
  const changes = [...(question.metadata?.proposed_changes || [])];
  const diagnostic = question.metadata?.diagnostic_context;
  if (!changes.length && metadata.target && Object.prototype.hasOwnProperty.call(metadata, 'current_value')) {
    changes.push({...metadata.target, old_value: metadata.current_value, new_value: null, awaiting_input: true});
  }
  if (!metadata.target && !contexts.length && !changes.length && !diagnostic) return;

  const section = element('section', 'question-context');
  section.append(element('strong', 'question-context-title', t('questions.context_title')));
  if (diagnostic) {
    const evidence = element('article', 'question-diagnostic-context');
    evidence.append(
      element('small', '', `${localizedCandidateToken('severities', diagnostic.severity)} · ${localizedFamily(diagnostic.family)}`),
      element('p', '', localizedDiagnostic(diagnostic).summary)
    );
    if (!metadata.target) evidence.append(element('strong', '', t('questions.no_exact_edit')));
    section.append(evidence);
  }
  if (metadata.target) {
    const target = element('div', 'question-target');
    target.append(
      element('span', '', t('questions.exact_target')),
      element('code', '', questionTargetText(metadata.target))
    );
    section.append(target);
  }

  if (changes.length) {
    const list = element('div', 'question-change-list');
    changes.forEach((change, index) => {
      const row = element('article', 'question-change');
      row.append(element('small', '', `${t('questions.candidate_change')} ${index + 1} · ${questionTargetText(change)}`));
      const values = element('div', 'question-change-values');
      const before = element('span');
      before.append(element('small', '', t('questions.before_value')), element('code', '', questionChangeValue(change, 'old')));
      const after = element('span');
      after.append(element('small', '', t('questions.after_value')));
      const afterValue = element('code', '', questionChangeValue(change, 'new'));
      if (change.awaiting_input) afterValue.setAttribute('data-question-after', 'true');
      after.append(afterValue);
      values.append(before, element('b', '', '→'), after);
      row.append(values);
      list.append(row);
    });
    section.append(list);
  }

  contexts.forEach((context, index) => {
    const details = element('details', 'question-source-context');
    details.open = index === 0;
    const location = context.line_start === context.line_end
      ? t('questions.line', {line: context.line_start})
      : t('questions.line_range', {start: context.line_start, end: context.line_end});
    details.append(
      element('summary', '', `${t('questions.source_fragment')} · ${location}`),
      element('pre', 'question-idf-snippet', context.snippet || '')
    );
    if (context.truncated) details.append(element('small', 'question-context-note', t('questions.context_truncated')));
    section.append(details);
  });
  card.append(section);
}

function questionShell(question) {
  const card = element('article', 'question');
  card.dataset.rootId = question.root_id || '';
  const header = element('header');
  header.append(element('strong', 'question-type', t(`tokens.questions.${question.question_type}`)));
  card.append(header, element('p', '', t(`question_prompts.${question.question_type}`)));
  renderQuestionContext(card, question);
  const rawDetails = element('details', 'raw-question-prompt');
  rawDetails.append(
    element('summary', '', t('questions.raw_prompt')),
    element('small', '', question.prompt),
    element('code', '', question.question_type)
  );
  card.append(rawDetails);
  return card;
}

function candidateLabel(choice) {
  const operation = (choice.operations || [])[0] || {};
  const change = operation.new_value !== undefined
    ? `${operation.field_name || operation.field_index || ''}: ${operation.old_value || '∅'} → ${operation.new_value}`
    : (operation.kind || choice.family || 'candidate');
  return `${localizedProvider(choice.provider)} · ${change}`;
}

function candidateButton(question, choice, label) {
  const button = element('button', 'candidate-choice');
  button.type = 'button';
  button.dataset.token = choice.candidate_id;
  button.append(
    element('strong', '', label || candidateLabel(choice)),
    element('small', '', `${t('questions.confidence')}: ${choice.confidence ?? '—'} · ${t('questions.risk')}: ${localizedCandidateToken('risks', choice.risk)}`)
  );
  button.addEventListener('click', () => answer(question.question_id, {candidate_id: choice.candidate_id}));
  return button;
}

function renderCandidateQuestion(card, question) {
  const grid = element('div', 'choice-grid');
  for (const choice of question.choices || []) grid.append(candidateButton(question, choice));
  card.append(grid);
}

function renderFieldQuestion(card, question) {
  const controls = element('form', 'question-controls');
  const label = element('label');
  label.append(element('span', '', t('questions.field_value')));
  const input = element('input');
  input.name = 'value';
  input.required = true;
  input.value = question.metadata?.current_value || '';
  input.addEventListener('input', () => {
    const preview = card.querySelector('[data-question-after]');
    if (preview) preview.textContent = input.value || t('questions.awaiting_input');
  });
  label.append(input);
  const submit = element('button', 'primary', t('actions.submit_answer'));
  submit.type = 'submit';
  controls.append(label, submit);
  controls.addEventListener('submit', (event) => {
    event.preventDefault();
    answer(question.question_id, {value: input.value});
  });
  card.append(controls);
}

function renderReferenceQuestion(card, question) {
  const controls = element('form', 'question-controls');
  const label = element('label');
  label.append(element('span', '', t('questions.reference')));
  const select = element('select');
  for (const choice of question.choices || []) {
    const option = element('option', '', candidateLabel(choice));
    option.value = choice.candidate_id;
    option.dataset.token = choice.candidate_id;
    select.append(option);
  }
  label.append(select);
  const submit = element('button', 'primary', t('actions.confirm'));
  submit.type = 'submit';
  controls.append(label, submit);
  controls.addEventListener('submit', (event) => {
    event.preventDefault();
    answer(question.question_id, {candidate_id: select.value});
  });
  card.append(controls);
}

function renderObjectQuestion(card, question) {
  const controls = element('form', 'question-controls');
  const label = element('label');
  label.append(element('span', '', t('questions.object')));
  const select = element('select');
  (question.choices || []).forEach((choice, index) => {
    const option = element('option', '', choice.label || `${choice.object_type}: ${choice.object_name}`);
    option.value = String(index);
    select.append(option);
  });
  label.append(select);
  const submit = element('button', 'primary', t('actions.confirm'));
  submit.type = 'submit';
  controls.append(label, submit);
  controls.addEventListener('submit', (event) => {
    event.preventDefault();
    const choice = question.choices[Number(select.value)];
    answer(question.question_id, choice.value || choice);
  });
  card.append(controls);
}

function renderVersionQuestion(card, question) {
  const grid = element('div', 'choice-grid');
  for (const choice of question.choices || []) {
    const operation = (choice.operations || []).find((row) => row.kind === 'update_version');
    grid.append(candidateButton(question, choice, `${t('questions.target_version')}: ${operation?.new_value || choice.family}`));
  }
  card.append(grid);
}

function renderExternalQuestion(card, question) {
  const controls = element('form', 'question-controls');
  const label = element('label');
  label.append(element('span', '', `${t('questions.external_file')}: ${question.metadata?.relative_path || ''}`));
  const input = element('input');
  input.type = 'file';
  input.required = true;
  label.append(input);
  const submit = element('button', 'primary', t('actions.upload_resume'));
  submit.type = 'submit';
  controls.append(label, submit);
  controls.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!input.files[0]) return;
    const body = new FormData();
    body.set('question_id', question.question_id);
    body.set('file', input.files[0]);
    try {
      const summary = await request(`/api/sessions/${state.sessionId}/external-file`, {method: 'POST', body});
      setStatus(summary);
      await loadReport();
    } catch (error) { notice(error.message, true); }
  });
  card.append(controls);
}

function geometryPoints(question) {
  for (const choice of question.choices || []) {
    for (const operation of choice.operations || []) {
      if (Array.isArray(operation.vertices) && operation.vertices.length >= 3) {
        return operation.vertices.map((point) => [Number(point[0]), Number(point[1])]);
      }
    }
  }
  return [[20, 20], [180, 30], [165, 140], [35, 155]];
}

function renderGeometryQuestion(card, question) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('geometry-preview');
  svg.setAttribute('viewBox', '0 0 200 180');
  const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
  const points = geometryPoints(question);
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  const width = Math.max(...xs) - Math.min(...xs) || 1;
  const height = Math.max(...ys) - Math.min(...ys) || 1;
  polygon.setAttribute('points', points.map((point) => `${20 + 160 * (point[0] - Math.min(...xs)) / width},${20 + 140 * (point[1] - Math.min(...ys)) / height}`).join(' '));
  polygon.setAttribute('fill', '#e1f1e9');
  polygon.setAttribute('stroke', '#05785a');
  polygon.setAttribute('stroke-width', '3');
  svg.append(polygon);
  card.append(svg);
  renderCandidateQuestion(card, question);
}

function renderFamilyQuestion(card, question) {
  const controls = element('form', 'question-controls');
  const label = element('label');
  label.append(element('span', '', t('questions.family')));
  const select = element('select');
  for (const token of REPAIR_FAMILIES) {
    const option = element('option', '', t(`tokens.families.${token}`));
    option.value = token;
    option.dataset.token = token;
    select.append(option);
  }
  label.append(select);
  const submit = element('button', 'primary', t('actions.confirm'));
  submit.type = 'submit';
  controls.append(label, submit);
  controls.addEventListener('submit', (event) => {
    event.preventDefault();
    answer(question.question_id, {family: select.value});
  });
  card.append(controls);
}

function renderQuestions(questions) {
  questionBox.replaceChildren();
  if (questions.length) {
    const boundary = element('section', 'question-boundary');
    boundary.append(
      element('strong', '', t('questions.evidence_insufficient')),
      element('p', '', t('questions.validation_remains'))
    );
    if (state.summary?.mode === 'assisted') {
      boundary.append(element('p', '', t('questions.assisted_confirmation')));
    }
    questionBox.append(boundary);
  }
  for (const question of questions) {
    const card = questionShell(question);
    switch (question.question_type) {
      case 'choose_candidate': renderCandidateQuestion(card, question); break;
      case 'enter_field_value': renderFieldQuestion(card, question); break;
      case 'choose_reference': renderReferenceQuestion(card, question); break;
      case 'choose_object': renderObjectQuestion(card, question); break;
      case 'confirm_version': renderVersionQuestion(card, question); break;
      case 'provide_external_file': renderExternalQuestion(card, question); break;
      case 'confirm_geometry': renderGeometryQuestion(card, question); break;
      case 'select_repair_family': renderFamilyQuestion(card, question); break;
      default: card.append(element('p', '', t('questions.unsupported')));
    }
    const decline = element('button', '', t('actions.decline'));
    decline.type = 'button';
    decline.dataset.token = 'decline';
    decline.addEventListener('click', () => answer(question.question_id, 'decline'));
    card.append(decline);
    questionBox.append(card);
  }
  syncInspectorQuestionVisibility(
    workbenchIssueRows().find((row) => row.id === state.selectedIssueId) || null
  );
}

async function answer(questionId, value) {
  try {
    if (state.batchRecordContext) {
      const {batchId, recordId} = state.batchRecordContext;
      await request(`/api/batches/${batchId}/records/${recordId}/answers`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question_id: questionId, value})
      });
      state.batchRecordContext = null;
      state.batchId = batchId;
      state.batchPollGeneration += 1;
      document.querySelector('[data-panel="batch-panel"]').click();
      notice(t('batch.answer_requeued'));
      await pollBatch();
      return;
    }
    const summary = await request(`/api/sessions/${state.sessionId}/answers`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question_id: questionId, value})
    });
    setStatus(summary);
    await loadReport();
  } catch (error) { notice(error.message, true); }
}

function updateModelPreflightAction() {
  const run = $('#run-model-preflight');
  const apply = $('#apply-model-preflight');
  const rollback = $('#rollback-model-preflight');
  if (!run || !apply || !rollback) return;
  const hasChecks = [...document.querySelectorAll('input[name="preflight_check"]')]
    .some((input) => input.checked);
  const canCreateIdfSession = state.sourceKind === 'idf' && Boolean($('#idf-file')?.files?.[0]);
  const hasInput = Boolean(state.sessionId || canCreateIdfSession);
  run.disabled = state.preflightBusy || Boolean(state.busy) || !hasInput || !hasChecks;
  run.setAttribute('aria-busy', String(state.preflightBusy && state.preflightStatus === 'CHECKING'));
  const safeRepairs = Number(state.preflightReport?.summary?.safe_repairs || 0);
  apply.disabled = state.preflightBusy || state.preflightStatus !== 'CHECKED' || safeRepairs < 1;
  rollback.disabled = state.preflightBusy || state.preflightStatus !== 'APPLIED';
}

function preflightMetric(labelKey, value) {
  const node = element('div', 'preflight-metric');
  node.append(element('strong', '', String(value || 0)), element('small', '', t(labelKey)));
  return node;
}

function renderPreflightGroup(kind, plans) {
  const details = element('details', 'preflight-group');
  const heading = element('summary', 'preflight-group-heading');
  const copy = element('span');
  copy.append(
    element('strong', '', t(`preflight.groups.${kind}.title`)),
    element('small', '', t(`preflight.groups.${kind}.help`))
  );
  heading.append(copy, element('em', '', String(plans.length)));
  details.append(heading, element('p', '', t('preflight.open_navigator')));
  return details;
}

function renderModelPreflight() {
  const status = $('#model-preflight-status');
  const summaryBox = $('#model-preflight-summary');
  const groupsBox = $('#model-preflight-groups');
  const apply = $('#apply-model-preflight');
  const rollback = $('#rollback-model-preflight');
  if (!status || !summaryBox || !groupsBox || !apply || !rollback) return;
  status.classList.remove('running', 'ready', 'attention', 'failed');
  const report = state.preflightReport;
  const summary = report?.summary || state.summary?.preflight_summary || {};
  const counts = window.IDFRepairSessionWorkbench.derivePreflightCounts(report || {summary});
  const safe = counts.safe;
  const review = counts.review;
  const excluded = counts.excluded;
  const applied = Number(summary.applied_repairs ?? safe);
  const remainingAfter = Number(summary.audit_findings_after || 0);
  const isApplied = state.preflightStatus === 'APPLIED';
  if (state.preflightStatus === 'CHECKING') {
    status.textContent = t('preflight.running');
    status.classList.add('running');
  } else if (state.preflightStatus === 'APPLIED') {
    status.textContent = t('preflight.applied');
    status.classList.add('ready');
  } else if (state.preflightStatus === 'ROLLED_BACK') {
    status.textContent = t('preflight.rolled_back');
    status.classList.add('attention');
  } else if (state.preflightStatus === 'FAILED') {
    status.classList.add('failed');
  } else if (state.preflightStatus === 'CHECKED') {
    status.textContent = counts.detailsReady && (safe || review || excluded)
      ? t('preflight.checked', {safe, review, excluded})
      : (counts.detailsReady ? t('preflight.clean') : t('preflight.details_loading'));
    status.classList.add(safe ? 'attention' : 'ready');
  } else if (state.sourceKind === 'osm' && state.sessionId) {
    status.textContent = t('preflight.required');
    status.classList.add('attention');
  } else {
    status.textContent = t('preflight.empty');
  }
  summaryBox.replaceChildren();
  groupsBox.replaceChildren();
  if (report || state.preflightStatus === 'APPLIED') {
    const metrics = [
      preflightMetric(isApplied ? 'preflight.applied_repairs' : 'preflight.safe_repairs', isApplied ? applied : safe),
      preflightMetric('preflight.direct_pairs', summary.direct_pair_repairs),
      preflightMetric('preflight.split_groups', summary.split_group_repairs),
      preflightMetric('preflight.resegment_groups', summary.resegmented_overlap_repairs),
      preflightMetric('preflight.air_wall_groups', summary.air_wall_context_repairs),
      preflightMetric(
        isApplied ? 'preflight.remaining_after' : (counts.detailsReady ? 'preflight.review_only' : 'preflight.details_loading'),
        isApplied ? remainingAfter : (counts.detailsReady ? review : '—')
      )
    ];
    if (!isApplied) metrics.push(preflightMetric(
      counts.detailsReady ? 'preflight.excluded_candidates' : 'preflight.details_loading',
      counts.detailsReady ? excluded : '—'
    ));
    summaryBox.append(...metrics);
  }
  const plans = Array.isArray(report?.repair_plans) ? report.repair_plans : [];
  const groups = [
    ['direct', plans.filter((row) => row.safe_to_apply && row.kind === 'reciprocal_surface_pair')],
    ['split', plans.filter((row) => row.safe_to_apply && row.kind === 'split_and_pair')],
    ['resegment', plans.filter((row) => row.safe_to_apply && row.kind === 'resegment_and_pair')],
    ['review', plans.filter((row) => !row.safe_to_apply && row.kind !== 'vertex_snap')],
    ['evidence', plans.filter((row) => !row.safe_to_apply && row.kind === 'vertex_snap')]
  ];
  for (const [kind, rows] of groups) {
    if (rows.length) groupsBox.append(renderPreflightGroup(kind, rows));
  }
  apply.classList.toggle('hidden', state.preflightStatus !== 'CHECKED' || safe < 1);
  rollback.classList.toggle('hidden', state.preflightStatus !== 'APPLIED');
  updateModelPreflightAction();
}

async function loadSessionInputIntoViewer(inputUrl, name) {
  const requestedInputRevision = state.inputRevision;
  const requestedSessionId = state.sessionId;
  const response = await fetch(inputUrl);
  if (!operationStillCurrent(requestedInputRevision, requestedSessionId)) return false;
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const text = await response.text();
  if (!operationStillCurrent(requestedInputRevision, requestedSessionId)) return false;
  window.IDFRepairViewer?.loadText(text, name || 'session.idf');
  return true;
}

function operationStillCurrent(inputRevision, sessionId) {
  return state.inputRevision === inputRevision && state.sessionId === sessionId;
}

async function runModelPreflight() {
  if (state.preflightBusy) return;
  if (!state.sessionId) {
    if (state.sourceKind === 'osm' || !await createSessionForCurrentInput()) return;
  }
  const requestedInputRevision = state.inputRevision;
  const requestedSessionId = state.sessionId;
  const checks = [...document.querySelectorAll('input[name="preflight_check"]:checked')]
    .map((input) => input.value);
  const tolerance = Number($('#preflight-tolerance')?.value || 0.05);
  state.preflightBusy = true;
  state.preflightStatus = 'CHECKING';
  startRunProgress('preflight', 'CHECKING_MODEL');
  $('#model-tools-drawer').open = true;
  renderModelPreflight();
  updatePrimaryAction();
  try {
    const report = await request(`/api/sessions/${state.sessionId}/model-preflight`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({checks, tolerance_m: tolerance})
    });
    if (!operationStillCurrent(requestedInputRevision, requestedSessionId)) return;
    state.preflightReport = report;
    state.preflightApplication = null;
    state.preflightStatus = 'CHECKED';
    state.summary = {...state.summary, preflight_status: 'CHECKED', preflight_summary: report.summary};
    state.auditReport = report.audit || null;
    state.auditSurfaceFilter = null;
    state.selectedAuditFindingId = null;
    renderAudit(state.auditReport);
    renderModelPreflight();
    await loadOsmBridgeForSession(requestedSessionId);
    if (!operationStillCurrent(requestedInputRevision, requestedSessionId)) return;
    await loadSessions();
    if (!operationStillCurrent(requestedInputRevision, requestedSessionId)) return;
    finishRunProgress(true);
  } catch (error) {
    if (!operationStillCurrent(requestedInputRevision, requestedSessionId)) return;
    state.preflightStatus = 'FAILED';
    $('#model-preflight-status').textContent = t('preflight.failed', {reason: error.message});
    notice(error.message, true);
    finishRunProgress(false);
  } finally {
    if (!operationStillCurrent(requestedInputRevision, requestedSessionId)) return;
    state.preflightBusy = false;
    renderModelPreflight();
    updatePrimaryAction();
  }
}

async function applyModelPreflight() {
  if (!state.sessionId || state.preflightBusy) return;
  const requestedInputRevision = state.inputRevision;
  const requestedSessionId = state.sessionId;
  let operationSessionId = requestedSessionId;
  state.preflightBusy = true;
  const planTotal = (state.preflightReport?.repair_plans || [])
    .filter((row) => row.safe_to_apply).length;
  startRunProgress('preflight', 'APPLYING_IDF', {completed: 0, total: planTotal});
  renderModelPreflight();
  try {
    const result = await request(`/api/sessions/${state.sessionId}/model-preflight/apply`, {method: 'POST'});
    if (!operationStillCurrent(requestedInputRevision, requestedSessionId)) return;
    state.preflightApplication = result.application;
    state.report = null;
    state.outputReady = false;
    state.lastCompletedAction = null;
    state.auditReport = null;
    setStatus(result.session);
    operationSessionId = result.session.session_id;
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    state.preflightStatus = 'APPLIED';
    await loadSessionInputIntoViewer(result.input_url, result.session.input_name);
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    await loadOsmBridgeForSession(result.session.session_id);
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    renderIssueNavigator();
    renderModelPreflight();
    await loadSessions();
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    if (state.sourceKind === 'osm') setRunProgressStage('VERIFYING_OSM');
    finishRunProgress(true);
  } catch (error) {
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    $('#model-preflight-status').textContent = t('preflight.apply_failed', {reason: error.message});
    $('#model-preflight-status').classList.add('failed');
    notice(error.message, true);
    finishRunProgress(false);
  } finally {
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    state.preflightBusy = false;
    renderModelPreflight();
    updatePrimaryAction();
  }
}

async function rollbackModelPreflight() {
  if (!state.sessionId || state.preflightBusy) return;
  const requestedInputRevision = state.inputRevision;
  const requestedSessionId = state.sessionId;
  let operationSessionId = requestedSessionId;
  state.preflightBusy = true;
  renderModelPreflight();
  try {
    const result = await request(`/api/sessions/${state.sessionId}/model-preflight/rollback`, {method: 'POST'});
    if (!operationStillCurrent(requestedInputRevision, requestedSessionId)) return;
    state.report = null;
    state.outputReady = false;
    state.lastCompletedAction = null;
    setStatus(result.session);
    operationSessionId = result.session.session_id;
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    await loadSessionInputIntoViewer(result.input_url, result.session.input_name);
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    state.preflightReport = await request(`/api/sessions/${result.session.session_id}/model-preflight`);
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    state.preflightApplication = null;
    state.preflightStatus = 'CHECKED';
    state.auditReport = state.preflightReport.audit || null;
    await loadOsmBridgeForSession(result.session.session_id);
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    renderAudit(state.auditReport);
    renderModelPreflight();
    notice(t('preflight.rolled_back'));
    await loadSessions();
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
  } catch (error) {
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    $('#model-preflight-status').textContent = t('preflight.rollback_failed', {reason: error.message});
    $('#model-preflight-status').classList.add('failed');
    notice(error.message, true);
  } finally {
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    state.preflightBusy = false;
    renderModelPreflight();
    updatePrimaryAction();
  }
}

function updateAuditAction() {
  const button = $('#run-audit');
  if (!button) return;
  const hasInput = Boolean(state.sessionId || $('#idf-file')?.files?.[0]);
  const hasChecks = [...document.querySelectorAll('input[name="audit_check"]')]
    .some((input) => input.checked);
  button.disabled = state.auditBusy || Boolean(state.busy) || !hasInput || !hasChecks;
  button.setAttribute('aria-busy', String(state.auditBusy));
}

function auditRuleText(finding) {
  const title = t(`audit.rules.${finding.rule_id}.title`);
  const summary = t(`audit.rules.${finding.rule_id}.summary`);
  return {
    title: title.startsWith('audit.rules.') ? finding.rule_id : title,
    summary: summary.startsWith('audit.rules.') ? finding.message_id || finding.rule_id : summary
  };
}

function auditSurfaceCard(surface, heading) {
  const card = element('article', 'audit-surface-card');
  card.append(element('strong', '', heading));
  if (!surface) {
    card.append(element('p', 'empty-copy', '—'));
    return card;
  }
  const description = document.createElement('dl');
  const rows = [
    [t('audit.object'), [surface.object_type, surface.name].filter(Boolean).join(' · ')],
    [t('audit.surface_type'), surface.surface_type],
    [t('audit.zone'), [surface.zone, surface.space].filter(Boolean).join(' · ')],
    [t('audit.construction'), surface.construction],
    [t('audit.boundary'), [surface.boundary_condition, surface.boundary_object].filter(Boolean).join(' · ')],
    [t('audit.sun_wind'), [surface.sun_exposure, surface.wind_exposure].filter(Boolean).join(' · ')],
    [t('audit.area'), Number.isFinite(surface.area) ? surface.area.toLocaleString(undefined, {maximumFractionDigits: 5}) : '—'],
    [t('audit.vertices'), String(surface.vertices?.length || 0)]
  ];
  for (const [label, value] of rows) {
    const row = element('div');
    row.append(element('dt', '', label), element('dd', '', value || '—'));
    description.append(row);
  }
  card.append(description);
  return card;
}

function auditCoordinateLines(vertices) {
  return (vertices || []).map((point, index) => (
    `${index + 1}. (${(point || []).map((value) => Number(value).toFixed(9)).join(', ')})`
  )).join('\n');
}

function renderAuditRepairPreview(finding) {
  const preview = finding.repair_preview;
  if (!preview) return null;
  const section = element('section', 'audit-repair-preview');
  section.append(
    element('strong', '', t('audit.preview_title')),
    element('p', '', t(
      preview.direct_reciprocal_pair
        ? 'audit.preview_direct'
        : 'audit.preview_split'
    ))
  );
  const cards = element('div', 'audit-preview-grid');
  for (const surface of preview.surfaces || []) {
    const card = element('article', 'audit-preview-surface');
    card.append(
      element('strong', '', `${surface.zone_name || '—'} · ${surface.surface_name || '—'}`)
    );
    const comparison = element('div', 'audit-before-after');
    const before = surface.before || {};
    const after = surface.after;
    for (const [labelKey, field] of [
      ['audit.boundary', 'boundary_condition'],
      ['audit.boundary_object', 'boundary_object'],
      ['audit.sun_exposure', 'sun_exposure'],
      ['audit.wind_exposure', 'wind_exposure'],
      ['audit.construction', 'construction']
    ]) {
      const row = element('div');
      const afterValue = field === 'construction'
        ? t('audit.construction_unresolved')
        : (after ? after[field] : t('audit.split_required'));
      row.append(
        element('span', '', t(labelKey)),
        element('code', 'before-value', before[field] || '∅'),
        element('span', 'change-arrow', '→'),
        element('code', 'after-value', afterValue || '∅')
      );
      comparison.append(row);
    }
    card.append(
      comparison,
      element('small', '', t('audit.global_coordinates')),
      element('pre', 'audit-coordinate-list', auditCoordinateLines(surface.global_vertices))
    );
    cards.append(card);
  }
  const apply = element('button', 'quiet-button audit-apply-disabled', t('audit.auto_apply_unavailable'));
  apply.type = 'button';
  apply.disabled = true;
  section.append(cards, apply, element('small', '', t('audit.auto_apply_reason')));
  return section;
}

function renderAuditDetail(finding) {
  const box = $('#audit-detail');
  box.replaceChildren();
  if (!finding) {
    box.classList.add('hidden');
    return;
  }
  const copy = auditRuleText(finding);
  const heading = element('div', 'audit-detail-heading');
  heading.append(
    element('span', `audit-severity ${finding.severity}`, t(`audit.severities.${finding.severity}`)),
    element('strong', '', copy.title)
  );
  const grid = element('div', 'audit-detail-grid');
  grid.append(auditSurfaceCard(finding.surface, t('audit.surface')));
  if (finding.paired_surface) {
    grid.append(auditSurfaceCard(finding.paired_surface, t('audit.paired_surface')));
  }
  const preview = renderAuditRepairPreview(finding);
  const raw = element('details');
  raw.append(
    element('summary', '', t('audit.raw_evidence')),
    element('pre', '', JSON.stringify({
      finding_id: finding.finding_id,
      rule_id: finding.rule_id,
      evidence: finding.evidence,
      repair_preview: finding.repair_preview,
      surface: finding.surface,
      paired_surface: finding.paired_surface,
      read_only: finding.read_only,
      automatic_change_authorized: finding.automatic_change_authorized
    }, null, 2))
  );
  box.append(heading, element('p', 'audit-detail-summary', copy.summary), grid);
  if (preview) box.append(preview);
  box.append(raw);
  box.classList.remove('hidden');
}

function filteredAuditFindings() {
  const query = String($('#audit-search')?.value || '').trim().toLowerCase();
  const severity = $('#audit-severity')?.value || 'all';
  const surfaceFilter = String(state.auditSurfaceFilter || '').trim().toLowerCase();
  return (state.auditReport?.findings || []).filter((finding) => {
    if (severity !== 'all' && finding.severity !== severity) return false;
    const surfaceNames = [finding.surface?.name, finding.paired_surface?.name]
      .map((value) => String(value || '').trim().toLowerCase());
    if (surfaceFilter && !surfaceNames.includes(surfaceFilter)) return false;
    if (!query) return true;
    const copy = auditRuleText(finding);
    const haystack = [
      finding.rule_id, copy.title, copy.summary,
      finding.surface?.name, finding.surface?.zone, finding.surface?.space,
      finding.surface?.construction, finding.surface?.boundary_condition,
      finding.paired_surface?.name, finding.paired_surface?.zone,
      finding.paired_surface?.space, finding.paired_surface?.construction
    ].filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(query);
  });
}

function renderAuditFindings() {
  const box = $('#audit-findings');
  const loadMore = $('#audit-load-more');
  const clearSurface = $('#audit-clear-surface');
  if (!box || !loadMore || !clearSurface) return;
  const findings = filteredAuditFindings();
  const visible = findings.slice(0, state.auditRenderLimit);
  box.replaceChildren();
  clearSurface.classList.toggle('hidden', !state.auditSurfaceFilter);
  clearSurface.title = state.auditSurfaceFilter
    ? t('audit.surface_filter', {surface: state.auditSurfaceFilter})
    : '';
  if (!visible.length) {
    box.append(element('p', 'empty-copy', t('audit.no_findings')));
  }
  for (const finding of visible) {
    const copy = auditRuleText(finding);
    const button = element('button', 'audit-finding');
    button.type = 'button';
    button.dataset.findingId = finding.finding_id;
    const active = state.selectedAuditFindingId === finding.finding_id;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
    const body = element('span', 'audit-finding-copy');
    body.append(element('strong', '', copy.title), element('small', '', copy.summary));
    const location = [finding.surface?.zone, finding.surface?.name].filter(Boolean).join(' · ') || '—';
    button.append(
      element('span', `audit-severity ${finding.severity}`, t(`audit.severities.${finding.severity}`)),
      body,
      element('code', 'audit-surface-name', location)
    );
    button.addEventListener('click', () => selectAuditFinding(finding.finding_id));
    box.append(button);
  }
  loadMore.classList.toggle('hidden', visible.length >= findings.length);
  loadMore.textContent = `${t('audit.load_more')} · ${t('audit.showing', {shown: visible.length, total: findings.length})}`;
  const selected = visible.find((finding) => finding.finding_id === state.selectedAuditFindingId);
  if (!selected && state.selectedAuditFindingId) {
    state.selectedAuditFindingId = null;
    renderAuditDetail(null);
  }
}

function selectAuditFinding(findingId, {syncWorkbench = true} = {}) {
  const finding = (state.auditReport?.findings || [])
    .find((row) => row.finding_id === findingId);
  if (!finding) return;
  state.selectedAuditFindingId = findingId;
  if (syncWorkbench) state.selectedIssueId = findingId;
  renderAuditFindings();
  renderAuditDetail(finding);
  const surfaces = [finding.surface, finding.paired_surface].filter(Boolean);
  window.IDFRepairViewer?.focusRoots(surfaces.map((surface, index) => ({
    root_id: `${finding.finding_id}:${index}`,
    object_name: surface.name,
    object_type: surface.object_type,
    family: 'model_audit',
    message: auditRuleText(finding).title
  })));
  if (syncWorkbench) {
    renderIssueNavigator();
    const issue = workbenchIssueRows().find((row) => row.id === findingId) || null;
    showWorkbenchIssueInViewer(issue);
    renderIssueInspector(issue);
    loadIssueContexts(issue);
  }
}

function renderAudit(report = state.auditReport) {
  updateAuditAction();
  if (!report) {
    renderIssueNavigator();
    return;
  }
  const summary = report.summary || {};
  $('#audit-status').textContent = t('audit.summary', {
    surfaces: summary.surfaces_checked || 0,
    errors: summary.errors || 0,
    warnings: summary.warnings || 0,
    review: summary.review || 0
  });
  $('#audit-summary').replaceChildren(
    metricNode(t('audit.surfaces_checked'), String(summary.surfaces_checked || 0)),
    metricNode(t('audit.severities.error'), String(summary.errors || 0)),
    metricNode(t('audit.severities.warning'), String(summary.warnings || 0)),
    metricNode(t('audit.severities.review'), String(summary.review || 0))
  );
  renderAuditFindings();
  renderIssueNavigator();
  if (state.selectedAuditFindingId) {
    renderAuditDetail((report.findings || []).find(
      (finding) => finding.finding_id === state.selectedAuditFindingId
    ));
  }
}

async function runModelAudit() {
  if (!state.sessionId && !await createSessionForCurrentInput()) return;
  const checks = [...document.querySelectorAll('input[name="audit_check"]:checked')]
    .map((input) => input.value);
  state.auditBusy = true;
  updateAuditAction();
  $('#audit-status').textContent = t('audit.running');
  try {
    const report = await request(`/api/sessions/${state.sessionId}/audit`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({checks})
    });
    state.auditReport = report;
    state.auditSurfaceFilter = null;
    state.selectedAuditFindingId = null;
    state.auditRenderLimit = 200;
    renderAudit(report);
  } catch (error) {
    $('#audit-status').textContent = t('audit.run_failed', {reason: error.message});
    notice(error.message, true);
  } finally {
    state.auditBusy = false;
    updateAuditAction();
  }
}

function updateExperimentalAction() {
  const button = $('#run-experimental-preview');
  if (!button) return;
  const hasInput = Boolean(state.sessionId || $('#idf-file')?.files?.[0]);
  const hasMechanism = [...document.querySelectorAll('input[name="experimental_mechanism"]')]
    .some((input) => input.checked);
  button.disabled = state.experimentalBusy || Boolean(state.busy) || !hasInput || !hasMechanism;
  button.setAttribute('aria-busy', String(state.experimentalBusy));
}

function experimentalMechanismCopy(mechanismId) {
  const name = t(`experimental.mechanisms.${mechanismId}.name`);
  const status = t(`experimental.mechanisms.${mechanismId}.status`);
  return {
    name: name.startsWith('experimental.mechanisms.') ? mechanismId : name,
    status: status.startsWith('experimental.mechanisms.') ? '—' : status
  };
}

function experimentalPreviewRows() {
  return (state.experimentalReport?.mechanisms || []).flatMap((mechanism) =>
    (mechanism.previews || []).map((preview) => ({...preview, mechanism_id: mechanism.mechanism_id}))
  );
}

function filteredExperimentalPreviews() {
  const query = String($('#experimental-search')?.value || '').trim().toLowerCase();
  const surfaceFilter = String(state.experimentalSurfaceFilter || '').trim().toLowerCase();
  return experimentalPreviewRows().filter((preview) => {
    const names = [preview.surface?.name, preview.paired_surface?.name]
      .map((value) => String(value || '').trim().toLowerCase());
    if (surfaceFilter && !names.includes(surfaceFilter)) return false;
    if (!query) return true;
    const mechanism = experimentalMechanismCopy(preview.mechanism_id);
    return [
      preview.mechanism_id, mechanism.name, preview.preview_kind,
      preview.surface?.name, preview.surface?.zone,
      preview.paired_surface?.name, preview.paired_surface?.zone
    ].filter(Boolean).join(' ').toLowerCase().includes(query);
  });
}

function experimentalJsonDetails(label, value) {
  const details = element('details');
  details.append(
    element('summary', '', label),
    element('pre', '', JSON.stringify(value ?? {}, null, 2))
  );
  return details;
}

function renderExperimentalCoordinateChange(operation) {
  if (!operation || (!operation.before && !operation.after)) return null;
  const section = element('section', 'experimental-coordinate-change');
  section.append(element('strong', '', t('experimental.global_change')));
  const grid = element('div', 'experimental-coordinate-grid');
  const normalize = (value) => {
    if (!Array.isArray(value)) return [];
    return Array.isArray(value[0]) ? value : [value];
  };
  for (const [labelKey, value, className] of [
    ['experimental.before_coordinates', operation.before, 'before'],
    ['experimental.after_coordinates', operation.after, 'after']
  ]) {
    const card = element('article', className);
    card.append(
      element('span', '', t(labelKey)),
      element('pre', '', auditCoordinateLines(normalize(value)))
    );
    grid.append(card);
  }
  section.append(grid);
  return section;
}

function renderExperimentalDetail(preview) {
  const box = $('#experimental-preview-detail');
  box.replaceChildren();
  if (!preview) {
    box.classList.add('hidden');
    return;
  }
  const mechanism = experimentalMechanismCopy(preview.mechanism_id);
  const heading = element('div', 'experimental-detail-heading');
  heading.append(
    element('strong', '', mechanism.name),
    element('span', 'experimental-status disabled', t('experimental.not_authorized'))
  );
  const surfaceGrid = element('div', 'experimental-detail-grid');
  if (preview.surface) surfaceGrid.append(auditSurfaceCard(preview.surface, t('experimental.surface')));
  if (preview.paired_surface) {
    surfaceGrid.append(auditSurfaceCard(preview.paired_surface, t('experimental.paired_surface')));
  }
  const jsonGrid = element('div', 'experimental-json-grid');
  jsonGrid.append(
    experimentalJsonDetails(t('experimental.operation'), preview.preview_operation),
    experimentalJsonDetails(t('experimental.evidence'), preview.evidence),
    experimentalJsonDetails(t('experimental.shadow_validation'), preview.shadow_validation)
  );
  box.append(heading, surfaceGrid);
  const coordinates = renderExperimentalCoordinateChange(preview.preview_operation);
  if (coordinates) box.append(coordinates);
  box.append(jsonGrid, experimentalJsonDetails(t('experimental.raw'), preview));
  box.classList.remove('hidden');
}

function renderExperimentalResults() {
  const box = $('#experimental-results');
  const loadMore = $('#experimental-load-more');
  const clearSurface = $('#experimental-clear-surface');
  if (!box || !loadMore || !clearSurface) return;
  const toggle = $('#experimental-toggle-results');
  const expanded = state.experimentalResultsExpanded;
  box.classList.toggle('hidden', !expanded);
  $('#experimental-preview-detail').classList.toggle('results-hidden', !expanded);
  toggle.setAttribute('aria-expanded', String(expanded));
  toggle.textContent = t(expanded ? 'experimental.hide_results' : 'experimental.show_results');
  const filtered = filteredExperimentalPreviews();
  const visible = filtered.slice(0, state.experimentalRenderLimit);
  const visibleIds = new Set(visible.map((preview) => preview.preview_id));
  box.replaceChildren();
  clearSurface.classList.toggle('hidden', !state.experimentalSurfaceFilter);
  clearSurface.title = state.experimentalSurfaceFilter
    ? t('experimental.surface_filter', {surface: state.experimentalSurfaceFilter})
    : '';
  for (const mechanism of state.experimentalReport?.mechanisms || []) {
    const copy = experimentalMechanismCopy(mechanism.mechanism_id);
    const card = element('article', 'experimental-mechanism');
    const header = element('div', 'experimental-mechanism-header');
    header.append(
      element('strong', '', copy.name),
      element('span', `experimental-status ${mechanism.support_status === 'disabled' ? 'disabled' : 'evidence'}`, copy.status)
    );
    const meta = element('div', 'experimental-mechanism-meta');
    meta.append(
      element('span', 'pill', `${t('experimental.registry_status')} · ${mechanism.registry_entry_id}`),
      element('span', 'pill', `${t('experimental.preview_count')} · ${mechanism.preview_count}`),
      element('span', 'pill disabled', t('experimental.not_authorized'))
    );
    const note = state.locale === 'en' ? mechanism.notes_en : mechanism.notes_zh;
    card.append(header, meta, element('p', 'experimental-mechanism-note', note || '—'));
    const previews = (mechanism.previews || []).filter((preview) => visibleIds.has(preview.preview_id));
    if (!previews.length) {
      card.append(element('p', 'empty-copy', t('experimental.no_mechanism_previews')));
    } else {
      const list = element('div', 'experimental-preview-list');
      for (const preview of previews) {
        const button = element('button', 'experimental-preview');
        button.type = 'button';
        button.dataset.previewId = preview.preview_id;
        const active = state.selectedExperimentalPreviewId === preview.preview_id;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
        button.append(
          element('span', `experimental-status ${preview.preview_kind === 'candidate' ? 'disabled' : 'evidence'}`, t(preview.preview_kind === 'candidate' ? 'experimental.candidate_preview' : 'experimental.evidence_preview')),
          element('strong', '', preview.surface?.name || preview.preview_id),
          element('code', '', [preview.surface?.zone, preview.paired_surface?.name].filter(Boolean).join(' · ') || '—')
        );
        button.addEventListener('click', () => selectExperimentalPreview(preview.preview_id));
        list.append(button);
      }
      card.append(list);
    }
    box.append(card);
  }
  if (!state.experimentalReport?.mechanisms?.length) {
    box.append(element('p', 'empty-copy', t('experimental.no_results')));
  }
  loadMore.classList.toggle('hidden', !expanded || visible.length >= filtered.length);
  loadMore.textContent = `${t('experimental.load_more')} · ${t('experimental.showing', {shown: visible.length, total: filtered.length})}`;
  const selected = visible.find((preview) => preview.preview_id === state.selectedExperimentalPreviewId);
  if (!selected && state.selectedExperimentalPreviewId) {
    state.selectedExperimentalPreviewId = null;
    renderExperimentalDetail(null);
  }
}

function selectExperimentalPreview(previewId, {syncWorkbench = true} = {}) {
  const preview = experimentalPreviewRows().find((row) => row.preview_id === previewId);
  if (!preview) return;
  state.selectedExperimentalPreviewId = previewId;
  if (syncWorkbench) state.selectedIssueId = previewId;
  renderExperimentalResults();
  renderExperimentalDetail(preview);
  const surfaces = [preview.surface, preview.paired_surface].filter(Boolean);
  window.IDFRepairViewer?.focusRoots(surfaces.map((surface, index) => ({
    root_id: `${preview.preview_id}:${index}`,
    object_name: surface.name,
    object_type: surface.object_type,
    family: 'experimental_geometry',
    message: experimentalMechanismCopy(preview.mechanism_id).name
  })));
  if (syncWorkbench) {
    renderIssueNavigator();
    const issue = workbenchIssueRows().find((row) => row.id === previewId) || null;
    showWorkbenchIssueInViewer(issue);
    renderIssueInspector(issue);
    loadIssueContexts(issue);
  }
}

function renderExperimental(report = state.experimentalReport) {
  updateExperimentalAction();
  if (!report) {
    renderIssueNavigator();
    return;
  }
  const previews = experimentalPreviewRows();
  $('#experimental-status').textContent = t('experimental.summary', {
    surfaces: report.surfaces_scanned || 0,
    mechanisms: (report.mechanisms || []).length,
    previews: previews.length
  });
  $('#experimental-summary').replaceChildren(
    metricNode(t('experimental.surfaces_scanned'), String(report.surfaces_scanned || 0)),
    metricNode(t('experimental.mechanisms_selected'), String((report.mechanisms || []).length)),
    metricNode(t('experimental.preview_count'), String(previews.length))
  );
  renderExperimentalResults();
  renderIssueNavigator();
  if (state.selectedExperimentalPreviewId) {
    renderExperimentalDetail(previews.find(
      (preview) => preview.preview_id === state.selectedExperimentalPreviewId
    ));
  }
}

async function runExperimentalPreview() {
  if (!state.sessionId && !await createSessionForCurrentInput()) return;
  const mechanisms = [...document.querySelectorAll('input[name="experimental_mechanism"]:checked')]
    .map((input) => input.value);
  state.experimentalBusy = true;
  updateExperimentalAction();
  $('#experimental-status').textContent = t('experimental.running');
  try {
    const report = await request(`/api/sessions/${state.sessionId}/experimental/geometry-preview`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        mechanisms,
        snap_absolute_m: Number($('#snap-absolute-m').value),
        snap_relative: Number($('#snap-relative').value)
      })
    });
    state.experimentalReport = report;
    state.experimentalSurfaceFilter = null;
    state.selectedExperimentalPreviewId = null;
    state.experimentalRenderLimit = 100;
    state.experimentalResultsExpanded = true;
    renderExperimental(report);
  } catch (error) {
    $('#experimental-status').textContent = t('experimental.run_failed', {reason: error.message});
    notice(error.message, true);
  } finally {
    state.experimentalBusy = false;
    updateExperimentalAction();
  }
}

function updateOsmAction() {
  syncSourceKindUi({restoreIdfMode: false});
}

function renderOsmCapability() {
  const box = $('#osm-capability');
  if (!box) return;
  const capability = state.osmCapability;
  box.classList.remove('available', 'unavailable');
  if (!capability) {
    box.textContent = t('osm.checking');
    updateOsmAction();
    return;
  }
  const available = Boolean(capability.diagnostic_bridge_available);
  box.classList.add(available ? 'available' : 'unavailable');
  box.textContent = available
    ? t('osm.available', {
      version: capability.openstudio_version || '—',
      energyplus: capability.energyplus_version || '—'
    })
    : t('osm.unavailable');
  updateOsmAction();
}

function osmMappingRows(report) {
  return [
    ...(report?.mappings || []),
    ...(report?.diagnostic_mappings || []),
    ...(report?.model_audit?.mapped_findings || [])
  ];
}

function focusOsmMapping(row) {
  const original = row.original || row;
  const exact = original.mapping_status === 'MAPPED_EXACT'
    || original.mapping_status === 'EXPLICIT_EXACT_TYPE_NAME';
  if (!exact) return;
  const derivedType = row.derivedType || original.derived_idf_object?.type
    || original.derived_idf_object_type || '';
  const derivedName = row.derivedName || original.derived_idf_object?.name
    || original.derived_idf_object_name || '';
  if (!['buildingsurface:detailed', 'fenestrationsurface:detailed']
    .includes(String(derivedType).toLowerCase())) return;
  window.IDFRepairViewer?.focusRoots([{
    root_id: original.finding_id || original.mapping_id || 'osm-mapping',
    object_name: derivedName,
    object_type: derivedType,
    family: original.family || 'osm_bridge',
    message: t('osm.mapped')
  }]);
}

function renderOsmTimeline(summary) {
  for (const step of summary.timeline) {
    const item = document.querySelector(`[data-osm-step="${step.key}"]`);
    if (!item) continue;
    item.classList.remove('pending', 'complete', 'attention');
    item.classList.add(step.state);
    const status = item.querySelector('em');
    status.textContent = t(`osm.timeline.states.${step.state}`, {
      count: step.count || 0,
      status: step.status || ''
    });
    status.removeAttribute('data-i18n');
  }
}

function resetOsmTimeline() {
  document.querySelectorAll('.osm-timeline-step').forEach((item) => {
    item.classList.remove('complete', 'attention');
    item.classList.add('pending');
    const status = item.querySelector('em');
    status.textContent = t('osm.timeline.waiting');
  });
}

function renderOsmAdaptationFacts(summary) {
  const box = $('#osm-adaptation-facts');
  box.replaceChildren(
    element('strong', '', t('osm.derived_adaptation', {count: summary.derivedAdaptationCount})),
    element('strong', '', t('osm.source_unchanged')),
    element('strong', '', t('osm.equivalence_unclaimed')),
    element('p', '', t('osm.diagnostic_adaptation_help', {count: summary.derivedAdaptationCount}))
  );
  box.classList.remove('hidden');
}

function renderOsmValidity(report) {
  const section = $('#osm-validity-section');
  const box = $('#osm-validity-errors');
  const finalValidity = report?.model_validity?.final || report?.model_validity?.minimal;
  const rows = finalValidity?.errors || [];
  box.replaceChildren();
  section.classList.toggle('hidden', !rows.length);
  const visible = rows.slice(0, state.osmValidityLimit);
  for (const source of visible) {
    const issue = window.IDFRepairOsmTools.classifyValidityIssue(source);
    const item = element('article', 'osm-validity-error');
    const heading = element('div', 'osm-validity-heading');
    heading.append(
      element('strong', '', t(`osm.validity_categories.${issue.category}`)),
      element('span', '', issue.where)
    );
    const raw = element('details', 'osm-validity-raw');
    raw.append(
      element('summary', '', t('osm.raw_validity')),
      element('pre', '', issue.raw)
    );
    item.append(
      heading,
      element('p', '', t(`osm.validity_meanings.${issue.category}`)),
      raw
    );
    box.append(item);
  }
  const more = $('#osm-validity-more');
  more.classList.toggle('hidden', visible.length >= rows.length);
  more.textContent = t('osm.show_more_count', {shown: visible.length, total: rows.length});
  if (finalValidity?.errors_truncated) {
    box.append(element('p', 'osm-bounded-note', t('osm.validity_bounded', {
      shown: visible.length, total: finalValidity?.error_count || rows.length
    })));
  }
}

function renderOsmMappings(report) {
  const box = $('#osm-mappings');
  const section = $('#osm-mapping-section');
  if (!box) return;
  box.replaceChildren();
  if (!report) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');
  const rows = osmMappingRows(report);
  const filtered = window.IDFRepairOsmTools.filterOsmMappings(
    rows, state.osmMappingQuery, state.osmMappingLimit
  );
  $('#osm-mapping-summary').textContent = filtered.total
    ? t('osm.mapping_showing', {
      shown: filtered.rows.length, matched: filtered.matched, total: filtered.total
    })
    : t('osm.no_findings');
  for (const row of filtered.rows) {
    const tr = document.createElement('tr');
    tr.className = row.mapped ? 'mapped' : 'unsupported';
    const status = document.createElement('td');
    status.append(element('span', 'osm-mapping-status', t(row.mapped ? 'osm.mapped' : 'osm.unsupported')));
    const source = document.createElement('td');
    source.append(
      element('strong', '', row.osmName || '—'),
      element('small', '', [row.osmType, row.osmHandle].filter(Boolean).join(' · ') || '—')
    );
    const derived = document.createElement('td');
    const canFocus = row.mapped && ['buildingsurface:detailed', 'fenestrationsurface:detailed']
      .includes(row.derivedType.toLowerCase());
    if (canFocus) {
      const button = element('button', 'osm-mapping-focus', row.derivedName || '—');
      button.type = 'button';
      button.title = t('osm.focus_derived');
      button.addEventListener('click', () => focusOsmMapping(row));
      derived.append(button);
    } else {
      derived.append(element('strong', '', row.derivedName || '—'));
    }
    derived.append(element('small', '', row.derivedType || row.reason || t('osm.candidate_disabled')));
    tr.append(status, source, derived);
    box.append(tr);
  }
  const more = $('#osm-mapping-more');
  more.classList.toggle('hidden', !(filtered.rows.length < filtered.matched));
  more.textContent = t('osm.show_more_count', {shown: filtered.rows.length, total: filtered.matched});
}

function osmDownloadLink(labelKey, url, filename) {
  const link = element('a', 'button-link', t(labelKey));
  link.href = url;
  link.download = filename;
  return link;
}

function renderOsmDownloads(result) {
  const box = $('#osm-downloads');
  if (!box) return;
  box.replaceChildren();
  if (!result) {
    box.classList.add('hidden');
    return;
  }
  const sourceName = result.bridge?.source_name || 'source.osm';
  const links = [
    element('strong', '', t('osm.downloads')),
    osmDownloadLink('osm.download_source', result.source_osm_url, sourceName),
    osmDownloadLink(
      'osm.download_derived', result.derived_idf_url,
      `${sourceName.replace(/\.osm$/i, '')}-derived.idf`
    ),
    osmDownloadLink('osm.download_report', result.bridge_report_url, 'osm-bridge-report.json')
  ];
  if (result.osm_download_url) {
    links.push(osmDownloadLink(
      'osm.download_repaired', result.osm_download_url,
      `${sourceName.replace(/\.osm$/i, '')}-repaired.osm`
    ));
  }
  if (result.osm_writeback_report_url) {
    links.push(osmDownloadLink(
      'osm.download_writeback_report', result.osm_writeback_report_url,
      'osm-writeback-verification.json'
    ));
  }
  box.append(...links);
  box.classList.remove('hidden');
}

function renderOsmBridge() {
  renderOsmCapability();
  const report = state.osmReport;
  if (!report) {
    resetOsmTimeline();
    return;
  }
  $('#osm-bridge').classList.remove('hidden');
  $('#osm-bridge').open = true;
  const summary = window.IDFRepairOsmTools.summarizeOsmReport(report);
  const mappingSummary = report.mapping_summary || {};
  const diagnostics = Number(mappingSummary.diagnostics || 0);
  const mapped = Number(mappingSummary.diagnostics_mapped_exact || 0);
  $('#osm-status').textContent = t('osm.complete', {
    status: report.diagnostic_status || '—', mapped, diagnostics
  });
  $('#osm-status').classList.remove('running');
  renderOsmTimeline(summary);
  $('#osm-summary').replaceChildren(
    metricNode(t('osm.openstudio'), report.openstudio_capability?.openstudio_version || '—'),
    metricNode(
      t('osm.derived_runtime'),
      `${report.derived_idf_version || '—'} / ${report.derived_runtime_version || '—'}`
    ),
    metricNode(t('osm.validity_issues'), String(summary.validityErrors)),
    metricNode(t('osm.diagnostic_mappings'), `${mapped}/${diagnostics}`)
  );
  renderOsmAdaptationFacts(summary);
  renderOsmValidity(report);
  renderOsmMappings(report);
  renderOsmDownloads(state.osmResult);
  $('#osm-report').textContent = JSON.stringify(report, null, 2);
  $('#osm-technical').classList.remove('hidden');
}

async function runOsmDiagnostic() {
  const file = state.activeModelFile || $('#osm-file')?.files?.[0];
  if (!file || state.osmBusy) return;
  if (state.sourceKind !== 'osm') return;
  const requestedInputRevision = state.inputRevision;
  const requestedSessionId = state.sessionId;
  let operationSessionId = requestedSessionId;
  state.osmBusy = true;
  startRunProgress('osm', 'WRITING_OSM');
  state.osmResult = null;
  state.osmReport = null;
  state.osmMappingQuery = '';
  state.osmMappingLimit = 50;
  state.osmValidityLimit = 50;
  $('#osm-summary').replaceChildren();
  $('#osm-adaptation-facts').replaceChildren();
  $('#osm-adaptation-facts').classList.add('hidden');
  $('#osm-validity-section').classList.add('hidden');
  $('#osm-validity-errors').replaceChildren();
  $('#osm-mapping-section').classList.add('hidden');
  $('#osm-mappings').replaceChildren();
  $('#osm-mapping-summary').textContent = '';
  $('#osm-mapping-search').value = '';
  $('#osm-validity-more').classList.add('hidden');
  $('#osm-mapping-more').classList.add('hidden');
  resetOsmTimeline();
  $('#osm-downloads').classList.add('hidden');
  $('#osm-technical').classList.add('hidden');
  $('#osm-status').classList.add('running');
  $('#osm-status').textContent = t('osm.running');
  updateOsmAction();
  try {
    const body = new FormData();
    const osmUploadName = /\.osm$/i.test(file.name)
      ? file.name
      : `${file.name.replace(/\.[^.]+$/i, '') || 'model'}.osm`;
    body.set('osm_file', file, osmUploadName);
    const weather = $('#epw-file')?.files?.[0];
    if (weather) body.set('epw', weather, weather.name);
    for (const dependency of $('#dependency-files')?.files || []) {
      body.append('dependencies', dependency, dependency.name);
    }
    const result = await request('/api/osm/import', {method: 'POST', body});
    if (!operationStillCurrent(requestedInputRevision, requestedSessionId)) return;
    state.osmResult = result;
    state.osmReport = result.bridge;
    state.sessionId = result.session.session_id;
    state.lastCompletedAction = null;
    state.outputReady = false;
    setStatus(result.session);
    operationSessionId = result.session.session_id;
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    state.preflightStatus = 'REQUIRED';
    state.preflightReport = null;
    $('#model-tools-drawer').open = true;
    renderModelPreflight();
    renderOsmBridge();
    const derived = await fetch(result.derived_idf_url);
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    if (derived.ok) {
      const derivedText = await derived.text();
      if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
      window.IDFRepairViewer?.loadText(
        derivedText,
        `${osmUploadName.replace(/\.osm$/i, '')}-derived.idf`
      );
    }
    await loadSessions();
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    $('#model-preflight-panel').scrollIntoView({behavior: 'smooth', block: 'center'});
    finishRunProgress(true);
  } catch (error) {
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    $('#osm-status').classList.remove('running');
    $('#osm-status').textContent = t('osm.failed', {reason: error.message});
    finishRunProgress(false);
    notice(error.message, true);
  } finally {
    if (!operationStillCurrent(requestedInputRevision, operationSessionId)) return;
    state.osmBusy = false;
    updatePrimaryAction();
  }
}

function formatBytes(value) {
  const bytes = Math.max(0, Number(value || 0));
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let amount = bytes;
  let unit = -1;
  do {
    amount /= 1024;
    unit += 1;
  } while (amount >= 1024 && unit < units.length - 1);
  return `${amount.toFixed(amount >= 10 ? 1 : 2)} ${units[unit]}`;
}

function formatDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value || 0)));
  if (seconds < 60) return t('batch.duration_seconds', {seconds});
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t('batch.duration_minutes', {minutes});
  return t('batch.duration_hours_minutes', {
    hours: Math.floor(minutes / 60),
    minutes: minutes % 60
  });
}

function batchEntryPrecheck(entry) {
  const pathMatches = state.batchEntries.filter((row) => row.logicalPath === entry.logicalPath);
  const hintMatches = entry.duplicateHintKey
    ? state.batchEntries.filter((row) => (
        row.duplicateHintKey === entry.duplicateHintKey && row.isIdf
      ))
    : [];
  if (!entry.readable) return {key: 'unreadable', level: 'error', eligible: false};
  if (entry.size > 50 * 1024 * 1024) return {key: 'too_large', level: 'error', eligible: false};
  if (pathMatches.length > 1) return {key: 'duplicate_path', level: 'error', eligible: false};
  if (entry.isSupport) return {key: 'supporting_file', level: 'ready', eligible: true};
  if (entry.isZip) return {key: 'zip', level: 'warning', eligible: true};
  const selectedRuntime = state.runtimes.find(
    (runtime) => runtime.runtime_id === $('#batch-runtime-select')?.value
  );
  if (entry.version && selectedRuntime && !window.IDFRepairBatch.versionsMatch(
    entry.version,
    selectedRuntime.version
  )) {
    return {key: 'runtime_mismatch', level: 'warning', eligible: true};
  }
  if (hintMatches.length > 1) return {key: 'possible_duplicate', level: 'warning', eligible: true};
  return {key: 'ready', level: 'ready', eligible: true};
}

function selectBatchRuntimeForEntries() {
  const select = $('#batch-runtime-select');
  if (!select || !window.IDFRepairBatch) return;
  const declaredVersions = [...new Set(
    state.batchEntries
      .filter((entry) => entry.isIdf && entry.readable && entry.version)
      .map((entry) => entry.version)
  )];
  if (declaredVersions.length !== 1) return;
  const runtimeId = window.IDFRepairBatch.runtimeIdForVersion(
    declaredVersions[0],
    state.runtimes
  );
  if (runtimeId) select.value = runtimeId;
}

async function appendBatchFiles(files, sourceKind = 'files') {
  for (const file of [...files]) {
    const rawPath = sourceKind === 'folder' && file.webkitRelativePath
      ? file.webkitRelativePath
      : file.name;
    let logicalPath;
    try {
      logicalPath = window.IDFRepairBatch.normalizeLogicalPath(rawPath);
    } catch (_error) {
      logicalPath = file.name || `invalid-${state.batchEntries.length + 1}`;
    }
    const lower = logicalPath.toLowerCase();
    const identity = window.IDFRepairBatchWorkbench.lightweightFileIdentity(file, logicalPath);
    const entry = {
      key: `${Date.now()}-${state.batchEntries.length}-${file.name}`,
      file,
      ...identity,
      isIdf: lower.endsWith('.idf'),
      isZip: lower.endsWith('.zip'),
      isSupport: !lower.endsWith('.idf') && !lower.endsWith('.zip'),
      readable: true,
      version: null
    };
    try {
      if (entry.isIdf) {
        entry.version = window.IDFRepairBatch.idfVersionForText(
          await file.slice(0, 128 * 1024).text()
        );
      }
    } catch (_error) {
      entry.readable = false;
    }
    state.batchEntries.push(entry);
  }
  selectBatchRuntimeForEntries();
  renderBatchPreview();
}

function batchMetricNode(label, value) {
  const node = element('div', 'batch-metric');
  node.append(element('span', '', label), element('strong', '', String(value)));
  return node;
}

function batchSummary() {
  return window.IDFRepairBatch.summarizeBatchFiles(state.batchEntries.map((entry) => ({
    logicalPath: entry.logicalPath,
    size: entry.size,
    duplicateHintKey: entry.duplicateHintKey,
    readable: entry.readable,
    version: entry.version,
    isZip: entry.isZip
  })));
}

function updateBatchStartState() {
  const button = $('#batch-start');
  if (!button) return;
  const checks = state.batchEntries.map(batchEntryPrecheck);
  const eligible = checks.filter((row) => row.eligible).length;
  const totalSize = state.batchEntries.reduce((total, row) => total + row.size, 0);
  const hardFailure = state.batchEntries.length > 5000
    || totalSize > 2 * 1024 * 1024 * 1024
    || checks.some((row) => row.key === 'duplicate_path');
  button.disabled = Boolean(button.dataset.busy)
    || !eligible
    || !$('#batch-runtime-select')?.value
    || hardFailure;
}

function renderBatchPreview() {
  const summaryBox = $('#batch-preview-summary');
  const rowsBox = $('#batch-preview-rows');
  if (!summaryBox || !rowsBox || !window.IDFRepairBatch) return;
  const summary = batchSummary();
  summaryBox.replaceChildren(
    batchMetricNode(t('batch.metrics.found'), summary.totalIdfs),
    batchMetricNode(t('batch.metrics.total_size'), formatBytes(summary.totalSize)),
    batchMetricNode(t('batch.metrics.depth'), summary.maxDepth),
    batchMetricNode(t('batch.metrics.duplicates'), summary.duplicateContent),
    batchMetricNode(t('batch.metrics.unreadable'), summary.unreadable),
    batchMetricNode(t('batch.metrics.invalid'), summary.invalidExtension)
  );
  rowsBox.replaceChildren();
  for (const entry of state.batchEntries) {
    const check = batchEntryPrecheck(entry);
    const row = element('div', 'batch-preview-row');
    row.setAttribute('role', 'row');
    const remove = element('button', '', t('batch.remove'));
    remove.type = 'button';
    remove.addEventListener('click', () => {
      state.batchEntries = state.batchEntries.filter((item) => item.key !== entry.key);
      renderBatchPreview();
    });
    row.append(
      element('span', 'logical-path', entry.logicalPath),
      element('span', '', formatBytes(entry.size)),
      element('span', '', entry.isZip
        ? 'ZIP'
        : entry.isSupport ? t('batch.supporting_file') : (entry.version || t('batch.version_unknown'))),
      element('span', `batch-precheck ${check.level}`, t(`batch.prechecks.${check.key}`)),
      remove
    );
    rowsBox.append(row);
  }
  updateBatchStartState();
}

function countBatchState(snapshot, stateName) {
  return Number(snapshot?.counts?.[stateName] || 0);
}

function applyBatchLayout() {
  const workbench = $('.batch-workbench');
  const preparation = $('#batch-preparation');
  const toggle = $('#batch-preparation-toggle');
  if (!workbench || !preparation || !toggle || !window.IDFRepairBatchWorkbench) return;
  const layout = window.IDFRepairBatchWorkbench.deriveBatchLayout(
    state.batchSnapshot,
    window.innerWidth
  );
  workbench.classList.toggle('batch-results-first', layout.resultsFirst);
  preparation.classList.toggle('collapsed', !state.batchPreparationExpanded);
  toggle.setAttribute('aria-expanded', String(state.batchPreparationExpanded));
  const label = toggle.querySelector('.batch-preparation-toggle-label');
  if (label) {
    const key = state.batchPreparationExpanded ? 'batch.hide_preparation' : 'batch.show_preparation';
    label.textContent = t(key);
    label.dataset.i18n = key;
  }
}

function batchRecordField(label, value, className = '') {
  const node = element('span', `batch-record-field ${className}`.trim(), value);
  node.dataset.label = label;
  node.setAttribute('role', 'cell');
  return node;
}

function updateBatchSelectionActions() {
  const eligibleIds = new Set(
    state.batchRecords
      .filter((row) => window.IDFRepairBatchWorkbench?.isRecordRetryEligible(row))
      .map((row) => row.record_id)
  );
  for (const recordId of [...state.batchSelectedRecordIds]) {
    if (!eligibleIds.has(recordId)) state.batchSelectedRecordIds.delete(recordId);
  }
  const count = state.batchSelectedRecordIds.size;
  const summary = $('#batch-selected-summary');
  summary.textContent = count
    ? t('batch.selected_count', {count})
    : t('batch.none_selected');
  summary.removeAttribute('data-i18n');
  const terminal = window.IDFRepairBatch.isBatchTerminal(state.batchSnapshot?.status);
  $('#batch-retry-selected').disabled = !terminal || count === 0;
}

function renderBatchCounts(snapshot) {
  const completed = Number(snapshot?.progress?.completed || 0);
  const total = Number(snapshot?.progress?.total || 0);
  const failed = ['FAILED', 'SEARCH_EXHAUSTED', 'CANCELLED']
    .reduce((sum, key) => sum + countBatchState(snapshot, key), 0);
  $('#batch-counts').replaceChildren(
    batchMetricNode(t('batch.counts.repaired'), countBatchState(snapshot, 'REPAIRED')),
    batchMetricNode(t('batch.counts.valid'), countBatchState(snapshot, 'VALID')),
    batchMetricNode(t('batch.counts.action_required'), countBatchState(snapshot, 'NEEDS_INPUT')),
    batchMetricNode(t('batch.counts.unsupported'), countBatchState(snapshot, 'UNSUPPORTED')),
    batchMetricNode(t('batch.counts.failed'), failed),
    batchMetricNode(t('batch.counts.remaining'), Math.max(0, total - completed))
  );
}

function renderBatchRecords() {
  const box = $('#batch-records');
  if (!box || !window.IDFRepairBatch || !window.IDFRepairBatchWorkbench) return;
  const filtered = window.IDFRepairBatch.filterBatchRecords(
    state.batchRecords,
    $('#batch-filter')?.value || 'all'
  );
  const records = window.IDFRepairBatchWorkbench.sortBatchRecords(filtered, {
    query: $('#batch-record-search')?.value || '',
    sortBy: $('#batch-record-sort')?.value || 'path',
    direction: $('#batch-sort-direction')?.dataset.direction || 'asc'
  });
  box.replaceChildren();
  if (!records.length) {
    box.append(element('p', 'empty-copy', t('batch.empty_records')));
    updateBatchSelectionActions();
    return;
  }
  const runtime = state.batchSnapshot?.energyplus_version || state.runtimes.find(
    (row) => row.runtime_id === $('#batch-runtime-select')?.value
  )?.version || '—';
  for (const record of records) {
    const preview = state.batchEntries.find((entry) => entry.logicalPath === record.logical_name);
    const row = element('div', 'batch-record-row');
    row.setAttribute('role', 'row');
    const selectionCell = element('div', 'batch-selection-cell');
    selectionCell.dataset.label = t('batch.retry_selection');
    selectionCell.setAttribute('role', 'cell');
    const status = element('div', 'batch-status-cell');
    status.dataset.label = t('batch.status');
    status.setAttribute('role', 'cell');
    if (window.IDFRepairBatchWorkbench.isRecordRetryEligible(record)) {
      const selection = document.createElement('input');
      selection.type = 'checkbox';
      selection.checked = state.batchSelectedRecordIds.has(record.record_id);
      selection.setAttribute('aria-label', t('batch.select_for_retry', {path: record.logical_name}));
      selection.addEventListener('change', () => {
        if (selection.checked) state.batchSelectedRecordIds.add(record.record_id);
        else state.batchSelectedRecordIds.delete(record.record_id);
        updateBatchSelectionActions();
      });
      selectionCell.append(selection);
    }
    const statusCopy = element('span', 'batch-state-copy');
    statusCopy.append(
      element('span', `batch-state state-${String(record.state).toLowerCase()}`, t(`batch.states.${record.state}`)),
      element('small', '', t(`batch.state_help.${record.state}`))
    );
    if (Number(record.attempt_number || 1) > 1) {
      statusCopy.append(element('small', 'batch-attempt', t('batch.attempt', {
        number: record.attempt_number
      })));
    }
    status.append(statusCopy);
    const open = element('button', '', t('batch.open_detail'));
    open.type = 'button';
    open.classList.add('batch-detail-cell');
    open.dataset.label = t('batch.operation');
    open.setAttribute('role', 'cell');
    open.disabled = !record.session_id;
    open.addEventListener('click', () => openBatchRecord(record));
    row.append(
      selectionCell,
      status,
      batchRecordField(t('batch.relative_path'), record.logical_name, 'logical-path'),
      batchRecordField(t('batch.idf_runtime'), `${preview?.version || record.idf_version || t('batch.version_unknown')} / ${runtime}`),
      batchRecordField(t('batch.issues'), String(record.issue_count ?? 0)),
      batchRecordField(t('batch.committed'), String(record.committed_candidate_count ?? 0)),
      batchRecordField('EnergyPlus', String(record.energyplus_runs ?? 0)),
      batchRecordField(t('batch.duration'), record.duration_seconds === null || record.duration_seconds === undefined
        ? '—'
        : t('batch.duration_seconds', {seconds: Number(record.duration_seconds).toFixed(1)})),
      open
    );
    box.append(row);
  }
  updateBatchSelectionActions();
}

function renderBatchDashboard() {
  const dashboard = $('#batch-dashboard');
  if (!dashboard) return;
  const snapshot = state.batchSnapshot;
  dashboard.classList.toggle('hidden', !snapshot);
  applyBatchLayout();
  if (!snapshot) return;
  const completed = Number(snapshot.progress?.completed || 0);
  const total = Number(snapshot.progress?.total || 0);
  $('#batch-progress').max = Math.max(total, 1);
  $('#batch-progress').value = completed;
  $('#batch-progress-label').textContent = `${completed} / ${total}`;
  $('#batch-current').textContent = snapshot.current
    ? t('batch.current', {
        path: snapshot.current.logical_name,
        state: t(`batch.states.${snapshot.current.state}`)
      })
    : t('batch.current_none');
  const remaining = Math.max(0, total - completed);
  const eta = window.IDFRepairBatchWorkbench.estimateRemainingSeconds(
    state.batchRecords,
    remaining
  );
  $('#batch-eta').textContent = eta === null
    ? t('batch.eta_pending')
    : t('batch.eta', {time: formatDuration(eta)});
  const actionCount = ['NEEDS_INPUT', 'UNSUPPORTED', 'SEARCH_EXHAUSTED', 'FAILED']
    .reduce((total, value) => total + countBatchState(snapshot, value), 0);
  const action = $('#batch-action-required');
  action.classList.toggle('hidden', actionCount === 0);
  action.textContent = actionCount ? t('batch.action_required_notice', {count: actionCount}) : '';
  renderBatchCounts(snapshot);
  renderBatchRecords();
  const terminal = window.IDFRepairBatch.isBatchTerminal(snapshot.status);
  $('#batch-retry-support').classList.toggle('hidden', !terminal || actionCount === 0);
  $('#batch-cancel').disabled = terminal;
  const download = $('#batch-download');
  download.classList.toggle('hidden', !terminal);
  if (terminal) download.href = `/api/batches/${snapshot.batch_id}/download`;
  const csvExport = $('#batch-export-csv');
  const jsonExport = $('#batch-export-json');
  csvExport.classList.toggle('hidden', !terminal);
  jsonExport.classList.toggle('hidden', !terminal);
  if (terminal) {
    csvExport.href = `/api/batches/${snapshot.batch_id}/export.csv`;
    jsonExport.href = `/api/batches/${snapshot.batch_id}/export.json`;
  }
  updateBatchSelectionActions();
}

async function startBatch() {
  const checks = state.batchEntries.map((entry) => [entry, batchEntryPrecheck(entry)]);
  const selected = checks.filter(([, check]) => check.eligible).map(([entry]) => entry);
  const runtimeId = $('#batch-runtime-select').value;
  if (!selected.length) return notice(t('batch.no_files'), true);
  if (!runtimeId) return notice(t('batch.runtime_required'), true);
  const button = $('#batch-start');
  button.dataset.busy = 'true';
  updateBatchStartState();
  const body = new FormData();
  for (const entry of selected) {
    body.append('files', entry.file, entry.file.name);
    body.append('logical_paths', entry.logicalPath);
  }
  body.set('runtime_id', runtimeId);
  body.set('mode', $('#batch-mode').value);
  try {
    const created = await request('/api/batches', {method: 'POST', body});
    state.batchId = created.batch_id;
    state.batchSnapshot = created;
    state.batchRecords = [];
    state.batchPreparationExpanded = false;
    state.batchSelectedRecordIds.clear();
    state.batchRetrySettingsDirty = false;
    state.batchPollGeneration += 1;
    await request(`/api/batches/${state.batchId}/start`, {method: 'POST'});
    notice(t('batch.created'));
    renderBatchDashboard();
    await pollBatch();
  } catch (error) {
    notice(t('batch.upload_failed', {reason: error.message}), true);
  } finally {
    delete button.dataset.busy;
    updateBatchStartState();
  }
}

async function pollBatch() {
  if (!state.batchId) return;
  const generation = state.batchPollGeneration;
  window.clearTimeout(state.batchPollTimer);
  try {
    const [snapshot, records] = await Promise.all([
      request(`/api/batches/${state.batchId}`),
      request(`/api/batches/${state.batchId}/records`)
    ]);
    if (generation !== state.batchPollGeneration) return;
    state.batchSnapshot = snapshot;
    state.batchRecords = records.records || [];
    renderBatchDashboard();
    if (!window.IDFRepairBatch.isBatchTerminal(snapshot.status)) {
      state.batchPollTimer = window.setTimeout(pollBatch, 1000);
    }
  } catch (error) {
    if (generation === state.batchPollGeneration) notice(error.message, true);
  }
}

async function loadLatestBatch() {
  if (state.batchId) return;
  try {
    const payload = await request('/api/batches');
    const latest = payload.batches?.[0];
    if (!latest) return;
    state.batchId = latest.batch_id;
    state.batchSnapshot = latest;
    state.batchPreparationExpanded = String(latest.status || '') === 'CREATED';
    state.batchSelectedRecordIds.clear();
    state.batchRetrySettingsDirty = false;
    const runtimeId = window.IDFRepairBatch.runtimeIdForVersion(
      latest.energyplus_version,
      state.runtimes
    );
    if (runtimeId) $('#batch-runtime-select').value = runtimeId;
    if (latest.mode) $('#batch-mode').value = latest.mode;
    state.batchPollGeneration += 1;
    await pollBatch();
  } catch (error) {
    notice(error.message, true);
  }
}

async function cancelBatch() {
  if (!state.batchId) return;
  try {
    state.batchSnapshot = await request(`/api/batches/${state.batchId}/cancel`, {method: 'POST'});
    state.batchPollGeneration += 1;
    renderBatchDashboard();
    await pollBatch();
  } catch (error) {
    notice(error.message, true);
  }
}

async function retrySelectedBatch() {
  if (!state.batchId || !state.batchSelectedRecordIds.size) return;
  const button = $('#batch-retry-selected');
  button.disabled = true;
  const body = new FormData();
  for (const recordId of state.batchSelectedRecordIds) body.append('record_ids', recordId);
  if (state.batchRetrySettingsDirty) {
    const runtimeId = $('#batch-runtime-select')?.value;
    if (runtimeId) body.set('runtime_id', runtimeId);
    body.set('mode', $('#batch-mode')?.value || 'safe-auto');
  }
  for (const file of $('#batch-retry-support-folder')?.files || []) {
    if (/\.idf$/i.test(file.name)) continue;
    body.append('files', file, file.name);
    body.append('logical_paths', file.webkitRelativePath || file.name);
  }
  try {
    const created = await request(`/api/batches/${state.batchId}/retry`, {
      method: 'POST',
      body
    });
    state.batchId = created.batch_id;
    state.batchSnapshot = created;
    state.batchRecords = [];
    state.batchSelectedRecordIds.clear();
    state.batchRetrySettingsDirty = false;
    state.batchPreparationExpanded = false;
    $('#batch-retry-support-folder').value = '';
    $('#batch-retry-support-name').textContent = t('batch.retry_support_none');
    state.batchPollGeneration += 1;
    notice(t('batch.retry_started'));
    renderBatchDashboard();
    await pollBatch();
  } catch (error) {
    notice(t('batch.retry_failed', {reason: error.message}), true);
    updateBatchSelectionActions();
  }
}

async function openBatchRecord(
  record,
  batchId = state.batchId,
  batchSnapshot = state.batchSnapshot
) {
  if (!batchId || !record.session_id) return;
  try {
    const detail = await request(`/api/batches/${batchId}/records/${record.record_id}`);
    if (!detail.session_id) return;
    resetRepairViewForNewInput();
    $('#idf-file').value = '';
    state.batchId = batchId;
    state.batchSnapshot = batchSnapshot;
    state.batchRecords = batchSnapshot?.records || state.batchRecords;
    selectSingleRuntimeByVersion(batchSnapshot?.energyplus_version);
    state.batchRecordContext = {batchId, recordId: record.record_id};
    state.sessionId = detail.session_id;
    setStatus(await request(`/api/sessions/${detail.session_id}`));
    document.querySelector('[data-panel="repair-panel"]').click();
    await loadReport();
  } catch (error) {
    notice(error.message, true);
  }
}

function renderWorkflow(report) {
  const steps = [...document.querySelectorAll('#workflow-steps li')];
  steps.forEach((step) => step.classList.remove('active', 'complete'));
  steps[0]?.classList.add('complete');
  steps[1]?.classList.add('complete');
  if (report.final_status === 'NEEDS_INPUT') {
    steps[2]?.classList.add('active');
    return;
  }
  steps[2]?.classList.add('complete');
  steps[3]?.classList.add('complete');
  steps[4]?.classList.add('active');
}

function renderReport(report) {
  state.report = report;
  state.sessionId = report.session_id || state.sessionId;
  if (!state.summary?.last_completed_action && !state.lastCompletedAction) {
    state.lastCompletedAction = report.configuration?.mode === 'analyze-only'
      ? 'diagnose'
      : 'run';
  }
  if ((report.limitations || []).includes('MODEL_RUNTIME_UNAVAILABLE')) {
    notice(t('report.model_unavailable'), true);
  }
  reportBox.textContent = JSON.stringify(report, null, 2);
  const raw = report.raw_energyplus_err || [];
  rawErrBox.textContent = raw.length ? raw.join('\n\n===== EnergyPlus ERR =====\n\n') : t('report.no_raw_err');
  renderDiagnosis(report);
  renderTrace(report);
  renderResult(report);
  renderWorkflow(report);
}

async function loadOsmBridgeForSession(sessionId) {
  if (state.sourceKind !== 'osm' || !sessionId) return;
  const bridge = await request(`/api/sessions/${sessionId}/osm-bridge-report`);
  if (state.sessionId !== sessionId) return;
  state.osmReport = bridge;
  const summary = state.summary;
  const sourceName = bridge.source_name || summary?.source_input_name || 'source.osm';
  state.osmResult = {
    bridge,
    source_osm_url: `/api/sessions/${sessionId}/osm-source`,
    derived_idf_url: `/api/sessions/${sessionId}/osm-derived-idf`,
    bridge_report_url: `/api/sessions/${sessionId}/osm-bridge-report`,
    osm_download_url: summary?.osm_download_url || null,
    osm_writeback_report_url: summary?.osm_writeback_report_url || null,
    source_name: sourceName
  };
  renderOsmBridge();
}

async function loadReport() {
  const requestedSessionId = state.sessionId;
  if (!requestedSessionId) return;
  try {
    const report = await request(`/api/sessions/${requestedSessionId}/report`);
    if (state.sessionId !== requestedSessionId) return;
    renderReport(report);
    await loadOsmBridgeForSession(requestedSessionId);
    if (state.sessionId !== requestedSessionId) return;
    renderViewerSelection(null);
    const response = await fetch(`/api/sessions/${requestedSessionId}/download`);
    state.outputReady = response.ok;
    if (response.ok) {
      const text = await response.text();
      if (state.sessionId !== requestedSessionId) return;
      window.IDFRepairViewer?.loadText(
        text,
        report.input_identity?.name || 'session.idf'
      );
    }
    updatePrimaryAction();
  }
  catch (error) {
    if (state.sessionId === requestedSessionId) notice(error.message, true);
  }
}

async function runSession(action) {
  if (!state.sessionId) return;
  const requestedSessionId = state.sessionId;
  const tracksEnergyPlus = action === 'diagnose' || action === 'run';
  if (tracksEnergyPlus) startRunProgress(
    action,
    action === 'diagnose' ? 'DIAGNOSING' : 'REPAIRING'
  );
  try {
    const summary = await request(`/api/sessions/${requestedSessionId}/${action}`, {method: 'POST'});
    if (state.sessionId !== requestedSessionId) return;
    if (tracksEnergyPlus) state.lastCompletedAction = action;
    setStatus(summary);
    await loadReport();
    if (state.sessionId !== requestedSessionId) return;
    await loadSessions();
    if (state.sessionId !== requestedSessionId) return;
    if (tracksEnergyPlus) {
      setRunProgressStage('FINAL_VALIDATION');
      finishRunProgress(true);
    }
  } catch (error) {
    if (state.sessionId !== requestedSessionId) return;
    if (tracksEnergyPlus) finishRunProgress(false);
    const checkIds = error.payload?.params?.check_ids || error.payload?.check_ids || [];
    const weatherBlocked = error.payload?.message_id === 'error.run_readiness_blocked'
      && Array.isArray(checkIds) && checkIds.includes('weather');
    if (weatherBlocked) {
      await refreshReadiness(requestedSessionId);
      if (state.sessionId !== requestedSessionId) return;
      renderReadiness();
      updatePrimaryAction();
      notice(t('readiness.blocked_recoverable'), true);
      $('#readiness-blocker').scrollIntoView({behavior: 'smooth', block: 'center'});
      return;
    }
    notice(error.message, true);
  }
}

async function loadSessions() {
  try {
    const archived = $('#include-archived').checked ? 'true' : 'false';
    const [payload, batchPayload] = await Promise.all([
      request(`/api/sessions?include_archived=${archived}`),
      request('/api/batches')
    ]);
    state.sessions = payload.sessions || [];
    state.historyBatches = await Promise.all((batchPayload.batches || []).map(async (batch) => {
      const recordPayload = await request(`/api/batches/${batch.batch_id}/records`);
      return {...batch, records: recordPayload.records || []};
    }));
    renderSessionList();
  } catch (error) { notice(error.message, true); }
}

function sessionAction(labelKey, handler, disabled = false) {
  const button = element('button', '', t(labelKey));
  button.type = 'button';
  button.disabled = disabled;
  button.addEventListener('click', handler);
  return button;
}

function formatSessionTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(state.locale === 'zh-CN' ? 'zh-CN' : 'en', {
    dateStyle: 'medium', timeStyle: 'short'
  }).format(date);
}

function historyFact(label, value, className = '') {
  const node = element('span', `history-fact ${className}`.trim());
  node.append(element('small', '', label), element('strong', '', value));
  return node;
}

async function openHistorySession(row, {resume = false} = {}) {
  try {
    resetRepairViewForNewInput();
    $('#idf-file').value = '';
    state.batchRecordContext = null;
    state.sessionId = row.session_id;
    const summary = resume
      ? await request(`/api/sessions/${row.session_id}/resume`, {method: 'POST'})
      : await request(`/api/sessions/${row.session_id}`);
    setStatus(summary);
    document.querySelector('[data-panel="repair-panel"]').click();
    switchMainView('3d');
    if (summary.preflight_status === 'CHECKED') {
      state.preflightReport = await request(`/api/sessions/${row.session_id}/model-preflight`);
      state.auditReport = state.preflightReport.audit || null;
      renderAudit(state.auditReport);
      renderModelPreflight();
    } else if (summary.preflight_status === 'APPLIED' && summary.preflight_parent_session_id) {
      const parentId = summary.preflight_parent_session_id;
      state.preflightReport = await request(`/api/sessions/${parentId}/model-preflight`);
      state.preflightApplication = null;
      state.auditReport = null;
      renderAudit(null);
      renderModelPreflight();
    }
    if (summary.status) {
      await loadReport();
    } else {
      await loadSessionInputIntoViewer(
        `/api/sessions/${row.session_id}/input`,
        summary.input_name
      );
      await loadOsmBridgeForSession(row.session_id);
      renderViewerSelection(null);
    }
    if (resume) await loadSessions();
  } catch (error) {
    notice(error.message, true);
  }
}

function renderStandaloneSessionCard(row) {
  const card = element('article', 'data-row session-row');
  const header = element('header', 'history-header');
  header.append(
    element('strong', '', row.source_input_name || row.input_name),
    element('time', '', formatSessionTime(row.created_at))
  );
  const statusToken = row.status || row.lifecycle_status || '—';
  const summary = element('div', 'history-summary');
  summary.append(
    historyFact(t('result.status'), statusToken, `session-state status-${String(statusToken).toLowerCase()}`),
    historyFact(t('form.mode'), t(`tokens.modes.${row.mode}`)),
    historyFact('EnergyPlus', row.energyplus_version || '—'),
    historyFact(t('sessions.committed'), String(row.committed_candidate_count ?? 0)),
    historyFact(t('sessions.attempts'), String(row.candidate_attempt_count ?? 0)),
    historyFact('', row.output_changed ? t('sessions.output_changed') : t('sessions.output_unchanged'), row.output_changed ? 'changed' : 'unchanged')
  );
  card.append(header, element('p', 'history-message', renderMessage(row.message)), summary);
  const actions = element('div', 'actions');
  actions.append(
    sessionAction('actions.open', () => openHistorySession(row)),
    sessionAction('actions.resume', () => openHistorySession(row, {resume: true}),
      ['CANCELLED', 'ARCHIVED'].includes(row.lifecycle_status)),
    sessionAction('sessions.open_folder', async () => {
      try {
        const opened = await request(`/api/sessions/${row.session_id}/open-workspace`, {method: 'POST'});
        if (opened?.opened !== true) {
          notice(t('sessions.folder_open_failed'), true);
          return;
        }
        notice(t('sessions.folder_opened'));
      } catch (_error) {
        notice(t('sessions.folder_open_failed'), true);
      }
    }),
    sessionAction('actions.cancel', async () => {
      await request(`/api/sessions/${row.session_id}/cancel`, {method: 'POST'}); await loadSessions();
    }, ['CANCELLED', 'ARCHIVED'].includes(row.lifecycle_status)),
    sessionAction('actions.archive', async () => {
      await request(`/api/sessions/${row.session_id}/archive`, {method: 'POST'}); await loadSessions();
    }, row.lifecycle_status === 'RUNNING'),
    sessionAction('actions.delete', async () => {
      if (!window.confirm(t('sessions.confirm_delete'))) return;
      await request(`/api/sessions/${row.session_id}`, {method: 'DELETE'}); await loadSessions();
    }, row.lifecycle_status === 'RUNNING')
  );
  card.append(actions);
  return card;
}

function showBatchWorkspace(batch) {
  state.batchId = batch.batch_id;
  state.batchSnapshot = batch;
  state.batchRecords = batch.records || [];
  state.batchPollGeneration += 1;
  renderBatchDashboard();
  document.querySelector('[data-panel="batch-panel"]').click();
  if (!window.IDFRepairBatch.isBatchTerminal(batch.status)) pollBatch();
}

function renderBatchHistoryCard(batch) {
  const records = batch.records || [];
  const reportedTotal = batch.progress?.total ?? batch.record_count;
  const total = Number.isFinite(Number(reportedTotal))
    ? Math.max(0, Number(reportedTotal))
    : records.length;
  const card = element('article', 'data-row session-row batch-history-row');
  const header = element('header', 'history-header');
  header.append(
    element('strong', '', t('sessions.batch_title', {count: total})),
    element('time', '', formatSessionTime(batch.created_at))
  );
  const completed = Number(batch.progress?.completed || 0);
  const summary = element('div', 'history-summary');
  summary.append(
    historyFact(t('result.status'), batch.status || '—'),
    historyFact(t('form.mode'), t(`tokens.modes.${batch.mode}`)),
    historyFact('EnergyPlus', batch.energyplus_version || '—'),
    historyFact(t('sessions.batch_progress'), `${completed}/${total}`)
  );
  const details = element('details', 'batch-history-details');
  details.append(element('summary', '', t('sessions.batch_expand', {count: total})));
  const recordList = element('div', 'batch-history-records');
  for (const record of records) {
    const row = element('div', 'batch-history-record');
    const open = sessionAction('actions.open', () => openBatchRecord(record, batch.batch_id, batch));
    open.disabled = !record.session_id;
    row.append(
      element('span', `batch-state state-${String(record.state).toLowerCase()}`, t(`batch.states.${record.state}`)),
      element('strong', '', record.logical_name),
      element('span', '', `${record.remaining_issue_count ?? 0}/${record.issue_count ?? 0}`),
      open
    );
    recordList.append(row);
  }
  details.append(recordList);
  const actions = element('div', 'actions');
  actions.append(sessionAction('sessions.open_batch', () => showBatchWorkspace(batch)));
  if (window.IDFRepairBatch.isBatchTerminal(batch.status)) {
    const download = element('a', 'button-link', t('batch.download'));
    download.href = `/api/batches/${batch.batch_id}/download`;
    actions.append(download);
  }
  card.append(header, summary, details, actions);
  return card;
}

function renderSessionList() {
  const box = $('#session-list');
  if (!box) return;
  box.replaceChildren();
  const entries = [
    ...state.sessions.filter((row) => !row.batch_id).map((row) => ({kind: 'session', row})),
    ...state.historyBatches.map((row) => ({kind: 'batch', row}))
  ].sort((left, right) => String(right.row.updated_at || right.row.created_at)
    .localeCompare(String(left.row.updated_at || left.row.created_at)));
  if (!entries.length) box.append(element('p', '', t('sessions.empty')));
  for (const entry of entries) {
    box.append(entry.kind === 'batch'
      ? renderBatchHistoryCard(entry.row)
      : renderStandaloneSessionCard(entry.row));
  }
}

async function loadRuleSets() {
  try {
    state.ruleSets = (await request('/api/rule-sets')).rule_sets || [];
    populateRuleSets();
  } catch (error) { notice(error.message, true); }
}

async function loadCapabilities() {
  state.capabilities = await request('/api/capabilities');
  state.osmCapability = state.capabilities?.osm_bridge || null;
  renderCapabilitySummary();
  renderOsmBridge();
}

function renderCapabilitySummary() {
  const counts = state.capabilities?.display_metadata?.registry_counts || {};
  $('#release-profile').textContent = state.capabilities?.release_profile_id || '—';
  $('#capability-counts').textContent = t('capability.counts', {
    total: state.capabilities?.entry_count ?? '—',
    safe: counts['safe-auto'] ?? '—',
    assisted: counts.assisted ?? '—',
    interactive: counts.interactive ?? '—',
    evidence: counts['evidence-only'] ?? '—',
    disabled: counts.disabled ?? '—'
  });
  const runtimeVersions = [...new Set(state.runtimes.map((runtime) => runtime.version))];
  $('#capability-runtimes').textContent = runtimeVersions.length
    ? runtimeVersions.join(' · ')
    : t('form.runtime_none');
  const osm = state.osmCapability;
  $('#capability-osm').textContent = osm?.diagnostic_bridge_available
    ? t('capability.osm_available', {version: osm.openstudio_version || '—'})
    : t('capability.osm_unavailable');
}

function populateSelect(select, includeAll) {
  if (!select) return;
  const current = select.value;
  select.replaceChildren();
  if (includeAll) {
    const option = element('option', '', t('rules.all_sets'));
    option.value = '';
    select.append(option);
  }
  for (const row of state.ruleSets) {
    const option = element('option', '', state.locale === 'zh-CN' ? row.name_zh : row.name_en);
    option.value = row.rule_set_id;
    option.dataset.token = row.rule_set_id;
    select.append(option);
  }
  if ([...select.options].some((option) => option.value === current)) select.value = current;
}

function populateRuleSets() {
  populateSelect($('#session-rule-set'), false);
  populateSelect($('#rule-set-filter'), true);
  const selected = $('#rule-set-filter')?.value || '';
  $('#rule-export').href = `/api/rules/export${selected ? `?rule_set_id=${encodeURIComponent(selected)}` : ''}`;
}

async function loadRules() {
  try {
    const params = new URLSearchParams();
    const search = $('#rule-search').value.trim();
    const ruleSet = $('#rule-set-filter').value;
    if (search) params.set('search', search);
    if (ruleSet) params.set('rule_set_id', ruleSet);
    state.rules = (await request(`/api/rules?${params}`)).rules || [];
    renderRuleList();
  } catch (error) { notice(error.message, true); }
}

function ruleAction(labelKey, handler) {
  const button = element('button', '', t(labelKey));
  button.type = 'button';
  button.addEventListener('click', handler);
  return button;
}

function renderRuleList() {
  const box = $('#rule-list');
  if (!box) return;
  box.replaceChildren();
  if (!state.rules.length) box.append(element('p', '', t('rules.empty')));
  for (const rule of state.rules) {
    const row = element('article', 'data-row');
    row.append(element('strong', '', state.locale === 'zh-CN' ? rule.name_zh : rule.name_en));
    const summary = element('div', 'rule-summary');
    summary.append(
      element('span', `pill ${rule.enabled ? 'enabled' : 'disabled'}`, t(rule.enabled ? 'rules.enabled' : 'rules.disabled')),
      element('span', 'pill', t(`tokens.families.${rule.family}`)),
      element('span', 'pill', rule.scope),
      element('span', 'pill', `${rule.success_count}/${rule.failure_count}`)
    );
    row.append(summary, element('p', '', rule.error_signature || t('rules.no_signature')));
    const actions = element('div', 'actions');
    actions.append(
      ruleAction('actions.edit', () => openRuleEditor(rule)),
      ruleAction(rule.enabled ? 'actions.disable' : 'actions.enable', () => toggleRule(rule)),
      ruleAction('actions.clone', () => cloneRule(rule)),
      ruleAction('actions.delete', () => deleteRule(rule))
    );
    row.append(actions);
    box.append(row);
  }
}

function renderRuleEditorSummary(rule) {
  const box = $('#rule-editor-summary');
  if (!box) return;
  box.replaceChildren();
  const name = state.locale === 'zh-CN' ? rule.name_zh : rule.name_en;
  const description = state.locale === 'zh-CN' ? rule.description_zh : rule.description_en;
  box.append(
    element('small', 'section-index', t('rules.summary')),
    element('h4', '', name || rule.rule_id || t('rules.new')),
    element('p', '', description || rule.error_signature || t('rules.no_signature'))
  );
  const facts = element('div', 'rule-summary');
  facts.append(
    element('span', `pill ${rule.enabled ? 'enabled' : 'disabled'}`, t(rule.enabled ? 'rules.enabled' : 'rules.disabled')),
    element('span', 'pill', t(`tokens.families.${rule.family || 'unknown'}`)),
    element('span', 'pill', rule.scope || '—'),
    element('span', 'pill', rule.requires_confirmation ? 'confirmation required' : 'finite rule')
  );
  box.append(facts);
}

function openRuleEditor(rule = null) {
  state.editingRuleId = rule?.rule_id || null;
  const template = rule || {
    rule_set_id: $('#rule-set-filter').value || 'default',
    name_zh: '新规则', name_en: 'New rule', description_zh: '', description_en: '',
    enabled: false, priority: 0, scope: 'EXACT_TEMPLATE', source: 'USER_CREATED',
    error_signature: '', family: 'schema', object_type: null, field_name: null,
    field_index: 1, conditions: {}, candidate_template: {},
    finite_operations: [{kind: 'replace_field', object_type: 'ObjectType', object_name: '$ROOT_OBJECT_NAME', field_index: 1, old_value: '$CURRENT', new_value: 'Value'}],
    requires_confirmation: true, confidence: 0.8, tags: []
  };
  $('#rule-json').value = JSON.stringify(template, null, 2);
  renderRuleEditorSummary(template);
  $('#rule-definition-details').open = false;
  $('#rule-history-output').classList.add('hidden');
  $('#rule-editor').classList.remove('hidden');
}

async function toggleRule(rule) {
  try {
    await request(`/api/rules/${rule.rule_id}/${rule.enabled ? 'disable' : 'enable'}`, {method: 'POST'});
    await loadRules();
  } catch (error) { notice(error.message, true); }
}

async function cloneRule(rule) {
  try {
    await request(`/api/rules/${rule.rule_id}/clone`, {method: 'POST'});
    await loadRules();
  } catch (error) { notice(error.message, true); }
}

async function deleteRule(rule) {
  if (!window.confirm(t('rules.confirm_delete', {name: rule.name_zh}))) return;
  try {
    await request(`/api/rules/${rule.rule_id}`, {method: 'DELETE'});
    await loadRules();
  } catch (error) { notice(error.message, true); }
}

async function showRuleHistory() {
  if (!state.editingRuleId) return;
  try {
    const [versions, applications] = await Promise.all([
      request(`/api/rules/${state.editingRuleId}/versions`),
      request(`/api/rules/${state.editingRuleId}/applications`)
    ]);
    const box = $('#rule-history-output');
    box.textContent = JSON.stringify({versions: versions.versions, applications: applications.applications}, null, 2);
    box.classList.remove('hidden');
  } catch (error) { notice(error.message, true); }
}

async function createSessionForCurrentInput() {
  const form = $('#session-form');
  const body = new FormData(form);
  resetRepairViewForNewInput({clearViewerSelection: false});
  const requestedInputRevision = state.inputRevision;
  state.busy = 'creating';
  updatePrimaryAction();
  try {
    const payload = await request('/api/sessions', {method: 'POST', body});
    if (state.inputRevision !== requestedInputRevision) return false;
    state.sessionId = payload.session_id;
    const summary = await request(`/api/sessions/${payload.session_id}`);
    if (state.inputRevision !== requestedInputRevision || state.sessionId !== payload.session_id) {
      return false;
    }
    setStatus(summary);
    await refreshReadiness(payload.session_id);
    if (state.inputRevision !== requestedInputRevision || state.sessionId !== payload.session_id) {
      return false;
    }
    notice(renderMessage(payload.message));
    return true;
  } catch (error) {
    if (state.inputRevision === requestedInputRevision) notice(error.message, true);
    return false;
  } finally {
    if (state.inputRevision === requestedInputRevision && state.busy === 'creating') {
      state.busy = null;
      updatePrimaryAction();
    }
  }
}

async function handlePrimaryAction() {
  const current = primaryActionState();
  if (current.disabled) return;
  switch (current.action) {
    case 'choose-file':
      $('#idf-file').click();
      break;
    case 'diagnose':
      if (!state.sessionId && !await createSessionForCurrentInput()) return;
      if (!state.runReadiness && !await refreshReadiness(state.sessionId)) return;
      if (!currentReadinessState().canDiagnose) {
        renderReadiness();
        notice(t('readiness.not_ready'), true);
        $('#readiness-blocker').scrollIntoView({behavior: 'smooth', block: 'center'});
        return;
      }
      await runSession('diagnose');
      break;
    case 'retry-readiness':
      await refreshReadiness(state.sessionId);
      break;
    case 'focus-weather':
      $('#readiness-blocker').scrollIntoView({behavior: 'smooth', block: 'center'});
      $('#session-epw-file').click();
      break;
    case 'import-osm':
      await runOsmDiagnostic();
      break;
    case 'run-preflight':
      $('#model-tools-drawer').open = true;
      $('#model-preflight-panel').scrollIntoView({behavior: 'smooth', block: 'center'});
      await runModelPreflight();
      break;
    case 'apply-preflight':
      $('#model-tools-drawer').open = true;
      $('#model-preflight-panel').scrollIntoView({behavior: 'smooth', block: 'center'});
      await applyModelPreflight();
      break;
    case 'repair':
      await runSession('run');
      break;
    case 'focus-input': {
      questionBox.scrollIntoView({behavior: 'smooth', block: 'center'});
      const control = questionBox.querySelector('button, input, select');
      control?.focus({preventScroll: true});
      break;
    }
    case 'download':
      downloadLink.click();
      break;
    default:
      break;
  }
}

function setPanelCollapsed(panel, collapsed) {
  const heading = panel.querySelector(':scope > [data-collapse-heading]');
  if (!heading) return;
  panel.classList.toggle('collapsed', collapsed);
  heading.setAttribute('aria-expanded', String(!collapsed));
  heading.title = t(collapsed ? 'common.expand_panel' : 'common.collapse_panel');
}

function syncCollapsibleLabels() {
  document.querySelectorAll('[data-collapsible]').forEach((panel) => {
    setPanelCollapsed(panel, panel.classList.contains('collapsed'));
  });
}

function bindCollapsiblePanels() {
  document.querySelectorAll('[data-collapsible]').forEach((panel) => {
    const heading = panel.querySelector(':scope > [data-collapse-heading]');
    if (!heading || heading.dataset.collapseBound) return;
    heading.dataset.collapseBound = 'true';
    heading.tabIndex = 0;
    heading.setAttribute('role', 'button');
    const toggle = () => setPanelCollapsed(panel, !panel.classList.contains('collapsed'));
    heading.addEventListener('click', (event) => {
      if (event.target.closest('a, button, input, select, textarea, label, summary')) return;
      toggle();
    });
    heading.addEventListener('keydown', (event) => {
      if (!['Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      toggle();
    });
    setPanelCollapsed(panel, false);
  });
}

function bindEvents() {
  bindCollapsiblePanels();
  document.querySelectorAll('[data-new-input]').forEach((button) => {
    button.addEventListener('click', startNewInput);
  });
  $('#issue-search').addEventListener('input', (event) => {
    state.issueQuery = event.target.value;
    state.issueGroupLimits = new Map();
    renderIssueNavigator();
  });
  $('#issue-categories').addEventListener('click', (event) => {
    const button = event.target.closest('[data-issue-category]');
    if (!button) return;
    state.issueCategory = button.dataset.issueCategory || 'all';
    state.issueGroupLimits = new Map();
    renderIssueNavigator();
  });
  $('#open-session-settings').addEventListener('click', () => {
    state.settingsOpen = true;
    updateSessionWorkbench();
    $('#session-settings-close').focus({preventScroll: true});
  });
  $('#session-settings-close').addEventListener('click', () => {
    state.settingsOpen = false;
    updateSessionWorkbench();
    $('#open-session-settings').focus({preventScroll: true});
  });
  $('#session-download').addEventListener('click', () => {
    if (state.outputReady) downloadLink.click();
  });
  $('#session-more').addEventListener('click', () => {
    const consoleNode = $('#run-console');
    consoleNode.open = !consoleNode.open;
    if (consoleNode.open) consoleNode.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !state.settingsOpen) return;
    state.settingsOpen = false;
    updateSessionWorkbench();
    $('#open-session-settings').focus({preventScroll: true});
  });
  $('#main-view-tabs').addEventListener('click', (event) => {
    const button = event.target.closest('[role="tab"]');
    if (!button) return;
    switchMainView(button.getAttribute('aria-controls'));
  });
  $('#main-view-tabs').addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [...document.querySelectorAll('#main-view-tabs [role="tab"]')];
    const current = tabs.indexOf(event.target.closest('[role="tab"]'));
    if (current < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0
      : event.key === 'End' ? tabs.length - 1
        : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    switchMainView(tabs[next].getAttribute('aria-controls'), {focus: true});
  });
  $('#source-previous-issue').addEventListener('click', () => selectAdjacentIssue(-1));
  $('#source-next-issue').addEventListener('click', () => selectAdjacentIssue(1));
  $('#copy-source-context').addEventListener('click', async () => {
    if (!state.sourceContext?.text || !navigator.clipboard?.writeText) return;
    try {
      await navigator.clipboard.writeText(state.sourceContext.text);
      notice(t('workbench.source_copied'));
    } catch (_error) {
      notice(t('workbench.source_copy_failed'), true);
    }
  });
  $('#language').addEventListener('change', (event) => loadLocale(event.target.value));
  $('#batch-files').addEventListener('change', async (event) => {
    await appendBatchFiles(event.target.files, 'files');
    event.target.value = '';
  });
  $('#batch-folder').addEventListener('change', async (event) => {
    await appendBatchFiles(event.target.files, 'folder');
    event.target.value = '';
  });
  $('#batch-zip').addEventListener('change', async (event) => {
    await appendBatchFiles(event.target.files, 'zip');
    event.target.value = '';
  });
  $('.batch-input-panel').addEventListener('dragover', (event) => {
    event.preventDefault();
    event.currentTarget.classList.add('dragging');
  });
  $('.batch-input-panel').addEventListener('dragleave', (event) => {
    event.currentTarget.classList.remove('dragging');
  });
  $('.batch-input-panel').addEventListener('drop', async (event) => {
    event.preventDefault();
    event.currentTarget.classList.remove('dragging');
    await appendBatchFiles(event.dataTransfer?.files || [], 'files');
  });
  $('#batch-clear').addEventListener('click', () => {
    state.batchEntries = [];
    renderBatchPreview();
  });
  $('#batch-preparation-toggle').addEventListener('click', () => {
    state.batchPreparationExpanded = !state.batchPreparationExpanded;
    applyBatchLayout();
  });
  $('#batch-start').addEventListener('click', startBatch);
  $('#batch-retry-selected').addEventListener('click', retrySelectedBatch);
  $('#batch-filter').addEventListener('change', renderBatchRecords);
  $('#batch-record-search').addEventListener('input', renderBatchRecords);
  $('#batch-record-sort').addEventListener('change', renderBatchRecords);
  $('#batch-sort-direction').addEventListener('click', (event) => {
    const button = event.currentTarget;
    button.dataset.direction = button.dataset.direction === 'desc' ? 'asc' : 'desc';
    button.textContent = button.dataset.direction === 'desc' ? '↓' : '↑';
    renderBatchRecords();
  });
  $('#batch-cancel').addEventListener('click', cancelBatch);
  $('#batch-runtime-select').addEventListener('change', () => {
    if (state.batchSnapshot) state.batchRetrySettingsDirty = true;
    renderBatchPreview();
  });
  $('#batch-mode').addEventListener('change', () => {
    if (state.batchSnapshot) state.batchRetrySettingsDirty = true;
  });
  $('#batch-retry-support-folder').addEventListener('change', (event) => {
    const count = [...(event.target.files || [])].filter((file) => !/\.idf$/i.test(file.name)).length;
    const label = $('#batch-retry-support-name');
    label.textContent = count
      ? t('batch.retry_support_count', {count})
      : t('batch.retry_support_none');
    label.removeAttribute('data-i18n');
  });
  $('#run-model-preflight').addEventListener('click', runModelPreflight);
  $('#apply-model-preflight').addEventListener('click', applyModelPreflight);
  $('#rollback-model-preflight').addEventListener('click', rollbackModelPreflight);
  document.querySelectorAll('input[name="preflight_check"]').forEach((input) => {
    input.addEventListener('change', updateModelPreflightAction);
  });
  $('#run-audit').addEventListener('click', runModelAudit);
  $('#audit-search').addEventListener('input', () => {
    state.auditRenderLimit = 200;
    renderAuditFindings();
  });
  $('#audit-severity').addEventListener('change', () => {
    state.auditRenderLimit = 200;
    renderAuditFindings();
  });
  $('#audit-clear-surface').addEventListener('click', () => {
    state.auditSurfaceFilter = null;
    state.auditRenderLimit = 200;
    renderAuditFindings();
  });
  $('#audit-load-more').addEventListener('click', () => {
    state.auditRenderLimit += 200;
    renderAuditFindings();
  });
  document.querySelectorAll('input[name="audit_check"]').forEach((input) => {
    input.addEventListener('change', updateAuditAction);
  });
  $('#run-experimental-preview').addEventListener('click', runExperimentalPreview);
  $('#experimental-search').addEventListener('input', () => {
    state.experimentalRenderLimit = 100;
    renderExperimentalResults();
  });
  $('#experimental-clear-surface').addEventListener('click', () => {
    state.experimentalSurfaceFilter = null;
    state.experimentalRenderLimit = 100;
    renderExperimentalResults();
  });
  $('#experimental-load-more').addEventListener('click', () => {
    state.experimentalRenderLimit += 100;
    renderExperimentalResults();
  });
  $('#experimental-toggle-results').addEventListener('click', () => {
    state.experimentalResultsExpanded = !state.experimentalResultsExpanded;
    renderExperimentalResults();
  });
  document.querySelectorAll('input[name="experimental_mechanism"]').forEach((input) => {
    input.addEventListener('change', updateExperimentalAction);
  });
  window.addEventListener('message', (event) => {
    const viewerFrame = $('#model-viewer');
    const message = event.data || {};
    if (event.source !== viewerFrame?.contentWindow
        || event.origin !== window.location.origin
        || message.type !== 'idfrepair:viewer-ready') return;
    const selectedIssue = workbenchIssueRows()
      .find((row) => row.id === state.selectedIssueId);
    if (selectedIssue) showWorkbenchIssueInViewer(selectedIssue);
  });
  window.addEventListener('idfrepair:viewer-selected', (event) => {
    renderViewerSelection(event.detail);
    if (state.auditReport) {
      state.auditSurfaceFilter = event.detail?.selectionKind === 'surface'
        ? String(event.detail?.objectName || '') || null
        : null;
      state.auditRenderLimit = 200;
      renderAuditFindings();
    }
    if (state.experimentalReport) {
      state.experimentalSurfaceFilter = event.detail?.selectionKind === 'surface'
        ? String(event.detail?.objectName || '') || null
        : null;
      state.experimentalRenderLimit = 100;
      renderExperimentalResults();
    }
    if (event.detail?.selectionKind !== 'surface') return;
    const objectName = String(event.detail?.objectName || '').trim().toLowerCase();
    const root = state.rootDetails.find((row) => String(row.object_name || '').trim().toLowerCase() === objectName);
    if (root) selectRoot(root.root_id);
  });
  $('#idf-file').addEventListener('change', async (event) => {
    resetRepairViewForNewInput();
    const file = event.target.files?.[0];
    const name = file?.name;
    const label = $('#idf-file-name');
    label.textContent = name || t('form.idf_none');
    if (name) label.removeAttribute('data-i18n');
    else label.dataset.i18n = 'form.idf_none';
    if (file) {
      state.activeModelFile = file;
      $('#osm-file').value = '';
      $('#osm-file-name').textContent = t('workbench.osm_none');
      $('#osm-file-name').dataset.i18n = 'workbench.osm_none';
      const modelText = await file.text();
      const sourceKind = detectSourceKind(file, modelText);
      if (sourceKind === 'unknown') {
        event.target.value = '';
        state.activeModelFile = null;
        setSourceKind('idf');
        notice(t('form.model_extension_invalid'), true);
        updatePrimaryAction();
        return;
      }
      setSourceKind(sourceKind);
      if (sourceKind === 'osm') {
        if (!/\.osm$/i.test(file.name)) notice(t('form.osm_content_detected'));
        $('#osm-status').textContent = t('osm.ready');
        renderOsmCapability();
        updatePrimaryAction();
        return;
      }
      const selected = window.IDFRepairWorkflow.runtimeIdForText(
        modelText, state.runtimes, state.selectedRuntimeId
      );
      if (event.target.files?.[0] === file && selected !== state.selectedRuntimeId) {
        state.selectedRuntimeId = selected;
        renderRuntimeOptions();
      }
    } else {
      setSourceKind('idf');
    }
    updatePrimaryAction();
  });
  $('#osm-file').addEventListener('change', (event) => {
    resetRepairViewForNewInput();
    const file = event.target.files?.[0];
    const label = $('#osm-file-name');
    label.textContent = file?.name || t('workbench.osm_none');
    if (file) label.removeAttribute('data-i18n');
    else label.dataset.i18n = 'workbench.osm_none';
    if (file) {
      state.activeModelFile = file;
      $('#idf-file').value = '';
      $('#idf-file-name').textContent = t('form.idf_none');
      $('#idf-file-name').dataset.i18n = 'form.idf_none';
      setSourceKind('osm');
      $('#osm-status').textContent = t('osm.ready');
      renderOsmCapability();
    } else {
      setSourceKind('idf');
    }
    updatePrimaryAction();
  });
  $('#osm-mapping-search').addEventListener('input', (event) => {
    state.osmMappingQuery = event.target.value || '';
    state.osmMappingLimit = 50;
    renderOsmMappings(state.osmReport);
  });
  $('#osm-validity-more').addEventListener('click', () => {
    state.osmValidityLimit += 50;
    renderOsmValidity(state.osmReport);
  });
  $('#osm-mapping-more').addEventListener('click', () => {
    state.osmMappingLimit += 50;
    renderOsmMappings(state.osmReport);
  });
  $('#session-epw-file').addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    $('#session-epw-name').textContent = file?.name || t('readiness.no_epw');
    renderReadiness();
  });
  $('#attach-session-weather').addEventListener('click', attachSessionWeather);
  $('#epw-file').addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    const label = $('#epw-file-name');
    label.textContent = file?.name || t('form.epw_none');
    if (file) label.removeAttribute('data-i18n');
    else label.dataset.i18n = 'form.epw_none';
  });
  $('#dependency-files').addEventListener('change', (event) => {
    const files = [...(event.target.files || [])];
    const label = $('#dependency-file-name');
    label.textContent = files.length === 1
      ? files[0].name
      : (files.length ? t('form.dependency_count', {count: files.length}) : t('form.dependencies_none'));
    if (files.length) label.removeAttribute('data-i18n');
    else label.dataset.i18n = 'form.dependencies_none';
  });
  $('#runtime-select').addEventListener('change', (event) => {
    state.selectedRuntimeId = event.target.value || null;
    renderRuntimeOptions();
    void handoffSessionSettings();
  });
  $('#rescan-runtimes').addEventListener('click', () => loadRuntimes(true));
  $('#migration-target-runtime').addEventListener('change', (event) => {
    state.migrationTargetRuntimeId = event.target.value || null;
    state.migrationReport = null;
    renderMigrationAssistant();
  });
  $('#migration-run').addEventListener('click', runMigrationCopy);
  document.querySelectorAll('input[name="mode"]').forEach((input) => {
    input.addEventListener('change', () => {
      updatePrimaryAction();
      void handoffSessionSettings();
    });
  });
  primaryActionButtons.forEach((button) => button.addEventListener('click', handlePrimaryAction));
  $('#open-capabilities').addEventListener('click', () => $('#capability-dialog').showModal());
  $('#close-capabilities').addEventListener('click', () => $('#capability-dialog').close());
  document.querySelectorAll('.tab').forEach((button) => button.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((row) => row.classList.toggle('active', row === button));
    document.querySelectorAll('.tab-panel').forEach((row) => row.classList.toggle('active', row.id === button.dataset.panel));
    if (button.dataset.panel === 'sessions-panel') loadSessions();
    if (button.dataset.panel === 'batch-panel') loadLatestBatch();
    if (button.dataset.panel === 'rules-panel') { loadRuleSets(); loadRules(); }
  }));
  $('#session-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    await handlePrimaryAction();
  });
  cancelButton.addEventListener('click', () => runSession('cancel'));
  $('#rule-save-scope').addEventListener('change', (event) => {
    $('#rule-save-global-row').classList.toggle('hidden', event.target.value !== 'GLOBAL');
  });
  $('#rule-save-decline').addEventListener('click', () => ruleSaveBox.classList.add('hidden'));
  ruleSaveBox.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const payload = {
        candidate_id: $('#rule-save-candidate').value,
        scope: $('#rule-save-scope').value,
        name_zh: $('#rule-save-name-zh').value,
        name_en: $('#rule-save-name-en').value,
        global_authorized: $('#rule-save-global').checked
      };
      const result = await request(`/api/sessions/${state.sessionId}/rules`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
      });
      notice(renderMessage(result.message) || t('rules.saved'));
      setStatus(await request(`/api/sessions/${state.sessionId}`));
      await loadRules();
    } catch (error) { notice(error.message, true); }
  });
  $('#refresh-sessions').addEventListener('click', loadSessions);
  $('#include-archived').addEventListener('change', loadSessions);
  $('#search-rules').addEventListener('click', loadRules);
  $('#rule-set-filter').addEventListener('change', () => { populateRuleSets(); loadRules(); });
  $('#new-rule').addEventListener('click', () => openRuleEditor());
  $('#close-editor').addEventListener('click', () => $('#rule-editor').classList.add('hidden'));
  $('#rule-history').addEventListener('click', showRuleHistory);
  $('#rule-editor').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const payload = JSON.parse($('#rule-json').value);
      const url = state.editingRuleId ? `/api/rules/${state.editingRuleId}` : '/api/rules';
      const method = state.editingRuleId ? 'PATCH' : 'POST';
      if (state.editingRuleId) {
        ['rule_id', 'created_at', 'success_count', 'failure_count', 'last_validation_status'].forEach((key) => delete payload[key]);
      }
      const result = await request(url, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      state.editingRuleId = result.rule.rule_id;
      $('#rule-json').value = JSON.stringify(result.rule, null, 2);
      await loadRules();
      notice(t('rules.saved'));
    } catch (error) { notice(error.message, true); }
  });
  $('#create-rule-set').addEventListener('click', async () => {
    const nameZh = window.prompt(t('rules.prompt_name_zh'));
    if (!nameZh) return;
    const nameEn = window.prompt(t('rules.prompt_name_en'));
    if (!nameEn) return;
    try {
      await request('/api/rule-sets', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name_zh: nameZh, name_en: nameEn})});
      await loadRuleSets();
    } catch (error) { notice(error.message, true); }
  });
  $('#rule-import').addEventListener('change', async (event) => {
    if (!event.target.files[0]) return;
    const body = new FormData();
    body.set('file', event.target.files[0]);
    const selected = $('#rule-set-filter').value;
    if (selected) body.set('rule_set_id', selected);
    try {
      const result = await request('/api/rules/import', {method: 'POST', body});
      notice(renderMessage(result.message));
      await loadRules();
    } catch (error) { notice(error.message, true); }
    event.target.value = '';
  });
}

async function initialize() {
  bindEvents();
  switchMainView('3d');
  renderValidation(null);
  try {
    await loadLocale(['zh-CN', 'en'].includes(state.locale) ? state.locale : 'zh-CN');
    await loadRuntimes();
    await loadCapabilities();
    await loadRuleSets();
    await loadSessions();
    await loadLatestBatch();
  } catch (error) { notice(error.message, true); }
}

initialize();
