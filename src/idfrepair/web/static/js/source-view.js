const FIELD_COPY = Object.freeze({
  'zh-CN': {
    types: {alpha: '文字', real: '数字', integer: '整数', choice: '选项', 'object-list': '对象引用', node: '节点引用'},
    required: '必填', optional: '可选', available: '这是当前 EnergyPlus 版本对该字段的定义。',
    unavailable: '当前 EnergyPlus 版本的字段规则中没有找到这个定义；请保留原始值并人工复核。'
  },
  en: {
    types: {alpha: 'Text', real: 'Number', integer: 'Integer', choice: 'Choice', 'object-list': 'Object reference', node: 'Node reference'},
    required: 'Required', optional: 'Optional', available: 'This is the field definition for the current EnergyPlus version.',
    unavailable: 'No definition for this field was found in the current EnergyPlus version; preserve the original value and review it manually.'
  }
});

function normalizedLines(text) {
  const lines = String(text ?? '').split(/\r\n|\r|\n/);
  if (lines.length > 1 && lines.at(-1) === '') lines.pop();
  return lines;
}

function sourceRows(payload = {}) {
  const firstLine = Number(payload.context_line_start || 1);
  const fieldLine = Number(payload.field_line || 0);
  const start = Math.max(0, Number(payload.field_column_start || 1) - 1);
  const end = Math.max(start, Number(payload.field_column_end || payload.field_column_start || 1) - 1);
  return normalizedLines(payload.text).map((text, index) => {
    const lineNumber = firstLine + index;
    const marked = lineNumber === fieldLine && Number.isFinite(start) && Number.isFinite(end);
    return {
      lineNumber,
      text,
      marked,
      before: marked ? text.slice(0, start) : text,
      mark: marked ? text.slice(start, end) : '',
      after: marked ? text.slice(end) : ''
    };
  });
}

function node(documentRef, tag, className, text) {
  const item = documentRef.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = String(text);
  return item;
}

function renderSourceContext(container, payload, options = {}) {
  const documentRef = options.documentRef || globalThis.document;
  container.replaceChildren();
  if (!payload || typeof payload.text !== 'string') {
    container.append(node(documentRef, 'p', 'source-error', options.errorText || 'Source context is unavailable.'));
    return {ok: false, rowCount: 0};
  }
  const rows = sourceRows(payload);
  const list = node(documentRef, 'div', 'source-lines');
  for (const row of rows) {
    const line = node(documentRef, 'div', `source-line${row.marked ? ' field-marked' : ''}`);
    line.setAttribute('data-line', row.lineNumber);
    line.append(node(documentRef, 'span', 'source-line-number', row.lineNumber));
    const code = node(documentRef, 'code', 'source-line-code');
    if (row.marked) {
      code.append(
        node(documentRef, 'span', 'source-before', row.before),
        node(documentRef, 'mark', 'source-field-mark', row.mark),
        node(documentRef, 'span', 'source-after', row.after)
      );
    } else {
      code.textContent = row.text;
    }
    line.append(code);
    list.append(line);
  }
  container.append(list);
  return {ok: true, rowCount: rows.length, truncated: Boolean(payload.truncated)};
}

function iddFieldPresentation(field = {}, locale = 'zh-CN') {
  const language = locale === 'en' ? 'en' : 'zh-CN';
  const copy = FIELD_COPY[language];
  const available = field.definition_available === true;
  const rawType = String(field.data_type || '');
  const allowed = Array.isArray(field.keys) && field.keys.length
    ? [...field.keys]
    : [...(field.object_lists || []), ...(field.references || [])];
  return {
    available,
    fieldName: field.field_name || null,
    currentValue: field.current_value ?? '',
    dataType: copy.types[rawType] || rawType || '—',
    required: field.required ? copy.required : copy.optional,
    defaultValue: field.default ?? null,
    units: field.units || null,
    minimum: field.minimum ?? null,
    maximum: field.maximum ?? null,
    allowed,
    extensible: Boolean(field.extensible),
    explanation: available ? copy.available : copy.unavailable,
    raw: field
  };
}

const api = Object.freeze({iddFieldPresentation, renderSourceContext, sourceRows});
globalThis.IDFRepairSourceView = api;

export {iddFieldPresentation, renderSourceContext, sourceRows};
