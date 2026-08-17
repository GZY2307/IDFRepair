'use strict';

((root, factory) => {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.IDFRepairWorkflow = api;
})(typeof globalThis === 'object' ? globalThis : this, () => {
  function normalizeVersion(value) {
    const parts = String(value || '').trim().replace(/^[vV]/, '').split('.');
    while (parts.length > 1 && parts.at(-1) === '0') parts.pop();
    return parts.join('.');
  }

  function runtimeIdForText(text, runtimes = [], fallback = null) {
    const uncommented = String(text || '')
      .split(/\r?\n/)
      .map((line) => line.replace(/!.*$/, ''))
      .join('\n');
    const declared = uncommented.match(/(?:^|;)\s*Version\s*,\s*([^;,\s]+)/i)?.[1];
    if (!declared) return fallback;
    const target = normalizeVersion(declared);
    return runtimes.find((runtime) => normalizeVersion(runtime.version) === target)?.runtime_id
      || fallback;
  }

  function derivePrimaryAction(context = {}) {
    if (!context.hasFile) {
      return {action: 'choose-file', labelKey: 'actions.choose_file', disabled: false};
    }
    if (!context.runtimeReady) {
      return {action: 'runtime-required', labelKey: 'actions.runtime_required', disabled: true};
    }
    if (context.busy) {
      const labelKey = context.busy === 'repair' || context.busy === 'run'
        ? 'progress.repair'
        : context.busy === 'diagnose'
          ? 'progress.diagnose'
          : 'progress.preparing';
      return {action: 'busy', labelKey, disabled: true};
    }
    if (context.reportStatus === 'NEEDS_INPUT') {
      return {action: 'focus-input', labelKey: 'actions.review_input', disabled: false};
    }
    const terminalOutput = context.outputReady && (
      context.lastCompletedAction === 'run'
      || (context.lastCompletedAction === 'diagnose' && context.mode === 'analyze-only')
    );
    if (terminalOutput) {
      const labelKey = context.reportStatus === 'REPAIRED'
        ? 'actions.download_repaired'
        : 'actions.download_unchanged';
      return {action: 'download', labelKey, disabled: false};
    }
    if (context.sessionId && context.lastCompletedAction === 'diagnose') {
      return {action: 'repair', labelKey: 'actions.run', disabled: false};
    }
    return {action: 'diagnose', labelKey: 'actions.diagnose', disabled: false};
  }

  return Object.freeze({derivePrimaryAction, runtimeIdForText});
});
