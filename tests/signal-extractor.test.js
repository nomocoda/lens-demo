import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import {
  diffSnapshots,
  classifyDelta,
  extractSignals,
  REASONS,
  __internal,
} from '../signal-extractor.js';

// Synthetic snapshots that mirror the atlas shape produced by
// scripts/eval/hubspot_adapter.py and the live Composio plumbing the
// parallel session is wiring up. Three deals + three companies + two
// contacts is enough to cover create, update, remove, and the three
// classification predicates without the suite drifting into fixture
// maintenance.

function baseSnapshot(asOf) {
  return {
    asOf,
    companies: [
      { id: 'CO-00001', name: 'Figueroa and Sons',        segment: 'mid-market',    current_arr: 100000, lifecycle_stage: 'customer' },
      { id: 'CO-00002', name: 'Garcia, Yang and Gardner', segment: 'mid-market',    current_arr: 80000,  lifecycle_stage: 'customer' },
      { id: 'CO-00003', name: 'Cole LLC',                 segment: 'small-business', current_arr: 21000,  lifecycle_stage: 'customer' },
    ],
    contacts: [
      { id: 'CT-001', company_id: 'CO-00001', email: 'brent.ward@figueroa.com', lifecycle_stage: 'lead' },
      { id: 'CT-002', company_id: 'CO-00002', email: 'thomas.arnold@garciayang.com', lifecycle_stage: 'sql', became_sql_date: '2026-04-15' },
    ],
    deals: [
      { id: 'DL-0001', company_id: 'CO-00001', amount: 50000,  stage: 'qualifying',  create_date: '2026-04-01' },
      { id: 'DL-0002', company_id: 'CO-00002', amount: 80000,  stage: 'proposal',    create_date: '2026-03-20' },
    ],
  };
}

const watchedDefaults = {
  deal: {
    stage: {
      type: 'enum_change',
      interestingTransitions: [
        'qualifying->proposal',
        'proposal->closedwon',
        'proposal->closedlost',
      ],
      freshDays: 30,
    },
    amount: { type: 'numeric_pct', threshold: 0.20, freshDays: 30 },
    __created__: { freshDays: 30 },
  },
  company: {
    current_arr:     { type: 'numeric_pct', threshold: 0.10, freshDays: 60 },
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: ['customer->churned', 'lead->customer'],
      freshDays: 90,
    },
  },
  contact: {
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: ['lead->sql', 'sql->customer'],
      freshDays: 14,
    },
  },
};

describe('diffSnapshots', () => {
  test('flags created entities with after value', () => {
    const previous = baseSnapshot('2026-04-25T00:00:00Z');
    const current  = baseSnapshot('2026-04-30T00:00:00Z');
    current.deals.push({
      id: 'DL-0003', company_id: 'CO-00003', amount: 13000, stage: 'qualifying', create_date: '2026-04-29',
    });
    const deltas = diffSnapshots(previous, current);
    const created = deltas.find(d => d.entityId === 'DL-0003');
    assert.equal(created.deltaType, 'created');
    assert.equal(created.entityType, 'deal');
    assert.equal(created.after.amount, 13000);
  });

  test('flags removed entities with before value', () => {
    const previous = baseSnapshot('2026-04-25T00:00:00Z');
    const current  = baseSnapshot('2026-04-30T00:00:00Z');
    current.deals = current.deals.filter(d => d.id !== 'DL-0001');
    const deltas = diffSnapshots(previous, current);
    const removed = deltas.find(d => d.entityId === 'DL-0001');
    assert.equal(removed.deltaType, 'removed');
    assert.equal(removed.before.amount, 50000);
  });

  test('flags field-level updates with before/after', () => {
    const previous = baseSnapshot('2026-04-25T00:00:00Z');
    const current  = baseSnapshot('2026-04-30T00:00:00Z');
    const deal = current.deals.find(d => d.id === 'DL-0002');
    deal.stage = 'closedwon';
    deal.close_date = '2026-04-29';
    const deltas = diffSnapshots(previous, current);
    const stageDelta = deltas.find(d => d.entityId === 'DL-0002' && d.field === 'stage');
    assert.equal(stageDelta.deltaType, 'updated');
    assert.equal(stageDelta.before, 'proposal');
    assert.equal(stageDelta.after, 'closedwon');
    assert.equal(stageDelta.at, '2026-04-29');
  });

  test('returns empty array for identical snapshots', () => {
    const a = baseSnapshot('2026-04-30T00:00:00Z');
    const b = baseSnapshot('2026-04-30T00:00:00Z');
    assert.deepEqual(diffSnapshots(a, b), []);
  });

  test('handles missing previous (cold start = everything is created)', () => {
    const current = baseSnapshot('2026-04-30T00:00:00Z');
    const deltas = diffSnapshots(null, current);
    const allCreated = deltas.every(d => d.deltaType === 'created');
    assert.ok(allCreated);
    const ids = deltas.map(d => d.entityId).sort();
    assert.ok(ids.includes('CO-00001'));
    assert.ok(ids.includes('DL-0001'));
    assert.ok(ids.includes('CT-001'));
  });
});

