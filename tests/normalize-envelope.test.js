// normalize-envelope.test.js
//
// Tests for the chart validation path through normalizeCardEnvelope.
// worker.js imports .md files via wrangler's [[rules]] text transform —
// that transform is unavailable in Node's native test runner, so we inspect
// the function source statically (same pattern as prompts.test.js) and
// exercise the chart validator directly (same module normalizeCardEnvelope
// calls at runtime).

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { validateChartSpec, CHART_SPEC_EXAMPLES } from '../chart-spec.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');
const workerSrc = readFileSync(resolve(repoRoot, 'worker.js'), 'utf8');

// Extract normalizeCardEnvelope body for structural assertions.
const normalizeFnMatch = /export function normalizeCardEnvelope\s*\([\s\S]*?\n\}/.exec(workerSrc);
const normalizeFnBody = normalizeFnMatch?.[0] ?? '';

// ---------------------------------------------------------------------------
// Static-analysis: chart path is wired into normalizeCardEnvelope
// ---------------------------------------------------------------------------

describe('normalizeCardEnvelope — chart path is present in worker.js', () => {
  test('normalizeCardEnvelope is exported', () => {
    assert.match(workerSrc, /export function normalizeCardEnvelope\s*\(/);
  });

  test('function body is extractable', () => {
    assert.ok(normalizeFnMatch, 'could not extract normalizeCardEnvelope body from worker.js');
  });

  test('checks card.chart !== undefined before entering chart path', () => {
    assert.ok(
      normalizeFnBody.includes('card.chart !== undefined'),
      'chart presence guard missing from normalizeCardEnvelope',
    );
  });

  test('calls validateChartSpec on the chart field', () => {
    assert.ok(
      normalizeFnBody.includes('validateChartSpec'),
      'validateChartSpec call missing from normalizeCardEnvelope',
    );
  });

  test('gates on result.ok before setting out.chart', () => {
    assert.ok(normalizeFnBody.includes('result.ok'), 'result.ok gate missing');
    assert.ok(normalizeFnBody.includes('out.chart'), 'out.chart assignment missing');
  });

  test('console.warns on invalid chart spec', () => {
    assert.ok(
      normalizeFnBody.includes('console.warn'),
      'console.warn for dropped invalid spec missing',
    );
  });

  test('validateChartSpec is imported from chart-spec.js', () => {
    assert.match(
      workerSrc,
      /import\s*\{[^}]*validateChartSpec[^}]*\}\s*from\s*['"]\.\/chart-spec\.js['"]/,
    );
  });
});

// ---------------------------------------------------------------------------
// Runtime: validateChartSpec behaves correctly for the cases normalizeCard-
// Envelope relies on — valid specs pass through, invalid specs are rejected
// ---------------------------------------------------------------------------

describe('normalizeCardEnvelope — validateChartSpec behavior backing the chart path', () => {
  test('valid bar spec passes and is returned as spec', () => {
    const result = validateChartSpec(CHART_SPEC_EXAMPLES.bar);
    assert.ok(result.ok, `expected ok, got errors: ${JSON.stringify(result.errors ?? [])}`);
    assert.deepEqual(result.spec, CHART_SPEC_EXAMPLES.bar);
  });

  test('valid line spec passes', () => {
    const result = validateChartSpec(CHART_SPEC_EXAMPLES.line);
    assert.ok(result.ok);
  });

  test('valid stat spec with comparison passes', () => {
    const result = validateChartSpec(CHART_SPEC_EXAMPLES.stat);
    assert.ok(result.ok);
  });

  test('valid funnel spec passes', () => {
    const result = validateChartSpec(CHART_SPEC_EXAMPLES.funnel);
    assert.ok(result.ok);
  });

  test('valid table spec passes', () => {
    const result = validateChartSpec(CHART_SPEC_EXAMPLES.table);
    assert.ok(result.ok);
  });

  test('spec with unknown top-level key is rejected (decorative key the renderer ignores)', () => {
    const bad = { ...CHART_SPEC_EXAMPLES.bar, color: '#ff0000' };
    const result = validateChartSpec(bad);
    assert.equal(result.ok, false);
    assert.ok(result.errors.some(e => e.path === 'color'), 'expected error on "color" key');
  });

  test('spec that is a JSON string (not an object) is rejected', () => {
    const result = validateChartSpec(JSON.stringify(CHART_SPEC_EXAMPLES.bar));
    assert.equal(result.ok, false);
    assert.ok(result.errors.some(e => e.message.includes('must be an object')));
  });

  test('null is rejected', () => {
    const result = validateChartSpec(null);
    assert.equal(result.ok, false);
  });

  test('rising funnel values are rejected', () => {
    const bad = {
      format: 'funnel',
      stages: [
        { name: 'A', value: 10 },
        { name: 'B', value: 20 },
      ],
    };
    const result = validateChartSpec(bad);
    assert.equal(result.ok, false);
    assert.ok(result.errors.some(e => e.message.includes('non-increasing')));
  });

  test('bar spec with categories/series length mismatch is rejected', () => {
    const bad = {
      format: 'bar',
      categories: ['A', 'B', 'C'],
      series: [{ name: 'Series', values: [1, 2] }], // two values, three categories
    };
    const result = validateChartSpec(bad);
    assert.equal(result.ok, false);
    assert.ok(result.errors.some(e => e.path.includes('values')));
  });

  test('stat spec without comparison passes', () => {
    const result = validateChartSpec({ format: 'stat', value: 42 });
    assert.ok(result.ok);
  });

  test('unknown format is rejected', () => {
    const result = validateChartSpec({ format: 'pie', slices: [] });
    assert.equal(result.ok, false);
    assert.ok(result.errors.some(e => e.path === 'format'));
  });
});
