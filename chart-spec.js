// chart-spec.js
//
// Contract for Lens chart visuals. The agent emits a chart spec alongside Data
// Story prose; a renderer (Task 2) consumes the spec and draws the visual
// inline in the Card body or in a Chat response. This module is the single
// source of truth for both ends of that handshake — schema, validator, and
// worked examples in one file so prompts, tests, and renderer all index off
// the same definitions.
//
// V1 covers five formats only, per the Lens Visualization Principle: bar,
// line, stat callout, funnel, table. Pies, radial gauges, sankeys, scatter
// plots, area stacks, and other elaborate formats are out of scope. The
// principle: the smallest visual that makes the reader say "ah, now I see
// it." If prose lands without a chart, no chart. Visuals never decorate.
//
// The validator is intentionally strict. Unknown top-level keys are rejected
// so the model cannot drift into decorative options (color, style, axis
// styling, gridline density, legend position) that the renderer will not
// honor anyway. Length caps come from the same principle — past them the
// chart stops adding clarity and the agent should pick a different format
// or leave the comparison in prose.
//
// Used by:
//   - tests/chart-spec.test.js              — schema invariants
//   - worker.js (Task 4)                    — prompt-time emission contract
//   - lens-demo renderer component (Task 2) — runtime consumer
//   - eval harness (Task 5)                 — multi-seed validation

export const CHART_FORMATS = Object.freeze(['bar', 'line', 'stat', 'funnel', 'table']);

export const CHART_FORMAT_DESCRIPTIONS = Object.freeze({
  bar:    'Compare a quantity across discrete categories. Up to 3 series for side-by-side comparison.',
  line:   'Show a trend over an ordered axis, typically time. Up to 3 series.',
  stat:   'Single headline number with optional comparison context.',
  funnel: 'Stage-to-stage progression with falloff between steps.',
  table:  'Structured side-by-side detail when prose cannot carry the comparison.'
});

// Caps from the Visualization Principle. Past these the chart stops adding
// clarity, the agent should pick a different format or leave the detail in
// prose. Min values guard against degenerate shapes (a one-point line, a
// zero-stage funnel, a one-column table).
export const CHART_SPEC_LIMITS = Object.freeze({
  bar:    { categories: { min: 1, max: 12 }, series:  { min: 1, max: 3  } },
  line:   { points:     { min: 2, max: 30 }, series:  { min: 1, max: 3  } },
  funnel: { stages:     { min: 2, max: 7  } },
  table:  { columns:    { min: 2, max: 5  }, rows:    { min: 2, max: 10 } }
});

export const VALUE_FORMATS = Object.freeze(['number', 'percent', 'currency', 'duration']);

export const COLUMN_FORMATS = Object.freeze(['number', 'percent', 'currency', 'duration', 'text', 'delta']);

export const COLUMN_ALIGNS = Object.freeze(['left', 'right']);

export const COMPARISON_DIRECTIONS = Object.freeze(['up', 'down', 'flat']);

const TITLE_MAX = 80;
const CAPTION_MAX = 140;

// Allowed top-level keys per format. Anything outside this set is rejected.
const ENVELOPE_KEYS = ['format', 'title', 'caption', 'valueFormat'];
const ALLOWED_TOP_KEYS = Object.freeze({
  bar:    new Set([...ENVELOPE_KEYS, 'categories', 'series', 'axisLabel']),
  line:   new Set([...ENVELOPE_KEYS, 'points',     'series', 'axisLabel']),
  stat:   new Set([...ENVELOPE_KEYS, 'value',      'comparison']),
  funnel: new Set([...ENVELOPE_KEYS, 'stages']),
  table:  new Set([...ENVELOPE_KEYS, 'columns',    'rows'])
});

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

const isPlainObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isFiniteNumber = (v) => typeof v === 'number' && Number.isFinite(v);
const isNonEmptyString = (v) => typeof v === 'string' && v.length > 0;

function pushErr(errors, path, message) {
  errors.push({ path, message });
}

function checkEnvelope(spec, errors) {
  if (spec.title !== undefined) {
    if (!isNonEmptyString(spec.title)) {
      pushErr(errors, 'title', 'must be a non-empty string when present');
    } else if (spec.title.length > TITLE_MAX) {
      pushErr(errors, 'title', `must be ${TITLE_MAX} characters or fewer`);
    }
  }
  if (spec.caption !== undefined) {
    if (!isNonEmptyString(spec.caption)) {
      pushErr(errors, 'caption', 'must be a non-empty string when present');
    } else if (spec.caption.length > CAPTION_MAX) {
      pushErr(errors, 'caption', `must be ${CAPTION_MAX} characters or fewer`);
    }
  }
  if (spec.valueFormat !== undefined && !VALUE_FORMATS.includes(spec.valueFormat)) {
    pushErr(errors, 'valueFormat', `must be one of: ${VALUE_FORMATS.join(', ')}`);
  }
}

