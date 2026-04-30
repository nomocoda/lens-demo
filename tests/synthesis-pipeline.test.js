import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { resolveEntities } from '../entity-resolver.js';
import { extractSignals, REASONS } from '../signal-extractor.js';
import {
  watchedSignalsFor,
  WATCHED_SIGNALS_BY_ARCHETYPE,
} from '../data/watched-signals.js';

// End-to-end synthesis pipeline tests. Exercise the full
// resolveEntities → extractSignals chain against atlas-shape fixtures, plus
// the watched-signals registry that picks which deltas surface for each
// archetype. This is the contract the lens-web Inngest synthesizer is built
// against (lens-web/src/lib/lens/synthesis/synthesize.ts is a TypeScript
// caller of these same modules).

const ASOF_NOW = '2026-04-30T12:00:00Z';

function hubspotInput() {
  return {
    companies: [
      { id: 'CO-1', name: 'Ridgeline Health', segment: 'mid-market', current_arr: 250000, lifecycle_stage: 'customer' },
      { id: 'CO-2', name: 'Northwind Logistics', segment: 'enterprise', current_arr: 800000, lifecycle_stage: 'customer' },
    ],
    contacts: [
      { id: 'CT-1', company_id: 'CO-1', email: 'priya@ridgeline.health',  lifecycle_stage: 'sql', became_sql_date: '2026-04-25' },
      { id: 'CT-2', company_id: 'CO-2', email: 'kevin@northwind.example', lifecycle_stage: 'customer' },
    ],
    deals: [
      { id: 'DL-1', company_id: 'CO-1', amount: 60000, stage: 'proposal',   create_date: '2026-04-10' },
      { id: 'DL-2', company_id: 'CO-2', amount: 120000, stage: 'qualifying', create_date: '2026-03-15' },
    ],
  };
}

function fullResolverInput() {
  return {
    hubspot: hubspotInput(),
    slack: {
      channels: [
        { id: 'C-1', name: 'ridgeline-deal', topic: 'Ridgeline Health rollout coordination', purpose: '' },
      ],
      messages: [
        { ts: '1714400000.000100', channel_id: 'C-1', text: 'Ridgeline Health $60,000 — proposal sent' },
      ],
      users: [
        { id: 'U-1', profile: { real_name: 'Priya Sharma', email: 'priya@ridgeline.health' } },
      ],
    },
    gmail: {
      threads: [
        {
          id: 'TH-1',
          subject: 'Ridgeline rollout',
          participants: [{ email: 'priya@ridgeline.health' }, { email: 'sophie@atlassaas.com' }],
        },
      ],
    },
  };
}

describe('synthesis pipeline — first run (no previous snapshot)', () => {
  test('every entity becomes a created delta; freshDays narrows to recent', () => {
    const current = { asOf: ASOF_NOW, ...hubspotInput() };
    const watched = watchedSignalsFor('marketing-leader');

    const result = extractSignals({
      previous: null,
      current,
      asOf: ASOF_NOW,
      watchedSignals: watched,
    });

    // contacts.__created__ has freshDays: 14 in marketing-leader. CT-1 has
    // became_sql_date 2026-04-25 (5 days ago, fresh); CT-2 has no own
    // timestamp so falls back to asOf and is fresh by definition.
    const surfacedContactIds = result.surface
      .filter(d => d.entityType === 'contact')
      .map(d => d.entityId);
    assert.ok(surfacedContactIds.includes('CT-1'),
      'recent SQL contact should surface as a created delta');

    // deals.__created__ has freshDays: 14 for marketing-leader. DL-1 has
    // create_date 2026-04-10 (20 days ago, STALE — past 14d window);
    // DL-2 has create_date 2026-03-15 (45 days ago, STALE).
    const surfacedDealIds = result.surface
      .filter(d => d.entityType === 'deal')
      .map(d => d.entityId);
    assert.deepEqual(surfacedDealIds, [],
      'old-create deals should defer as stale, not surface');

    // The deferred deals carry a STALE reason — the audit log lens-web's
    // synthesis_runs.deferred field stores.
    const deferredDeals = result.defer.filter(d => d.entityType === 'deal');
    assert.ok(deferredDeals.length >= 2, 'both deals should be deferred');
    for (const d of deferredDeals) {
      assert.equal(d.classification.decision, 'defer');
      assert.equal(d.classification.reason, REASONS.STALE);
    }
  });

  test('archetype switch changes which deltas surface', () => {
    const fresh = hubspotInput();
    // Bring DL-1 into the fresh window for marketing-leader (freshDays:14 on
    // deal __created__) so ML sees a deal-create signal that revenue-developer
    // (which doesn't watch deals at all) does not.
    fresh.deals[0].create_date = '2026-04-25';
    const current = { asOf: ASOF_NOW, ...fresh };

    const mlResult = extractSignals({
      previous: null,
      current,
      asOf: ASOF_NOW,
      watchedSignals: watchedSignalsFor('marketing-leader'),
    });
    const rdResult = extractSignals({
      previous: null,
      current,
      asOf: ASOF_NOW,
      watchedSignals: watchedSignalsFor('revenue-developer'),
    });

    // Marketing Leader watches contact + deal + company. Revenue Developer
    // only watches contact (SDR rhythm). The surfaced kinds should differ.
    const mlKinds = new Set(mlResult.surface.map(d => d.entityType));
    const rdKinds = new Set(rdResult.surface.map(d => d.entityType));
    assert.ok(mlKinds.has('deal'), 'ML should surface the fresh deal create');
    assert.ok(!rdKinds.has('deal'), 'RD should not surface deals at all');
  });
});

