// entity-resolver.js
//
// Cross-system entity resolution for Lens. The engine pulls per-org data from
// HubSpot, Slack, and Gmail via Composio. The same business entity (a customer
// account, a deal, a person) shows up under different identifiers in each
// system; this module reconciles them into a single resolution graph keyed on
// the HubSpot atlas-shape ID where one exists, with supporting evidence from
// the other sources.
//
// Phase 1 (this file): name + domain matching with normalization. Email is the
// strong signal for people. Email domain is the strong signal for companies in
// Gmail. Normalized name match is the fallback signal in Slack message text.
// Deals are anchored to a company plus an amount string.
//
// Phase 2 (not yet built): graph-based confidence scoring using engagement
// frequency and recency to break ambiguity.
//
// Inputs are the same atlas-shape produced by scripts/eval/hubspot_adapter.py
// for HubSpot, plus a Slack shape and a Gmail shape that match what Composio
// returns from those connectors. The module is pure: no I/O, no globals.

// ---------------------------------------------------------------------------
// Normalization
// ---------------------------------------------------------------------------

const COMPANY_SUFFIXES = [
  'inc', 'incorporated', 'llc', 'l l c', 'ltd', 'limited', 'corp', 'corporation',
  'co', 'company', 'plc', 'gmbh', 'sa', 's a', 'ag', 'pty',
];

export function normalizeName(value) {
  if (!value) return '';
  let s = String(value).toLowerCase();
  s = s.replace(/[‘’“”]/g, "'");
  s = s.replace(/&/g, ' and ');
  s = s.replace(/[^\p{L}\p{N}\s]/gu, ' ');
  s = s.replace(/\s+/g, ' ').trim();
  for (const suffix of COMPANY_SUFFIXES) {
    const re = new RegExp(`(^|\\s)${suffix}$`);
    if (re.test(s)) {
      s = s.replace(re, '').trim();
      break;
    }
  }
  return s;
}

