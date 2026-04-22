import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');
const workerSrc = readFileSync(resolve(repoRoot, 'worker.js'), 'utf8');

function extractPromptTemplate(src, fnName) {
  const re = new RegExp(`function\\s+${fnName}[\\s\\S]*?return\\s+\`([\\s\\S]*?)\`;`);
  const m = re.exec(src);
  if (!m) throw new Error(`template literal for ${fnName} not found in worker.js`);
  return m[1];
}

const chatPrompt = extractPromptTemplate(workerSrc, 'buildChatSystemPrompt');
const cardPrompt = extractPromptTemplate(workerSrc, 'buildCardSystemPrompt');

describe('Invariant 1 — source-of-truth docs load into system prompts', () => {
  test('worker.js imports PERSONA from ./data/persona.md', () => {
    assert.match(workerSrc, /import\s+PERSONA\s+from\s+['"]\.\/data\/persona\.md['"]/);
  });

  test('worker.js imports VOICE_BRIEF from ./data/voice-brief.md', () => {
    assert.match(workerSrc, /import\s+VOICE_BRIEF\s+from\s+['"]\.\/data\/voice-brief\.md['"]/);
  });

  test('worker.js imports COMPANY_DATA from ./data/atlas-saas.md', () => {
    assert.match(workerSrc, /import\s+COMPANY_DATA\s+from\s+['"]\.\/data\/atlas-saas\.md['"]/);
  });

  for (const doc of ['data/persona.md', 'data/voice-brief.md', 'data/atlas-saas.md']) {
    test(`${doc} exists and is non-empty`, () => {
      const path = resolve(repoRoot, doc);
      assert.ok(existsSync(path), `${doc} is missing`);
      assert.ok(readFileSync(path, 'utf8').trim().length > 0, `${doc} is empty`);
    });
  }

  test('buildChatSystemPrompt interpolates PERSONA, VOICE_BRIEF, and COMPANY_DATA', () => {
    assert.match(chatPrompt, /\$\{PERSONA\}/, 'chat prompt missing ${PERSONA}');
    assert.match(chatPrompt, /\$\{VOICE_BRIEF\}/, 'chat prompt missing ${VOICE_BRIEF}');
    assert.match(chatPrompt, /\$\{COMPANY_DATA\}/, 'chat prompt missing ${COMPANY_DATA}');
  });

  test('buildCardSystemPrompt interpolates PERSONA, VOICE_BRIEF, and COMPANY_DATA', () => {
    assert.match(cardPrompt, /\$\{PERSONA\}/, 'card prompt missing ${PERSONA}');
    assert.match(cardPrompt, /\$\{VOICE_BRIEF\}/, 'card prompt missing ${VOICE_BRIEF}');
    assert.match(cardPrompt, /\$\{COMPANY_DATA\}/, 'card prompt missing ${COMPANY_DATA}');
  });
});

describe('Invariant 2 — card prompt contains composition formula (Headline + Anchor + Connect)', () => {
  test('card prompt names the Headline component', () => {
    assert.match(cardPrompt, /\bHeadline\b/, 'card prompt missing Headline');
  });

  test('card prompt names the anchor component', () => {
    assert.match(cardPrompt, /\banchor\b/i, 'card prompt missing anchor');
  });

  test('card prompt names the connect component', () => {
    assert.match(cardPrompt, /\bconnect\b/i, 'card prompt missing connect');
  });
});

describe('Invariant 3 — card prompt forbids the five composition constraints', () => {
  const constraints = [
    'no recommendations',
    'no verdicts',
    'no emotional framing',
    'no collaboration prompts',
    'no interpretive leaps',
  ];

  for (const phrase of constraints) {
    test(`card prompt states "${phrase}"`, () => {
      assert.ok(
        cardPrompt.toLowerCase().includes(phrase),
        `card prompt is missing constraint: "${phrase}"`
      );
    });
  }
});

// Invariant 11 — The chat and card system prompts must carry an identity guardrail
// that prevents Lens from self-identifying as Claude, Anthropic, or any model.
describe('Invariant 11 — identity guardrail present in both system prompts', () => {
  const guardrailMatch = /const\s+IDENTITY_GUARDRAIL\s*=\s*`([\s\S]*?)`;/.exec(workerSrc);

  test('worker.js defines IDENTITY_GUARDRAIL constant', () => {
    assert.ok(guardrailMatch, 'IDENTITY_GUARDRAIL constant not found in worker.js');
  });

  test('IDENTITY_GUARDRAIL names Lens and forbids model/provider disclosure', () => {
    const text = (guardrailMatch?.[1] || '').toLowerCase();
    assert.ok(text.includes('lens'), 'guardrail must name Lens');
    assert.ok(text.includes('claude'), 'guardrail must explicitly forbid "Claude"');
    assert.ok(
      /\bnot\b/.test(text) || /\bnever\b/.test(text),
      'guardrail must use negative language (not/never) to forbid disclosure'
    );
    assert.ok(
      text.includes('language model') || text.includes('underlying model') || text.includes('model'),
      'guardrail must address the underlying model'
    );
  });

  test('buildChatSystemPrompt interpolates ${IDENTITY_GUARDRAIL}', () => {
    assert.match(chatPrompt, /\$\{IDENTITY_GUARDRAIL\}/, 'chat prompt missing IDENTITY_GUARDRAIL');
  });

  test('buildCardSystemPrompt interpolates ${IDENTITY_GUARDRAIL}', () => {
    assert.match(cardPrompt, /\$\{IDENTITY_GUARDRAIL\}/, 'card prompt missing IDENTITY_GUARDRAIL');
  });
});

// Invariant 12 — prompt-block constants are interpolated, not orphaned.
//
// Added 2026-04-22 after the 2026-04-20 LENS FRAMING incident, where a
// prompt block had been written as bare text between two `const` declarations
// with no template-literal wrapper. Effect: `wrangler deploy` would have
// failed on syntax, AND the content had never actually been in the
// production prompt. Layer 3 behavioral evals cannot see this failure mode
// because they only exercise what's interpolated — a dropped block is
// silently absent, not mis-applied.
//
// Two cheap checks catch the class of failure:
//   (a) `node --check worker.js` rejects bare prompt-block text (it is
//       invalid JavaScript outside a template literal or string).
//   (b) Every top-level all-caps `const NAME = \`...\`` must appear at
//       least twice in worker.js source — once as its declaration, and at
//       least once as a usage (either `${NAME}` interpolation inside a
//       builder template, or a bare value reference like `text: NAME`).
//       A const that appears only in its declaration is orphaned.
describe('Invariant 12 — prompt-block constants are interpolated, not orphaned', () => {
  test('worker.js parses as valid JavaScript (node --check)', () => {
    const result = spawnSync(
      process.execPath,
      ['--check', resolve(repoRoot, 'worker.js')],
      { encoding: 'utf8' },
    );
    assert.strictEqual(
      result.status,
      0,
      `node --check worker.js failed — bare prompt-block text outside a template literal?\n${result.stderr}`,
    );
  });

  // Discover every top-level const whose name is ALL_CAPS and whose value
  // begins with a backtick (a template literal). This is the shape every
  // prompt block uses in worker.js.
  const constPattern = /^const ([A-Z][A-Z_0-9]+)\s*=\s*`/gm;
  const promptConsts = [];
  let m;
  while ((m = constPattern.exec(workerSrc)) !== null) {
    promptConsts.push(m[1]);
  }

  test('at least one prompt-block const is discovered (sanity check)', () => {
    assert.ok(
      promptConsts.length >= 5,
      `expected 5+ prompt-block consts in worker.js, discovered ${promptConsts.length}: ${promptConsts.join(', ')}`,
    );
  });

  for (const name of promptConsts) {
    test(`${name} is referenced at least once outside its declaration`, () => {
      const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const re = new RegExp(`\\b${escaped}\\b`, 'g');
      const hits = (workerSrc.match(re) || []).length;
      assert.ok(
        hits >= 2,
        `${name} appears only in its own declaration (${hits} total reference). ` +
          `Either interpolate it via \${${name}} in a builder template, pass it as a ` +
          `value somewhere, or delete the const. Orphaned prompt blocks are silently ` +
          `absent from the production prompt — Layer 3 behavioral evals cannot see them.`,
      );
    });
  }
});
