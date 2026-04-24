import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');
const indexHtml = readFileSync(resolve(repoRoot, 'index.html'), 'utf8');

// Locked Intelligence Areas (NomoCoda Operating Context v11, locked 2026-04-24).
// Three GTM delivery domains plus the ever-present "all" filter. Product
// retired as a delivery domain 2026-04-24 and is now a Source Domain only.
const ALLOWED_FILTER_SLUGS = new Set(['all', 'customers', 'revenue', 'marketing']);
const ALLOWED_DOMAIN_KEYS = new Set(['customers', 'revenue', 'marketing']);
const ALLOWED_DOMAIN_TITLES = new Set(['Customers', 'Revenue', 'Marketing']);

describe('Invariant 8 — Intelligence Areas match the locked set', () => {
  test('MOBILE_FILTER_DOMAINS keys are all in the allowed set', () => {
    // Filter chips are runtime-rendered from MOBILE_FILTER_DOMAINS, not
    // hardcoded as data-filter HTML attributes. Parse the array instead.
    const block = /const MOBILE_FILTER_DOMAINS\s*=\s*\[([\s\S]*?)\];/m.exec(indexHtml);
    assert.ok(block, 'MOBILE_FILTER_DOMAINS array not found in index.html');
    const keys = [...block[1].matchAll(/key:\s*'([^']+)'/g)].map(m => m[1]);
    assert.ok(keys.length > 0, 'no keys parsed from MOBILE_FILTER_DOMAINS');
    const offenders = keys.filter(k => !ALLOWED_DOMAIN_KEYS.has(k));
    assert.deepEqual(offenders, [], `unknown filter keys: ${offenders.join(', ')}`);
  });

  test('insightData domain keys are all in the allowed set', () => {
    const block = /const insightData = \{([\s\S]*?)^\};/m.exec(indexHtml);
    assert.ok(block, 'insightData block not found in index.html');
    const keys = [...block[1].matchAll(/^\s*([a-z]+):\s*\{\s*$/gm)].map(m => m[1]);
    assert.ok(keys.length > 0, 'no domain keys parsed from insightData');
    const offenders = keys.filter(k => !ALLOWED_DOMAIN_KEYS.has(k));
    assert.deepEqual(offenders, [], `unknown insightData keys: ${offenders.join(', ')}`);
  });

  test('insightData title values are all in the allowed set', () => {
    // Scope to the insightData block. Scanning the whole file catches
    // unrelated `title:` strings elsewhere (e.g. chat thread seeds).
    const block = /const insightData = \{([\s\S]*?)^\};/m.exec(indexHtml);
    assert.ok(block, 'insightData block not found in index.html');
    const titles = [...block[1].matchAll(/^\s*title:\s*'([^']+)',?\s*$/gm)].map(m => m[1]);
    assert.ok(titles.length > 0, 'no titles parsed from insightData');
    const offenders = titles.filter(t => !ALLOWED_DOMAIN_TITLES.has(t));
    assert.deepEqual(offenders, [], `unknown domain titles: ${offenders.join(', ')}`);
  });

  test('categoryOrder array uses only allowed domain keys', () => {
    const m = /categoryOrder\s*=\s*\[([^\]]+)\]/.exec(indexHtml);
    assert.ok(m, 'categoryOrder array not found');
    const keys = [...m[1].matchAll(/'([^']+)'/g)].map(x => x[1]);
    const offenders = keys.filter(k => !ALLOWED_DOMAIN_KEYS.has(k));
    assert.deepEqual(offenders, [], `categoryOrder contains unknown keys: ${offenders.join(', ')}`);
  });
});
