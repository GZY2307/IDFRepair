const COPY = Object.freeze({
  'zh-CN': {
    unknown: '系统已记录这个问题，但还没有更具体的通俗说明。',
    file: '整个 IDF 文件',
    where: '位置',
    energyplus: '这个问题来自 EnergyPlus 检查；它可能阻止仿真或使结果不可靠。',
    safe: '现有证据足以准备一个受限改法，但只有通过全部检查后才会写入结果。',
    input: '文件里没有足够证据判断设计意图，需要您在列出的有限选项中选择。',
    unsupported: '当前规则不能据此生成可靠改法；请人工查看原文位置和现有证据后处理。',
    audit: '这是模型一致性检查发现的建模冲突或风险提示，不是 EnergyPlus ERR；模型即使能运行也可能出现此项。',
    auditNext: '对照三维位置、相邻表面和 IDF 原文复核；本检查不会直接修改文件。',
    experimental: '这是实验工具生成的预览证据，不代表问题已被确认，也不会直接修改 IDF。',
    experimentalNext: '先对照原始与预览坐标；确认依据充分后再进入正式、可验证的修复流程。',
    genericNext: '查看定位与证据，再选择页面提供的下一步。'
  },
  en: {
    unknown: 'The issue was recorded, but no more specific plain-language explanation is available yet.',
    file: 'the whole IDF file',
    where: 'Location',
    energyplus: 'This issue came from an EnergyPlus check and may block simulation or make results unreliable.',
    safe: 'The evidence can support one bounded change, but it is written only after every check passes.',
    input: 'The file does not contain enough evidence to determine design intent, so you must choose from the listed finite options.',
    unsupported: 'Current rules cannot produce a reliable change; inspect the source location and available evidence manually.',
    audit: 'This is a model-consistency conflict or risk flag, not an EnergyPlus ERR. A runnable model can still receive this finding.',
    auditNext: 'Review the 3D location, adjacent surfaces, and IDF source. This check does not directly change the file.',
    experimental: 'This is preview evidence from an experimental tool; it neither confirms an issue nor directly changes the IDF.',
    experimentalNext: 'Compare original and preview coordinates first, then use the formal validated repair flow only when evidence is sufficient.',
    genericNext: 'Review the location and evidence, then choose an available next step.'
  }
});

const SEVERITY = Object.freeze({
  'zh-CN': {error: '确定性冲突', warning: '风险提示', review: '建议复核'},
  en: {error: 'Deterministic conflict', warning: 'Risk flag', review: 'Suggested review'}
});

function compact(value) {
  return String(value ?? '').trim();
}

function auditSeverityLabel(severity, locale = 'zh-CN') {
  const language = locale === 'en' ? 'en' : 'zh-CN';
  return SEVERITY[language][compact(severity).toLowerCase()] || compact(severity) || SEVERITY[language].review;
}

function locationText(row, copy) {
  const parts = [
    row.zone || row.zone_name || row.surface?.zone,
    row.story || row.building_story || row.elevation_group,
    row.object_type || row.surface?.object_type,
    row.object_name || row.surface?.name,
    row.field_name
  ].map(compact).filter(Boolean);
  return parts.length ? `${copy.where}：${parts.join(' · ')}` : `${copy.where}：${copy.file}`;
}

function issueExplanation(row = {}, options = {}) {
  const locale = options.locale === 'en' ? 'en' : 'zh-CN';
  const copy = COPY[locale];
  const kind = compact(row.kind || 'energyplus').toLowerCase();
  const support = compact(row.support_status).toLowerCase();
  const what = compact(row.what || row.title || row.presentation?.title || row.message) || copy.unknown;
  const where = compact(row.where) || locationText(row, copy);
  let importance = compact(row.importance || row.summary || row.presentation?.summary);
  let next = compact(row.next || row.action || row.presentation?.action);
  if (kind === 'audit') {
    if (!row.preflight_kind) {
      importance = importance ? `${importance} ${copy.audit}` : copy.audit;
      next ||= copy.auditNext;
    }
  } else if (kind === 'experimental') {
    importance ||= copy.experimental;
    next ||= copy.experimentalNext;
  } else {
    importance ||= copy.energyplus;
    if (support === 'safe-auto') next ||= copy.safe;
    else if (support === 'interactive') next ||= copy.input;
    else if (['unsupported', 'disabled'].includes(support)) next ||= copy.unsupported;
    else next ||= copy.genericNext;
  }
  return {what, where, importance, next, kind, severity: compact(row.severity), technical: row};
}

const api = Object.freeze({auditSeverityLabel, issueExplanation});
globalThis.IDFRepairInspector = api;

export {auditSeverityLabel, issueExplanation};