function checkUnknownKeys(spec, format, errors) {
  const allowed = ALLOWED_TOP_KEYS[format];
  for (const key of Object.keys(spec)) {
    if (!allowed.has(key)) {
      pushErr(errors, key, `unknown key for format "${format}" (allowed: ${[...allowed].join(', ')})`);
    }
  }
}

function checkSeriesArray(series, expectedLength, axisName, errors) {
  if (!Array.isArray(series)) {
    pushErr(errors, 'series', 'must be an array');
    return;
  }
  const limits = CHART_SPEC_LIMITS.bar.series; // bar and line share the same series caps
  if (series.length < limits.min || series.length > limits.max) {
    pushErr(errors, 'series', `must contain ${limits.min} to ${limits.max} series`);
  }
  series.forEach((s, i) => {
    if (!isPlainObject(s)) {
      pushErr(errors, `series[${i}]`, 'must be an object');
      return;
    }
    const sKeys = Object.keys(s);
    const allowed = new Set(['name', 'values']);
    for (const k of sKeys) {
      if (!allowed.has(k)) pushErr(errors, `series[${i}].${k}`, 'unknown key (allowed: name, values)');
    }
    if (!isNonEmptyString(s.name)) {
      pushErr(errors, `series[${i}].name`, 'must be a non-empty string');
    }
    if (!Array.isArray(s.values)) {
      pushErr(errors, `series[${i}].values`, 'must be an array');
      return;
    }
    if (s.values.length !== expectedLength) {
      pushErr(errors, `series[${i}].values`, `length ${s.values.length} does not match ${axisName} length ${expectedLength}`);
    }
    s.values.forEach((v, j) => {
      if (!isFiniteNumber(v)) pushErr(errors, `series[${i}].values[${j}]`, 'must be a finite number');
    });
  });
}

function validateBar(spec, errors) {
  const { categories: catLim } = CHART_SPEC_LIMITS.bar;
  if (!Array.isArray(spec.categories)) {
    pushErr(errors, 'categories', 'must be an array');
  } else {
    if (spec.categories.length < catLim.min || spec.categories.length > catLim.max) {
      pushErr(errors, 'categories', `must contain ${catLim.min} to ${catLim.max} entries`);
    }
    spec.categories.forEach((c, i) => {
      if (!isNonEmptyString(c)) pushErr(errors, `categories[${i}]`, 'must be a non-empty string');
    });
    checkSeriesArray(spec.series, spec.categories.length, 'categories', errors);
  }
  if (spec.axisLabel !== undefined && !isNonEmptyString(spec.axisLabel)) {
    pushErr(errors, 'axisLabel', 'must be a non-empty string when present');
  }
}

function validateLine(spec, errors) {
  const { points: ptLim } = CHART_SPEC_LIMITS.line;
  if (!Array.isArray(spec.points)) {
    pushErr(errors, 'points', 'must be an array');
  } else {
    if (spec.points.length < ptLim.min || spec.points.length > ptLim.max) {
      pushErr(errors, 'points', `must contain ${ptLim.min} to ${ptLim.max} entries`);
    }
    spec.points.forEach((p, i) => {
      if (!isNonEmptyString(p)) pushErr(errors, `points[${i}]`, 'must be a non-empty string');
    });
    checkSeriesArray(spec.series, spec.points.length, 'points', errors);
  }
  if (spec.axisLabel !== undefined && !isNonEmptyString(spec.axisLabel)) {
    pushErr(errors, 'axisLabel', 'must be a non-empty string when present');
  }
}

function validateStat(spec, errors) {
  if (!isFiniteNumber(spec.value)) {
    pushErr(errors, 'value', 'must be a finite number');
  }
  if (spec.comparison !== undefined) {
    if (!isPlainObject(spec.comparison)) {
      pushErr(errors, 'comparison', 'must be an object when present');
      return;
    }
    const allowed = new Set(['value', 'label', 'direction']);
    for (const k of Object.keys(spec.comparison)) {
      if (!allowed.has(k)) pushErr(errors, `comparison.${k}`, 'unknown key (allowed: value, label, direction)');
    }
    if (!isFiniteNumber(spec.comparison.value)) {
      pushErr(errors, 'comparison.value', 'must be a finite number');
    }
    if (!isNonEmptyString(spec.comparison.label)) {
      pushErr(errors, 'comparison.label', 'must be a non-empty string');
    }
    if (spec.comparison.direction !== undefined && !COMPARISON_DIRECTIONS.includes(spec.comparison.direction)) {
      pushErr(errors, 'comparison.direction', `must be one of: ${COMPARISON_DIRECTIONS.join(', ')}`);
    }
  }
}

