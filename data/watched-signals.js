// data/watched-signals.js
//
// Per-archetype Watched Signals registry. Read by signal-extractor.js to decide
// which deltas count as role-relevant. Hand-authored against the locked Goal
// Cluster pairings (Notion: Product > Lens > Goal Clusters; mirrored in
// memory:project_goal_cluster_layer). Notion is the human authoring surface;
// this module is the compiled, machine-readable artifact the extractor reads.
//
// Shape (one entry per archetype slug):
//   { [entityType: 'company' | 'contact' | 'deal']:
//       { [field: string]: rule }
//   }
//
// Rule shapes:
//   { type: 'enum_change', interestingTransitions: [...], freshDays: N }
//   { type: 'numeric_pct', threshold: 0.10, freshDays: N }
//   { type: 'numeric_abs', threshold: 50000, freshDays: N }
//   { type: 'any_change', freshDays: N }
//   __created__: { freshDays: N }   — special key for entity-creation events
//   __removed__: { freshDays: N }   — special key for entity-removal events
//
// Fields covered today are the ones the HubSpot atlas-shape carries
// (lens-demo/scripts/eval/hubspot_adapter.py): companies.{name, segment,
// current_arr, lifecycle_stage}; contacts.{email, lifecycle_stage,
// became_sql_date}; deals.{amount, stage, close_date}. As more sources land
// (Salesforce, Slack threads as deal-context, Gmail thread heat), the
// registry grows new rules without touching signal-extractor.js itself.
//
// Calibration philosophy:
//   - Surface what the role acts on, defer everything else (canonical Signal
//     definition: role-relevant + statistically interesting + contextually
//     fresh, all three).
//   - freshDays mirrors the cadence the archetype actually checks the data
//     (daily-pipeline roles get ~14d; quarterly-positioning roles get ~90d).
//   - thresholds err toward letting noise in early; we tighten them after
//     watching real cards rather than guessing in the abstract.
//
// Marketing Leader is the default archetype and gets the most calibration.
// The other 10 get defensible baselines drawn from the same Goal Cluster
// pairings; tighter calibration lands as we run real-org data through them.

const STAGE_PROGRESS = [
  'qualifying->proposal',
  'proposal->closedwon',
  'proposal->closedlost',
];

const STAGE_LATE_FUNNEL = [
  'proposal->closedwon',
  'proposal->closedlost',
];

const LIFECYCLE_QUALIFY = [
  'lead->mql',
  'mql->sql',
  'lead->sql',
];

const LIFECYCLE_WIN = [
  'sql->customer',
  'lead->customer',
  'mql->customer',
];

const LIFECYCLE_LOSS = [
  'customer->churned',
];

// ---------------------------------------------------------------------------
// Marketing
// ---------------------------------------------------------------------------

const MARKETING_LEADER = {
  // Lead-quality + funnel conversion are the daily-rhythm metrics. Brand and
  // ICP-drift signals show up as company lifecycle changes and segment moves.
  contact: {
    __created__:     { freshDays: 14 },
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: [...LIFECYCLE_QUALIFY, ...LIFECYCLE_WIN],
      freshDays: 14,
    },
  },
  deal: {
    __created__: { freshDays: 14 },
    stage: {
      type: 'enum_change',
      interestingTransitions: STAGE_LATE_FUNNEL,
      freshDays: 30,
    },
  },
  company: {
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: [...LIFECYCLE_WIN, ...LIFECYCLE_LOSS],
      freshDays: 90,
    },
    segment: { type: 'any_change', freshDays: 90 },
  },
};

const MARKETING_STRATEGIST = {
  // ICP/positioning: closedlost transitions and segment shifts carry the
  // strongest signal. Less rhythm-bound than the Leader; longer freshDays.
  contact: {
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: LIFECYCLE_QUALIFY,
      freshDays: 30,
    },
  },
  deal: {
    stage: {
      type: 'enum_change',
      interestingTransitions: ['proposal->closedlost', ...STAGE_LATE_FUNNEL],
      freshDays: 30,
    },
  },
  company: {
    segment:         { type: 'any_change', freshDays: 90 },
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: [...LIFECYCLE_WIN, ...LIFECYCLE_LOSS],
      freshDays: 90,
    },
  },
};

const MARKETING_BUILDER = {
  // Campaign-execution: what's freshly entering the funnel, channel-attributable
  // creates. Tight freshDays (7-14 days) match weekly campaign rhythm.
  contact: {
    __created__:     { freshDays: 7 },
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: LIFECYCLE_QUALIFY,
      freshDays: 14,
    },
  },
  deal: {
    __created__: { freshDays: 14 },
  },
};

// ---------------------------------------------------------------------------
// Revenue
// ---------------------------------------------------------------------------

