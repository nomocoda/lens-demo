import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  normalizeName,
  normalizeDomain,
  normalizeEmail,
  emailDomain,
  isPublicEmailDomain,
  tokenJaccard,
  scoreCompanyNameMatch,
  findCompanyMentions,
  findDealMentions,
  resolveEntities,
  __internal,
} from '../entity-resolver.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..');

// Synthetic but representative fixture: shapes mirror what the HubSpot
// adapter, Slack connector, and Gmail connector each return per the seeders
// in scripts/eval/. Three companies, two of them mentioned across systems,
// one absent from Slack and Gmail to prove no spurious matches surface.
const fixture = {
  hubspot: {
    companies: [
      { id: 'CO-00001', name: 'Figueroa and Sons',          segment: 'mid-market' },
      { id: 'CO-00002', name: 'Garcia, Yang and Gardner',   segment: 'mid-market' },
      { id: 'CO-00003', name: 'Cole LLC',                   segment: 'small-business' },
    ],
    contacts: [
      { id: 'CT-001', company_id: 'CO-00001', first_name: 'Brent',  last_name: 'Ward',     email: 'brent.ward@figueroa.com' },
      { id: 'CT-002', company_id: 'CO-00001', first_name: 'Sandra', last_name: 'Maldonado', email: 'sandra.maldonado@figueroa.com' },
      { id: 'CT-003', company_id: 'CO-00002', first_name: 'Thomas', last_name: 'Arnold',   email: 'thomas.arnold@garciayang.com' },
      { id: 'CT-004', company_id: 'CO-00003', first_name: 'Maya',   last_name: 'Cole',     email: 'maya@cole.com' },
    ],
    deals: [
      { id: 'DL-0001', company_id: 'CO-00001', amount: 87075, stage: 'closedwon' },
      { id: 'DL-0002', company_id: 'CO-00002', amount: 81146, stage: 'qualifying' },
      { id: 'DL-0003', company_id: 'CO-00003', amount: 13260, stage: 'closedwon' },
    ],
  },
  slack: {
    channels: [
      { id: 'C100', name: 'atlas-sales-pipeline', topic: 'Sales motion for Atlas SaaS deals', purpose: '' },
      { id: 'C200', name: 'atlas-customer-success', topic: 'Garcia, Yang and Gardner renewal coordination', purpose: '' },
    ],
    messages: [
      { channel_id: 'C100', ts: '1.001', text: 'Status update on Figueroa and Sons ($87,075): stage moved to closed-won this morning.' },
      { channel_id: 'C100', ts: '1.002', text: 'Demo with Garcia, Yang and Gardner tomorrow at 2pm.' },
      { channel_id: 'C200', ts: '1.003', text: 'Figueroa and Sons renewal looking healthy, expansion conversation surfacing.' },
      { channel_id: 'C100', ts: '1.004', text: 'No mentions here, just a generic team update.' },
    ],
    users: [
      { id: 'U001', profile: { email: 'brent.ward@figueroa.com', real_name: 'Brent Ward' } },
      { id: 'U002', profile: { email: 'someone-else@nomocoda.com', real_name: 'Sandra Maldonado' } },
    ],
  },
  gmail: {
    threads: [
      {
        id: 'TH-1',
        subject: 'Figueroa and Sons — security review',
        participants: [
          { name: 'Brent Ward', email: 'brent.ward@figueroa.com' },
          { name: 'Lens AE',    email: 'ae@nomocoda.com' },
        ],
        messages: [{ from: { email: 'brent.ward@figueroa.com' }, snippet: 'Looping in security.' }],
      },
      {
        id: 'TH-2',
        subject: 'RE: contract',
        participants: [
          { name: 'Thomas Arnold', email: 'thomas.arnold@garciayang.com' },
        ],
        messages: [
          { from: { email: 'thomas.arnold@garciayang.com' }, snippet: 'Garcia, Yang and Gardner review of $81,146 deal terms attached.' },
        ],
      },
      {
        id: 'TH-3',
        subject: 'unrelated newsletter',
        participants: [{ name: 'Marketer', email: 'news@gmail.com' }],
        messages: [{ from: { email: 'news@gmail.com' }, snippet: 'Weekly digest.' }],
      },
    ],
  },
};

