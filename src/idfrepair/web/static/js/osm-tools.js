const DEFAULT_MAPPING_PAGE_SIZE = 50;

function compact(value) {
  return String(value ?? '').trim();
}

function integer(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : 0;
}

function diagnosticAdaptationCount(report = {}) {
  return (Array.isArray(report.diagnostic_adaptations) ? report.diagnostic_adaptations : [])
    .filter((row) => row?.adaptation === 'temporary_thermal_zone_for_unzoned_space')
    .reduce((total, row) => total + integer(row?.count), 0);
}

function summarizeOsmReport(report = {}) {
  const finalValidity = report.model_validity?.final || report.model_validity?.minimal || null;
  const validityErrors = integer(finalValidity?.error_count);
  const forwardErrors = [
    ...(Array.isArray(report.version_translator?.errors) ? report.version_translator.errors : []),
    ...(Array.isArray(report.forward_translator?.errors) ? report.forward_translator.errors : [])
  ];
  const derived = Boolean(compact(report.derived_idf_version));
  const diagnosisStatus = compact(report.diagnostic_status);
  const preflightComplete = [
    'PRECHECKED', 'PREPROCESSING_APPLIED', 'VALID', 'REPAIRED', 'NEEDS_INPUT',
    'UNSUPPORTED', 'SEARCH_EXHAUSTED', 'PROCESS_FAILED', 'ROLLED_BACK', 'LIMIT_REACHED',
    'DIAGNOSED'
  ].includes(diagnosisStatus);
  const diagnosisComplete = Boolean(diagnosisStatus) && ![
    'TRANSLATED', 'PRECHECK_REQUIRED', 'PRECHECKED', 'PREPROCESSING_APPLIED'
  ].includes(diagnosisStatus);
  const mapping = report.mapping_summary || {};
  const derivedAdaptationCount = diagnosticAdaptationCount(report);
  return Object.freeze({
    timeline: Object.freeze([
      Object.freeze({
        key: 'validity',
        state: !finalValidity ? 'pending' : finalValidity.valid ? 'complete' : 'attention',
        count: validityErrors
      }),
      Object.freeze({
        key: 'forward',
        state: forwardErrors.length ? 'attention' : derived ? 'complete' : 'pending',
        count: forwardErrors.length
      }),
      Object.freeze({
        key: 'preflight',
        state: preflightComplete ? 'complete' : 'pending',
        status: preflightComplete ? diagnosisStatus : null
      }),
      Object.freeze({
        key: 'diagnosis',
        state: diagnosisComplete ? 'complete' : 'pending',
        status: diagnosisComplete ? diagnosisStatus : null
      })
    ]),
    derivedAdaptationCount,
    sourceOsmModified: report.source_osm_modified === true,
    semanticEquivalenceClaimed: false,
    mapping: Object.freeze({
      mapped: integer(mapping.explicit_object_mappings),
      unsupported: integer(mapping.unsupported_object_mappings),
      temporary: derivedAdaptationCount,
      diagnosticMapped: integer(mapping.diagnostics_mapped_exact),
      diagnosticUnsupported: integer(mapping.diagnostics_unsupported)
    }),
    validityErrors
  });
}

function classifyValidityIssue(row = {}) {
  const raw = compact(row.raw);
  const haystack = [row.error_type, row.object_type, row.object_name, row.field, raw]
    .map(compact).join(' ').toLowerCase();
  let category = 'model_rule';
  if (/weather\s*file|useweatherfile|epw/.test(haystack)) category = 'weather';
  else if (/required|missing\s+(?:field|value)|must\s+be\s+set|is\s+empty/.test(haystack)) {
    category = 'required_value';
  } else if (/reference|not\s+found|does\s+not\s+exist|target/.test(haystack)) {
    category = 'reference';
  } else if (/surface|vertex|geometry|planar|area/.test(haystack)) category = 'geometry';
  else if (/duplicate|unique|already\s+exists/.test(haystack)) category = 'duplicate';
  const where = [row.object_type, row.object_name, row.field, row.scope]
    .map(compact).filter(Boolean).join(' · ') || '—';
  return Object.freeze({category, where, raw: raw || '—'});
}

function normalizeMapping(row = {}, index = 0) {
  const osm = row.osm_object || {};
  const derived = row.derived_idf_object || {};
  const status = compact(row.mapping_status);
  const mapped = status === 'MAPPED_EXACT' || status === 'EXPLICIT_EXACT_TYPE_NAME';
  const osmType = compact(osm.type || row.osm_object_type);
  const osmName = compact(osm.name || row.osm_object_name);
  const derivedType = compact(derived.type || row.derived_idf_object_type);
  const derivedName = compact(derived.name || row.derived_idf_object_name);
  const kind = row.finding_id || row.finding_stage ? 'finding' : 'object';
  return Object.freeze({
    id: compact(row.mapping_id || row.finding_id || `osm-mapping-${index}`),
    status,
    mapped,
    kind,
    osmType,
    osmName,
    osmHandle: compact(osm.handle || row.osm_handle),
    derivedType,
    derivedName,
    field: compact(derived.field),
    reason: compact(row.mapping_reason),
    original: row,
    searchText: [status, osmType, osmName, derivedType, derivedName, derived.field, row.family, row.message]
      .map(compact).join(' ').toLowerCase()
  });
}

function filterOsmMappings(rows = [], query = '', limit = DEFAULT_MAPPING_PAGE_SIZE) {
  const normalized = (Array.isArray(rows) ? rows : []).map(normalizeMapping);
  const needle = compact(query).toLowerCase();
  const matches = needle
    ? normalized.filter((row) => row.searchText.includes(needle))
    : normalized;
  const requested = Number.isFinite(Number(limit))
    ? Math.max(1, Math.trunc(Number(limit)))
    : DEFAULT_MAPPING_PAGE_SIZE;
  return Object.freeze({
    rows: Object.freeze(matches.slice(0, requested)),
    total: normalized.length,
    matched: matches.length,
    truncated: matches.length > requested,
    limit: requested
  });
}

const api = Object.freeze({
  DEFAULT_MAPPING_PAGE_SIZE,
  summarizeOsmReport,
  classifyValidityIssue,
  filterOsmMappings
});

globalThis.IDFRepairOsmTools = api;

export {DEFAULT_MAPPING_PAGE_SIZE, summarizeOsmReport, classifyValidityIssue, filterOsmMappings};
