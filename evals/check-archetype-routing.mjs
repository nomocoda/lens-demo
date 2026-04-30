#!/usr/bin/env node
// Ad-hoc cross-archetype routing verification.
//
// Hits the Anthropic API directly with the per-archetype card system prompt
// and a role-neutral user message, then prints the cards for each archetype
// so we can confirm routing produces materially different, role-appropriate
// outputs. Not part of the ship-gate eval — this is a one-shot verification
// after worker.js gains per-archetype routing.
//
// Usage:
//   ANTHROPIC_API_KEY=sk-... node evals/check-archetype-routing.mjs
//   ANTHROPIC_API_KEY=sk-... node evals/check-archetype-routing.mjs marketing-leader revenue-leader

import { ARCHETYPE_SLUGS, buildCardPrompt, buildCardUserMessage, roleLabelFor, LENS_MODEL } from './prompt-builder.mjs';

const API_KEY = process.env.ANTHROPIC_API_KEY;
if (!API_KEY) {
  console.error('Missing ANTHROPIC_API_KEY in environment.');
  process.exit(1);
}

const API_URL = 'https://api.anthropic.com/v1/messages';
const API_VERSION = '2023-06-01';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const args = process.argv.slice(2);
const slugs = args.length > 0 ? args : ARCHETYPE_SLUGS;

async function callOnce(archetypeSlug) {
  const role = roleLabelFor(archetypeSlug);
  const system = [
    {
      type: 'text',
      text: buildCardPrompt({ archetypeSlug }),
      cache_control: { type: 'ephemeral' },
    },
  ];
  // Bubble matches the archetype's domain so the prompt has internal
  // consistency. Marketing archetypes get marketing bubble, revenue gets
  // revenue, customer gets customers.
  const bubble = archetypeSlug.startsWith('marketing-')
    ? 'marketing'
    : archetypeSlug.startsWith('revenue-')
      ? 'revenue'
      : 'customers';
  const userText = `${buildCardUserMessage({ bubble, role })}\n\nGenerate 3 Data Stories.`;

  let attempt = 0;
  while (true) {
    const res = await fetch(API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': API_KEY,
        'anthropic-version': API_VERSION,
      },
      body: JSON.stringify({
        model: LENS_MODEL,
        max_tokens: 2048,
        system,
        messages: [{ role: 'user', content: userText }],
      }),
    });

    if (res.ok) {
      const data = await res.json();
      const text = data.content?.find((b) => b.type === 'text')?.text;
      return text;
    }

    if ((res.status === 429 || res.status >= 500) && attempt < 4) {
      const retryAfter = parseInt(res.headers.get('retry-after') || '0', 10);
      const wait = retryAfter > 0 ? retryAfter * 1000 : Math.min(60_000, 2 ** attempt * 1000);
      process.stdout.write(`(rate-limited, waiting ${Math.round(wait / 1000)}s) `);
      await sleep(wait);
      attempt++;
      continue;
    }

    const body = await res.text();
    throw new Error(`Anthropic API ${res.status}: ${body.slice(0, 300)}`);
  }
}

function parseCards(text) {
  const m = text?.trim().match(/\[[\s\S]*\]/);
  if (!m) return null;
  try {
    return JSON.parse(m[0]);
  } catch {
    return null;
  }
}

function summarize(cards) {
  if (!Array.isArray(cards)) return '<not an array>';
  const titles = cards.map((c) => `  • ${c.title || '<no title>'}`).join('\n');
  const shapeOK = cards.every(
    (c) =>
      typeof c.title === 'string' &&
      typeof c.anchor === 'string' &&
      typeof c.connect === 'string' &&
      typeof c.body === 'string',
  );
  const bodyOK = cards.every((c) => c.body === `${c.anchor.trim()} ${c.connect.trim()}`);
  return `  shape={title,anchor,connect,body}: ${shapeOK ? 'OK' : 'MISSING FIELDS'} | body=anchor+" "+connect: ${bodyOK ? 'OK' : 'DRIFT'}\n${titles}`;
}

async function main() {
  console.log(`Cross-archetype routing check — model: ${LENS_MODEL}`);
  console.log('='.repeat(70));
  let failed = 0;
  for (const slug of slugs) {
    process.stdout.write(`${slug.padEnd(22)} ... `);
    try {
      const text = await callOnce(slug);
      const cards = parseCards(text);
      if (!cards) {
        console.log('FAIL — no JSON array parsed');
        failed++;
        continue;
      }
      console.log(`${cards.length} cards`);
      console.log(summarize(cards));
    } catch (err) {
      console.log(`ERROR — ${err.message}`);
      failed++;
    }
    await sleep(20_000);
  }
  console.log('='.repeat(70));
  console.log(failed === 0 ? `OK — ${slugs.length} archetypes routed.` : `FAIL — ${failed} of ${slugs.length} archetypes failed.`);
  process.exit(failed === 0 ? 0 : 1);
}

main();