describe('Normalization helpers', () => {
  test('normalizeName lowercases, strips punctuation, collapses whitespace', () => {
    assert.equal(normalizeName('Garcia, Yang and Gardner'), 'garcia yang and gardner');
    assert.equal(normalizeName('  Cole   LLC  '), 'cole');
    assert.equal(normalizeName('Figueroa & Sons'), 'figueroa and sons');
    assert.equal(normalizeName(''), '');
    assert.equal(normalizeName(null), '');
  });

  test('normalizeName strips common entity-suffixes', () => {
    assert.equal(normalizeName('Acme Inc.'), 'acme');
    assert.equal(normalizeName('Acme Inc'), 'acme');
    assert.equal(normalizeName('Acme Corp'), 'acme');
    assert.equal(normalizeName('Acme LLC'), 'acme');
    assert.equal(normalizeName('Acme Ltd'), 'acme');
  });

  test('normalizeDomain strips protocol and www, lowercases', () => {
    assert.equal(normalizeDomain('https://www.Figueroa.com/about'), 'figueroa.com');
    assert.equal(normalizeDomain('FIGUEROA.COM'), 'figueroa.com');
  });

  test('emailDomain extracts and normalizes the right-hand side', () => {
    assert.equal(emailDomain('Brent.Ward@Figueroa.COM'), 'figueroa.com');
    assert.equal(emailDomain('not-an-email'), '');
    assert.equal(emailDomain(''), '');
  });

  test('normalizeEmail trims and lowercases', () => {
    assert.equal(normalizeEmail('  Brent.Ward@Figueroa.COM '), 'brent.ward@figueroa.com');
  });

  test('isPublicEmailDomain flags free-mail providers', () => {
    assert.equal(isPublicEmailDomain('gmail.com'), true);
    assert.equal(isPublicEmailDomain('Outlook.com'), true);
    assert.equal(isPublicEmailDomain('figueroa.com'), false);
  });
});

describe('Match scoring', () => {
  test('tokenJaccard handles identical, partial, and disjoint inputs', () => {
    assert.equal(tokenJaccard('Figueroa and Sons', 'Figueroa and Sons'), 1);
    assert.equal(tokenJaccard('', 'anything'), 0);
    assert.ok(tokenJaccard('Figueroa Sons', 'Figueroa and Sons') > 0);
    assert.ok(tokenJaccard('Acme', 'Beta') === 0);
  });

  test('scoreCompanyNameMatch returns 1 on normalized equivalence', () => {
    assert.equal(scoreCompanyNameMatch('Cole LLC', 'cole'), 1);
    assert.equal(scoreCompanyNameMatch('Figueroa & Sons', 'figueroa and sons'), 1);
  });

  test('scoreCompanyNameMatch returns 0 with no overlap', () => {
    assert.equal(scoreCompanyNameMatch('Figueroa', 'Garcia'), 0);
  });
});

describe('Mention finders', () => {
  const companies = fixture.hubspot.companies;
  const deals = fixture.hubspot.deals;

  test('findCompanyMentions detects exact phrase mentions', () => {
    const text = 'Status update on Figueroa and Sons: stage moved to closed-won.';
    const matches = findCompanyMentions(text, companies);
    const ids = matches.map(m => m.companyId);
    assert.ok(ids.includes('CO-00001'));
    assert.ok(!ids.includes('CO-00002'));
    assert.ok(!ids.includes('CO-00003'));
  });

  test('findCompanyMentions handles punctuation in account names', () => {
    const text = 'Demo with Garcia, Yang and Gardner tomorrow at 2pm.';
    const matches = findCompanyMentions(text, companies);
    assert.deepEqual(matches.map(m => m.companyId), ['CO-00002']);
  });

  test('findCompanyMentions returns nothing for unrelated text', () => {
    assert.deepEqual(findCompanyMentions('Generic team update.', companies), []);
    assert.deepEqual(findCompanyMentions('', companies), []);
  });

  test('findDealMentions requires both the company name and the amount', () => {
    const hit = 'Figueroa and Sons ($87,075): stage moved to closed-won.';
    assert.deepEqual(
      findDealMentions(hit, deals, companies).map(m => m.dealId),
      ['DL-0001'],
    );
    const onlyName = 'Figueroa and Sons looking strong this quarter.';
    assert.deepEqual(findDealMentions(onlyName, deals, companies), []);
    const onlyAmount = 'A deal closed for $87,075 today.';
    assert.deepEqual(findDealMentions(onlyAmount, deals, companies), []);
  });
});

