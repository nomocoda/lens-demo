// signal-extractor.js
//
// Signal extraction over time. Pulls deltas between two snapshots of resolved
// entities, applies the three predicates that define a Signal, and returns
// surface-vs-defer decisions. Pure module: no I/O, no persistence, no
// per-archetype configuration baked in. The caller passes a `watchedSignals`
// dictionary that names which (entityType, field) tuples this archetype cares
// about and what counts as a meaningful change. That keeps archetype-specific
// goal-cluster configuration where it belongs (the Intelligence Briefs in
// data/*.md, eventually a shared registry) and keeps this module the engine
// that runs against any configuration.
//
// Canonical Signal definition (NomoCoda operating context, multiple Notion
// canonicals): a Signal must be role-relevant, statistically interesting, and
// contextually fresh. Failing any of the three is a defer with a named reason.
//
// This is sub-objective 4 of the Activation Pipeline. It runs after the
// per-org data plumbing pulls a fresh snapshot (sub-objective 2) and after
// entity-resolver.js reconciles cross-system identity (sub-objective 3). Both
// upstream pieces are in flight in parallel sessions; this module is wire-
// ready and its tests run against the same fixture shapes that match the
// HubSpot atlas adapter and Slack/Gmail seeders.
//
// Phase 5 of the broader Lens architecture defines a Signal Log persistence
// layer (signal_log table in lens-web with scope_key, expiry, retrieval
// priority, embedding-based retrieval, and compounding pattern detection).
// That layer is out of scope here; this module produces the surface/defer
// decision a Signal Log writer would consume.

const ONE_DAY_MS = 24 * 60 * 60 * 1000;

// ---------------------------------------------------------------------------
// Snapshot diff
// ---------------------------------------------------------------------------

const ENTITY_KINDS = ['companies', 'contacts', 'deals'];
const ENTITY_TYPE_BY_KIND = {
  companies: 'company',
  contacts:  'contact',
  deals:     'deal',
};

function indexById(arr) {
  const m = new Map();
  for (const item of arr || []) {
    if (item && item.id) m.set(item.id, item);
  }
  return m;
}

function valuesEqual(a, b) {
  if (a === b) return true;
  if (a == null && b == null) return true;
  if (typeof a !== typeof b) return false;
  if (typeof a === 'object') {
    try { return JSON.stringify(a) === JSON.stringify(b); }
    catch { return false; }
  }
  return false;
}

// Diff two snapshots. A snapshot is the same atlas-shape produced by the
// HubSpot adapter: { companies, contacts, deals }. Returns a flat array of
// deltas. Each delta has:
//
//   - kind:       'companies' | 'contacts' | 'deals'
//   - entityType: 'company' | 'contact' | 'deal'
//   - entityId:   the atlas ID
//   - deltaType:  'created' | 'updated' | 'removed'
//   - field:      (only for 'updated') the changed field name
//   - before:     (only for 'updated') the prior value
//   - after:      (only for 'updated') the new value
//   - at:         delta timestamp (ISO string), best-effort: the entity's own
//                 most-relevant date if the field carries one, otherwise the
//                 current snapshot's `asOf`
export function diffSnapshots(previous, current, opts = {}) {
  const asOf = opts.asOf || (current && current.asOf) || null;
  const out = [];
  for (const kind of ENTITY_KINDS) {
    const prev = indexById(previous && previous[kind]);
    const curr = indexById(current && current[kind]);
    const entityType = ENTITY_TYPE_BY_KIND[kind];

    for (const [id, item] of curr) {
      if (!prev.has(id)) {
        out.push({
          kind, entityType, entityId: id, deltaType: 'created',
          after: item,
          at: pickEntityTimestamp(item, asOf),
        });
        continue;
      }
      const prior = prev.get(id);
      for (const field of allFields(prior, item)) {
        if (!valuesEqual(prior[field], item[field])) {
          out.push({
            kind, entityType, entityId: id, deltaType: 'updated',
            field,
            before: prior[field],
            after:  item[field],
            at: pickFieldTimestamp(field, item, prior, asOf),
          });
        }
      }
    }

    for (const [id, item] of prev) {
      if (!curr.has(id)) {
        out.push({
          kind, entityType, entityId: id, deltaType: 'removed',
          before: item,
          at: asOf,
        });
      }
    }
  }
  return out;
}

