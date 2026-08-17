'use strict';

(() => {
  const iframe = document.querySelector('#model-viewer');
  const fileInput = document.querySelector('#idf-file');
  if (!iframe || !fileInput) return;

  let ready = false;
  let pendingModel = null;
  let pendingSource = null;
  let pendingRoots = [];
  let pendingIssueMode = null;
  let pendingLocale = document.documentElement.lang || 'zh-CN';

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
  }

  function loadText(text, name = 'IDF geometry') {
    pendingSource = null;
    pendingModel = {text: String(text || ''), name};
    post({type: 'idfrepair:viewer-load', ...pendingModel});
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
    post({type: 'idfrepair:viewer-clear'});
  }

  function setLocale(locale) {
    pendingLocale = locale === 'en' ? 'en' : 'zh-CN';
    post({type: 'idfrepair:viewer-locale', locale: pendingLocale});
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
    if (message.type === 'idfrepair:viewer-error') {
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

  window.IDFRepairViewer = Object.freeze({loadFile, loadText, focusRoots, showIssue, clearModel, setLocale});
  window.requestAnimationFrame(ping);
})();