export function normalizeDomain(value) {
  if (!value) return '';
  let s = String(value).toLowerCase().trim();
  s = s.replace(/^https?:\/\//, '');
  s = s.replace(/^www\./, '');
  s = s.split('/')[0];
  s = s.split('?')[0];
  return s;
}

export function normalizeEmail(value) {
  if (!value) return '';
  return String(value).toLowerCase().trim();
}

export function emailDomain(email) {
  const e = normalizeEmail(email);
  const at = e.lastIndexOf('@');
  if (at < 0) return '';
  return normalizeDomain(e.slice(at + 1));
}

export function tokenSet(value) {
  const norm = normalizeName(value);
  if (!norm) return new Set();
  return new Set(norm.split(' ').filter(t => t.length >= 2));
}

// Generic free-domain providers — these can never anchor a company match.
const PUBLIC_EMAIL_DOMAINS = new Set([
  'gmail.com', 'googlemail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
  'live.com', 'icloud.com', 'me.com', 'aol.com', 'proton.me', 'protonmail.com',
  'msn.com', 'pm.me', 'gmx.com', 'mail.com',
]);

export function isPublicEmailDomain(domain) {
  return PUBLIC_EMAIL_DOMAINS.has(normalizeDomain(domain));
}

// ---------------------------------------------------------------------------
// Match scoring
// ---------------------------------------------------------------------------

// Jaccard token overlap. Strong, simple, deterministic — good enough for
// account-name matching where names tend to be 2-4 distinctive tokens. Fuzzier
// schemes (Levenshtein, embeddings) are deferred to Phase 2.
export function tokenJaccard(a, b) {
  const A = tokenSet(a);
  const B = tokenSet(b);
  if (A.size === 0 || B.size === 0) return 0;
  let inter = 0;
  for (const t of A) if (B.has(t)) inter += 1;
  const union = A.size + B.size - inter;
  return union === 0 ? 0 : inter / union;
}

export function scoreCompanyNameMatch(a, b) {
  const na = normalizeName(a);
  const nb = normalizeName(b);
  if (!na || !nb) return 0;
  if (na === nb) return 1;
  return tokenJaccard(na, nb);
}

// ---------------------------------------------------------------------------
// Mention finders — locate references to known entities inside free text.
// ---------------------------------------------------------------------------

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Find HubSpot company name occurrences inside a block of text. Whole-word
// matching against the normalized name; falls back to all-token presence when
// the literal phrase is broken up. Returns the list of company IDs the text
// references.
export function findCompanyMentions(text, companies) {
  if (!text) return [];
  const haystack = ' ' + normalizeName(text) + ' ';
  const out = [];
  for (const co of companies) {
    const norm = normalizeName(co.name);
    if (!norm) continue;
    if (haystack.includes(' ' + norm + ' ')) {
      out.push({ companyId: co.id, match: 'phrase' });
      continue;
    }
    const tokens = norm.split(' ').filter(t => t.length >= 4);
    if (tokens.length >= 2 && tokens.every(t => haystack.includes(' ' + t + ' '))) {
      out.push({ companyId: co.id, match: 'tokens' });
    }
  }
  return out;
}

// Deals don't carry a free-text name in the atlas shape — they're identified
// by `(company_id, amount)`. A slack/gmail mention is treated as a deal
// reference when both the company name and the amount appear in the same
// text. Amounts are normalized to strip thousands separators and currency
// glyphs.
function amountVariants(amount) {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return [];
  const rounded = Math.round(amount);
  return [
    String(rounded),
    rounded.toLocaleString('en-US'),
    `$${rounded.toLocaleString('en-US')}`,
    `$${rounded}`,
  ];
}

export function findDealMentions(text, deals, companies) {
  if (!text) return [];
  const coById = new Map(companies.map(c => [c.id, c]));
  const lower = String(text).toLowerCase();
  const normHaystack = ' ' + normalizeName(text) + ' ';
  const out = [];
  for (const d of deals) {
    const co = coById.get(d.company_id);
    if (!co) continue;
    const coNorm = normalizeName(co.name);
    if (!coNorm) continue;
    const coPresent = normHaystack.includes(' ' + coNorm + ' ');
    if (!coPresent) continue;
    for (const v of amountVariants(d.amount)) {
      if (lower.includes(v.toLowerCase())) {
        out.push({ dealId: d.id, companyId: co.id, match: 'name+amount' });
        break;
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Resolution
// ---------------------------------------------------------------------------

const DEFAULT_INPUT = Object.freeze({
  hubspot: { companies: [], contacts: [], deals: [] },
  slack:   { channels: [], messages: [] },
  gmail:   { threads: [] },
});

function defaulted(input) {
  const i = input || {};
  return {
    hubspot: {
      companies: (i.hubspot && i.hubspot.companies) || [],
      contacts:  (i.hubspot && i.hubspot.contacts)  || [],
      deals:     (i.hubspot && i.hubspot.deals)     || [],
    },
    slack: {
      channels: (i.slack && i.slack.channels) || [],
      messages: (i.slack && i.slack.messages) || [],
      users:    (i.slack && i.slack.users)    || [],
    },
    gmail: {
      threads: (i.gmail && i.gmail.threads) || [],
    },
  };
}

// Map a HubSpot company to the email domain its contacts use most often.
// This is the only signal strong enough to anchor Gmail matches without a
// per-company website field; it falls out of contacts the customer has
// already connected.
function companyDomainsFromContacts(companies, contacts) {
  const counts = new Map(); // companyId -> Map(domain -> count)
  for (const ct of contacts) {
    const domain = emailDomain(ct.email);
    if (!domain || isPublicEmailDomain(domain)) continue;
    if (!ct.company_id) continue;
    const inner = counts.get(ct.company_id) || new Map();
    inner.set(domain, (inner.get(domain) || 0) + 1);
    counts.set(ct.company_id, inner);
  }
  const out = new Map();
  for (const [companyId, inner] of counts) {
    let bestDomain = null;
    let bestCount = 0;
    for (const [domain, count] of inner) {
      if (count > bestCount) {
        bestCount = count;
        bestDomain = domain;
      }
    }
    if (bestDomain) out.set(companyId, bestDomain);
  }
  return out;
}

function resolveCompanies({ hubspot, slack, gmail }, contactDomains) {
  const out = new Map();
  for (const co of hubspot.companies) {
    const domain = contactDomains.get(co.id) || '';
    out.set(co.id, {
      id: co.id,
      name: co.name || '',
      domain,
      sources: {
        hubspot: { id: co.id },
        slack:   { channelIds: [], messageRefs: [] },
        gmail:   { threadIds: [], domains: [] },
      },
      confidence: 1,
    });
  }
  if (out.size === 0) return [];

  const companies = hubspot.companies;
  const domainToCompanyId = new Map();
  for (const [companyId, domain] of contactDomains) {
    if (domain) domainToCompanyId.set(domain, companyId);
  }

  // Slack channel topic / purpose mentions — accept name match in either.
  for (const ch of slack.channels) {
    const text = [ch.topic, ch.purpose, ch.name && ch.name.replace(/-/g, ' ')]
      .filter(Boolean).join(' ');
    for (const { companyId } of findCompanyMentions(text, companies)) {
      const node = out.get(companyId);
      if (node && !node.sources.slack.channelIds.includes(ch.id)) {
        node.sources.slack.channelIds.push(ch.id);
      }
    }
  }

  // Slack message text mentions.
  for (const msg of slack.messages) {
    if (!msg || !msg.text) continue;
    for (const { companyId } of findCompanyMentions(msg.text, companies)) {
      const node = out.get(companyId);
      if (!node) continue;
      node.sources.slack.messageRefs.push({
        channelId: msg.channel_id || null,
        ts: msg.ts || null,
      });
      if (msg.channel_id && !node.sources.slack.channelIds.includes(msg.channel_id)) {
        node.sources.slack.channelIds.push(msg.channel_id);
      }
    }
  }

  // Gmail: participant domains anchor company matches.
  for (const t of gmail.threads) {
    const seenDomains = new Set();
    const participants = t.participants || [];
    for (const p of participants) {
      const d = emailDomain(p && p.email);
      if (d && !isPublicEmailDomain(d)) seenDomains.add(d);
    }
    if (t.subject) {
      for (const { companyId } of findCompanyMentions(t.subject, companies)) {
        const node = out.get(companyId);
        if (node && !node.sources.gmail.threadIds.includes(t.id)) {
          node.sources.gmail.threadIds.push(t.id);
        }
      }
    }
    for (const d of seenDomains) {
      const companyId = domainToCompanyId.get(d);
      if (!companyId) continue;
      const node = out.get(companyId);
      if (!node) continue;
      if (!node.sources.gmail.threadIds.includes(t.id)) {
        node.sources.gmail.threadIds.push(t.id);
      }
      if (!node.sources.gmail.domains.includes(d)) {
        node.sources.gmail.domains.push(d);
      }
    }
  }

  return [...out.values()];
}

function resolvePeople({ hubspot, slack, gmail }) {
  // Index contacts by normalized email and by full name.
  const byEmail = new Map();   // email -> contact
  const byName  = new Map();   // normalized "first last" -> [contact]
  for (const ct of hubspot.contacts) {
    const email = normalizeEmail(ct.email);
    if (email) byEmail.set(email, ct);
    const name = normalizeName(`${ct.first_name || ''} ${ct.last_name || ''}`);
    if (name) {
      const list = byName.get(name) || [];
      list.push(ct);
      byName.set(name, list);
    }
  }

  const out = new Map();
  function ensureNode(contact, confidence) {
    const node = out.get(contact.id);
    if (node) {
      if (confidence > node.confidence) node.confidence = confidence;
      return node;
    }
    const fresh = {
      id: contact.id,
      email: normalizeEmail(contact.email),
      name: `${contact.first_name || ''} ${contact.last_name || ''}`.trim(),
      companyId: contact.company_id || null,
      sources: {
        hubspot: { id: contact.id },
        slack:   { userIds: [], userEmails: [] },
        gmail:   { threadIds: [], participantEmails: [] },
      },
      confidence,
    };
    out.set(contact.id, fresh);
    return fresh;
  }
  for (const ct of hubspot.contacts) ensureNode(ct, 1);

  // Slack: resolve users by email when the workspace exposes profile.email.
  // Name-only fallback applies confidence 0.6 (ambiguous: same name can collide).
  for (const u of slack.users || []) {
    if (!u) continue;
    const email = normalizeEmail(u.profile && u.profile.email);
    if (email && byEmail.has(email)) {
      const node = ensureNode(byEmail.get(email), 1);
      if (u.id && !node.sources.slack.userIds.includes(u.id)) {
        node.sources.slack.userIds.push(u.id);
      }
      if (!node.sources.slack.userEmails.includes(email)) {
        node.sources.slack.userEmails.push(email);
      }
      continue;
    }
    const fullName = u.profile && (u.profile.real_name || u.profile.display_name);
    const norm = normalizeName(fullName || '');
    if (norm && byName.has(norm)) {
      const matches = byName.get(norm);
      if (matches.length === 1) {
        const node = ensureNode(matches[0], Math.max(0.6, out.get(matches[0].id)?.confidence || 0.6));
        node.confidence = Math.min(node.confidence, 0.6);
        if (u.id && !node.sources.slack.userIds.includes(u.id)) {
          node.sources.slack.userIds.push(u.id);
        }
      }
    }
  }

  // Gmail: resolve participants by email; record thread membership.
  for (const t of gmail.threads) {
    const participants = t.participants || [];
    for (const p of participants) {
      const email = normalizeEmail(p && p.email);
      if (!email) continue;
      if (byEmail.has(email)) {
        const node = ensureNode(byEmail.get(email), 1);
        if (t.id && !node.sources.gmail.threadIds.includes(t.id)) {
          node.sources.gmail.threadIds.push(t.id);
        }
        if (!node.sources.gmail.participantEmails.includes(email)) {
          node.sources.gmail.participantEmails.push(email);
        }
      }
    }
  }

  return [...out.values()];
}

function resolveDeals({ hubspot, slack, gmail }) {
  const out = new Map();
  const companies = hubspot.companies;
  for (const d of hubspot.deals) {
    out.set(d.id, {
      id: d.id,
      companyId: d.company_id || null,
      amount: typeof d.amount === 'number' ? d.amount : null,
      stage: d.stage || null,
      sources: {
        hubspot: { id: d.id },
        slack:   { messageRefs: [] },
        gmail:   { threadIds: [] },
      },
      confidence: 1,
    });
  }
  if (out.size === 0) return [];

  for (const msg of slack.messages) {
    if (!msg || !msg.text) continue;
    for (const { dealId } of findDealMentions(msg.text, hubspot.deals, companies)) {
      const node = out.get(dealId);
      if (!node) continue;
      node.sources.slack.messageRefs.push({
        channelId: msg.channel_id || null,
        ts: msg.ts || null,
      });
    }
  }

  for (const t of gmail.threads) {
    const text = [t.subject, ...(t.messages || []).map(m => m.snippet || '')].filter(Boolean).join('\n');
    for (const { dealId } of findDealMentions(text, hubspot.deals, companies)) {
      const node = out.get(dealId);
      if (!node) continue;
      if (t.id && !node.sources.gmail.threadIds.includes(t.id)) {
        node.sources.gmail.threadIds.push(t.id);
      }
    }
  }

  return [...out.values()];
}

export function resolveEntities(input) {
  const data = defaulted(input);
  const contactDomains = companyDomainsFromContacts(
    data.hubspot.companies,
    data.hubspot.contacts,
  );
  const companies = resolveCompanies(data, contactDomains);
  const people    = resolvePeople(data);
  const deals     = resolveDeals(data);
  return { companies, people, deals };
}

export const __internal = {
  COMPANY_SUFFIXES,
  PUBLIC_EMAIL_DOMAINS,
  companyDomainsFromContacts,
  resolveCompanies,
  resolvePeople,
  resolveDeals,
  amountVariants,
  escapeRegex,
  DEFAULT_INPUT,
};
