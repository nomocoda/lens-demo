import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

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