const REVENUE_LEADER = {
  // Pipeline coverage + forecast. Stage transitions, deal-amount adjustments,
  // ARR moves on existing accounts.
  deal: {
    __created__: { freshDays: 14 },
    stage: {
      type: 'enum_change',
      interestingTransitions: STAGE_PROGRESS,
      freshDays: 30,
    },
    amount: { type: 'numeric_pct', threshold: 0.20, freshDays: 30 },
  },
  company: {
    current_arr: { type: 'numeric_pct', threshold: 0.10, freshDays: 60 },
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: [...LIFECYCLE_WIN, ...LIFECYCLE_LOSS],
      freshDays: 60,
    },
  },
};

const REVENUE_GENERATOR = {
  // AE rhythm: their deals' stage moves and amount adjustments, fresh SQLs
  // they need to action.
  deal: {
    stage: {
      type: 'enum_change',
      interestingTransitions: STAGE_PROGRESS,
      freshDays: 14,
    },
    amount: { type: 'numeric_pct', threshold: 0.20, freshDays: 14 },
  },
  contact: {
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: ['mql->sql', 'lead->sql'],
      freshDays: 7,
    },
  },
};

const REVENUE_DEVELOPER = {
  // SDR rhythm: tight, daily. Fresh inbound, lifecycle qualifications.
  contact: {
    __created__:     { freshDays: 7 },
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: LIFECYCLE_QUALIFY,
      freshDays: 7,
    },
  },
};

const REVENUE_OPERATOR = {
  // RevOps: infrastructure and data hygiene. Watch all creates and stage
  // transitions to catch routing/process failures.
  contact: {
    __created__:     { freshDays: 30 },
    lifecycle_stage: { type: 'any_change', freshDays: 30 },
  },
  deal: {
    __created__: { freshDays: 30 },
    stage:       { type: 'any_change', freshDays: 30 },
  },
  company: {
    lifecycle_stage: { type: 'any_change', freshDays: 60 },
  },
};

// ---------------------------------------------------------------------------
// Customers
// ---------------------------------------------------------------------------

const CUSTOMER_LEADER = {
  // VP CS: NRR, churn, expansion. Watches ARR moves on existing customers
  // and lifecycle transitions out of customer.
  company: {
    current_arr:     { type: 'numeric_pct', threshold: 0.10, freshDays: 30 },
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: [...LIFECYCLE_LOSS],
      freshDays: 60,
    },
  },
  deal: {
    __created__: { freshDays: 30 },
    stage: {
      type: 'enum_change',
      interestingTransitions: STAGE_LATE_FUNNEL,
      freshDays: 30,
    },
  },
};

const CUSTOMER_ADVOCATE = {
  // CSM front-line: account-level changes and recently activated customers.
  company: {
    current_arr:     { type: 'numeric_pct', threshold: 0.10, freshDays: 30 },
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: [...LIFECYCLE_WIN, ...LIFECYCLE_LOSS],
      freshDays: 30,
    },
  },
  contact: {
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: LIFECYCLE_WIN,
      freshDays: 14,
    },
  },
};

const CUSTOMER_OPERATOR = {
  // CS Ops: account hygiene and lifecycle transitions across the book.
  company: {
    lifecycle_stage: { type: 'any_change', freshDays: 60 },
    current_arr:     { type: 'numeric_pct', threshold: 0.15, freshDays: 60 },
  },
  contact: {
    __created__: { freshDays: 30 },
  },
};

const CUSTOMER_TECHNICIAN = {
  // CS technical: usage/ARR shifts and account changes that signal a
  // technical engagement need.
  company: {
    current_arr:     { type: 'numeric_pct', threshold: 0.15, freshDays: 30 },
    lifecycle_stage: {
      type: 'enum_change',
      interestingTransitions: LIFECYCLE_LOSS,
      freshDays: 60,
    },
  },
  deal: {
    stage: {
      type: 'enum_change',
      interestingTransitions: STAGE_LATE_FUNNEL,
      freshDays: 30,
    },
  },
};

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export const WATCHED_SIGNALS_BY_ARCHETYPE = Object.freeze({
  'marketing-leader':     MARKETING_LEADER,
  'marketing-strategist': MARKETING_STRATEGIST,
  'marketing-builder':    MARKETING_BUILDER,
  'revenue-leader':       REVENUE_LEADER,
  'revenue-generator':    REVENUE_GENERATOR,
  'revenue-developer':    REVENUE_DEVELOPER,
  'revenue-operator':     REVENUE_OPERATOR,
  'customer-leader':      CUSTOMER_LEADER,
  'customer-advocate':    CUSTOMER_ADVOCATE,
  'customer-operator':    CUSTOMER_OPERATOR,
  'customer-technician':  CUSTOMER_TECHNICIAN,
});

const DEFAULT_ARCHETYPE = 'marketing-leader';

export function watchedSignalsFor(archetypeSlug) {
  if (typeof archetypeSlug !== 'string') {
    return WATCHED_SIGNALS_BY_ARCHETYPE[DEFAULT_ARCHETYPE];
  }
  const slug = archetypeSlug.trim().toLowerCase().replaceAll('_', '-');
  return WATCHED_SIGNALS_BY_ARCHETYPE[slug]
      || WATCHED_SIGNALS_BY_ARCHETYPE[DEFAULT_ARCHETYPE];
}
