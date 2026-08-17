const RETRYABLE_STATES = new Set([
  'FAILED', 'NEEDS_INPUT', 'UNSUPPORTED', 'SEARCH_EXHAUSTED'
]);

const STATUS_ORDER = new Map([
  ['NEEDS_INPUT', 0],
  ['FAILED', 1],
  ['SEARCH_EXHAUSTED', 2],
  ['UNSUPPORTED', 3],
  ['PREPARING', 4],
  ['DIAGNOSING', 5],
  ['REPAIRING', 6],
  ['VALIDATING', 7],
  ['QUEUED', 8],
  ['REPAIRED', 9],
  ['VALID', 10],
  ['CANCELLED', 11]
]);

function normalizeLogicalPath(value) {
  const raw = String(value || '').replaceAll('\\', '/');
  const parts = raw.split('/').filter((part) => part && part !== '.');
  if (!parts.length || raw.startsWith('/') || parts.some((part) => part === '..')) {
    throw new Error('batch_path_invalid');
  }
  return parts.join('/');
}

function lightweightFileIdentity(file = {}, logicalPath = '') {
  const normalized = normalizeLogicalPath(logicalPath || file.name);
  const basename = normalized.split('/').at(-1) || normalized;
  const size = Math.max(0, Number(file.size || 0));
  const lastModified = Math.max(0, Number(file.lastModified || 0));
  const duplicateHintKey = [basename.toLocaleLowerCase('en-US'), size, lastModified].join('|');
  return Object.freeze({
    logicalPath: normalized,
    basename,
    size,
    lastModified,
    duplicateHintKey,
    stableKey: [normalized.toLocaleLowerCase('en-US'), size, lastModified].join('|')
  });
}

function deriveBatchLayout(snapshot = null, viewportWidth = 1440) {
  const status = String(snapshot?.status || 'CREATED').toUpperCase();
  const started = !['', 'CREATED'].includes(status);
  return Object.freeze({
    resultsFirst: started,
    preparationCollapsed: started,
    recordPresentation: Number(viewportWidth) <= 520 ? 'cards' : 'table',
    status
  });
}

function valueForSort(row, sortBy) {
  if (sortBy === 'duration') {
    const value = Number(row?.duration_seconds);
    return Number.isFinite(value) && row?.duration_seconds !== null ? value : Number.POSITIVE_INFINITY;
  }
  if (sortBy === 'issues') return Number(row?.issue_count || 0);
  if (sortBy === 'status') return STATUS_ORDER.get(String(row?.state || '').toUpperCase()) ?? 99;
  return String(row?.logical_name || '').toLocaleLowerCase('en-US');
}

function sortBatchRecords(records = [], options = {}) {
  const query = String(options.query || '').trim().toLocaleLowerCase('en-US');
  const sortBy = ['path', 'status', 'duration', 'issues'].includes(options.sortBy)
    ? options.sortBy
    : 'path';
  const direction = options.direction === 'desc' ? -1 : 1;
  return (Array.isArray(records) ? records : [])
    .map((row, index) => ({row, index}))
    .filter(({row}) => {
      if (!query) return true;
      return [row?.logical_name, row?.state, row?.message]
        .map((value) => String(value || '').toLocaleLowerCase('en-US'))
        .some((value) => value.includes(query));
    })
    .sort((left, right) => {
      const a = valueForSort(left.row, sortBy);
      const b = valueForSort(right.row, sortBy);
      if (a === b) return left.index - right.index;
      if (typeof a === 'string' && typeof b === 'string') return a.localeCompare(b) * direction;
      if (!Number.isFinite(a)) return 1;
      if (!Number.isFinite(b)) return -1;
      return (a < b ? -1 : 1) * direction;
    })
    .map(({row}) => row);
}

function isRecordRetryEligible(record = {}) {
  return RETRYABLE_STATES.has(String(record.state || '').toUpperCase());
}

function estimateRemainingSeconds(records = [], remainingCount = 0) {
  const durations = (Array.isArray(records) ? records : [])
    .map((row) => Number(row?.duration_seconds))
    .filter((value) => Number.isFinite(value) && value >= 0);
  if (durations.length < 3) return null;
  const remaining = Math.max(0, Math.trunc(Number(remainingCount || 0)));
  const mean = durations.reduce((total, value) => total + value, 0) / durations.length;
  return Math.round(mean * remaining);
}

const api = Object.freeze({
  deriveBatchLayout,
  estimateRemainingSeconds,
  isRecordRetryEligible,
  lightweightFileIdentity,
  sortBatchRecords
});

globalThis.IDFRepairBatchWorkbench = api;

export {
  deriveBatchLayout,
  estimateRemainingSeconds,
  isRecordRetryEligible,
  lightweightFileIdentity,
  sortBatchRecords
};
