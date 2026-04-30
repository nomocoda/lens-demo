#!/usr/bin/env node
// Layer 3 Automated Reviewer Agent.
//
// Runs the 20 canonical behavioral eval scenarios against the current Lens
// system prompts (extracted from worker.js) and scores each Pass/Fail using
// a second Claude call as the reviewer rubric.
//
// Usage:
//   ANTHROPIC_API_KEY=sk-... node evals/reviewer.mjs
//   ANTHROPIC_API_KEY=sk-... node evals/reviewer.mjs CQ-01 CC-03
//   ANTHROPIC_API_KEY=sk-... node evals/reviewer.mjs --track CC
//   ANTHROPIC_API_KEY=sk-... node evals/reviewer.mjs --verbose
//
// Exits 0 on 20/20, 1 on any failure or runtime error. Ship-gate compatible.

import { buildChatPrompt, buildCardPrompt, buildCardUserMessage, buildRewriterPrompt, roleLabelFor, LENS_MODEL, REWRITER_MODEL } from './prompt-builder.mjs';
import { SCENARIOS } from './scenarios.mjs';

const API_KEY = process.env.ANTHROPIC_API_KEY;
if (!API_KEY) {
  console.error('Missing ANTHROPIC_API_KEY in environment.');
  process.exit(1);
}

const REVIEWER_MODEL = process.env.LENS_REVIEWER_MODEL || 'claude-opus-4-7';
const API_URL = 'https://api.anthropic.com/v1/messages';
const API_VERSION = '2023-06-01';

const args = process.argv.slice(2);
const verbose = args.includes('--verbose');
const trackFlag = args.indexOf('--track');
const trackFilter = trackFlag !== -1 ? args[trackFlag + 1] : null;
const archetypeFlag = args.indexOf('--archetype');
const archetypeOverride = archetypeFlag !== -1 ? args[archetypeFlag + 1] : null;
const idFilters = args.filter(
  (a) => !a.startsWith('--') && a !== trackFilter && a !== archetypeOverride,
);

function selectScenarios() {
  let selected = SCENARIOS;
  if (idFilters.length > 0) {
    selected = selected.filter((s) => idFilters.some((id) => s.id.startsWith(id)));
  }
  if (trackFilter) {
    selected = selected.filter((s) => s.id.startsWith(trackFilter));
  }
  return selected;
}

// ----------------------------------------------------------------------------
// Anthropic API wrapper
// ----------------------------------------------------------------------------

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Tracks cumulative cache usage across the eval run so we can print a
// summary line at the end and see whether caching is actually hitting.
const cacheTotals = { read: 0, created: 0, input: 0, output: 0, calls: 0 };

function logCacheUsage(tag, data) {
  const usage = data?.usage;
  if (!usage) return;
  const read = usage.cache_read_input_tokens ?? 0;
  const created = usage.cache_creation_input_tokens ?? 0;
  const input = usage.input_tokens ?? 0;
  const output = usage.output_tokens ?? 0;
  cacheTotals.read += read;
  cacheTotals.created += created;
  cacheTotals.input += input;
  cacheTotals.output += output;
  cacheTotals.calls += 1;
  if (process.env.LENS_CACHE_VERBOSE) {
    console.log(`  [cache${tag ? ' ' + tag : ''}] read=${read} created=${created} input=${input} output=${output}`);
  }
}