function allFields(a, b) {
  const s = new Set();
  for (const k of Object.keys(a || {})) s.add(k);
  for (const k of Object.keys(b || {})) s.add(k);
  return [...s];
}

// Pull the most fact-shaped timestamp off an entity for delta freshness.
// Atlas-shape carries close_date, became_sql_date, created_date — pick the
// one most relevant to the kind, then fall back to snapshot asOf.
function pickEntityTimestamp(item, asOf) {
  return item.close_date
      || item.became_sql_date
      || item.create_date
      || item.created_date
      || asOf;
}

function pickFieldTimestamp(field, item, prior, asOf) {
  if (field === 'stage' && item.close_date && prior.stage !== item.stage) {
    return item.close_date;
  }
  if (field === 'lifecycle_stage' && item.became_sql_date) {
    return item.became_sql_date;
  }
  return pickEntityTimestamp(item, asOf);
}

// ---------------------------------------------------------------------------
// Classification — the three Signal predicates.
// ---------------------------------------------------------------------------
//
// watchedSignals shape (caller-supplied):
//
//   {
//     deal: {
//       stage:    { type: 'enum_change',
//                   interestingTransitions: ['proposal->closedwon', ...],
//                   freshDays: 30 },
//       amount:   { type: 'numeric_pct', threshold: 0.20, freshDays: 30 },
//     },
//     company: {
//       current_arr:     { type: 'numeric_pct', threshold: 0.10, freshDays: 60 },
//       lifecycle_stage: { type: 'enum_change',
//                          interestingTransitions: ['lead->customer'],
//                          freshDays: 90 },
//     },
//     contact: {
//       lifecycle_stage: { type: 'enum_change',
//                          interestingTransitions: ['lead->sql', 'sql->customer'],
//                          freshDays: 14 },
//     },
//     // Per-entity-type 'created' rule (events, not field changes):
//     deal:    { __created__: { freshDays: 30 } },
//     contact: { __created__: { freshDays: 14 } },
//   }
//
// The shape is flat enough for engines to author by hand and small enough that
// archetype-specific overrides stay readable.

export const REASONS = Object.freeze({
  NOT_ROLE_RELEVANT:           'not_role_relevant',
  NOT_STATISTICALLY_INTERESTING: 'not_statistically_interesting',
  STALE:                       'stale',
});

function getRule(watchedSignals, entityType, field) {
  if (!watchedSignals) return null;
  const block = watchedSignals[entityType];
  if (!block) return null;
  return block[field] || null;
}

function isFresh(deltaAt, asOf, freshDays) {
  if (!deltaAt || !asOf || !freshDays) return Boolean(deltaAt);
  const a = Date.parse(deltaAt);
  const b = Date.parse(asOf);
  if (Number.isNaN(a) || Number.isNaN(b)) return Boolean(deltaAt);
  return (b - a) <= freshDays * ONE_DAY_MS;
}

function isInterestingTransition(rule, before, after) {
  if (!rule || !rule.interestingTransitions) return false;
  const key = `${before ?? ''}->${after ?? ''}`;
  return rule.interestingTransitions.includes(key);
}

function pctChange(before, after) {
  if (typeof before !== 'number' || typeof after !== 'number') return null;
  if (before === 0) return after === 0 ? 0 : Infinity;
  return Math.abs(after - before) / Math.abs(before);
}

