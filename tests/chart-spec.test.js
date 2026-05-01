import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import {
  CHART_FORMATS,
  CHART_SPEC_LIMITS,
  CHART_SPEC_EXAMPLES,
  VALUE_FORMATS,
  COLUMN_FORMATS,
  COMPARISON_DIRECTIONS,
  validateChartSpec
} from '../chart-spec.js';

// Helpers ---------------------------------------------------------------

const clone = (v) => JSON.parse(JSON.stringify(v));

function expectOk(spec) {
  const result = validateChartSpec(spec);
  if (!result.ok) {
    assert.fail(`expected valid spec, got errors:\n${JSON.stringify(result.errors, null, 2)}`);
  }
  return result;
}

function expectFail(spec, expectedPathSubstr) {
  const result = validateChartSpec(spec);
  assert.equal(result.ok, false, 'expected invalid spec to fail');
  if (expectedPathSubstr !== undefined) {
    const found = result.errors.some(e => e.path.includes(expectedPathSubstr));
    assert.ok(found, `expected an error path containing "${expectedPathSubstr}", got: ${JSON.stringify(result.errors)}`);
  }
  return result;
}

// Format set -----------------------------------------------------------

describe('CHART_FORMATS', () => {
  test('exposes exactly the five v1 formats', () => {
    assert.deepEqual([...CHART_FORMATS].sort(), ['bar', 'funnel', 'line', 'stat', 'table']);
  });

  test('every format has a worked example', () => {
    for (const fmt of CHART_FORMATS) {
      assert.ok(CHART_SPEC_EXAMPLES[fmt], `missing example for format "${fmt}"`);
      assert.equal(CHART_SPEC_EXAMPLES[fmt].format, fmt);
    }
  });
});

// Worked examples are themselves valid -------------------------------

describe('worked examples validate cleanly', () => {
  for (const fmt of CHART_FORMATS) {
    test(`CHART_SPEC_EXAMPLES.${fmt} passes validateChartSpec`, () => {
      expectOk(CHART_SPEC_EXAMPLES[fmt]);
    });
  }
});

// Top-level envelope ---------------------------------------------------

describe('top-level envelope', () => {
  test('rejects non-object spec', () => {
    for (const v of [null, undefined, 42, 'bar', [], true]) {
      const r = validateChartSpec(v);
      assert.equal(r.ok, false);
    }
  });

  test('rejects unknown format', () => {
    expectFail({ format: 'pie', value: 1 }, 'format');
  });

  test('rejects unknown top-level keys', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.stat);
    spec.color = 'blue';
    expectFail(spec, 'color');
  });

  test('rejects unknown valueFormat', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.bar);
    spec.valueFormat = 'fraction';
    expectFail(spec, 'valueFormat');
  });

  test('accepts every documented valueFormat', () => {
    for (const vf of VALUE_FORMATS) {
      const spec = clone(CHART_SPEC_EXAMPLES.bar);
      spec.valueFormat = vf;
      expectOk(spec);
    }
  });

  test('rejects title over the cap', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.stat);
    spec.title = 'x'.repeat(200);
    expectFail(spec, 'title');
  });

  test('rejects caption over the cap', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.stat);
    spec.caption = 'x'.repeat(200);
    expectFail(spec, 'caption');
  });
});

// Bar -----------------------------------------------------------------

describe('bar format', () => {
  test('rejects categories/series length mismatch', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.bar);
    spec.series[0].values = [1, 2, 3]; // categories has 4
    expectFail(spec, 'series[0].values');
  });

  test('rejects more than 3 series', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.bar);
    spec.series.push({ name: 'Two prior', values: [1, 1, 1, 1] });
    spec.series.push({ name: 'Three prior', values: [1, 1, 1, 1] });
    expectFail(spec, 'series');
  });

  test('rejects more than 12 categories', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.bar);
    spec.categories = Array.from({ length: 13 }, (_, i) => `C${i}`);
    spec.series = [{ name: 'a', values: Array(13).fill(1) }];
    expectFail(spec, 'categories');
  });

  test('rejects empty category string', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.bar);
    spec.categories[0] = '';
    expectFail(spec, 'categories[0]');
  });

  test('rejects non-finite values', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.bar);
    spec.series[0].values[0] = NaN;
    expectFail(spec, 'series[0].values[0]');
  });

  test('rejects unknown series-level key', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.bar);
    spec.series[0].color = 'red';
    expectFail(spec, 'series[0].color');
  });
});

// Line ----------------------------------------------------------------

describe('line format', () => {
  test('rejects fewer than 2 points', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.line);
    spec.points = ['W1'];
    spec.series[0].values = [5.2];
    expectFail(spec, 'points');
  });

  test('rejects more than 30 points', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.line);
    spec.points = Array.from({ length: 31 }, (_, i) => `P${i}`);
    spec.series[0].values = Array(31).fill(1);
    expectFail(spec, 'points');
  });

  test('rejects points/series length mismatch', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.line);
    spec.series[0].values = spec.series[0].values.slice(0, 5);
    expectFail(spec, 'series[0].values');
  });
});

