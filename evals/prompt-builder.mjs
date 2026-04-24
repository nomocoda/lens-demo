// Rebuilds the Lens system prompts outside the Cloudflare Worker runtime by
// extracting the template literals from worker.js and interpolating the
// markdown source files that normally load via Worker bundler imports.
//
// This is the reviewer agent's only way to know what ships. If worker.js
// changes shape, update the extractors here.

import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');

const workerSrc = readFileSync(resolve(repoRoot, 'worker.js'), 'utf8');
const PERSONA = readFileSync(resolve(repoRoot, 'data/persona.md'), 'utf8');
const VOICE_BRIEF = readFileSync(resolve(repoRoot, 'data/voice-brief.md'), 'utf8');
const COMPANY_DATA = readFileSync(resolve(repoRoot, 'data/atlas-saas.md'), 'utf8');

function extractTaggedConst(src, name) {
  const re = new RegExp(`const\\s+${name}\\s*=\\s*\`([\\s\\S]*?)\`;`);
  const m = re.exec(src);
  if (!m) throw new Error(`Could not extract const ${name} from worker.js`);
  return m[1];
}

function extractReturnTemplate(src, fnName) {
  const re = new RegExp(`function\\s+${fnName}[\\s\\S]*?return\\s+\`([\\s\\S]*?)\`;`);
  const m = re.exec(src);
  if (!m) throw new Error(`Could not extract template from ${fnName} in worker.js`);
  return m[1];
}

function extractModelId(src) {
  const m = /model:\s*'([^']+)'/.exec(src);
  return m ? m[1] : 'claude-sonnet-4-5';
}

// The rewriter call uses a different model than the generator. Extract the
// model string from inside applyCardRewriter specifically so the eval mirrors
// worker.js even when the two models diverge.
function extractRewriterModelId(src) {
  const fnMatch = /async function applyCardRewriter[\s\S]*?\n\}/.exec(src);
  if (!fnMatch) return null;
  const m = /model:\s*'([^']+)'/.exec(fnMatch[0]);
  return m ? m[1] : null;
}

const IDENTITY_GUARDRAIL = extractTaggedConst(workerSrc, 'IDENTITY_GUARDRAIL');
const DATA_BOUNDARY = extractTaggedConst(workerSrc, 'DATA_BOUNDARY');
const FABRICATION_GUARD = extractTaggedConst(workerSrc, 'FABRICATION_GUARD');
const SKEPTICISM_GUARD = extractTaggedConst(workerSrc, 'SKEPTICISM_GUARD');
const ROLE_SCOPING = extractTaggedConst(workerSrc, 'ROLE_SCOPING');
const CARD_SELECTION_ROLE_SCOPED = extractTaggedConst(workerSrc, 'CARD_SELECTION_ROLE_SCOPED');
const FORWARD_FRAMING_GUARD = extractTaggedConst(workerSrc, 'FORWARD_FRAMING_GUARD');
const CHAT_CLOSING_GUARD = extractTaggedConst(workerSrc, 'CHAT_CLOSING_GUARD');
const PEOPLE_NAMING_GUARD = extractTaggedConst(workerSrc, 'PEOPLE_NAMING_GUARD');
const SIGNAL_VS_REPORT_GUARD = extractTaggedConst(workerSrc, 'SIGNAL_VS_REPORT_GUARD');
const COMPOSITION_COMPLETENESS_GUARD = extractTaggedConst(workerSrc, 'COMPOSITION_COMPLETENESS_GUARD');
const FRESHNESS_GUARD = extractTaggedConst(workerSrc, 'FRESHNESS_GUARD');
const OUTPUT_HYGIENE_GUARD = extractTaggedConst(workerSrc, 'OUTPUT_HYGIENE_GUARD');
const SOURCE_DISCLOSURE_GUARD = extractTaggedConst(workerSrc, 'SOURCE_DISCLOSURE_GUARD');
const ARCHETYPE_PERSISTENCE_GUARD = extractTaggedConst(workerSrc, 'ARCHETYPE_PERSISTENCE_GUARD');
const chatTemplate = extractReturnTemplate(workerSrc, 'buildChatSystemPrompt');
const cardTemplate = extractReturnTemplate(workerSrc, 'buildCardSystemPrompt');

// The rewriter system prompt interpolates three guard constants. Extract the
// raw template and then interpolate the guards so the eval sees the exact
// string the worker would send.
const rawRewriterTemplate = extractTaggedConst(workerSrc, 'CARD_REWRITER_SYSTEM');
const CARD_REWRITER_SYSTEM = rawRewriterTemplate
  .replaceAll('${FORWARD_FRAMING_GUARD}', FORWARD_FRAMING_GUARD)
  .replaceAll('${SIGNAL_VS_REPORT_GUARD}', SIGNAL_VS_REPORT_GUARD)
  .replaceAll('${COMPOSITION_COMPLETENESS_GUARD}', COMPOSITION_COMPLETENESS_GUARD)
  .replaceAll('${PEOPLE_NAMING_GUARD}', PEOPLE_NAMING_GUARD);

