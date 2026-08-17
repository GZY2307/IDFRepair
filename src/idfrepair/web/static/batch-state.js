'use strict';

((root, factory) => {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.IDFRepairBatch = api;
})(typeof globalThis === 'object' ? globalThis : this, () => {
  const ACTIVE_STATES = new Set([
    'QUEUED', 'PREPARING', 'DIAGNOSING', 'REPAIRING', 'VALIDATING'
  ]);
  const TERMINAL_BATCH_STATES = new Set([
    'COMPLETED', 'COMPLETED_WITH_ACTION_REQUIRED', 'CANCELLED'
  ]);

  function normalizeLogicalPath(value) {
    const raw = String(value || '').replaceAll('\\', '/');
    if (!raw || raw.startsWith('/')) throw new Error('batch_path_invalid');
    const parts = raw.split('/').filter((part) => part && part !== '.');
    if (!parts.length || parts.some((part) => part === '..')) {
      throw new Error('batch_path_escape');
    }
    return parts.join('/');
  }

  function normalizeVersion(value) {
    const parts = String(value || '').trim().replace(/^[vV]/, '').split('.');
    while (parts.length > 1 && parts.at(-1) === '0') parts.pop();
    return parts.join('.');
  }

  function idfVersionForText(text) {
    const uncommented = String(text || '')
      .split(/\r?\n/)
      .map((line) => line.replace(/!.*$/, ''))
      .join('\n');
    const declared = uncommented.match(/(?:^|;)\s*Version\s*,\s*([^;,\s]+)/i)?.[1];
    return declared ? normalizeVersion(declared) : null;
  }

  function versionsMatch(left, right) {
    return Boolean(left && right && normalizeVersion(left) === normalizeVersion(right));
  }

  function runtimeIdForVersion(version, runtimes = []) {
    if (!version) return null;
    return runtimes.find((runtime) => versionsMatch(runtime.version, version))?.runtime_id || null;
  }

  function summarizeBatchFiles(rows = []) {
    const idfs = rows.filter((row) => String(row.logicalPath || '').toLowerCase().endsWith('.idf'));
    const duplicateHints = new Map();
    for (const row of idfs) {
      const hint = row.duplicateHintKey || row.sha256;
      if (!row.readable || !hint) continue;
      duplicateHints.set(hint, (duplicateHints.get(hint) || 0) + 1);
    }
    return {
      totalIdfs: idfs.length,
      totalSize: idfs.reduce((total, row) => total + Number(row.size || 0), 0),
      maxDepth: idfs.reduce((depth, row) => Math.max(
        depth,
        String(row.logicalPath || '').split('/').filter(Boolean).length
      ), 0),
      duplicateContent: [...duplicateHints.values()].reduce(
        (total, count) => total + Math.max(0, count - 1),
        0
      ),
      unreadable: idfs.filter((row) => !row.readable).length,
      invalidExtension: rows.filter((row) => {
        const path = String(row.logicalPath || '').toLowerCase();
        return !path.endsWith('.idf') && !row.isZip && !path.endsWith('.zip');
      }).length
    };
  }

  function recordCategory(state) {
    if (ACTIVE_STATES.has(state)) return 'processing';
    if (state === 'REPAIRED') return 'repaired';
    if (state === 'VALID') return 'valid';
    if (state === 'NEEDS_INPUT') return 'action-required';
    if (state === 'UNSUPPORTED') return 'unsupported';
    return 'failed';
  }

  function filterBatchRecords(records = [], filter = 'all') {
    if (!filter || filter === 'all') return [...records];
    return records.filter((record) => recordCategory(record.state) === filter);
  }

  function isBatchTerminal(state) {
    return TERMINAL_BATCH_STATES.has(state);
  }

  return Object.freeze({
    filterBatchRecords,
    idfVersionForText,
    isBatchTerminal,
    normalizeLogicalPath,
    recordCategory,
    runtimeIdForVersion,
    versionsMatch,
    summarizeBatchFiles
  });
});