describe('synthesis pipeline — cross-cycle deltas', () => {
  test('stage transition on a deal surfaces with before/after', () => {
    const previousState = hubspotInput();
    const currentState = hubspotInput();
    // DL-1 advances proposal → closedwon since the prior run.
    const dl1 = currentState.deals.find(d => d.id === 'DL-1');
    dl1.stage = 'closedwon';
    dl1.close_date = '2026-04-29';

    const result = extractSignals({
      previous: { asOf: '2026-04-20T00:00:00Z', ...previousState },
      current:  { asOf: ASOF_NOW, ...currentState },
      asOf: ASOF_NOW,
      watchedSignals: watchedSignalsFor('revenue-leader'),
    });

    const stageDelta = result.surface.find(
      d => d.entityType === 'deal' && d.field === 'stage' && d.entityId === 'DL-1',
    );
    assert.ok(stageDelta, 'proposal→closedwon should surface for revenue-leader');
    assert.equal(stageDelta.before, 'proposal');
    assert.equal(stageDelta.after, 'closedwon');
    assert.equal(stageDelta.classification.decision, 'surface');
    assert.equal(stageDelta.classification.reason, null);
  });

  test('ARR drop on a customer surfaces for customer-leader', () => {
    const previousState = hubspotInput();
    const currentState = hubspotInput();
    // Ridgeline ARR drops 20% — well above customer-leader's 10% threshold.
    const co1 = currentState.companies.find(c => c.id === 'CO-1');
    co1.current_arr = 200000;

    const result = extractSignals({
      previous: { asOf: '2026-04-20T00:00:00Z', ...previousState },
      current:  { asOf: ASOF_NOW, ...currentState },
      asOf: ASOF_NOW,
      watchedSignals: watchedSignalsFor('customer-leader'),
    });

    const arrDelta = result.surface.find(
      d => d.entityType === 'company' && d.field === 'current_arr',
    );
    assert.ok(arrDelta, 'ARR drop should surface for customer-leader');
    assert.equal(arrDelta.before, 250000);
    assert.equal(arrDelta.after, 200000);
  });

  test('snapshot mutation does not happen — both inputs survive intact', () => {
    const previousState = { asOf: '2026-04-20T00:00:00Z', ...hubspotInput() };
    const currentState  = { asOf: ASOF_NOW, ...hubspotInput() };
    currentState.deals[0].stage = 'closedwon';

    const previousJson = JSON.stringify(previousState);
    const currentJson = JSON.stringify(currentState);

    extractSignals({
      previous: previousState,
      current: currentState,
      asOf: ASOF_NOW,
      watchedSignals: watchedSignalsFor('revenue-leader'),
    });

    assert.equal(JSON.stringify(previousState), previousJson, 'previous unchanged');
    assert.equal(JSON.stringify(currentState),  currentJson,  'current unchanged');
  });
});

describe('synthesis pipeline — cross-system entity resolution', () => {
  test('a HubSpot company gets its Slack channel + Gmail domain stitched in', () => {
    const resolved = resolveEntities(fullResolverInput());

    const ridgeline = resolved.companies.find(c => c.id === 'CO-1');
    assert.ok(ridgeline, 'Ridgeline should resolve');
    assert.equal(ridgeline.sources.hubspot.id, 'CO-1');
    assert.deepEqual(ridgeline.sources.slack.channelIds, ['C-1'],
      'Slack channel mentioning Ridgeline should attach');
    assert.ok(ridgeline.sources.gmail.threadIds.includes('TH-1'),
      'Gmail thread with Ridgeline subject should attach');
    assert.ok(ridgeline.sources.gmail.domains.includes('ridgeline.health'),
      'participant domain should attach as a Gmail anchor');
  });

  test('Slack user resolves to HubSpot contact by email', () => {
    const resolved = resolveEntities(fullResolverInput());
    const priya = resolved.people.find(p => p.email === 'priya@ridgeline.health');
    assert.ok(priya, 'Priya should resolve from HubSpot');
    assert.deepEqual(priya.sources.slack.userIds, ['U-1'],
      'Slack user with matching profile.email should attach');
  });
});

describe('watched-signals registry — completeness', () => {
  test('all 11 archetypes are present', () => {
    const expected = [
      'marketing-leader', 'marketing-strategist', 'marketing-builder',
      'revenue-leader', 'revenue-generator', 'revenue-developer', 'revenue-operator',
      'customer-leader', 'customer-advocate', 'customer-operator', 'customer-technician',
    ];
    for (const slug of expected) {
      assert.ok(WATCHED_SIGNALS_BY_ARCHETYPE[slug],
        `${slug} should have a watched-signals entry`);
    }
    assert.equal(Object.keys(WATCHED_SIGNALS_BY_ARCHETYPE).length, expected.length,
      'no unexpected archetypes in the registry');
  });

  test('unknown archetype falls back to marketing-leader', () => {
    const fallback = watchedSignalsFor('does-not-exist');
    const ml = watchedSignalsFor('marketing-leader');
    assert.deepEqual(fallback, ml);
  });

  test('underscore slug normalizes to hyphen slug (lens-web compat)', () => {
    assert.deepEqual(
      watchedSignalsFor('revenue_leader'),
      watchedSignalsFor('revenue-leader'),
    );
  });
});
