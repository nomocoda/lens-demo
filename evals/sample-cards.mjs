#!/usr/bin/env node
// One-off card sampler for demo-ready quality audits.
// Generates card sets for (role, bubble) pairs using the same two-pass
// (Sonnet draft + Opus rewriter) flow as worker.js /cards.
//
// Usage:
//   node --env-file=.env evals/sample-cards.mjs
//   node --env-file=.env evals/sample-cards.mjs --role "VP of Revenue" --bubble revenue --n 3
//   node --env-file=.env evals/sample-cards.mjs --all

import { buildCardPrompt, buildCardUserMessage, buildRewriterPrompt, LENS_MODEL, REWRITER_MODEL } from './prompt-builder.mjs';

const API_KEY = process.env.ANTHROPIC_API_KEY;
if (!API_KEY) {
  console.error('Missing ANTHROPIC_API_KEY in environment.');
  process.exit(1);
}

const API_URL = 'https://api.anthropic.com/v1/messages';
const API_VERSION = '2023-06-01';

const ARCHETYPES = [
  { role: 'VP of Marketing', bubble: 'marketing' },
  { role: 'VP of Revenue',   bubble: 'revenue' },
  { role: 'VP of Customer Success', bubble: 'customers' },
];

const args = process.argv.slice(2);
function arg(name, fallback = null) {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
}
const flag = (name) => args.includes(`--${name}`);

const runAll = flag('all') || (!arg('role') && !arg('bubble'));
const n = parseInt(arg('n', '2'), 10);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function anthropic({ model, system, messages, maxTokens = 2048, maxRetries = 5 }) {
  let attempt = 0;
  while (true) {
    const res = await fetch(API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': API_KEY,
        'anthropic-version': API_VERSION,
      },
      body: JSON.stringify({ model, max_tokens: maxTokens, system, messages }),
    });
    if (res.ok) {
      const data = await res.json();
      const text = data.content?.find((b) => b.type === 'text')?.text;
      if (!text) throw new Error('No text block');
      return text;
    }
    const retryable = res.status === 429 || res.status === 529 || res.status >= 500;
    if (!retryable || attempt >= maxRetries) {
      const body = await res.text();
      throw new Error(`Anthropic ${res.status}: ${body}`);
    }
    const ra = res.headers.get('retry-after');
    const backoff = ra ? parseInt(ra, 10) * 1000 : Math.min(60_000, 2 ** attempt * 1000);
    process.stdout.write(`(rate-limited ${Math.round(backoff / 1000)}s) `);
    await sleep(backoff);
    attempt++;
  }
}

function parseCards(text) {
  const m = text.trim().match(/\[[\s\S]*\]/);
  if (!m) return null;
  try {
    const parsed = JSON.parse(m[0]);
    return Array.isArray(parsed) ? parsed : null;
  } catch { return null; }
}

async function generateCardSet({ role, bubble }) {
  const cardSystem = buildCardPrompt({ role });
  const userMsg = buildCardUserMessage({ bubble, role });

  const draft = await anthropic({
    model: LENS_MODEL,
    system: [{ type: 'text', text: cardSystem, cache_control: { type: 'ephemeral' } }],
    messages: [{ role: 'user', content: userMsg }],
  });
  const draftCards = parseCards(draft);
  if (!draftCards) return { draft, rewritten: null, cards: null };

  const rewriterSys = buildRewriterPrompt();
  const rewriteUser = `Here is the draft JSON array of cards for the "${bubble}" bubble. For each card, apply the rewriter workflow. Preserve the anchor topics and specifics. Return ONLY the corrected JSON array — same count, same anchors, only language reshaped.\n\n${JSON.stringify(draftCards, null, 2)}`;

  const rewritten = await anthropic({
    model: REWRITER_MODEL,
    system: [{ type: 'text', text: rewriterSys, cache_control: { type: 'ephemeral' } }],
    messages: [{ role: 'user', content: rewriteUser }],
  });
  const finalCards = parseCards(rewritten) || draftCards;
  return { draftCards, finalCards };
}

function printCardSet({ role, bubble, sampleIdx, finalCards, draftCards }) {
  const hr = '─'.repeat(70);
  console.log(`\n${hr}`);
  console.log(`${role}  ·  bubble: ${bubble}  ·  sample ${sampleIdx + 1}`);
  console.log(hr);
  if (!finalCards) {
    console.log('[no parseable cards]');
    return;
  }
  finalCards.forEach((c, i) => {
    console.log(`\n  [${i + 1}] ${c.headline}`);
    const body = (c.body || '').split('. ').filter(Boolean);
    body.forEach((s) => {
      const clean = s.endsWith('.') ? s : s + '.';
      console.log(`      ${clean}`);
    });
  });
}

async function main() {
  const targets = runAll
    ? ARCHETYPES
    : [{ role: arg('role', 'VP of Marketing'), bubble: arg('bubble', 'marketing') }];

  console.log(`Sampling ${targets.length} archetype(s) × ${n} samples each = ${targets.length * n} card sets`);
  console.log(`Draft model: ${LENS_MODEL}  ·  Rewriter model: ${REWRITER_MODEL}`);

  for (const t of targets) {
    for (let i = 0; i < n; i++) {
      try {
        const out = await generateCardSet(t);
        printCardSet({ ...t, sampleIdx: i, ...out });
      } catch (e) {
        console.log(`\n[error ${t.role} / ${t.bubble} sample ${i + 1}]: ${e.message}`);
      }
      if (i < n - 1 || targets.indexOf(t) < targets.length - 1) await sleep(2000);
    }
  }
  console.log('\nDone.');
}

main().catch((e) => { console.error(e); process.exit(1); });
