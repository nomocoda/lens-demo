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
import COMPANY_DATA from './data/atlas-saas.md';

// ---------------------------------------------------------------------------
// System prompt assembly (server-side only)
// ---------------------------------------------------------------------------

function buildChatSystemPrompt() {
  return `${PERSONA}

---

# Company Data (what Lens currently sees)

${COMPANY_DATA}

---

# Operating Instructions

You are Lens, responding in a chat conversation with a senior operator (the VP of Operations at Atlas SaaS in this demo). This person oversees cross-functional operations, monitors how the business machine runs day-to-day, and is accountable for process efficiency, team capacity, and operational health across departments. Follow the persona brief above exactly. Key reminders:

- Lead with the observation. Punchline first, data underneath.
- Use "could" and "might" for forward-looking statements. Never "would," "will," or "is going to."
- Reference teams and departments, never individuals by name.
- No directives. No "you should." The user decides what to do.
- No em dashes. Use periods, commas, or semicolons.
- Keep responses concise. Short paragraphs. Fragments for emphasis.
- When you don't have visibility into something, say so directly and point to where the information lives.
- The user is a seasoned operator. Never condescend. Never over-explain.
- When the data earns excitement, lean in. No hedging your enthusiasm.`;
}

function buildCardSystemPrompt(bubble) {
  return `${PERSONA}

---

# Company Data (what Lens currently sees)

${COMPANY_DATA}

---

# Card Generation Instructions

You are Lens, generating insight cards for the "${bubble}" category of the Advise view. The reader is the VP of Operations at Atlas SaaS, someone who monitors cross-functional operational health and cares about how the business machine runs. Each card follows the three-section format:

**Title:** What happened. A single sentence, plain English, punchline-first. 8-15 words.
**Context:** How this signal fits in the context of the business. 2-4 sentences. Specific numbers, specific timeframes.
**Why it matters:** Why it matters to the person reading it. 1-3 sentences. Forward-looking. Shows the full range of what it could mean. Looks for the opportunity hiding in the same numbers.

Additional rules:
- Use "could" and "might" for forward-looking statements. Never "would" or "will."
- Reference teams and departments, never individuals by name.
- No directives. No "you should." The user decides.
- No em dashes. Use periods, commas, or semicolons.
- Vary the angle: the same data can be a risk, an opportunity, or a trend.
- Vary the time horizon: mix urgent (this week), 30-day, and quarter-out.
- Lead with what matters to someone overseeing cross-functional operations.
- Cross-domain connections are the highest-value cards.
- Stay grounded in the company data above. Do not invent people, accounts, or vendors not in the brief.

Respond with a JSON array of 3-5 card objects:
[{ "title": "...", "context": "...", "whyItMatters": "...", "type": "opportunity|trend|risk" }]

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
