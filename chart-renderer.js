// chart-renderer.js
//
// Renders a validated chart spec (see chart-spec.js) to a React element using
// Recharts. Single component covers all five v1 formats: bar, line, stat
// callout, funnel, table.
//
// Browser:  loaded via the importmap in index.html (esm.sh hosts react,
//           react-dom, recharts). Use mountChart(spec, container, opts).
// Tests:    react-dom/server.renderToStaticMarkup turns the element into
//           HTML for snapshot assertions. See tests/chart-renderer.test.js.
// Caps:     trusted from validateChartSpec in chart-spec.js. The renderer
//           never re-clips. If a spec arrives oversized it is the validator's
//           job to have rejected it upstream.
//
// Visual style: minimum-effective. Calm two-color base palette, no
// decorative grid, no marketing color. Direction arrows for stat are
// neutral (no red/green) — Lens watches outcomes, not operators. Comparison
// is the user's judgement to make.

import React from 'react';
import {
  BarChart, Bar,
  LineChart, Line,
  FunnelChart, Funnel,
  XAxis, YAxis, CartesianGrid, Tooltip,
  LabelList, Cell
} from 'recharts';

const h = React.createElement;

const DEFAULT_OPTIONS = Object.freeze({
  width: 320,
  height: 180
});

// Calm two-color base. Primary for the latest/this-period series, neutral
// for the comparison series. Keeps the chart from competing with prose.
const PALETTE = Object.freeze({
  primary:    '#3F5BD9',
  comparison: '#9CA3AF',
  tertiary:   '#94B0F0',
  axis:       '#6B7280',
  axisLine:   '#D1D5DB',
  text:       '#3A3A3A'
});

const SERIES_COLORS = [PALETTE.primary, PALETTE.comparison, PALETTE.tertiary];

const FUNNEL_SHADES = ['#3F5BD9', '#5B73DD', '#788CE2', '#94A6E6', '#B0BFEB', '#CCD8EF', '#E8F1F4'];

// ---------------------------------------------------------------------------
// Value formatting
// ---------------------------------------------------------------------------

const numberFormatter = new Intl.NumberFormat('en-US');
const currencyFormatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

function formatValue(v, fmt) {
  if (typeof v !== 'number' || !Number.isFinite(v)) return String(v ?? '');
  switch (fmt) {
    case 'percent':  return `${trimDecimal(v)}%`;
    case 'currency': return currencyFormatter.format(v);
    case 'duration': return `${trimDecimal(v)}d`;
    case 'delta':    return `${v > 0 ? '+' : ''}${trimDecimal(v)}`;
    case 'number':
    default:         return numberFormatter.format(v);
  }
}

