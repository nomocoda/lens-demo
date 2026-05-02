// provenance.test.js
//
// Tests for the provenance tagging and permission-scoped delivery paths.
//
// Like normalize-envelope.test.js, worker.js cannot be ESM-imported in Node
// (the wrangler .md text transform is unavailable in the test runner). Static
// analysis of the function source covers structural assertions; runtime
// behaviour is exercised by importing the pure helpers from source-ref.js.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  PERMITTED_SYSTEMS,
  validateSourceRef,
  resolvePermissionScopes,
  buildPermissionScopeBlock,
} from '../source-ref.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');
const workerSrc = readFileSync(resolve(repoRoot, 'worker.js'), 'utf8');

// Extract normalizeCardEnvelope body for structural assertions.
const normalizeFnMatch = /export function normalizeCardEnvelope\s*\([\s\S]*?\n\}/.exec(workerSrc);
const normalizeFnBody = normalizeFnMatch?.[0] ?? '';

// ---------------------------------------------------------------------------
// Static-analysis: PROVENANCE_GUARD is wired into the card system prompt
// ---------------------------------------------------------------------------

describe('PROVENANCE_GUARD — wiring into card system prompt', () => {
  test('PROVENANCE_GUARD const is declared in worker.js', () => {
    assert.match(workerSrc, /const\s+PROVENANCE_GUARD\s*=\s*`/, 'PROVENANCE_GUARD const not found');
  });

  test('PROVENANCE_GUARD is interpolated into buildCardSystemPrompt', () => {
    const cardPromptRe = /function\s+buildCardSystemPrompt[\s\S]*?return\s+`([\s\S]*?)`;/;
    const m = cardPromptRe.exec(workerSrc);
    assert.ok(m, 'could not extract buildCardSystemPrompt return template');
    assert.ok(
      m[1].includes('${PROVENANCE_GUARD}'),
      'buildCardSystemPrompt does not interpolate ${PROVENANCE_GUARD}',
    );
  });

  test('PROVENANCE_GUARD text names the "sources" field', () => {
    const guardRe = /const\s+PROVENANCE_GUARD\s*=\s*`([\s\S]*?)`;/;
    const m = guardRe.exec(workerSrc);
    assert.ok(m, 'PROVENANCE_GUARD body not extractable');
    assert.ok(m[1].toLowerCase().includes('sources'), 'PROVENANCE_GUARD must name the "sources" field');
  });

  test('PROVENANCE_GUARD lists permitted system identifiers', () => {
    const guardRe = /const\s+PROVENANCE_GUARD\s*=\s*`([\s\S]*?)`;/;
    const m = guardRe.exec(workerSrc);
    assert.ok(m, 'PROVENANCE_GUARD body not extractable');
    const body = m[1];
    for (const sys of ['hubspot', 'salesforce', 'mixpanel']) {
      assert.ok(body.includes(sys), `PROVENANCE_GUARD missing example system "${sys}"`);
    }
  });
});

// ---------------------------------------------------------------------------
// Static-analysis: normalizeCardEnvelope handles the sources path
// ---------------------------------------------------------------------------

describe('normalizeCardEnvelope — sources path is present in worker.js', () => {
  test('normalizeCardEnvelope accepts a permissionScopes parameter', () => {
    assert.ok(
      normalizeFnBody.includes('permissionScopes'),
      'normalizeCardEnvelope must accept permissionScopes parameter',
    );
  });

  test('normalizeCardEnvelope validates each source via validateSourceRef', () => {
    assert.ok(
      normalizeFnBody.includes('validateSourceRef'),
      'normalizeCardEnvelope must call validateSourceRef on each source',
    );
  });

  test('normalizeCardEnvelope filters out-of-scope sources when permittedSystemSet is active', () => {
    assert.ok(
      normalizeFnBody.includes('permittedSystemSet'),
      'normalizeCardEnvelope must build and consult a permittedSystemSet',
    );
  });

  test('normalizeCardEnvelope warns on missing sources field', () => {
    assert.ok(
      normalizeFnBody.includes('[sources]'),
      'normalizeCardEnvelope must log [sources] warnings for missing/invalid sources',
    );
  });

  test('normalizeCardEnvelope sets out.sources', () => {
    assert.ok(normalizeFnBody.includes('out.sources'), 'normalizeCardEnvelope must set out.sources');
  });
});

// ---------------------------------------------------------------------------
// Static-analysis: permission scopes are threaded through handlers
// ---------------------------------------------------------------------------

describe('permission scopes — threaded through handleCards and handleChat', () => {
  test('handleCards reads body.permissionScopes', () => {
    const fnMatch = /async function handleCards[\s\S]*?\n\}/.exec(workerSrc);
    assert.ok(fnMatch, 'handleCards body not extractable');
    assert.ok(
      fnMatch[0].includes('body.permissionScopes'),
      'handleCards must read body.permissionScopes',
    );
  });

  test('handleCards calls resolvePermissionScopes', () => {
    const fnMatch = /async function handleCards[\s\S]*?\n\}/.exec(workerSrc);
    assert.ok(fnMatch, 'handleCards body not extractable');
    assert.ok(
      fnMatch[0].includes('resolvePermissionScopes'),
      'handleCards must call resolvePermissionScopes',
    );
  });

  test('handleCards passes permissionScopes to buildCardSystemPrompt', () => {
    const fnMatch = /async function handleCards[\s\S]*?\n\}/.exec(workerSrc);
    assert.ok(fnMatch, 'handleCards body not extractable');
    assert.match(
      fnMatch[0],
      /buildCardSystemPrompt\s*\(\s*archetypeSlug\s*,\s*companyData\s*,\s*permissionScopes\s*\)/,
      'handleCards must pass permissionScopes as third arg to buildCardSystemPrompt',
    );
  });

  test('handleCards passes permissionScopes to normalizeCardEnvelope', () => {
    const fnMatch = /async function handleCards[\s\S]*?\n\}/.exec(workerSrc);
    assert.ok(fnMatch, 'handleCards body not extractable');
    assert.match(
      fnMatch[0],
      /normalizeCardEnvelope\s*\(\s*rewrittenText\s*,\s*permissionScopes\s*\)/,
      'handleCards must pass permissionScopes to normalizeCardEnvelope',
    );
  });

  test('handleChat reads body.permissionScopes', () => {
    const fnMatch = /async function handleChat[\s\S]*?\n\}/.exec(workerSrc);
    assert.ok(fnMatch, 'handleChat body not extractable');
    assert.ok(
      fnMatch[0].includes('body.permissionScopes'),
      'handleChat must read body.permissionScopes',
    );
  });

  test('handleChat passes permissionScopes to buildChatSystemPrompt', () => {
    const fnMatch = /async function handleChat[\s\S]*?\n\}/.exec(workerSrc);
    assert.ok(fnMatch, 'handleChat body not extractable');
    assert.match(
      fnMatch[0],
      /buildChatSystemPrompt\s*\(\s*companyData\s*,\s*permissionScopes\s*\)/,
      'handleChat must pass permissionScopes as second arg to buildChatSystemPrompt',
    );
  });
});

// ---------------------------------------------------------------------------
// Runtime: validateSourceRef
// ---------------------------------------------------------------------------

describe('validateSourceRef — SourceRef validation', () => {
  test('valid ref passes and is returned normalized', () => {
    const result = validateSourceRef({ system: 'hubspot', record: 'deal:test-123' });
    assert.ok(result.ok, `expected ok, got: ${result.error}`);
    assert.deepEqual(result.ref, { system: 'hubspot', record: 'deal:test-123' });
  });

  test('all PERMITTED_SYSTEMS values are accepted', () => {
    for (const sys of PERMITTED_SYSTEMS) {
      const result = validateSourceRef({ system: sys, record: 'report:test' });
      assert.ok(result.ok, `system "${sys}" should be valid`);
    }
  });

  test('unknown system is rejected', () => {
    const result = validateSourceRef({ system: 'jira', record: 'issue:PROJ-1' });
    assert.equal(result.ok, false);
    assert.ok(result.error.includes('unknown system'));
  });

  test('missing system is rejected', () => {
    const result = validateSourceRef({ record: 'deal:test' });
    assert.equal(result.ok, false);
    assert.ok(result.error.includes('"system"'));
  });

  test('empty system string is rejected', () => {
    const result = validateSourceRef({ system: '  ', record: 'deal:test' });
    assert.equal(result.ok, false);
  });

  test('missing record is rejected', () => {
    const result = validateSourceRef({ system: 'hubspot' });
    assert.equal(result.ok, false);
    assert.ok(result.error.includes('"record"'));
  });

  test('empty record string is rejected', () => {
    const result = validateSourceRef({ system: 'hubspot', record: '' });
    assert.equal(result.ok, false);
  });

  test('null input is rejected', () => {
    const result = validateSourceRef(null);
    assert.equal(result.ok, false);
  });

  test('array input is rejected', () => {
    const result = validateSourceRef([{ system: 'hubspot', record: 'deal:test' }]);
    assert.equal(result.ok, false);
  });

  test('url field on input is silently ignored (not passed through)', () => {
    const result = validateSourceRef({
      system: 'salesforce',
      record: 'opportunity:opp-001',
      url: 'https://example.salesforce.com/opp-001',
    });
    assert.ok(result.ok);
    assert.equal(result.ref.url, undefined, 'url should not be preserved by validateSourceRef');
  });

  test('system and record values are trimmed', () => {
    const result = validateSourceRef({ system: ' hubspot ', record: ' deal:test ' });
    assert.ok(result.ok);
    assert.equal(result.ref.system, 'hubspot');
    assert.equal(result.ref.record, 'deal:test');
  });
});

// ---------------------------------------------------------------------------
// Runtime: resolvePermissionScopes
// ---------------------------------------------------------------------------

describe('resolvePermissionScopes — input validation', () => {
  test('null input returns null (demo mode — all data visible)', () => {
    assert.equal(resolvePermissionScopes(null), null);
  });

  test('empty array returns null', () => {
    assert.equal(resolvePermissionScopes([]), null);
  });

  test('non-array returns null', () => {
    assert.equal(resolvePermissionScopes({ toolkit: 'hubspot' }), null);
  });

  test('valid scope object is accepted and normalized', () => {
    const scopes = resolvePermissionScopes([
      { toolkit: 'hubspot', scopeData: { teamIds: ['team-marketing'] } },
    ]);
    assert.ok(Array.isArray(scopes) && scopes.length === 1);
    assert.equal(scopes[0].toolkit, 'hubspot');
    assert.deepEqual(scopes[0].scopeData, { teamIds: ['team-marketing'] });
  });

  test('multiple valid scopes are all accepted', () => {
    const scopes = resolvePermissionScopes([
      { toolkit: 'hubspot', scopeData: null },
      { toolkit: 'salesforce', scopeData: { profile: { profileName: 'Marketing User' } } },
    ]);
    assert.ok(Array.isArray(scopes) && scopes.length === 2);
  });

  test('scope with unknown toolkit is dropped', () => {
    const scopes = resolvePermissionScopes([
      { toolkit: 'jira', scopeData: null },
      { toolkit: 'hubspot', scopeData: null },
    ]);
    assert.ok(Array.isArray(scopes) && scopes.length === 1);
    assert.equal(scopes[0].toolkit, 'hubspot');
  });

  test('scope with missing toolkit is dropped', () => {
    const scopes = resolvePermissionScopes([
      { scopeData: null },
      { toolkit: 'mixpanel', scopeData: null },
    ]);
    assert.ok(Array.isArray(scopes) && scopes.length === 1);
    assert.equal(scopes[0].toolkit, 'mixpanel');
  });

  test('all-invalid scopes returns null', () => {
    const scopes = resolvePermissionScopes([{ toolkit: 'jira' }, { toolkit: '' }]);
    assert.equal(scopes, null);
  });
});

// ---------------------------------------------------------------------------
// Runtime: buildPermissionScopeBlock
// ---------------------------------------------------------------------------

describe('buildPermissionScopeBlock — prompt block generation', () => {
  test('null scopes returns empty string (cache-safe no-op)', () => {
    assert.equal(buildPermissionScopeBlock(null), '');
  });

  test('empty array returns empty string', () => {
    assert.equal(buildPermissionScopeBlock([]), '');
  });

  test('single scope produces a block naming the system', () => {
    const block = buildPermissionScopeBlock([{ toolkit: 'hubspot', scopeData: null }]);
    assert.ok(block.includes('hubspot'), 'block must name the permitted system');
    assert.ok(block.length > 0);
  });

  test('Slack scope includes channel names in block', () => {
    const block = buildPermissionScopeBlock([
      { toolkit: 'slack', scopeData: { channels: ['#sales', '#general'] } },
    ]);
    assert.ok(block.includes('#sales'));
    assert.ok(block.includes('#general'));
  });

  test('HubSpot scope with teamIds includes team detail', () => {
    const block = buildPermissionScopeBlock([
      { toolkit: 'hubspot', scopeData: { teamIds: ['team-marketing'] } },
    ]);
    assert.ok(block.includes('team-marketing'));
  });

  test('Salesforce scope with profile includes profile name', () => {
    const block = buildPermissionScopeBlock([
      {
        toolkit: 'salesforce',
        scopeData: { profile: { profileName: 'Marketing User' } },
      },
    ]);
    assert.ok(block.includes('Marketing User'));
  });

  test('block contains permission scope header', () => {
    const block = buildPermissionScopeBlock([{ toolkit: 'hubspot', scopeData: null }]);
    assert.ok(
      block.toUpperCase().includes('PERMISSION SCOPE'),
      'block must include a PERMISSION SCOPE header',
    );
  });
});
