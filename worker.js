/**
 * Cloudflare Worker — Lens API (server-side intelligence layer)
 *
 * Routes:
 *   POST /chat         → Lens chat (Claude with persona + company data)
 *   POST /cards        → Generate insight cards (Claude with persona + company data)
 *   POST /transcribe   → Speech-to-text (OpenAI Whisper)
 *
 * The browser sends only user messages. The system prompt, persona brief,
 * and company data are assembled here and never sent to the client.
 *
 * Setup:
 *   wrangler secret put ANTHROPIC_API_KEY
 *   wrangler secret put OPENAI_API_KEY
 */

// ---------------------------------------------------------------------------
// Persona + company data — bundled at deploy time, invisible to the browser
// ---------------------------------------------------------------------------

import PERSONA from './data/persona.md';
import VOICE_BRIEF from './data/voice-brief.md';
import COMPANY_DATA from './data/atlas-saas.md';

// ---------------------------------------------------------------------------
// System prompt assembly (server-side only)
// ---------------------------------------------------------------------------

function buildChatSystemPrompt() {
  return `${PERSONA}

---

${VOICE_BRIEF}

---

# Company Data (what Lens currently sees)

${COMPANY_DATA}

---

# Chat Operating Instructions

You are Lens, responding in a chat conversation with a senior operator (the VP of Operations at Atlas SaaS in this demo). This person oversees cross-functional operations, monitors how the business machine runs day-to-day, and is accountable for process efficiency, team capacity, and operational health across departments.

Follow the persona brief above exactly. You are the narrator it describes.

## Context tracking

When a card appears in the conversation history (an intelligence card the user bridged into chat), treat it as the active topic. Follow-up questions ("what contributed to this?", "tell me more", "what else?") refer to that card's subject. Do not ask for clarification when the context is present in the thread. A peer who just showed you a card and asked a question does not need you to ask "which piece caught your attention?"

## Place of yes in chat

When the user asks a question, your first move is to look at what you have and offer it. If you can partially answer, answer the part you can and name what you cannot see. If you genuinely have nothing, say so directly. Never deflect with a list of unrelated metrics. Never dump the dashboard.

The reflex: "let me see what's here." Not "I need more from you."

## Chat rhythm

Short sentences. Real exchanges. Never lecture mode. The same narrator voice from cards continues into chat, but the rhythm becomes conversational. Answer the question that was asked, then stop. Do not keep going to demonstrate value, do not pre-empt follow-ups, do not explain unless asked.

## Key reminders

- Lead with the observation. Punchline first, data underneath.
- Keep responses concise. Short paragraphs. Fragments for emphasis.
- The five composition constraints from the persona apply here too: no recommendations, no verdicts, no emotional framing, no collaboration prompts, no interpretive leaps.
- When you do not have visibility into something, name where the data lives and offer what is adjacent.
- The user is a seasoned operator. Never condescend. Never over-explain.`;
}

function buildCardSystemPrompt(bubble) {
  return `${PERSONA}

---

${VOICE_BRIEF}

---

# Company Data (what Lens currently sees)

${COMPANY_DATA}

---

# Card Generation Instructions

You are Lens, generating insight cards for the "${bubble}" category of the Advise view. The reader is the VP of Operations at Atlas SaaS, someone who monitors cross-functional operational health and cares about how the business machine runs.

## Card structure: Headline + Body

Cards have two parts. No labels, no sections. The UI displays them directly.

**Headline** (one sentence): Pure factual observation. A quantified change (delta, ratio, threshold, trend) OR a discrete event (something started, stopped, launched, ended). The shape of the fact is whatever the data naturally supports. Must fit in two lines at 375px mobile width. Aim for 6-12 words.

**Body** (two sentences): First sentence is the anchor. Adds specificity: when, where it is concentrated, what changed internally that correlates. Second sentence is the connect. Widens the lens: relates the pattern to another internal data point or a known benchmark.

## Narrator voice in cards

- Include temporal grounding: "since Tuesday," "over the past month," "for the third week running."
- Name uncertainty modestly: "though it's one cohort," "whether X or Y isn't clear yet."
- End at the observation. Leave threads pulled, not tied. The unfinished feeling is intentional.
- Every card is neutral intelligence. No signal type labels (no opportunity, risk, or trend). The human applies judgment.

## Headline test

Every headline must pass: can you imagine this VP Ops asking the question this card answers? If a VP Ops would never walk into a meeting and ask it, the headline is wrong.

## Rules

- The five composition constraints apply: no recommendations, no verdicts, no emotional framing, no collaboration prompts, no interpretive leaps.
- Vary the time horizon: mix recent (this week), 30-day, and quarter-out.
- Cross-domain connections are the highest-value cards.
- Stay grounded in the company data above. Do not invent people, accounts, or vendors not in the brief.

Respond with a JSON array of 3-5 card objects:
[{ "headline": "...", "body": "..." }]

Return ONLY the JSON array, no other text.`;
}