function validateFunnel(spec, errors) {
  const { stages: sLim } = CHART_SPEC_LIMITS.funnel;
  if (!Array.isArray(spec.stages)) {
    pushErr(errors, 'stages', 'must be an array');
    return;
  }
  if (spec.stages.length < sLim.min || spec.stages.length > sLim.max) {
    pushErr(errors, 'stages', `must contain ${sLim.min} to ${sLim.max} stages`);
  }
  let prev = Infinity;
  spec.stages.forEach((stg, i) => {
    if (!isPlainObject(stg)) {
      pushErr(errors, `stages[${i}]`, 'must be an object');
      return;
    }
    const allowed = new Set(['name', 'value']);
    for (const k of Object.keys(stg)) {
      if (!allowed.has(k)) pushErr(errors, `stages[${i}].${k}`, 'unknown key (allowed: name, value)');
    }
    if (!isNonEmptyString(stg.name)) {
      pushErr(errors, `stages[${i}].name`, 'must be a non-empty string');
    }
    if (!isFiniteNumber(stg.value)) {
      pushErr(errors, `stages[${i}].value`, 'must be a finite number');
    } else {
      if (stg.value < 0) {
        pushErr(errors, `stages[${i}].value`, 'must be non-negative');
      }
      if (stg.value > prev) {
        pushErr(errors, `stages[${i}].value`, 'funnel stages must be non-increasing — pick a different format if values rise');
      }
      prev = stg.value;
    }
  });
}

function validateTable(spec, errors) {
  const { columns: colLim, rows: rowLim } = CHART_SPEC_LIMITS.table;
  if (!Array.isArray(spec.columns)) {
    pushErr(errors, 'columns', 'must be an array');
    return;
  }
  if (spec.columns.length < colLim.min || spec.columns.length > colLim.max) {
    pushErr(errors, 'columns', `must contain ${colLim.min} to ${colLim.max} columns`);
  }
  const seenKeys = new Set();
  spec.columns.forEach((c, i) => {
    if (!isPlainObject(c)) {
      pushErr(errors, `columns[${i}]`, 'must be an object');
      return;
    }
    const allowed = new Set(['key', 'label', 'align', 'format']);
    for (const k of Object.keys(c)) {
      if (!allowed.has(k)) pushErr(errors, `columns[${i}].${k}`, 'unknown key (allowed: key, label, align, format)');
    }
    if (!isNonEmptyString(c.key)) {
      pushErr(errors, `columns[${i}].key`, 'must be a non-empty string');
    } else if (seenKeys.has(c.key)) {
      pushErr(errors, `columns[${i}].key`, `duplicate column key "${c.key}"`);
    } else {
      seenKeys.add(c.key);
    }
    if (!isNonEmptyString(c.label)) {
      pushErr(errors, `columns[${i}].label`, 'must be a non-empty string');
    }
    if (c.align !== undefined && !COLUMN_ALIGNS.includes(c.align)) {
      pushErr(errors, `columns[${i}].align`, `must be one of: ${COLUMN_ALIGNS.join(', ')}`);
    }
    if (c.format !== undefined && !COLUMN_FORMATS.includes(c.format)) {
      pushErr(errors, `columns[${i}].format`, `must be one of: ${COLUMN_FORMATS.join(', ')}`);
    }
  });

  if (!Array.isArray(spec.rows)) {
    pushErr(errors, 'rows', 'must be an array');
    return;
  }
  if (spec.rows.length < rowLim.min || spec.rows.length > rowLim.max) {
    pushErr(errors, 'rows', `must contain ${rowLim.min} to ${rowLim.max} rows`);
  }
  const colKeys = spec.columns.filter(c => isPlainObject(c) && isNonEmptyString(c.key)).map(c => c.key);
  const colByKey = new Map(spec.columns.filter(c => isPlainObject(c) && isNonEmptyString(c.key)).map(c => [c.key, c]));
  spec.rows.forEach((row, i) => {
    if (!isPlainObject(row)) {
      pushErr(errors, `rows[${i}]`, 'must be an object');
      return;
    }
    for (const k of Object.keys(row)) {
      if (!colByKey.has(k)) pushErr(errors, `rows[${i}].${k}`, `unknown column key (declared columns: ${colKeys.join(', ')})`);
    }
    for (const k of colKeys) {
      if (!(k in row)) {
        pushErr(errors, `rows[${i}].${k}`, 'missing value for declared column');
        continue;
      }
      const v = row[k];
      const col = colByKey.get(k);
      const isText = col.format === 'text';
      const isNumericFormat = !isText && col.format !== undefined;
      if (isText) {
        if (!isNonEmptyString(v)) pushErr(errors, `rows[${i}].${k}`, 'must be a non-empty string for text column');
      } else if (isNumericFormat) {
        if (!isFiniteNumber(v)) pushErr(errors, `rows[${i}].${k}`, `must be a finite number for ${col.format} column`);
      } else {
        if (!isFiniteNumber(v) && !isNonEmptyString(v)) pushErr(errors, `rows[${i}].${k}`, 'must be a finite number or non-empty string');
      }
    }
  });
}