describe('resolveEntities — companies', () => {
  test('every HubSpot company shows up in the graph', () => {
    const out = resolveEntities(fixture);
    assert.equal(out.companies.length, fixture.hubspot.companies.length);
    const ids = out.companies.map(c => c.id).sort();
    assert.deepEqual(ids, ['CO-00001', 'CO-00002', 'CO-00003']);
  });

  test('contact emails learn the company-level domain', () => {
    const out = resolveEntities(fixture);
    const fig = out.companies.find(c => c.id === 'CO-00001');
    assert.equal(fig.domain, 'figueroa.com');
  });

  test('Slack message text and channel topic both anchor company evidence', () => {
    const out = resolveEntities(fixture);
    const fig = out.companies.find(c => c.id === 'CO-00001');
    assert.ok(fig.sources.slack.messageRefs.length >= 2,
      'expected at least two Slack messages to mention Figueroa and Sons');
    assert.ok(fig.sources.slack.channelIds.includes('C100'));

    const garcia = out.companies.find(c => c.id === 'CO-00002');
    assert.ok(garcia.sources.slack.channelIds.includes('C200'),
      'channel topic mentioning Garcia should attach C200 even with no message hits');
  });

  test('Gmail attaches threads via subject mention or domain match', () => {
    const out = resolveEntities(fixture);
    const fig = out.companies.find(c => c.id === 'CO-00001');
    assert.ok(fig.sources.gmail.threadIds.includes('TH-1'),
      'subject + matching participant domain should attach TH-1 to Figueroa');
    assert.ok(fig.sources.gmail.domains.includes('figueroa.com'));

    const garcia = out.companies.find(c => c.id === 'CO-00002');
    assert.ok(garcia.sources.gmail.threadIds.includes('TH-2'),
      'participant domain match should attach TH-2 even when subject is generic');
  });

  test('public free-mail domains never anchor a company', () => {
    const out = resolveEntities(fixture);
    for (const c of out.companies) {
      for (const d of c.sources.gmail.domains) {
        assert.equal(isPublicEmailDomain(d), false,
          `company ${c.id} should not be anchored to public domain ${d}`);
      }
    }
  });

  test('an unmentioned company keeps empty Slack and Gmail evidence', () => {
    const out = resolveEntities(fixture);
    const cole = out.companies.find(c => c.id === 'CO-00003');
    assert.equal(cole.sources.slack.messageRefs.length, 0);
    assert.equal(cole.sources.slack.channelIds.length, 0);
    assert.equal(cole.sources.gmail.threadIds.length, 0);
  });
});

describe('resolveEntities — people', () => {
  test('email-anchored Slack and Gmail linkage is high-confidence', () => {
    const out = resolveEntities(fixture);
    const brent = out.people.find(p => p.id === 'CT-001');
    assert.equal(brent.confidence, 1);
    assert.ok(brent.sources.slack.userIds.includes('U001'));
    assert.ok(brent.sources.gmail.threadIds.includes('TH-1'));
  });

  test('name-only Slack match without email yields lower confidence', () => {
    const out = resolveEntities(fixture);
    const sandra = out.people.find(p => p.id === 'CT-002');
    assert.equal(sandra.sources.slack.userIds.length, 1,
      'Slack user matched by display-name fallback');
    assert.ok(sandra.confidence <= 0.6,
      'name-only match should drop confidence below 1');
  });

  test('Gmail-only participants from outside HubSpot are not invented', () => {
    const out = resolveEntities(fixture);
    const ids = out.people.map(p => p.id);
    assert.ok(!ids.some(id => id.startsWith('TH-')),
      'no synthetic IDs from gmail threads should appear in people');
  });
});

describe('resolveEntities — deals', () => {
  test('deals are attached to slack messages by name + amount', () => {
    const out = resolveEntities(fixture);
    const d = out.deals.find(x => x.id === 'DL-0001');
    assert.ok(d.sources.slack.messageRefs.length >= 1,
      'closed-won mention with $87,075 should attach to DL-0001');
  });

  test('deals are attached to gmail threads when subject+snippet carry name+amount', () => {
    const out = resolveEntities(fixture);
    const d = out.deals.find(x => x.id === 'DL-0002');
    assert.ok(d.sources.gmail.threadIds.includes('TH-2'));
  });

  test('a deal whose company is not mentioned anywhere stays clean', () => {
    const out = resolveEntities(fixture);
    const cole = out.deals.find(x => x.id === 'DL-0003');
    assert.equal(cole.sources.slack.messageRefs.length, 0);
    assert.equal(cole.sources.gmail.threadIds.length, 0);
  });
});

describe('resolveEntities — robustness', () => {
  test('empty / missing input shapes do not throw', () => {
    assert.deepEqual(resolveEntities(undefined), { companies: [], people: [], deals: [] });
    assert.deepEqual(resolveEntities({}),         { companies: [], people: [], deals: [] });
    assert.deepEqual(
      resolveEntities({ hubspot: { companies: [] }, slack: {}, gmail: {} }),
      { companies: [], people: [], deals: [] },
    );
  });

  test('contact records with no email do not crash domain learning', () => {
    const data = JSON.parse(JSON.stringify(fixture));
    data.hubspot.contacts.push({ id: 'CT-005', company_id: 'CO-00003', first_name: 'No', last_name: 'Email' });
    const out = resolveEntities(data);
    assert.equal(out.people.length, fixture.hubspot.contacts.length + 1);
  });

  test('the resolver does not mutate its input', () => {
    const before = JSON.stringify(fixture);
    resolveEntities(fixture);
    assert.equal(JSON.stringify(fixture), before);
  });
});

describe('Module sits at repo root and is importable from tests/', () => {
  test('relative import resolves', () => {
    assert.ok(repoRoot.endsWith('lens-demo'));
    assert.ok(__internal && typeof __internal === 'object');
  });
});