function trimDecimal(v) {
  // Show up to 1 decimal, drop trailing .0
  const rounded = Math.round(v * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

// ---------------------------------------------------------------------------
// Bar
// ---------------------------------------------------------------------------

function renderBar(spec, opts) {
  const data = spec.categories.map((cat, i) => {
    const row = { __category: cat };
    spec.series.forEach(s => { row[s.name] = s.values[i]; });
    return row;
  });
  const tickFormatter = (v) => formatValue(v, spec.valueFormat || 'number');

  const children = [
    h(CartesianGrid, { key: 'grid', stroke: PALETTE.axisLine, strokeDasharray: '2 4', vertical: false }),
    h(XAxis, {
      key: 'x',
      dataKey: '__category',
      tick: { fill: PALETTE.axis, fontSize: 11 },
      stroke: PALETTE.axisLine
    }),
    h(YAxis, {
      key: 'y',
      tick: { fill: PALETTE.axis, fontSize: 11 },
      stroke: PALETTE.axisLine,
      tickFormatter,
      label: spec.axisLabel
        ? { value: spec.axisLabel, angle: -90, position: 'insideLeft', fill: PALETTE.axis, fontSize: 11 }
        : undefined
    }),
    h(Tooltip, { key: 'tip', formatter: tickFormatter, cursor: { fill: 'rgba(63,91,217,0.06)' } }),
    ...spec.series.map((s, i) =>
      h(Bar, {
        key: `bar-${i}`,
        dataKey: s.name,
        fill: SERIES_COLORS[i % SERIES_COLORS.length],
        isAnimationActive: false,
        radius: [2, 2, 0, 0]
      })
    )
  ];

  return wrap(spec, opts,
    h(BarChart, {
      width: opts.width,
      height: opts.height,
      data,
      margin: { top: 8, right: 8, bottom: 8, left: 0 }
    }, ...children)
  );
}

// ---------------------------------------------------------------------------
// Line
// ---------------------------------------------------------------------------

function renderLine(spec, opts) {
  const data = spec.points.map((pt, i) => {
    const row = { __point: pt };
    spec.series.forEach(s => { row[s.name] = s.values[i]; });
    return row;
  });
  const tickFormatter = (v) => formatValue(v, spec.valueFormat || 'number');

  const children = [
    h(CartesianGrid, { key: 'grid', stroke: PALETTE.axisLine, strokeDasharray: '2 4', vertical: false }),
    h(XAxis, {
      key: 'x',
      dataKey: '__point',
      tick: { fill: PALETTE.axis, fontSize: 11 },
      stroke: PALETTE.axisLine
    }),
    h(YAxis, {
      key: 'y',
      tick: { fill: PALETTE.axis, fontSize: 11 },
      stroke: PALETTE.axisLine,
      tickFormatter,
      label: spec.axisLabel
        ? { value: spec.axisLabel, angle: -90, position: 'insideLeft', fill: PALETTE.axis, fontSize: 11 }
        : undefined
    }),
    h(Tooltip, { key: 'tip', formatter: tickFormatter }),
    ...spec.series.map((s, i) =>
      h(Line, {
        key: `line-${i}`,
        dataKey: s.name,
        stroke: SERIES_COLORS[i % SERIES_COLORS.length],
        strokeWidth: 2,
        dot: { r: 2, fill: SERIES_COLORS[i % SERIES_COLORS.length] },
        activeDot: { r: 4 },
        isAnimationActive: false
      })
    )
  ];

  return wrap(spec, opts,
    h(LineChart, {
      width: opts.width,
      height: opts.height,
      data,
      margin: { top: 8, right: 12, bottom: 8, left: 0 }
    }, ...children)
  );
}

// ---------------------------------------------------------------------------
// Stat callout
// ---------------------------------------------------------------------------

const DIRECTION_GLYPH = { up: '↑', down: '↓', flat: '→' };

function renderStat(spec, opts) {
  const fmt = spec.valueFormat || 'number';
  const valueText = formatValue(spec.value, fmt);
  const cmp = spec.comparison;

  const children = [
    h('div', {
      key: 'value',
      style: {
        fontSize: '36px',
        fontWeight: 600,
        color: PALETTE.text,
        lineHeight: 1.1,
        letterSpacing: '-0.02em'
      }
    }, valueText)
  ];

  if (cmp) {
    const direction = cmp.direction || deriveDirection(spec.value, cmp.value);
    const cmpText = `${DIRECTION_GLYPH[direction]} ${formatValue(cmp.value, fmt)} ${cmp.label}`;
    children.push(h('div', {
      key: 'cmp',
      style: {
        marginTop: '6px',
        fontSize: '13px',
        color: PALETTE.axis,
        lineHeight: 1.3
      }
    }, cmpText));
  }

  return wrap(spec, opts,
    h('div', {
      style: {
        width: opts.width,
        minHeight: opts.height,
        padding: '8px 0',
        boxSizing: 'border-box'
      }
    }, ...children)
  );
}

function deriveDirection(curr, prior) {
  if (curr > prior) return 'up';
  if (curr < prior) return 'down';
  return 'flat';
}

// ---------------------------------------------------------------------------
// Funnel
// ---------------------------------------------------------------------------

function renderFunnel(spec, opts) {
  const data = spec.stages.map((stg, i) => ({
    name: stg.name,
    value: stg.value,
    fill: FUNNEL_SHADES[i % FUNNEL_SHADES.length]
  }));
  const fmt = spec.valueFormat || 'number';

  return wrap(spec, opts,
    h(FunnelChart, {
      width: opts.width,
      height: opts.height,
      margin: { top: 8, right: 8, bottom: 8, left: 8 }
    },
      h(Tooltip, { formatter: (v) => formatValue(v, fmt) }),
      h(Funnel, {
        dataKey: 'value',
        data,
        isAnimationActive: false,
        stroke: '#fff',
        strokeWidth: 1
      },
        h(LabelList, {
          position: 'right',
          fill: PALETTE.text,
          stroke: 'none',
          fontSize: 12,
          dataKey: 'name'
        }),
        h(LabelList, {
          position: 'center',
          fill: '#fff',
          stroke: 'none',
          fontSize: 12,
          formatter: (v) => formatValue(v, fmt)
        })
      )
    )
  );
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

function renderTable(spec, opts) {
  const head = h('thead', { key: 'thead' },
    h('tr', null,
      ...spec.columns.map((c, i) =>
        h('th', {
          key: `th-${i}`,
          style: {
            textAlign: c.align || (c.format === 'text' || !c.format ? 'left' : 'right'),
            padding: '6px 10px',
            fontSize: '11px',
            fontWeight: 600,
            color: PALETTE.axis,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            borderBottom: `1px solid ${PALETTE.axisLine}`
          }
        }, c.label)
      )
    )
  );

  const body = h('tbody', { key: 'tbody' },
    ...spec.rows.map((row, ri) =>
      h('tr', { key: `tr-${ri}` },
        ...spec.columns.map((c, ci) => {
          const v = row[c.key];
          const formatted = c.format === 'text' ? v : formatValue(v, c.format || 'number');
          return h('td', {
            key: `td-${ri}-${ci}`,
            style: {
              textAlign: c.align || (c.format === 'text' || !c.format ? 'left' : 'right'),
              padding: '8px 10px',
              fontSize: '13px',
              color: PALETTE.text,
              borderBottom: ri === spec.rows.length - 1 ? 'none' : `1px solid ${PALETTE.axisLine}`,
              fontVariantNumeric: 'tabular-nums'
            }
          }, formatted);
        })
      )
    )
  );

  return wrap(spec, opts,
    h('table', {
      style: {
        width: '100%',
        borderCollapse: 'collapse',
        tableLayout: 'auto'
      }
    }, head, body)
  );
}

// ---------------------------------------------------------------------------
// Envelope wrapper (title, caption)
// ---------------------------------------------------------------------------

function wrap(spec, opts, body) {
  const children = [];
  if (spec.title) {
    children.push(h('div', {
      key: 'title',
      style: {
        fontSize: '13px',
        fontWeight: 600,
        color: PALETTE.text,
        marginBottom: '4px'
      }
    }, spec.title));
  }
  children.push(h('div', { key: 'body', className: 'lens-chart-body' }, body));
  if (spec.caption) {
    children.push(h('div', {
      key: 'caption',
      style: {
        fontSize: '11px',
        color: PALETTE.axis,
        marginTop: '6px',
        lineHeight: 1.35
      }
    }, spec.caption));
  }
  return h('div', {
    className: `lens-chart lens-chart-${spec.format}`,
    'data-format': spec.format,
    style: { width: opts.width }
  }, ...children);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

const FORMAT_RENDERERS = {
  bar:    renderBar,
  line:   renderLine,
  stat:   renderStat,
  funnel: renderFunnel,
  table:  renderTable
};

// renderChartElement(spec, options?) → React element
//
// Caller is responsible for passing a validated spec (see validateChartSpec
// in chart-spec.js). Options:
//   width  — px width of the chart body (default 320)
//   height — px height of the chart body (default 180)
//
// Returns null for unknown formats. The renderer trusts the validator's
// caps and shape guarantees and does no defensive re-clipping.
export function renderChartElement(spec, options = {}) {
  const renderer = FORMAT_RENDERERS[spec?.format];
  if (!renderer) return null;
  const opts = { ...DEFAULT_OPTIONS, ...options };
  return renderer(spec, opts);
}

// mountChart(spec, container, options?) — browser convenience.
// Lazily imports react-dom/client so node tests do not pay the cost.
export async function mountChart(spec, container, options = {}) {
  const element = renderChartElement(spec, options);
  if (!element) return null;
  const { createRoot } = await import('react-dom/client');
  const root = createRoot(container);
  root.render(element);
  return root;
}

export const __palette = PALETTE;
export const __formatValue = formatValue;