// ---------------------------------------------------------------------------
// Origin allowlist + CORS
// ---------------------------------------------------------------------------

const ALLOWED_ORIGINS = [
  'https://nomocoda.com',
  'https://www.nomocoda.com',
  'https://demo.nomocoda.com',
  'http://localhost',
  'http://localhost:3000',
  'http://localhost:5500',
  'http://localhost:8080',
  'http://127.0.0.1:5500',
  'http://127.0.0.1:3000',
  'http://127.0.0.1:8080',
];

function isAllowedOrigin(origin) {
  if (!origin) return false;
  if (ALLOWED_ORIGINS.includes(origin)) return true;
  if (origin.endsWith('.github.io')) return true;
  if (origin.match(/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/)) return true;
  return false;
}

function corsHeaders(origin) {
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function jsonError(message, status, origin) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
  });
}

// ---------------------------------------------------------------------------
// /chat — Lens chat (browser sends user message, Worker adds system prompt)
// ---------------------------------------------------------------------------

async function handleChat(request, env, origin) {
  try {
    const body = await request.json();

    // The browser sends: { message: "user's question", history: [...] }
    // The Worker assembles the full Claude request with system prompt.
    const userMessage = body.message;
    const history = body.history || [];

    if (!userMessage && history.length === 0) {
      return jsonError('Missing message', 400, origin);
    }

    // Build messages array: prior history + the new user message
    const messages = [
      ...history,
      ...(userMessage ? [{ role: 'user', content: userMessage }] : []),
    ];

    const anthropicRes = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 1024,
        system: buildChatSystemPrompt(),
        messages,
      }),
    });

    const data = await anthropicRes.text();
    return new Response(data, {
      status: anthropicRes.status,
      headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
    });
  } catch (err) {
    return jsonError('Chat error: ' + err.message, 500, origin);
  }
}

// ---------------------------------------------------------------------------
// /cards — Generate insight cards for a bubble category
// ---------------------------------------------------------------------------

async function handleCards(request, env, origin) {
  try {
    const body = await request.json();
    const bubble = body.bubble || 'customers';

    const anthropicRes = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 2048,
        system: buildCardSystemPrompt(bubble),
        messages: [
          {
            role: 'user',
            content: `Generate insight cards for the "${bubble}" category. Focus on what's most relevant to a VP of Operations right now based on the company data.`,
          },
        ],
      }),
    });

    const data = await anthropicRes.text();
    return new Response(data, {
      status: anthropicRes.status,
      headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
    });
  } catch (err) {
    return jsonError('Cards error: ' + err.message, 500, origin);
  }
}

// ---------------------------------------------------------------------------
// /transcribe — Speech-to-text via OpenAI Whisper
// ---------------------------------------------------------------------------

async function handleTranscribe(request, env, origin) {
  if (!env.OPENAI_API_KEY) {
    return jsonError('Transcription not configured: missing OPENAI_API_KEY', 503, origin);
  }

  try {
    const incoming = await request.formData();
    const audio = incoming.get('audio');

    if (!audio || typeof audio === 'string') {
      return jsonError('Missing audio file', 400, origin);
    }

    const outgoing = new FormData();
    outgoing.append('file', audio, audio.name || 'audio.webm');
    outgoing.append('model', 'whisper-1');
    outgoing.append('response_format', 'json');
    outgoing.append('language', 'en');

    const whisperRes = await fetch('https://api.openai.com/v1/audio/transcriptions', {
      method: 'POST',
      headers: { Authorization: `Bearer ${env.OPENAI_API_KEY}` },
      body: outgoing,
    });

    const data = await whisperRes.text();
    return new Response(data, {
      status: whisperRes.status,
      headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
    });
  } catch (err) {
    return jsonError('Transcribe error: ' + err.message, 500, origin);
  }
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    const url = new URL(request.url);

    // CORS preflight
    if (request.method === 'OPTIONS') {
      if (isAllowedOrigin(origin)) {
        return new Response(null, { status: 204, headers: corsHeaders(origin) });
      }
      return new Response('Forbidden', { status: 403 });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }

    if (!isAllowedOrigin(origin)) {
      return new Response('Forbidden', { status: 403 });
    }

    // Route by path
    switch (url.pathname) {
      case '/chat':
        return handleChat(request, env, origin);
      case '/cards':
        return handleCards(request, env, origin);
      case '/transcribe':
        return handleTranscribe(request, env, origin);
      default:
        return jsonError('Not found. Available routes: /chat, /cards, /transcribe', 404, origin);
    }
  },
};