export function buildRewriterPrompt() {
  return CARD_REWRITER_SYSTEM;
}

export const LENS_MODEL = extractModelId(workerSrc);
export const REWRITER_MODEL = extractRewriterModelId(workerSrc) || LENS_MODEL;

function interpolate(template, vars) {
  let out = template;
  for (const [key, value] of Object.entries(vars)) {
    out = out.replaceAll('${' + key + '}', value);
  }
  return out;
}

// Role override swaps the hardcoded "VP of Marketing at Atlas SaaS" string
// for scenarios that need a different archetype (CMO, VP Revenue, marketing
// manager). Keeps the rest of the prompt shape identical to production.
function applyRoleOverride(prompt, role) {
  if (!role) return prompt;
  const replacements = [
    [/the VP of Marketing at Atlas SaaS/g, `the ${role} at Atlas SaaS`],
    [/VP of Marketing at Atlas SaaS/g, `${role} at Atlas SaaS`],
    [/a senior operator \(the VP of Marketing at Atlas SaaS in this demo\)/g,
     `a senior operator (the ${role} at Atlas SaaS in this demo)`],
  ];
  let out = prompt;
  for (const [re, rep] of replacements) out = out.replace(re, rep);
  return out;
}

export function buildChatPrompt({ role = null } = {}) {
  const out = interpolate(chatTemplate, {
    PERSONA,
    VOICE_BRIEF,
    IDENTITY_GUARDRAIL,
    DATA_BOUNDARY,
    COMPANY_DATA,
    FABRICATION_GUARD,
    SKEPTICISM_GUARD,
    ROLE_SCOPING,
    FORWARD_FRAMING_GUARD,
    CHAT_CLOSING_GUARD,
    PEOPLE_NAMING_GUARD,
    SOURCE_DISCLOSURE_GUARD,
    ARCHETYPE_PERSISTENCE_GUARD,
  });
  return applyRoleOverride(out, role);
}

// Mirrors buildRecentOutputsBlock in worker.js. When prior outputs exist for
// this scenario's run sequence, the block gets interpolated into the user
// message so the system prompt stays fully cacheable. Keep in sync with
// worker.js.
function buildRecentOutputsBlock(recentOutputs) {
  if (!recentOutputs || recentOutputs.length === 0) return '';
  const formatted = recentOutputs
    .map((output, i) => `Generation ${i + 1}:\n${typeof output === 'string' ? output : JSON.stringify(output, null, 2)}`)
    .join('\n\n');
  return `RECENT GENERATIONS FOR THIS READER — DO NOT REPEAT

The reader just saw these cards in their most recent refresh(es) of this bubble:

${formatted}

For this generation, produce a MATERIALLY DIFFERENT set:
- None of the named entities (accounts, people, features, campaigns, competitors) above may appear as the anchor of a card.
- None of the metric framings above may be reused — even with different numbers or different phrasing.
- None of the underlying stories above may be re-told from a different angle. If "Prism Analytics renewal risk" appeared above, do not anchor a card on Prism Analytics in this generation, period — not the renewal, not the champion departure, not the usage level, nothing about Prism.

Pull anchors from corners of the data that were NOT touched above. This is a hard exclusion rule: signals present in the recent generations are off-limits for this one, regardless of how tempting they feel.

---

`;
}

// Mirrors buildCardUserMessage in worker.js. Must stay in sync.
export function buildCardUserMessage({ bubble = 'customers', recentOutputs = [], role = 'VP of Marketing' } = {}) {
  const recentBlock = buildRecentOutputsBlock(recentOutputs);
  return `${recentBlock}Generate Data Stories for the "${bubble}" Intelligence Area. Focus on what's most relevant to the ${role} right now based on the company data.`;
}

// The card system prompt is now fully static (no ${bubble}, no ${recentBlock})
// so the prefix stays cacheable across all bubbles and calls. The role
// override still swaps "VP of Marketing" for scenarios that test other
// archetypes, which means scenarios with role overrides use a distinct cache
// entry from the default VP of Marketing production prefix. Acceptable —
// production only uses one role at a time.
export function buildCardPrompt({ role = null } = {}) {
  const out = interpolate(cardTemplate, {
    PERSONA,
    VOICE_BRIEF,
    IDENTITY_GUARDRAIL,
    DATA_BOUNDARY,
    COMPANY_DATA,
    FABRICATION_GUARD,
    ROLE_SCOPING,
    CARD_SELECTION_ROLE_SCOPED,
    FORWARD_FRAMING_GUARD,
    PEOPLE_NAMING_GUARD,
    SIGNAL_VS_REPORT_GUARD,
    COMPOSITION_COMPLETENESS_GUARD,
    FRESHNESS_GUARD,
    OUTPUT_HYGIENE_GUARD,
  });
  return applyRoleOverride(out, role);
}
