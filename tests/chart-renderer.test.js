import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { renderToStaticMarkup } from 'react-dom/server';

import { CHART_SPEC_EXAMPLES, validateChartSpec, CHART_FORMATS } from '../chart-spec.js';
import { renderChartElement, __formatValue } from '../chart-renderer.js';

// Snapshot test fixtures: the same CHART_SPEC_EXAMPLES that ship as agent
// few-shots and as renderer fixtures. Single source of truth across the
// chart-rendering chain.

function html(spec, opts) {
  const el = renderChartElement(spec, opts);
  return renderToStaticMarkup(el);
}

describe('renderChartElement — every example renders', () => {
  for (const fmt of CHART_FORMATS) {
    test(`${fmt}: produces non-empty HTML for the canonical example`, () => {
      const spec = CHART_SPEC_EXAMPLES[fmt];
      const out = html(spec);
      assert.ok(out.length > 100, `${fmt} output suspiciously short: ${out.length} chars`);
      assert.ok(out.includes(`lens-chart-${fmt}`), `${fmt}: envelope class missing`);
      assert.ok(out.includes(`data-format="${fmt}"`), `${fmt}: data-format attribute missing`);
    });
  }
});

describe('renderChartElement — caption and title surface in output', () => {
  test('caption is rendered when present', () => {
    const out = html(CHART_SPEC_EXAMPLES.bar);
    assert.ok(out.includes(CHART_SPEC_EXAMPLES.bar.caption), 'bar caption missing from output');
  });

  test('title is rendered when present', () => {
    const out = html({ ...CHART_SPEC_EXAMPLES.stat, title: 'Trial-to-paid' });
    assert.ok(out.includes('Trial-to-paid'));
  });
});

// Bar -----------------------------------------------------------------

describe('renderChartElement — bar', () => {
  test('emits SVG with category labels visible', () => {
    const out = html(CHART_SPEC_EXAMPLES.bar);
    assert.ok(out.includes('<svg'), 'svg root missing');
    for (const cat of CHART_SPEC_EXAMPLES.bar.categories) {
      assert.ok(out.includes(cat), `category "${cat}" missing from output`);
    }
  });

  test('emits one Bar layer per series', () => {
    const out = html(CHART_SPEC_EXAMPLES.bar);
    // Each Bar series produces a recharts-bar-rectangles group
    const layers = out.match(/recharts-bar-rectangles/g) || [];
    assert.equal(layers.length, CHART_SPEC_EXAMPLES.bar.series.length);
  });

  test('axis label shows when present', () => {
    const out = html(CHART_SPEC_EXAMPLES.bar);
    assert.ok(out.includes('MQLs'), 'axisLabel "MQLs" missing');
  });
});

// Line ----------------------------------------------------------------

describe('renderChartElement — line', () => {
  test('emits svg containing every point label', () => {
    const out = html(CHART_SPEC_EXAMPLES.line);
    assert.ok(out.includes('<svg'));
    for (const pt of CHART_SPEC_EXAMPLES.line.points) {
      assert.ok(out.includes(`>${pt}<`) || out.includes(pt), `point "${pt}" missing`);
    }
  });

  test('renders one path per series', () => {
    const out = html(CHART_SPEC_EXAMPLES.line);
    const lines = out.match(/recharts-line-curve/g) || [];
    assert.equal(lines.length, CHART_SPEC_EXAMPLES.line.series.length);
  });
});

// Stat ----------------------------------------------------------------