const FORMAT_VALIDATORS = {
  bar:    validateBar,
  line:   validateLine,
  stat:   validateStat,
  funnel: validateFunnel,
  table:  validateTable
};

// validateChartSpec(spec) → { ok: true, spec } | { ok: false, errors }
//
// `errors` is an array of `{ path, message }`. Multiple errors are returned
// from a single call so the caller (or the agent reading a model retry) sees
// every problem at once.
export function validateChartSpec(spec) {
  const errors = [];
  if (!isPlainObject(spec)) {
    return { ok: false, errors: [{ path: '', message: 'spec must be an object' }] };
  }
  if (!CHART_FORMATS.includes(spec.format)) {
    return { ok: false, errors: [{ path: 'format', message: `must be one of: ${CHART_FORMATS.join(', ')}` }] };
  }
  checkUnknownKeys(spec, spec.format, errors);
  checkEnvelope(spec, errors);
  FORMAT_VALIDATORS[spec.format](spec, errors);
  return errors.length === 0 ? { ok: true, spec } : { ok: false, errors };
}

// ---------------------------------------------------------------------------
// Worked examples
// ---------------------------------------------------------------------------
//
// One canonical example per format. These ship into the agent prompt as
// few-shots and serve as fixtures for the renderer + eval harness. They
// pass validateChartSpec by construction (enforced in tests).

export const CHART_SPEC_EXAMPLES = Object.freeze({
  bar: {
    format: 'bar',
    caption: 'MQLs sourced in the last 30 days versus the prior 30.',
    valueFormat: 'number',
    categories: ['Paid', 'Organic', 'Partner', 'Events'],
    series: [
      { name: 'Last 30 days',  values: [320, 215, 90,  48] },
      { name: 'Prior 30 days', values: [285, 198, 112, 35] }
    ],
    axisLabel: 'MQLs'
  },
  line: {
    format: 'line',
    caption: 'Weekly trial-to-paid conversion, last 12 weeks.',
    valueFormat: 'percent',
    points: ['W1','W2','W3','W4','W5','W6','W7','W8','W9','W10','W11','W12'],
    series: [
      { name: 'Conversion', values: [5.2, 5.4, 5.1, 5.6, 6.0, 6.3, 6.1, 6.4, 6.8, 7.1, 7.3, 7.6] }
    ],
    axisLabel: '% of trials'
  },
  stat: {
    format: 'stat',
    valueFormat: 'percent',
    caption: 'Trial-to-paid conversion, trailing 30 days.',
    value: 6.8,
    comparison: {
      value: 5.4,
      label: 'versus prior 30 days',
      direction: 'up'
    }
  },
  funnel: {
    format: 'funnel',
    caption: 'Q4 deals from SQL through close.',
    valueFormat: 'number',
    stages: [
      { name: 'SQL',      value: 142 },
      { name: 'Demo',     value: 89  },
      { name: 'Proposal', value: 41  },
      { name: 'Closed',   value: 18  }
    ]
  },
  table: {
    format: 'table',
    caption: 'Win rate by segment, this quarter versus prior.',
    columns: [
      { key: 'segment', label: 'Segment',    align: 'left',  format: 'text'    },
      { key: 'rate',    label: 'Win Rate',   align: 'right', format: 'percent' },
      { key: 'delta',   label: 'vs Prior Q', align: 'right', format: 'delta'   }
    ],
    rows: [
      { segment: 'Enterprise', rate: 32, delta:  4 },
      { segment: 'Mid-Market', rate: 28, delta: -2 },
      { segment: 'SMB',        rate: 41, delta:  1 }
    ]
  }
});
