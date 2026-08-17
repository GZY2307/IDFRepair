'use strict';

(() => {
  function initializeViewerBridge() {
  if (window.IDFRepairViewer) return;
  const iframe = document.querySelector('#model-viewer');
  const fileInput = document.querySelector('#idf-file');
  const occupancyInput = document.querySelector('#occupancy-payload-file');
  const occupancyClear = document.querySelector('#occupancy-payload-clear');
  const occupancyStatus = document.querySelector('#occupancy-payload-status');
  if (!iframe || !fileInput) return;

  const OCCUPANCY_COPY = Object.freeze({
    'zh-CN': Object.freeze({
      reading: '正在本地读取 {name}…',
      validating: '正在核对人员图层与当前 IDF…',
      invalid: '人员流量 JSON 读取或映射失败'
    }),
    en: Object.freeze({
      reading: 'Reading {name} locally…',
      validating: 'Checking occupancy layer against this IDF…',
      invalid: 'Occupancy JSON could not be read or mapped'
    })
  });

  let ready = false;
  let pendingModel = null;
  let pendingSource = null;
  let pendingRoots = [];
  let pendingIssueMode = null;
  let pendingOccupancy = null;
  let pendingLocale = document.documentElement.lang || 'zh-CN';
  let occupancyStatusState = {key: 'idle', values: {}};

  function occupancyCopy(key, values = {}) {
    const locale = pendingLocale === 'en' ? 'en' : 'zh-CN';
    let value = OCCUPANCY_COPY[locale][key] || OCCUPANCY_COPY.en[key] || key;
    Object.entries(values).forEach(([name, replacement]) => {
      value = value.replace(`{${name}}`, String(replacement));
    });
    return value;
  }

  function setOccupancyStatus(key, values = {}) {
    occupancyStatusState = {key, values};
    if (!occupancyStatus) return;
    const silent = key === 'idle' || key === 'ready';
    occupancyStatus.hidden = silent;
    occupancyStatus.textContent = silent ? '' : occupancyCopy(key, values);
  }

  function resetOccupancyLayerUi({status = 'idle'} = {}) {
    if (occupancyInput) occupancyInput.value = '';
    if (occupancyClear) occupancyClear.disabled = true;
    setOccupancyStatus(status);
  }

  function post(message) {
    if (!ready || !iframe.contentWindow) return false;
    iframe.contentWindow.postMessage(message, window.location.origin);
    return true;
  }

  function ping() {
    iframe.contentWindow?.postMessage(
      {type: 'idfrepair:viewer-ping'},
      window.location.origin
    );
  }

  function flush() {
    post({type: 'idfrepair:viewer-locale', locale: pendingLocale});
    if (pendingSource) post({type: 'idfrepair:viewer-source-pending', ...pendingSource});
    else if (pendingModel) post({type: 'idfrepair:viewer-load', ...pendingModel});
    if (pendingRoots.length) post({type: 'idfrepair:viewer-highlight', roots: pendingRoots});
    post({type: 'idfrepair:viewer-issue-mode', issue: pendingIssueMode});
    post({type: 'idfrepair:viewer-occupancy', payload: pendingOccupancy});
  }

  function loadText(text, name = 'IDF geometry') {
    pendingSource = null;
    pendingOccupancy = null;
    pendingModel = {text: String(text || ''), name};
    resetOccupancyLayerUi();
    post({type: 'idfrepair:viewer-occupancy', payload: null});
    post({type: 'idfrepair:viewer-load', ...pendingModel});
  }

  function loadOccupancy(payload) {
    pendingOccupancy = payload && typeof payload === 'object' ? payload : null;
    post({type: 'idfrepair:viewer-occupancy', payload: pendingOccupancy});
  }

  async function loadFile(file) {
    if (!file) return;
    if (/\.osm$/i.test(file.name)) {
      pendingModel = null;
      pendingSource = {name: file.name, sourceKind: 'osm'};
      post({type: 'idfrepair:viewer-source-pending', ...pendingSource});
      return;
    }
    loadText(await file.text(), file.name);
  }

  function focusRoots(roots = []) {
    pendingRoots = roots.map((root) => ({
      rootId: root.root_id || root.rootId || '',
      objectName: root.object_name || root.objectName || '',
      objectType: root.object_type || root.objectType || '',
      fieldName: root.field_name || root.fieldName || '',
      family: root.family || '',
      message: root.message || ''
    }));
    post({type: 'idfrepair:viewer-highlight', roots: pendingRoots});
  }

  function stringList(value) {
    return (Array.isArray(value) ? value : []).map(String);
  }

  function vertexEvidence(value) {
    return (Array.isArray(value) ? value : []).map((row) => ({
      ...row,
      vertices: (Array.isArray(row?.vertices) ? row.vertices : []).map((vertex) => (
        Array.isArray(vertex) ? vertex.slice(0, 3) : vertex
      ))
    }));
  }

  function showIssue(issue = null) {
    if (!issue) {
      pendingIssueMode = null;
    } else {
      const targetNames = stringList(issue.targetNames?.length ? issue.targetNames : issue.target_surface_names);
      const pairedNames = stringList(issue.pairedNames?.length ? issue.pairedNames : issue.paired_surface_names);
      const groupNames = stringList(issue.groupNames?.length ? issue.groupNames : issue.group_surface_names);
      const roleLabels = {...(issue.roleLabels || issue.role_labels || {})};
      pendingIssueMode = {
        ...issue,
        title: String(issue.title || ''),
        severity: String(issue.severity || 'review'),
        scopeLabel: String(issue.scopeLabel || ''),
        targetNames,
        pairedNames,
        groupNames,
        target_surface_names: stringList(issue.target_surface_names?.length ? issue.target_surface_names : targetNames),
        paired_surface_names: stringList(issue.paired_surface_names?.length ? issue.paired_surface_names : pairedNames),
        group_surface_names: stringList(issue.group_surface_names?.length ? issue.group_surface_names : groupNames),
        before_vertices: vertexEvidence(issue.before_vertices),
        after_vertices: vertexEvidence(issue.after_vertices),
        roleLabels,
        role_labels: {...roleLabels}
      };
    }
    post({type: 'idfrepair:viewer-issue-mode', issue: pendingIssueMode});
  }

  function clearModel() {
    pendingModel = null;
    pendingSource = null;
    pendingRoots = [];
    pendingIssueMode = null;
    pendingOccupancy = null;
    resetOccupancyLayerUi();
    post({type: 'idfrepair:viewer-occupancy', payload: null});
    post({type: 'idfrepair:viewer-clear'});
  }

  function setLocale(locale) {
    pendingLocale = locale === 'en' ? 'en' : 'zh-CN';
    setOccupancyStatus(occupancyStatusState.key, occupancyStatusState.values);
    post({type: 'idfrepair:viewer-locale', locale: pendingLocale});
  }

  function clearOccupancyLayer() {
    loadOccupancy(null);
    resetOccupancyLayerUi();
  }

  window.addEventListener('message', (event) => {
    if (event.source !== iframe.contentWindow || event.origin !== window.location.origin) return;
    const message = event.data || {};
    if (message.type === 'idfrepair:viewer-ready') {
      ready = true;
      flush();
    }
    if (message.type === 'idfrepair:viewer-selected') {
      window.dispatchEvent(new CustomEvent('idfrepair:viewer-selected', {detail: message}));
    }
    if (message.type === 'idfrepair:viewer-occupancy-ready') {
      if (occupancyClear) occupancyClear.disabled = false;
      setOccupancyStatus('ready', {
        count: message.spaceCount,
        scenario: message.scenarioId,
        period: message.periodId
      });
      window.dispatchEvent(new CustomEvent('idfrepair:viewer-occupancy-ready', {detail: message}));
    }
    if (message.type === 'idfrepair:viewer-error') {
      if (message.reason === 'occupancy_payload_invalid') {
        pendingOccupancy = null;
        post({type: 'idfrepair:viewer-occupancy', payload: null});
        resetOccupancyLayerUi({status: 'invalid'});
      }
      window.dispatchEvent(new CustomEvent('idfrepair:viewer-error', {detail: message}));
    }
  });

  iframe.addEventListener('load', () => {
    ready = false;
    ping();
  });
  fileInput.addEventListener('change', () => {
    loadFile(fileInput.files?.[0]).catch(() => {
      window.dispatchEvent(new CustomEvent('idfrepair:viewer-error', {
        detail: {reason: 'local_file_read_failed'}
      }));
    });
  });
  occupancyInput?.addEventListener('change', async () => {
    const file = occupancyInput.files?.[0];
    if (!file) return;
    setOccupancyStatus('reading', {name: file.name});
    try {
      const payload = JSON.parse(await file.text());
      if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
        throw new Error('occupancy_payload_not_an_object');
      }
      setOccupancyStatus('validating');
      loadOccupancy(payload);
    } catch (_error) {
      pendingOccupancy = null;
      post({type: 'idfrepair:viewer-occupancy', payload: null});
      resetOccupancyLayerUi({status: 'invalid'});
    }
  });
  occupancyClear?.addEventListener('click', clearOccupancyLayer);

  window.IDFRepairViewer = Object.freeze({
    loadFile, loadText, loadOccupancy, focusRoots, showIssue, clearModel,
    clearOccupancyLayer, setLocale
  });
  window.requestAnimationFrame(ping);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeViewerBridge, {once: true});
  } else {
    initializeViewerBridge();
  }
})();