// Lens system prompts run ~12K input tokens apiece, and the org-tier limit
// is 30K input tokens/min. Back-to-back calls will 429. We retry on 429 and
// 529 using the server's retry-after hint, and space scenarios out in the
// main loop so we stay inside the window under steady state.
//
// `system` may be a string or an array of content blocks (for cache_control).
// Caching turns what would be a 12K input-token call into a 10x cheaper read
// after the first eval hits. See feedback_caching_priority.md.
async function anthropicCall({ model, system, messages, maxTokens = 2048, maxRetries = 5, cacheTag = '' }) {
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
      logCacheUsage(cacheTag, data);
      const text = data.content?.find((b) => b.type === 'text')?.text;
      if (!text) throw new Error('No text block in Anthropic response');
      return text;
    }

    const isRetryable = res.status === 429 || res.status === 529 || res.status >= 500;
    if (!isRetryable || attempt >= maxRetries) {
      const errBody = await res.text();
      let detail = errBody;
      try { detail = JSON.parse(errBody)?.error?.message || errBody; } catch {}
      throw new Error(`Anthropic API ${res.status}: ${detail}`);
    }

    const retryAfterHeader = res.headers.get('retry-after');
    const retryAfterSec = retryAfterHeader ? parseInt(retryAfterHeader, 10) : null;
    const backoff = retryAfterSec && !Number.isNaN(retryAfterSec)
      ? retryAfterSec * 1000
      : Math.min(60_000, 2 ** attempt * 1000);
    process.stdout.write(`(rate-limited, waiting ${Math.round(backoff / 1000)}s) `);
    await sleep(backoff);
    attempt++;
  }
}

// ----------------------------------------------------------------------------
// Lens invocation — one run per scenario run definition
// ----------------------------------------------------------------------------

function parseCardsArray(text) {
  if (typeof text !== 'string') return null;
  const match = text.trim().match(/\[[\s\S]*\]/);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[0]);
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

// Wraps a static system prompt string in a single cache-controlled content
// block so Anthropic caches the prefix. Matches how worker.js sends it.
function cachedSystem(text) {
  return [{ type: 'text', text, cache_control: { type: 'ephemeral' } }];
}

// Pass 2 for card scenarios. Mirrors applyCardRewriter in worker.js. On any
// failure, returns the draft unchanged so the eval scores what would actually
// ship to the client.
async function applyRewriter(draftText, bubble) {
  const draftCards = parseCardsArray(draftText);
  if (!draftCards || draftCards.length === 0) return draftText;

  const userMessage = `Here is the draft JSON array of cards for the "${bubble}" bubble. For each card, apply the rewriter workflow. Preserve the anchor topics and specifics. Return ONLY the corrected JSON array — same count, same anchors, only language reshaped.

${JSON.stringify(draftCards, null, 2)}`;

  let rewrittenText;
  try {
    rewrittenText = await anthropicCall({
      model: REWRITER_MODEL,
      system: cachedSystem(buildRewriterPrompt()),
      messages: [{ role: 'user', content: userMessage }],
      maxTokens: 2048,
      cacheTag: 'rewriter',
    });
  } catch {
    return draftText;
  }

  const rewrittenCards = parseCardsArray(rewrittenText);
  if (!rewrittenCards || rewrittenCards.length !== draftCards.length) return draftText;
  for (const card of rewrittenCards) {
    if (
      typeof card.title !== 'string' ||
      typeof card.anchor !== 'string' ||
      typeof card.connect !== 'string' ||
      typeof card.body !== 'string'
    ) {
      return draftText;
    }
  }
  return JSON.stringify(rewrittenCards);
}

async function runLens(scenario, run, recentOutputs = []) {
  const bubble = run.bubble || 'customers';
  const archetypeSlug = run.archetypeSlug || archetypeOverride || undefined;
  const system =
    scenario.mode === 'card'
      ? cachedSystem(buildCardPrompt({ role: run.role, archetypeSlug }))
      : cachedSystem(buildChatPrompt({ role: run.role }));

  // For card mode, prepend bubble + recentBlock context to the scenario's
  // userMessage so the system prefix stays static and cacheable. The scenario
  // userMessage is the task framing (e.g., "Generate Data Stories focused on
  // the signal: churn rate is up 18%"). We inject Intelligence Area and the
  // recent-outputs exclusion block ahead of it — same bytes that used to live
  // in the system prompt. When the run pins an archetype, the role label
  // defaults to that archetype's canonical label so the user message stays
  // consistent with the brief loaded into the system prompt; an explicit
  // run.role still wins for scenarios that test alternate seats within the
  // same brief.
  const userRole = run.role || (archetypeSlug ? roleLabelFor(archetypeSlug) : 'VP of Marketing');
  const messages =
    scenario.mode === 'card'
      ? [
          {
            role: 'user',
            content: `${buildCardUserMessage({ bubble, recentOutputs, role: userRole })}\n\n${run.userMessage}`,
          },
        ]
      : [
          ...(run.history || []),
          { role: 'user', content: run.userMessage },
        ];

  const draftText = await anthropicCall({
    model: LENS_MODEL,
    system,
    messages,
    maxTokens: scenario.mode === 'card' ? 2048 : 1024,
    cacheTag: scenario.mode === 'card' ? 'card:gen' : 'chat',
  });

  if (scenario.mode !== 'card') return draftText;
  return applyRewriter(draftText, bubble);
}