describe('classifyDelta — role relevance', () => {
  test('an unwatched field is not role-relevant and defers', () => {
    const delta = {
      entityType: 'deal', field: 'segment',
      deltaType: 'updated', before: 'mid-market', after: 'enterprise',
      at: '2026-04-30',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.roleRelevant, false);
    assert.equal(c.decision, 'defer');
    assert.equal(c.reason, REASONS.NOT_ROLE_RELEVANT);
  });

  test('a watched field with a watched transition surfaces', () => {
    const delta = {
      entityType: 'deal', field: 'stage',
      deltaType: 'updated', before: 'qualifying', after: 'proposal',
      at: '2026-04-30',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.roleRelevant, true);
    assert.equal(c.statisticallyInteresting, true);
    assert.equal(c.contextuallyFresh, true);
    assert.equal(c.decision, 'surface');
    assert.equal(c.reason, null);
  });

  test('a watched field with a non-interesting transition defers as not statistically interesting', () => {
    const delta = {
      entityType: 'deal', field: 'stage',
      deltaType: 'updated', before: 'qualifying', after: 'discovery',
      at: '2026-04-30',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.roleRelevant, true);
    assert.equal(c.statisticallyInteresting, false);
    assert.equal(c.decision, 'defer');
    assert.equal(c.reason, REASONS.NOT_STATISTICALLY_INTERESTING);
  });
});

describe('classifyDelta — statistical interest (numeric_pct)', () => {
  test('5% ARR change defers below the 10% threshold', () => {
    const delta = {
      entityType: 'company', field: 'current_arr',
      deltaType: 'updated', before: 100000, after: 105000,
      at: '2026-04-30',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.statisticallyInteresting, false);
    assert.equal(c.reason, REASONS.NOT_STATISTICALLY_INTERESTING);
  });

  test('15% ARR change clears the 10% threshold and surfaces', () => {
    const delta = {
      entityType: 'company', field: 'current_arr',
      deltaType: 'updated', before: 100000, after: 115000,
      at: '2026-04-30',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.statisticallyInteresting, true);
    assert.equal(c.decision, 'surface');
  });

  test('exactly threshold change is interesting (>=)', () => {
    const delta = {
      entityType: 'company', field: 'current_arr',
      deltaType: 'updated', before: 100000, after: 110000,
      at: '2026-04-30',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.statisticallyInteresting, true);
  });

  test('change from zero to positive is treated as Infinity, surfaces', () => {
    const delta = {
      entityType: 'company', field: 'current_arr',
      deltaType: 'updated', before: 0, after: 50000,
      at: '2026-04-30',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.statisticallyInteresting, true);
  });
});

describe('classifyDelta — freshness', () => {
  test('a delta inside the freshness window is fresh', () => {
    const delta = {
      entityType: 'deal', field: 'stage',
      deltaType: 'updated', before: 'qualifying', after: 'proposal',
      at: '2026-04-25',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.contextuallyFresh, true);
    assert.equal(c.decision, 'surface');
  });

  test('a delta outside the freshness window defers as stale', () => {
    const delta = {
      entityType: 'deal', field: 'stage',
      deltaType: 'updated', before: 'qualifying', after: 'proposal',
      at: '2026-02-15',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.contextuallyFresh, false);
    assert.equal(c.decision, 'defer');
    assert.equal(c.reason, REASONS.STALE);
  });

  test('contact lifecycle uses its own (shorter) freshness window', () => {
    const delta = {
      entityType: 'contact', field: 'lifecycle_stage',
      deltaType: 'updated', before: 'lead', after: 'sql',
      at: '2026-04-10',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    // 14-day window, 20 days back → stale.
    assert.equal(c.contextuallyFresh, false);
    assert.equal(c.reason, REASONS.STALE);
  });
});

describe('classifyDelta — created/removed events', () => {
  test('a new deal in a watched type surfaces when within freshDays', () => {
    const delta = {
      entityType: 'deal', deltaType: 'created',
      after: { id: 'DL-9999', amount: 30000, stage: 'qualifying' },
      at: '2026-04-29',
    };
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.roleRelevant, true);
    assert.equal(c.contextuallyFresh, true);
    assert.equal(c.decision, 'surface');
  });

  test('a created delta for an unwatched entity type defers as not role-relevant', () => {
    const delta = {
      entityType: 'company', deltaType: 'created',
      after: { id: 'CO-9999' },
      at: '2026-04-29',
    };
    // watchedDefaults has company.current_arr and company.lifecycle_stage
    // but NO company.__created__ → company creation is not role-relevant for
    // this archetype's configuration.
    const c = classifyDelta(delta, { watchedSignals: watchedDefaults, asOf: '2026-04-30' });
    assert.equal(c.roleRelevant, false);
    assert.equal(c.reason, REASONS.NOT_ROLE_RELEVANT);
  });
});

