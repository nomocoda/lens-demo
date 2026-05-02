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

  test('buildChatSystemPrompt interpolates PERSONA, VOICE_BRIEF, and companyData', () => {
    assert.match(chatPrompt, /\$\{PERSONA\}/, 'chat prompt missing ${PERSONA}');
    assert.match(chatPrompt, /\$\{VOICE_BRIEF\}/, 'chat prompt missing ${VOICE_BRIEF}');
    assert.match(chatPrompt, /\$\{companyData\}/, 'chat prompt missing ${companyData}');
  });

  test('buildCardSystemPrompt interpolates PERSONA, VOICE_BRIEF, and companyData', () => {
    assert.match(cardPrompt, /\$\{PERSONA\}/, 'card prompt missing ${PERSONA}');
    assert.match(cardPrompt, /\$\{VOICE_BRIEF\}/, 'card prompt missing ${VOICE_BRIEF}');
    assert.match(cardPrompt, /\$\{companyData\}/, 'card prompt missing ${companyData}');
  });
});

// Invariant 1b — Per-org companyData pathway.
//
// /chat and /cards accept an optional `companyData` field on the request body
// carrying the requesting org's connected-source snapshot (markdown, same
// shape as data/atlas-saas.md). When omitted or invalid, the worker falls
// back to the bundled Atlas SaaS fixture so demo.nomocoda.com and the eval
// harness keep rendering Atlas cards. lens-web's Inngest cards function is
// the production caller that will pass the per-org snapshot.
//
// Added 2026-04-30 as part of Activation Pipeline sub-objective 2 (replace
// the static Atlas snapshot with per-org Composio data at synthesis time).
// Static-source checks against worker.js — the eval harness already exercises
// the bundled-Atlas pathway and the Cloudflare Worker runtime is not loaded
// in unit tests.
describe('Invariant 1b — per-org companyData pathway is wired through worker.js', () => {
  test('worker.js declares resolveCompanyData', () => {
    assert.match(
      workerSrc,
      /function\s+resolveCompanyData\s*\(/,
      'resolveCompanyData function not found in worker.js',
    );
  });

  test('resolveCompanyData enforces a length cap to bound prompt size', () => {
    const fnMatch = /function\s+resolveCompanyData[\s\S]*?\n\}/.exec(workerSrc);
    assert.ok(fnMatch, 'resolveCompanyData body not extractable');
    assert.match(
      fnMatch[0],
      /MAX_COMPANY_DATA_BYTES/,
      'resolveCompanyData must consult MAX_COMPANY_DATA_BYTES to cap input length',
    );
  });

  test('resolveCompanyData falls back to bundled COMPANY_DATA when input is invalid', () => {
    const fnMatch = /function\s+resolveCompanyData[\s\S]*?\n\}/.exec(workerSrc);
    assert.ok(fnMatch, 'resolveCompanyData body not extractable');
    const occurrences = (fnMatch[0].match(/return\s+COMPANY_DATA/g) || []).length;
    assert.ok(
      occurrences >= 3,
      `resolveCompanyData should fall back to bundled COMPANY_DATA on each invalid-input branch ` +
        `(non-string, empty after trim, oversized) — found ${occurrences} fallback returns`,
    );
  });

  test('handleChat reads body.companyData and passes it to buildChatSystemPrompt', () => {
    const fnMatch = /async function handleChat[\s\S]*?\n\}/.exec(workerSrc);
    assert.ok(fnMatch, 'handleChat body not extractable');
    assert.match(
      fnMatch[0],
      /resolveCompanyData\s*\(\s*body\.companyData\s*\)/,
      'handleChat must call resolveCompanyData(body.companyData)',
    );
    // Regex allows additional arguments after companyData (e.g. permissionScopes).
    assert.match(
      fnMatch[0],
      /buildChatSystemPrompt\s*\(\s*companyData[\s\S]*?\)/,
      'handleChat must pass the resolved companyData into buildChatSystemPrompt',
    );
  });

  test('handleCards reads body.companyData and passes it to buildCardSystemPrompt', () => {
    const fnMatch = /async function handleCards[\s\S]*?\n\}/.exec(workerSrc);
    assert.ok(fnMatch, 'handleCards body not extractable');
    assert.match(
      fnMatch[0],
      /resolveCompanyData\s*\(\s*body\.companyData\s*\)/,
      'handleCards must call resolveCompanyData(body.companyData)',
    );
    // Regex allows additional arguments after companyData (e.g. permissionScopes).
    assert.match(
      fnMatch[0],
      /buildCardSystemPrompt\s*\(\s*archetypeSlug\s*,\s*companyData[\s\S]*?\)/,
      'handleCards must pass archetypeSlug and the resolved companyData into buildCardSystemPrompt',
    );
  });

  test('buildChatSystemPrompt accepts a companyData parameter defaulting to COMPANY_DATA', () => {
    // Closing paren not required — the function may accept additional params
    // (e.g. permissionScopes) after companyData.
    assert.match(
      workerSrc,
      /function\s+buildChatSystemPrompt\s*\(\s*companyData\s*=\s*COMPANY_DATA/,
      'buildChatSystemPrompt must accept companyData with COMPANY_DATA as the default',
    );
  });

  test('buildCardSystemPrompt accepts a companyData parameter defaulting to COMPANY_DATA', () => {
    // Closing paren not required — the function may accept additional params
    // (e.g. permissionScopes) after companyData.
    assert.match(
      workerSrc,
      /function\s+buildCardSystemPrompt\s*\(\s*archetypeSlug\s*=\s*DEFAULT_ARCHETYPE\s*,\s*companyData\s*=\s*COMPANY_DATA/,
      'buildCardSystemPrompt must accept companyData with COMPANY_DATA as the default',
    );
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

// Invariant 12 — prompt-block constants are interpolated into a shipping
// template, not orphaned.
//
// Added 2026-04-22 after the 2026-04-20 LENS FRAMING incident, where a
// prompt block had been written as bare text between two `const` declarations
// with no template-literal wrapper. Effect: `wrangler deploy` would have
// failed on syntax, AND the content had never actually been in the
// production prompt. Layer 3 behavioral evals cannot see this failure mode
// because they only exercise what's interpolated — a dropped block is
// silently absent, not mis-applied.
//
// Tightened 2026-04-30 to match the original BVS Layer 1 spec: the check
// is no longer "appears at least twice in worker.js source" (that passed
// even when a const was only mentioned in a comment, leaving it unshipped).
// Now: every prompt-block const must either (a) appear interpolated as
// `${NAME}` inside one of the three shipping templates — the chat system
// prompt, the card system prompt, or the card-rewriter system prompt — or
// (b) BE one of those shipping templates (CARD_REWRITER_SYSTEM is sent
// directly as `text: CARD_REWRITER_SYSTEM` in applyCardRewriter, not via
// interpolation).
//
// `node --check worker.js` is kept as a separate, cheap guard that catches
// bare prompt-block text outside any string literal — the actual original
// LENS_FRAMING failure mode (it would have been a JavaScript syntax error).
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
  // prompt block uses in worker.js. Object-literal consts (e.g.
  // ARCHETYPE_BRIEFS) and array-literal consts (e.g. ALLOWED_ORIGINS) do
  // not match because their values do not start with a backtick.
  const constPattern = /^const ([A-Z][A-Z_0-9]+)\s*=\s*`/gm;
  const promptConsts = [];
  let m;
  while ((m = constPattern.exec(workerSrc)) !== null) {
    promptConsts.push(m[1]);
  }

  // Extract the three shipping templates: the chat system prompt, the card
  // system prompt, and the card-rewriter system prompt. A prompt-block
  // const must end up substituted into one of these to actually reach the
  // production prompt sent to the model.
  function extractTaggedConst(src, name) {
    const re = new RegExp(`const\\s+${name}\\s*=\\s*\`([\\s\\S]*?)\`;`);
    const match = re.exec(src);
    if (!match) {
      throw new Error(`could not extract const ${name} from worker.js`);
    }
    return match[1];
  }
  const cardRewriterTemplate = extractTaggedConst(workerSrc, 'CARD_REWRITER_SYSTEM');
  const shippingTemplates = {
    'buildChatSystemPrompt return template': chatPrompt,
    'buildCardSystemPrompt return template': cardPrompt,
    'CARD_REWRITER_SYSTEM template': cardRewriterTemplate,
  };

  // CARD_REWRITER_SYSTEM is itself a shipping template — applyCardRewriter
  // sends it directly as the system prompt for the rewriter pass. It does
  // not need to be interpolated; instead it must be referenced as a value
  // in an Anthropic API call.
  const SELF_SHIPPING_TEMPLATES = new Set(['CARD_REWRITER_SYSTEM']);

  test('at least 5 prompt-block consts are discovered (sanity check)', () => {
    assert.ok(
      promptConsts.length >= 5,
      `expected 5+ prompt-block consts in worker.js, discovered ${promptConsts.length}: ${promptConsts.join(', ')}`,
    );
  });

  for (const name of promptConsts) {
    test(`${name} reaches a shipping prompt`, () => {
      if (SELF_SHIPPING_TEMPLATES.has(name)) {
        // Self-shipping const must be passed as a `text:` value somewhere
        // in the Anthropic API request body. Look for the exact bare
        // reference shape worker.js uses, ignoring its declaration.
        const useRe = new RegExp(`text:\\s*${name}\\b`);
        assert.match(
          workerSrc,
          useRe,
          `${name} is a self-shipping prompt template but is never passed as ` +
            `\`text: ${name}\` in any Anthropic API call. The rewriter pass ` +
            `will not run if this reference is missing.`,
        );
        return;
      }

      const needle = '${' + name + '}';
      const lands = Object.entries(shippingTemplates)
        .filter(([, body]) => body.includes(needle))
        .map(([label]) => label);

      assert.ok(
        lands.length > 0,
        `${name} is declared but is never interpolated as ${needle} into any ` +
          `shipping template. Searched the chat system prompt, the card system ` +
          `prompt, and the CARD_REWRITER_SYSTEM template. An uninterpolated ` +
          `prompt-block const is silently absent from the production prompt — ` +
          `Layer 3 behavioral evals cannot see this. Either interpolate it ` +
          `into a shipping template, or delete the const.`,
      );
    });
  }
});
