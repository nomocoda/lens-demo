import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');

// Active surfaces only. Archived lens-*.html files are out of scope by design.
// All 11 archetype briefs in data/*-brief.md are imported into worker.js and
// loaded into the chat/card prompts whenever the matching archetype is
// active. Iter-3 (2026-05-01) extended this list from 6 to all 13 active
// data/*.md files after Voice's brief-audit task surfaced em-dash and
// against/gap/loss contamination across briefs that had been silently
// slipping into live model output. Every brief loaded into a shipping
// prompt now gets the full hygiene scan.
const ACTIVE_FILES = [
  'index.html',
  'worker.js',
  'data/persona.md',
  'data/voice-brief.md',
  'data/atlas-saas.md',
  'data/customer-advocate-brief.md',
  'data/customer-leader-brief.md',
  'data/customer-operator-brief.md',
  'data/customer-technician-brief.md',
  'data/marketing-builder-brief.md',
  'data/marketing-leader-brief.md',
  'data/marketing-strategist-brief.md',
  'data/sales-developer-brief.md',
  'data/sales-generator-brief.md',
  'data/sales-leader-brief.md',
  'data/sales-operator-brief.md',
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

// Invariant 9 — "Advise" as a proper-noun product term is retired (2026-04-14).
// Replaced by Stories (tab). The word "advise" as a verb is still valid (e.g. persona
// says "the narrator never does: exclaim, advise, prompt..."). This scan catches
// proper-noun usage and legacy identifier names only.
const ADVISE_PROPER_NOUN_PATTERNS = [
  /\bAdvise (view|mode|tab|card)\b/,
  /\badvise-view\b/,
  /\badvise-header\b/,
  /\btab-advise\b/,
  /\bremovedFromAdvise\b/,
  /\bsaveCardFromAdvise\b/,
  /switchTab\(\s*['"]advise['"]\s*\)/,
  /currentView\s*=\s*['"]advise['"]/,
];

describe('Invariant 9 — no "Advise" as proper-noun product term', () => {
  for (const path of ACTIVE_FILES) {
    test(path, () => {
      const content = readActive(path);
      const hits = [];
      for (const pattern of ADVISE_PROPER_NOUN_PATTERNS) {
        const m = pattern.exec(content);
        if (m) hits.push(`${pattern} → "${m[0]}" at ${locate(content, m.index)}`);
      }
      assert.deepEqual(hits, [], `legacy Advise usage in ${path}:\n  ${hits.join('\n  ')}`);
    });
  }
});

// Invariant 10 — No "Claude" references in data/*.md files.
// These files are loaded into the system prompt. Mentioning Claude inside the prompt
// names the underlying model and nudges self-reference; the IDENTITY_GUARDRAIL in
// worker.js forbids it, but the data files must not undermine it.
const DATA_MD_FILES = ACTIVE_FILES.filter(p => p.startsWith('data/') && p.endsWith('.md'));

describe('Invariant 10 — no "Claude" references in data/*.md', () => {
  for (const path of DATA_MD_FILES) {
    test(path, () => {
      const content = readActive(path);
      const idx = content.toLowerCase().indexOf('claude');
      if (idx !== -1) {
        const snippet = content.slice(Math.max(0, idx - 40), idx + 60).replace(/\n/g, ' ');
        assert.fail(`"Claude" in ${path} at ${locate(content, idx)} — ...${snippet}...`);
      }
    });
  }
});

// Invariant 11 — Seed card and chat content in index.html must not contain
// verdict words banned from the live FORWARD_FRAMING_GUARD. A prospect loading
// the demo should see the same voice discipline the live model is held to.
//
// Added 2026-04-22 after an audit found seed cards using "gap", "worsened",
// "below", "stretched", "declined", "down from", and "behind". The live chat
// cannot produce those words, so a demo that shows them breaks voice parity
// the moment a user clicks from a card into chat.
//
// Scans only `headline:` and `body:` values inside the seed content, and the
// `content:` values of assistant messages inside chatThreads. CSS `gap:`
// properties, JS identifiers, and comments are intentionally excluded.
const BANNED_VERDICT_WORDS = [
  { pattern: /\bgap(s)?\b/i, word: 'gap' },
  { pattern: /\bworsened\b/i, word: 'worsened' },
  { pattern: /\bdeteriorated\b/i, word: 'deteriorated' },
  { pattern: /\bdeclined?\b/i, word: 'declined' },
  { pattern: /\bdropped\b/i, word: 'dropped' },
  { pattern: /\bstretched\b/i, word: 'stretched' },
  { pattern: /\bballooned\b/i, word: 'ballooned' },
  { pattern: /\bsoftened\b/i, word: 'softened' },
  { pattern: /\bweakened\b/i, word: 'weakened' },
  { pattern: /\bweaker\b/i, word: 'weaker' },
  { pattern: /\bwidened\b/i, word: 'widened' },
  { pattern: /\bshortfall\b/i, word: 'shortfall' },
  { pattern: /\bconcerning\b/i, word: 'concerning' },
  { pattern: /\bshy of\b/i, word: 'shy of' },
  { pattern: /\bshort of\b/i, word: 'short of' },
  { pattern: /\bfell (to|from|short)\b/i, word: 'fell to/from/short' },
  { pattern: /\bdown (to|from)\b/i, word: 'down to/from' },
  { pattern: /\blower than\b/i, word: 'lower than' },
  { pattern: /\bwider than\b/i, word: 'wider than' },
  { pattern: /\bmissed\b/i, word: 'missed' },
  { pattern: /\bbehind\b/i, word: 'behind' },
  { pattern: /\bbelow\b/i, word: 'below' },
];

function extractSeedStringValues(content) {
  // Match `headline: '...'`, `body: '...'`, and `content: '...'` with
  // single-quoted values (the format used in index.html seed data). Escaped
  // single quotes inside the string are handled via the negated-class pattern.
  const fieldPattern = /(headline|body|content)\s*:\s*'((?:\\.|[^'\\])*)'/g;
  const matches = [];
  let m;
  while ((m = fieldPattern.exec(content)) !== null) {
    matches.push({ field: m[1], value: m[2], index: m.index });
  }
  return matches;
}

describe('Invariant 11 — no verdict words in seed card/chat content', () => {
  test('index.html seed strings', () => {
    const content = readActive('index.html');
    const seedValues = extractSeedStringValues(content);
    const hits = [];
    for (const { field, value, index } of seedValues) {
      for (const { pattern, word } of BANNED_VERDICT_WORDS) {
        if (pattern.test(value)) {
          const loc = locate(content, index);
          const snippet = value.length > 80 ? value.slice(0, 77) + '...' : value;
          hits.push(`${field} at ${loc}: "${word}" → "${snippet}"`);
        }
      }
    }
    assert.deepEqual(
      hits,
      [],
      `banned verdict words in seed content (live model would be blocked from producing these):\n  ${hits.join('\n  ')}`,
    );
  });
});
