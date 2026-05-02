// Five SAFETY_RAILS post-emit checks (Single Source of Truth architecture, locked 2026-05-01).
//
// These are the ONLY hard gates in the Lens pipeline. Voice quality is owned by
// the Persona Brief and Voice Brief; these checks protect the structural and
// permission invariants that voice docs cannot own.
//
// Each check takes the model's raw output string and a context object.
// Returns an array of violation objects { rail, detail }. Empty array = clean.
//
// Used by:
//   - worker.js handleCards (production post-emit gate)
//   - tests/safety-rails.test.js (Layer 1 unit tests)
//   - evals CI workflow (eval gate)

// Rail 1: Permission Scope
// Manager/IC roles must not receive dollar-denominated pipeline/revenue figures.
const MANAGER_IC_PATTERNS = /\b(marketing.builder|marketing.strategist|revenue.generator|revenue.developer|revenue.operator|customer.advocate|customer.operator|customer.technician)\b/i;
const PIPELINE_DOLLAR_PATTERN = /\$[\d,]+[KkMmBb]?\s*(weighted|pipeline|ARR|NRR|revenue|coverage|quota)/i;

export function checkPermissionScope(output, { archetypeSlug = '' } = {}) {
  if (!MANAGER_IC_PATTERNS.test(archetypeSlug)) return null;
  if (PIPELINE_DOLLAR_PATTERN.test(output)) {
    return { rail: 'PERMISSION_SCOPE', detail: 'Dollar-denominated pipeline/revenue metric surfaced for Manager/IC archetype' };
  }
  return null;
}

// Rail 2: No Fabrication
// Output must not contain a numeric claim paired with an explicit acknowledgment
// that the data is not present ("I don't have visibility" + a dollar/percent figure).
// Catches the specific failure mode of fabricating a number after a scope disclaimer.
const FABRICATION_PATTERN = /I don't have visibility[^.]*?\.\s*[^.]*?\$[\d,]+/i;

export function checkNoFabrication(output) {
  if (FABRICATION_PATTERN.test(output)) {
    return { rail: 'NO_FABRICATION', detail: 'Numeric figure emitted immediately after a scope-disclaimer acknowledgment' };
  }
  return null;
}

// Rail 3: No Individual-Name Authority
// Responses must not name a specific individual person as the source of, responsible
// for, or authority on a signal. Named accounts and competitors are allowed.
const INDIVIDUAL_AUTHORITY_PATTERN = /\b(?:[Aa]ccording to|[Ff]lagged by|[Nn]oted by|[Mm]entioned by|[Pp]er|[Ff]rom)\s+[A-Z][a-z]+(?!\s+(?:Analytics|Insurance|Logistics|Financial|Health|Manufacturing|Media|Corp|Inc|LLC|SaaS))(?:\s+[A-Z][a-z]+)?\b/;

export function checkNoIndividualNameAuthority(output) {
  if (INDIVIDUAL_AUTHORITY_PATTERN.test(output)) {
    return { rail: 'NO_INDIVIDUAL_NAME_AUTHORITY', detail: 'Individual person named as source or authority on a signal' };
  }
  return null;
}

// Rail 4: Card Structure
// Every card must have exactly four keys: title, anchor, connect, body.
// body must equal anchor + " " + connect.
// Only applies to card output (JSON array responses).
function parseCardsArray(text) {
  if (typeof text !== 'string') return null;
  const match = text.trim().match(/\[[\s\S]*\]/);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[0]);
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function checkCardStructure(output) {
  const cards = parseCardsArray(output);
  if (!cards) {
    return { rail: 'CARD_STRUCTURE', detail: 'Output is not a parseable JSON array' };
  }
  for (let i = 0; i < cards.length; i++) {
    const card = cards[i];
    const keys = Object.keys(card).filter((k) => k !== 'headline');
    const required = ['title', 'anchor', 'connect', 'body'];
    const missing = required.filter((k) => !keys.includes(k));
    const extra = keys.filter((k) => !required.includes(k));
    if (missing.length > 0) {
      return { rail: 'CARD_STRUCTURE', detail: `Card[${i}] missing keys: ${missing.join(', ')}` };
    }
    if (extra.length > 0) {
      return { rail: 'CARD_STRUCTURE', detail: `Card[${i}] unexpected keys: ${extra.join(', ')}` };
    }
    const expected = `${card.anchor.trim()} ${card.connect.trim()}`;
    if (card.body.trim() !== expected) {
      return { rail: 'CARD_STRUCTURE', detail: `Card[${i}] body does not equal anchor + " " + connect` };
    }
  }
  return null;
}

// Rail 5: No Problem on Card Surface
// Story Cards must not reference a loss, gap, miss, failure, or problem directly
// in title, anchor, or connect text. Only applies to card output.
const PROBLEM_SURFACE_PATTERN = /\b(gap|loss|losses|missed|miss|shortfall|failed|failure|fell short|problem|at.risk|risk accounts|not met|below target|underperformed|declined|dropped|worsened|deteriorated)\b/i;

export function checkNoProblemOnCardSurface(output) {
  const cards = parseCardsArray(output);
  if (!cards) return null;
  for (let i = 0; i < cards.length; i++) {
    const card = cards[i];
    const surface = [card.title, card.anchor, card.connect].filter(Boolean).join(' ');
    if (PROBLEM_SURFACE_PATTERN.test(surface)) {
      return { rail: 'NO_PROBLEM_ON_CARD_SURFACE', detail: `Card[${i}] contains problem language on card surface` };
    }
  }
  return null;
}

// Composite: run all applicable rails and return all violations.
// context.isCard = true for card output, false for chat output.
// context.archetypeSlug = archetype slug string for permission scope check.
export function checkSafetyRails(output, { isCard = false, archetypeSlug = '' } = {}) {
  const violations = [];

  const scopeViolation = checkPermissionScope(output, { archetypeSlug });
  if (scopeViolation) violations.push(scopeViolation);

  const fabricationViolation = checkNoFabrication(output);
  if (fabricationViolation) violations.push(fabricationViolation);

  const namingViolation = checkNoIndividualNameAuthority(output);
  if (namingViolation) violations.push(namingViolation);

  if (isCard) {
    const structureViolation = checkCardStructure(output);
    if (structureViolation) violations.push(structureViolation);

    const problemViolation = checkNoProblemOnCardSurface(output);
    if (problemViolation) violations.push(problemViolation);
  }

  return violations;
}