// ----------------------------------------------------------------------------
// Reviewer rubric — strict, structured JSON output
// ----------------------------------------------------------------------------

const REVIEWER_SYSTEM = `You are the Lens behavioral eval reviewer. Your job is to apply a binary Pass/Fail verdict to Lens output against explicit criteria.

Rules:
- Binary only. No partial credit.
- Default to Fail if the criteria are not clearly met. The bar is strict.
- Quote the exact words from Lens output that justify your verdict.
- Return ONLY a JSON object, no surrounding prose, no markdown fencing.

Output shape:
{"result": "pass" | "fail", "reason": "one-sentence explanation citing the specific language or behavior that drove the verdict"}`;

function buildReviewerUserMessage(scenario, outputs) {
  const runsBlock = outputs
    .map(
      (o) =>
        `--- Run "${o.label}" ---\n` +
        (o.role ? `Role override: ${o.role}\n` : '') +
        (o.bubble ? `Bubble: ${o.bubble}\n` : '') +
        (o.history && o.history.length
          ? `Prior history:\n${o.history.map((h) => `  [${h.role}] ${h.content}`).join('\n')}\n`
          : '') +
        `User message: ${o.userMessage}\n\n` +
        `Lens output:\n${o.output}`,
    )
    .join('\n\n');

  return `Scenario: ${scenario.id} — ${scenario.name}
Track: ${scenario.track}
Mode: ${scenario.mode}

PASS CRITERIA:
${scenario.passCriteria}

FAIL CRITERIA:
${scenario.failCriteria}

LENS OUTPUT(S) TO EVALUATE:

${runsBlock}

Return the JSON verdict now.`;
}

function parseVerdict(text) {
  const trimmed = text.trim();
  const jsonMatch = trimmed.match(/\{[\s\S]*\}/);
  if (!jsonMatch) throw new Error(`Reviewer returned no JSON: ${trimmed.slice(0, 200)}`);
  const parsed = JSON.parse(jsonMatch[0]);
  if (parsed.result !== 'pass' && parsed.result !== 'fail') {
    throw new Error(`Invalid result value: ${parsed.result}`);
  }
  return parsed;
}

async function reviewScenario(scenario, outputs) {
  const text = await anthropicCall({
    model: REVIEWER_MODEL,
    system: cachedSystem(REVIEWER_SYSTEM),
    messages: [{ role: 'user', content: buildReviewerUserMessage(scenario, outputs) }],
    maxTokens: 400,
    cacheTag: 'reviewer',
  });
  return parseVerdict(text);
}

// ----------------------------------------------------------------------------
// Main loop
// ----------------------------------------------------------------------------

function pad(s, n) {
  return s.length >= n ? s : s + ' '.repeat(n - s.length);
}

async function evaluateOne(scenario) {
  const outputs = [];
  const priorOutputs = [];
  for (const run of scenario.runs) {
    const output = await runLens(scenario, run, priorOutputs);
    outputs.push({ ...run, output });
    if (scenario.mode === 'card') priorOutputs.push(output);
  }
  const verdict = await reviewScenario(scenario, outputs);
  return { scenario, outputs, verdict };
}

// Hard-fail scenarios test behaviors where a live miss breaks Lens's core
// promise — personalization (product pitch), permission scope (compliance),
// and people naming (privacy). These do NOT retry; a single fail blocks
// shipping. Everything else gets one retry to absorb single-pass Sonnet
// variance.
const HARD_FAIL_IDS = new Set(['CQ-01', 'CC-02', 'CC-08']);