// Classify a single delta. Returns an object with the three predicate flags,
// the surface/defer decision, and (if defer) a reason from REASONS.
export function classifyDelta(delta, options = {}) {
  const { watchedSignals, asOf } = options;
  if (!delta) {
    return predicate(false, false, false, REASONS.NOT_ROLE_RELEVANT, null);
  }

  if (delta.deltaType === 'created') {
    const rule = getRule(watchedSignals, delta.entityType, '__created__');
    if (!rule) return predicate(false, true, true, REASONS.NOT_ROLE_RELEVANT, rule);
    const fresh = isFresh(delta.at, asOf || (options && options.asOf), rule.freshDays);
    return predicate(true, true, fresh, fresh ? null : REASONS.STALE, rule);
  }

  if (delta.deltaType === 'removed') {
    const rule = getRule(watchedSignals, delta.entityType, '__removed__');
    if (!rule) return predicate(false, true, true, REASONS.NOT_ROLE_RELEVANT, rule);
    const fresh = isFresh(delta.at, asOf || (options && options.asOf), rule.freshDays);
    return predicate(true, true, fresh, fresh ? null : REASONS.STALE, rule);
  }

  const rule = getRule(watchedSignals, delta.entityType, delta.field);
  if (!rule) {
    return predicate(false, true, true, REASONS.NOT_ROLE_RELEVANT, rule);
  }

  let interesting;
  if (rule.type === 'enum_change') {
    interesting = isInterestingTransition(rule, delta.before, delta.after);
  } else if (rule.type === 'numeric_pct') {
    const change = pctChange(delta.before, delta.after);
    interesting = change != null && change >= (rule.threshold ?? 0);
  } else if (rule.type === 'numeric_abs') {
    if (typeof delta.before === 'number' && typeof delta.after === 'number') {
      interesting = Math.abs(delta.after - delta.before) >= (rule.threshold ?? 0);
    } else {
      interesting = false;
    }
  } else if (rule.type === 'any_change') {
    interesting = true;
  } else {
    interesting = false;
  }

  const fresh = isFresh(delta.at, asOf || (options && options.asOf), rule.freshDays);
  if (!interesting) return predicate(true, false, fresh, REASONS.NOT_STATISTICALLY_INTERESTING, rule);
  if (!fresh)       return predicate(true, interesting, false, REASONS.STALE, rule);
  return predicate(true, true, true, null, rule);
}

function predicate(roleRelevant, statisticallyInteresting, contextuallyFresh, reason, rule) {
  return {
    roleRelevant,
    statisticallyInteresting,
    contextuallyFresh,
    decision: !reason ? 'surface' : 'defer',
    reason,
    rule: rule || null,
  };
}

// ---------------------------------------------------------------------------
// Top-level extraction
// ---------------------------------------------------------------------------

// Take previous + current snapshots, diff them, classify each delta, return
// {surface, defer, all}. Surface entries are ready to be drafted as cards;
// defer entries (with reason) are the input to the Signal Log writer in
// lens-web's Phase 5 persistence layer.
export function extractSignals({
  previous,
  current,
  asOf = null,
  watchedSignals = null,
} = {}) {
  const effectiveAsOf = asOf || (current && current.asOf) || null;
  const deltas = diffSnapshots(previous, current, { asOf: effectiveAsOf });
  const surface = [];
  const defer = [];
  for (const delta of deltas) {
    const classification = classifyDelta(delta, { watchedSignals, asOf: effectiveAsOf });
    const enriched = { ...delta, classification };
    if (classification.decision === 'surface') surface.push(enriched);
    else defer.push(enriched);
  }
  return {
    surface,
    defer,
    all: [...surface, ...defer],
    asOf: effectiveAsOf,
  };
}

export const __internal = {
  ONE_DAY_MS,
  ENTITY_KINDS,
  ENTITY_TYPE_BY_KIND,
  indexById,
  valuesEqual,
  pickEntityTimestamp,
  pickFieldTimestamp,
  isFresh,
  pctChange,
  isInterestingTransition,
};