describe('extractSignals — top-level integration', () => {
  test('weaves diff + classification end to end', () => {
    const previous = baseSnapshot('2026-04-25T00:00:00Z');
    const current  = baseSnapshot('2026-04-30T00:00:00Z');

    // Mutations:
    // 1. Surface — DL-0002 stage proposal -> closedwon (interesting)
    // 2. Defer (not interesting) — CO-00001 ARR +5% (below 10% threshold)
    // 3. Surface — CT-001 lifecycle lead -> sql (interesting + fresh window)
    // 4. Defer (not role-relevant) — DL-0001 segment field doesn't exist in
    //    atlas, so we'll instead change DL-0001.amount by 5% (below 20% threshold)
    const dl2 = current.deals.find(d => d.id === 'DL-0002');
    dl2.stage = 'closedwon';
    dl2.close_date = '2026-04-29';

    const co1 = current.companies.find(c => c.id === 'CO-00001');
    co1.current_arr = 105000;

    const ct1 = current.contacts.find(c => c.id === 'CT-001');
    ct1.lifecycle_stage = 'sql';
    ct1.became_sql_date = '2026-04-28';

    const dl1 = current.deals.find(d => d.id === 'DL-0001');
    dl1.amount = 52500; // 5% — below the 20% threshold

    const out = extractSignals({
      previous,
      current,
      asOf: '2026-04-30T00:00:00Z',
      watchedSignals: watchedDefaults,
    });

    const surfaceIds = out.surface.map(d => `${d.entityId}:${d.field || d.deltaType}`);
    assert.ok(surfaceIds.includes('DL-0002:stage'),
      `expected DL-0002 stage change to surface, got: ${surfaceIds.join(', ')}`);
    assert.ok(surfaceIds.includes('CT-001:lifecycle_stage'),
      `expected CT-001 lifecycle change to surface, got: ${surfaceIds.join(', ')}`);

    const deferReasons = out.defer.map(d => d.classification.reason);
    assert.ok(deferReasons.includes(REASONS.NOT_STATISTICALLY_INTERESTING),
      'expected at least one deferral with not_statistically_interesting');

    assert.equal(out.surface.length + out.defer.length, out.all.length);
    assert.equal(out.asOf, '2026-04-30T00:00:00Z');
  });

  test('cold start (previous=null) classifies every created delta', () => {
    const current = baseSnapshot('2026-04-30T00:00:00Z');
    const out = extractSignals({
      previous: null,
      current,
      watchedSignals: watchedDefaults,
    });
    // Only deals.__created__ is configured — companies/contacts shouldn't.
    const surfaceTypes = new Set(out.surface.map(d => d.entityType));
    assert.ok(surfaceTypes.has('deal'));
    assert.ok(!surfaceTypes.has('company'));
  });

  test('empty inputs do not throw', () => {
    const out = extractSignals({});
    assert.deepEqual(out.surface, []);
    assert.deepEqual(out.defer, []);
    assert.deepEqual(out.all, []);
  });

  test('identical snapshots produce zero signals', () => {
    const snap = baseSnapshot('2026-04-30T00:00:00Z');
    const out = extractSignals({
      previous: snap,
      current:  snap,
      watchedSignals: watchedDefaults,
    });
    assert.equal(out.surface.length, 0);
    assert.equal(out.defer.length, 0);
  });

  test('snapshots are not mutated by extraction', () => {
    const previous = baseSnapshot('2026-04-25T00:00:00Z');
    const current  = baseSnapshot('2026-04-30T00:00:00Z');
    const dl2 = current.deals.find(d => d.id === 'DL-0002');
    dl2.stage = 'closedwon';
    const before = JSON.stringify({ previous, current });
    extractSignals({ previous, current, watchedSignals: watchedDefaults });
    assert.equal(JSON.stringify({ previous, current }), before);
  });
});

describe('Internals (sanity)', () => {
  test('valuesEqual handles primitives, nulls, and JSON-serializable objects', () => {
    const { valuesEqual } = __internal;
    assert.ok(valuesEqual('a', 'a'));
    assert.ok(valuesEqual(null, undefined));
    assert.ok(!valuesEqual('a', 'b'));
    assert.ok(valuesEqual({ x: 1 }, { x: 1 }));
    assert.ok(!valuesEqual({ x: 1 }, { x: 2 }));
  });

  test('pctChange handles normal, zero, and non-numeric inputs', () => {
    const { pctChange } = __internal;
    assert.equal(pctChange(100, 110), 0.1);
    assert.equal(pctChange(0, 10), Infinity);
    assert.equal(pctChange(0, 0), 0);
    assert.equal(pctChange('a', 'b'), null);
  });

  test('isFresh returns true when no asOf or freshDays is set', () => {
    const { isFresh } = __internal;
    assert.equal(isFresh('2026-04-30', null, 30), true);
    assert.equal(isFresh('2026-04-30', '2026-04-30', 0), true);
    assert.equal(isFresh(null, '2026-04-30', 30), false);
  });
});