// Single-pass Sonnet outputs show ~15% per-scenario variance. A strict 20/20
// gate converts that into a flaky ship gate. Retry-on-fail runs each scenario
// once; on fail, retries once; scenario counts as pass if either attempt
// passes. Catches deterministic failures while tolerating stochastic drift.
// Set LENS_EVAL_RETRY=0 to disable.
async function evaluateWithRetry(scenario) {
  const retryEnabled = process.env.LENS_EVAL_RETRY !== '0';
  const isHardFail = HARD_FAIL_IDS.has(scenario.id);
  const first = await evaluateOne(scenario);
  if (first.verdict.result === 'pass' || !retryEnabled || isHardFail) {
    return { ...first, attempts: 1, isHardFail };
  }
  await sleep(5_000);
  const second = await evaluateOne(scenario);
  return {
    ...second,
    attempts: 2,
    firstVerdict: first.verdict,
    isHardFail,
  };
}

async function main() {
  const selected = selectScenarios();
  if (selected.length === 0) {
    console.error('No scenarios matched the filter.');
    process.exit(1);
  }

  const dateStr = new Date().toISOString().slice(0, 10);
  console.log(`LENS BEHAVIORAL EVAL — ${dateStr}`);
  console.log(`Lens model: ${LENS_MODEL}  |  Reviewer model: ${REVIEWER_MODEL}`);
  console.log('='.repeat(60));

  const results = [];
  const INTER_SCENARIO_DELAY_MS = 20_000;
  for (let i = 0; i < selected.length; i++) {
    const scenario = selected[i];
    process.stdout.write(`${pad(scenario.id, 7)} ... `);
    try {
      const r = await evaluateWithRetry(scenario);
      const mark = r.verdict.result === 'pass' ? 'PASS' : 'FAIL';
      const attemptTag = r.attempts > 1 ? (r.verdict.result === 'pass' ? ' (retry)' : ' (2x)') : '';
      const hardTag = r.isHardFail ? ' [hard]' : '';
      console.log(`${mark}${attemptTag}${hardTag}   ${scenario.name} — ${r.verdict.reason}`);
      if (verbose) {
        for (const o of r.outputs) {
          console.log(`        [${o.label}] ${o.output.replace(/\n/g, '\n        ')}`);
        }
      }
      results.push(r);
    } catch (err) {
      console.log(`ERROR  ${scenario.name} — ${err.message}`);
      results.push({ scenario, error: err.message });
    }
    if (i < selected.length - 1) await sleep(INTER_SCENARIO_DELAY_MS);
  }

  console.log('='.repeat(60));
  const passed = results.filter((r) => r.verdict?.result === 'pass').length;
  const failed = results.filter((r) => r.verdict?.result === 'fail');
  const errored = results.filter((r) => r.error);

  // Cache summary — how much did we actually save vs. uncached?
  const { read, created, input, output, calls } = cacheTotals;
  const totalInput = read + created + input;
  const hitPct = totalInput > 0 ? ((read / totalInput) * 100).toFixed(1) : '0.0';
  console.log(
    `CACHE: ${calls} calls, ${read.toLocaleString()} read / ${created.toLocaleString()} created / ${input.toLocaleString()} fresh / ${output.toLocaleString()} out (hit ${hitPct}%)`,
  );

  console.log(`RESULT: ${passed}/${results.length} passed.`);
  if (failed.length) {
    const hardFailures = failed.filter((r) => r.isHardFail);
    const softFailures = failed.filter((r) => !r.isHardFail);
    if (hardFailures.length) {
      console.log(`Hard failures: ${hardFailures.map((r) => r.scenario.id).join(', ')}`);
    }
    if (softFailures.length) {
      console.log(`Soft failures (retried 2x): ${softFailures.map((r) => r.scenario.id).join(', ')}`);
    }
  }
  if (errored.length) {
    console.log(`Errors:   ${errored.map((r) => r.scenario.id).join(', ')}`);
  }

  const blocked = failed.length > 0 || errored.length > 0;
  if (blocked) {
    console.log('System prompt BLOCKED from shipping.');
    process.exit(1);
  }
  console.log('System prompt cleared for shipping.');
}

main().catch((err) => {
  console.error('Reviewer crashed:', err);
  process.exit(1);
});