describe('renderChartElement — stat', () => {
  test('renders the headline value formatted', () => {
    const out = html(CHART_SPEC_EXAMPLES.stat);
    // valueFormat=percent → "6.8%"
    assert.ok(out.includes('6.8%'), 'formatted value missing');
  });

  test('renders comparison value and label', () => {
    const out = html(CHART_SPEC_EXAMPLES.stat);
    assert.ok(out.includes('5.4%'), 'comparison value missing');
    assert.ok(out.includes('versus prior 30 days'), 'comparison label missing');
  });

  test('renders direction glyph (↑ for up)', () => {
    const out = html(CHART_SPEC_EXAMPLES.stat);
    assert.ok(out.includes('↑') || out.includes('&#8593;'), 'up arrow missing');
  });

  test('omits comparison when not provided', () => {
    const out = html({ format: 'stat', value: 42, valueFormat: 'percent' });
    assert.ok(out.includes('42%'));
    // No arrows when there's no comparison
    assert.ok(!out.includes('↑') && !out.includes('↓') && !out.includes('→'),
      'direction arrow leaked without comparison');
  });

  test('derives direction from values when not specified', () => {
    const noDir = { ...CHART_SPEC_EXAMPLES.stat, comparison: { value: 5.4, label: 'versus prior' } };
    const out = html(noDir);
    assert.ok(out.includes('↑'), 'direction not derived from value > comparison.value');
  });
});

// Funnel --------------------------------------------------------------

describe('renderChartElement — funnel', () => {
  test('renders every stage name', () => {
    const out = html(CHART_SPEC_EXAMPLES.funnel);
    for (const stg of CHART_SPEC_EXAMPLES.funnel.stages) {
      assert.ok(out.includes(stg.name), `stage "${stg.name}" missing`);
    }
  });

  test('renders formatted stage values', () => {
    const out = html(CHART_SPEC_EXAMPLES.funnel);
    for (const stg of CHART_SPEC_EXAMPLES.funnel.stages) {
      assert.ok(out.includes(String(stg.value)), `stage value ${stg.value} missing`);
    }
  });
});

// Table ---------------------------------------------------------------

describe('renderChartElement — table', () => {
  test('renders an HTML table', () => {
    const out = html(CHART_SPEC_EXAMPLES.table);
    assert.ok(out.includes('<table'), '<table> missing');
    assert.ok(out.includes('<thead'), '<thead> missing');
    assert.ok(out.includes('<tbody'), '<tbody> missing');
  });

  test('renders every column label', () => {
    const out = html(CHART_SPEC_EXAMPLES.table);
    for (const c of CHART_SPEC_EXAMPLES.table.columns) {
      assert.ok(out.includes(c.label), `column label "${c.label}" missing`);
    }
  });

  test('renders every row, with delta column signed', () => {
    const out = html(CHART_SPEC_EXAMPLES.table);
    assert.ok(out.includes('Enterprise'));
    assert.ok(out.includes('32%'));
    assert.ok(out.includes('+4'));   // delta column adds sign
    assert.ok(out.includes('-2'));
    assert.ok(out.includes('+1'));
  });
});

// Format helper -------------------------------------------------------

describe('formatValue', () => {
  test('percent', () => {
    assert.equal(__formatValue(6.8, 'percent'), '6.8%');
    assert.equal(__formatValue(7,   'percent'), '7%');
  });
  test('currency', () => {
    assert.equal(__formatValue(320, 'currency'), '$320');
  });
  test('duration', () => {
    assert.equal(__formatValue(47, 'duration'), '47d');
  });
  test('delta is signed', () => {
    assert.equal(__formatValue(4,  'delta'), '+4');
    assert.equal(__formatValue(-2, 'delta'), '-2');
    assert.equal(__formatValue(0,  'delta'), '0');
  });
  test('number uses thousands separator', () => {
    assert.equal(__formatValue(1840, 'number'), '1,840');
  });
});

// Round-trip with validator ------------------------------------------

describe('every example survives validate → render', () => {
  for (const fmt of CHART_FORMATS) {
    test(`${fmt}: validateChartSpec accepts and renderChartElement renders`, () => {
      const result = validateChartSpec(CHART_SPEC_EXAMPLES[fmt]);
      assert.equal(result.ok, true);
      const out = html(result.spec);
      assert.ok(out.length > 100);
    });
  }
});
