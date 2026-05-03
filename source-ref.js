/**
 * source-ref.js
 *
 * SourceRef validation and permission scope helpers.
 *
 * Exports are imported by worker.js and are also directly importable in the
 * Node test runner (no wrangler .md transforms, no Cloudflare-specific APIs)
 * so unit tests can exercise the logic without spinning up the full worker.
 */

// Connected systems Lens reads from in the Atlas SaaS demo fiction and in
// production lens-web. Matches the "Connected systems" list in atlas-saas.md
// and the source-system identifiers in SOURCE_DISCLOSURE_GUARD.
//
// PRINCIPLE — APPLICATION LAYER, NOT INFRASTRUCTURE LAYER
//
// This list contains the systems where teams do their work and make decisions,
// not the underlying infrastructure that data flows through to get there.
//
// Stripe knows a charge happened. Salesforce knows what it means as a revenue
// event. Gainsight knows what it means for account health. ProfitWell knows
// what it means for MRR. Lens cites the system where the signal becomes
// intelligible and actionable — the downstream application — not the upstream
// processor or pipeline that produced the raw event.
//
// Payment processors (Stripe, Brex), data warehouses, ETL pipelines, webhooks,
// and raw database exports are therefore never valid source systems. If their
// data is relevant, it has already landed in one of the systems below, and
// that system is what gets cited.
export const PERMITTED_SYSTEMS = [
  'hubspot',
  'salesforce',
  'google-analytics',
  'linkedin-ads',
  'google-ads',
  'semrush',
  'mixpanel',
  'zendesk',
  'profitwell',
  'slack',
  'notion',
  'google-workspace',
];

/**
 * Validate a single SourceRef object.
 * Returns {ok: true, ref: {system, record}} or {ok: false, error: string}.
 *
 * Does NOT check that `record` matches any particular format — the type:id
 * convention is enforced by the model prompt, not here. This validator only
 * checks structural correctness and system membership.
 */
export function validateSourceRef(ref) {
  if (!ref || typeof ref !== 'object' || Array.isArray(ref)) {
    return { ok: false, error: 'must be a non-null object' };
  }
  if (typeof ref.system !== 'string' || ref.system.trim() === '') {
    return { ok: false, error: '"system" must be a non-empty string' };
  }
  if (!PERMITTED_SYSTEMS.includes(ref.system.trim())) {
    return { ok: false, error: `unknown system "${ref.system}"` };
  }
  if (typeof ref.record !== 'string' || ref.record.trim() === '') {
    return { ok: false, error: '"record" must be a non-empty string' };
  }
  return { ok: true, ref: { system: ref.system.trim(), record: ref.record.trim() } };
}

/**
 * Validate and normalize the permissionScopes input from a request body.
 *
 * Input shape (from lens-web's Inngest cards function or a server-to-server
 * caller): [{toolkit: string, scopeData: object|null}, ...] where toolkit is
 * one of PERMITTED_SYSTEMS and scopeData carries the connector-specific scope
 * (Slack: {channels}, HubSpot: {teamIds}, Salesforce: {profile}).
 *
 * Returns a validated array of {toolkit, scopeData} on success, or null when
 * no valid scopes are present (demo mode — all data is visible).
 */
export function resolvePermissionScopes(input) {
  if (!Array.isArray(input) || input.length === 0) return null;
  const valid = [];
  for (const scope of input) {
    if (!scope || typeof scope !== 'object' || Array.isArray(scope)) continue;
    if (typeof scope.toolkit !== 'string' || scope.toolkit.trim() === '') continue;
    const toolkit = scope.toolkit.trim();
    if (!PERMITTED_SYSTEMS.includes(toolkit)) continue;
    valid.push({ toolkit, scopeData: scope.scopeData ?? null });
  }
  return valid.length > 0 ? valid : null;
}

/**
 * Build the permission scope prompt block to inject into the system prompt.
 *
 * When permissionScopes is null (demo mode, no scopes provided), returns an
 * empty string so the prompt stays identical to the no-scopes path and the
 * Anthropic cache entry is not invalidated by an empty block.
 *
 * When scopes are provided, returns a hard-stop block listing the systems
 * this user is authorized to receive intelligence from. The model anchors
 * cards only on signals from those systems; normalizeCardEnvelope enforces
 * this at the source-ref level as a structural safety net.
 */
export function buildPermissionScopeBlock(permissionScopes) {
  if (!permissionScopes || permissionScopes.length === 0) return '';

  const lines = permissionScopes.map((s) => {
    let detail = s.toolkit;
    if (s.scopeData && typeof s.scopeData === 'object') {
      const { channels, teamIds, profile } = s.scopeData;
      if (Array.isArray(channels) && channels.length > 0) {
        detail += ` (channels: ${channels.join(', ')})`;
      } else if (Array.isArray(teamIds) && teamIds.length > 0) {
        detail += ` (team scope: ${teamIds.join(', ')})`;
      } else if (profile && typeof profile.profileName === 'string') {
        detail += ` (profile: ${profile.profileName})`;
      }
    }
    return `- ${detail}`;
  });

  return `
PERMISSION SCOPE, ACTIVE FOR THIS USER

This user's Lens instance is pre-loaded with data from the following connected systems only. Anchor cards exclusively on signals from these systems. Do not surface, summarize, or allude to signals from systems not in this list, even when the company data section contains them.

Permitted systems:
${lines.join('\n')}

Any "sources" array entry you emit must reference only these systems. Emitting a source whose "system" value does not appear in this list will cause that source to be dropped before delivery.`;
}