// Stat ----------------------------------------------------------------

describe('stat format', () => {
  test('accepts stat without comparison', () => {
    expectOk({ format: 'stat', value: 42, valueFormat: 'percent' });
  });

  test('rejects non-finite value', () => {
    expectFail({ format: 'stat', value: Infinity }, 'value');
  });

  test('rejects unknown comparison key', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.stat);
    spec.comparison.color = 'green';
    expectFail(spec, 'comparison.color');
  });

  test('rejects bad direction', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.stat);
    spec.comparison.direction = 'sideways';
    expectFail(spec, 'comparison.direction');
  });

  test('accepts every documented direction', () => {
    for (const dir of COMPARISON_DIRECTIONS) {
      const spec = clone(CHART_SPEC_EXAMPLES.stat);
      spec.comparison.direction = dir;
      expectOk(spec);
    }
  });

  test('rejects missing comparison.label', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.stat);
    delete spec.comparison.label;
    expectFail(spec, 'comparison.label');
  });
});

// Funnel --------------------------------------------------------------

describe('funnel format', () => {
  test('rejects fewer than 2 stages', () => {
    expectFail({ format: 'funnel', stages: [{ name: 'Only', value: 10 }] }, 'stages');
  });

  test('rejects more than 7 stages', () => {
    const spec = {
      format: 'funnel',
      stages: Array.from({ length: 8 }, (_, i) => ({ name: `S${i}`, value: 100 - i }))
    };
    expectFail(spec, 'stages');
  });

  test('rejects rising values (not a funnel)', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.funnel);
    spec.stages[2].value = 200; // jumps above stage[1]
    expectFail(spec, 'stages[2].value');
  });

  test('accepts equal consecutive values (zero falloff)', () => {
    expectOk({
      format: 'funnel',
      stages: [
        { name: 'A', value: 100 },
        { name: 'B', value: 100 },
        { name: 'C', value: 80 }
      ]
    });
  });

  test('rejects negative value', () => {
    expectFail({
      format: 'funnel',
      stages: [
        { name: 'A', value: 10 },
        { name: 'B', value: -1 }
      ]
    }, 'stages[1].value');
  });
});

// Table ---------------------------------------------------------------

describe('table format', () => {
  test('rejects fewer than 2 columns', () => {
    expectFail({
      format: 'table',
      columns: [{ key: 'a', label: 'A' }],
      rows: [{ a: 1 }, { a: 2 }]
    }, 'columns');
  });

  test('rejects duplicate column keys', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.table);
    spec.columns[1].key = spec.columns[0].key;
    expectFail(spec, 'columns[1].key');
  });

  test('rejects row with missing column key', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.table);
    delete spec.rows[0].rate;
    expectFail(spec, 'rows[0].rate');
  });

  test('rejects row with extra unknown key', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.table);
    spec.rows[0].notes = 'mystery';
    expectFail(spec, 'rows[0].notes');
  });

  test('rejects non-numeric value in numeric column', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.table);
    spec.rows[0].rate = '32%';
    expectFail(spec, 'rows[0].rate');
  });

  test('rejects non-string value in text column', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.table);
    spec.rows[0].segment = 7;
    expectFail(spec, 'rows[0].segment');
  });

  test('accepts every documented column format', () => {
    for (const colFmt of COLUMN_FORMATS) {
      const isText = colFmt === 'text';
      const spec = {
        format: 'table',
        columns: [
          { key: 'k', label: 'K', format: 'text' },
          { key: 'v', label: 'V', format: colFmt }
        ],
        rows: [
          { k: 'one', v: isText ? 'first'  : 1 },
          { k: 'two', v: isText ? 'second' : 2 }
        ]
      };
      expectOk(spec);
    }
  });

  test('rejects more than 10 rows', () => {
    const spec = clone(CHART_SPEC_EXAMPLES.table);
    spec.rows = Array.from({ length: 11 }, (_, i) => ({
      segment: `Seg${i}`,
      rate: i,
      delta: 0
    }));
    expectFail(spec, 'rows');
  });
});

// Limits coherence ----------------------------------------------------

describe('CHART_SPEC_LIMITS coherence', () => {
  test('every limit has min ≤ max with min ≥ 1', () => {
    for (const [fmt, dims] of Object.entries(CHART_SPEC_LIMITS)) {
      for (const [dim, { min, max }] of Object.entries(dims)) {
        assert.ok(min >= 1, `${fmt}.${dim}.min must be ≥ 1`);
        assert.ok(min <= max, `${fmt}.${dim}: min (${min}) must be ≤ max (${max})`);
      }
    }
  });
});
