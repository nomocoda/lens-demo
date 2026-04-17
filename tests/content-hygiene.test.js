import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');

// Active surfaces only. Archived lens-*.html files are out of scope by design.
const ACTIVE_FILES = [
  'index.html',
  'worker.js',
  'data/persona.md',
  'data/voice-brief.md',
  'data/atlas-saas.md',
];

function readActive(path) {
  return readFileSync(resolve(repoRoot, path), 'utf8');
}

function locate(content, index) {
  const line = content.slice(0, index).split('\n').length;
  const col = index - content.lastIndexOf('\n', index - 1);
  return `line ${line}, col ${col}`;
}

describe('Invariant 4 — no em dashes in active source files', () => {
  for (const path of ACTIVE_FILES) {
    test(path, () => {
      const content = readActive(path);
      const idx = content.indexOf('\u2014');
      if (idx !== -1) {
        const snippet = content.slice(Math.max(0, idx - 30), idx + 31).replace(/\n/g, ' ');
        assert.fail(`em dash (\\u2014) in ${path} at ${locate(content, idx)} — ...${snippet}...`);
      }
    });
  }
});

// Retired terms from NomoCoda Operating Context (nomocoda-operating-context skill).
// Includes invariant 7 additions ("decision advisor", "decision adviser") retired 2026-04-17.
// Context-ambiguous retired terms ("Advise", "Ask", "Save", "Pipeline", "humans") are
// intentionally omitted — they require context-aware scanning to avoid false positives.
const RETIRED_TERMS = [
  'Decision+',
  'Technology scales. Relationships win.',
  'The Adaptive Advantage',
  'Organizational AI Memory',
  'OAM',
  'Permission-Filtered',
  'insight card',
  'intelligence card',
  'Advise card',
  'Lens Brief',
  'Contextual Handoff',
  'Collaboration Trigger',
  'Conversation Bridge',
  'Opportunity Signals',
  'Risk Signals',
  'recommended next step',
  'Functional Personas',
  'hybrid offering',
  'hybrid engagement',
  'one girlfriend rule',
  'implementation gap',
  'decision advisor',
  'decision adviser',
];

describe('Invariants 5 & 7 — no retired terms in active source files', () => {
  for (const path of ACTIVE_FILES) {
    test(path, () => {
      const content = readActive(path);
      const lower = content.toLowerCase();
      const hits = [];
      for (const term of RETIRED_TERMS) {
        const idx = lower.indexOf(term.toLowerCase());
        if (idx !== -1) hits.push(`"${term}" at ${locate(content, idx)}`);
      }
      assert.deepEqual(hits, [], `retired terms in ${path}:\n  ${hits.join('\n  ')}`);
    });
  }
});
