// Layer 1 unit tests: one per SAFETY_RAIL.
// Each test verifies that the post-emit check rejects a deliberately violating
// response and passes a clean response.
//
// Run: npm test

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  checkPermissionScope,
  checkNoFabrication,
  checkNoIndividualNameAuthority,
  checkCardStructure,
  checkNoProblemOnCardSurface,
  checkSafetyRails,
} from '../safety-rails.mjs';

// ---------------------------------------------------------------------------
// Rail 1: Permission Scope
// ---------------------------------------------------------------------------
describe('Rail 1: Permission Scope', () => {
  it('flags dollar-denominated pipeline figure for a Manager/IC archetype', () => {
    const output = 'Marketing-sourced pipeline sits at $890K weighted against the $1.4M target.';
    const result = checkPermissionScope(output, { archetypeSlug: 'marketing-builder' });
    assert.ok(result !== null, 'Expected a violation');
    assert.equal(result.rail, 'PERMISSION_SCOPE');
  });

  it('passes the same figure for an executive archetype', () => {
    const output = 'Marketing-sourced pipeline sits at $890K weighted versus the $1.4M target.';
    const result = checkPermissionScope(output, { archetypeSlug: 'marketing-leader' });
    assert.equal(result, null, 'Expected no violation for executive archetype');
  });

  it('passes clean Manager/IC output with no pipeline dollars', () => {
    const output = 'MQL volume hit 1,240 this month; SQL conversion is running at 18%.';
    const result = checkPermissionScope(output, { archetypeSlug: 'revenue-generator' });
    assert.equal(result, null, 'Expected no violation for clean output');
  });
});

// ---------------------------------------------------------------------------
// Rail 2: No Fabrication
// ---------------------------------------------------------------------------
describe('Rail 2: No Fabrication', () => {
  it('flags a numeric figure emitted immediately after a scope disclaimer', () => {
    const output = "I don't have visibility into Q2 revenue projections from your seat. $980K of the $1.4M target is still to find.";
    const result = checkNoFabrication(output);
    assert.ok(result !== null, 'Expected a violation');
    assert.equal(result.rail, 'NO_FABRICATION');
  });

  it('passes a clean scope disclaimer with no fabricated figure', () => {
    const output = "I don't have visibility into Q2 revenue projections from your seat. What I can see from marketing: MQL volume hit 1,240 this month.";
    const result = checkNoFabrication(output);
    assert.equal(result, null, 'Expected no violation for clean output');
  });
});

// ---------------------------------------------------------------------------
// Rail 3: No Individual-Name Authority
// ---------------------------------------------------------------------------
describe('Rail 3: No Individual-Name Authority', () => {
  it('flags a named individual cited as source of a signal', () => {
    const output = 'According to Kevin, the pipeline coverage sits at 2.1x this quarter.';
    const result = checkNoIndividualNameAuthority(output);
    assert.ok(result !== null, 'Expected a violation');
    assert.equal(result.rail, 'NO_INDIVIDUAL_NAME_AUTHORITY');
  });

  it('passes a named company/account as source', () => {
    const output = 'Per Prism Analytics data, MQL conversion sits at 17%.';
    const result = checkNoIndividualNameAuthority(output);
    assert.equal(result, null, 'Named companies are allowed; expected no violation');
  });

  it('passes a team/function cited as source', () => {
    const output = 'The revenue team flagged this pattern in the last forecast call.';
    const result = checkNoIndividualNameAuthority(output);
    assert.equal(result, null, 'Expected no violation for team-level attribution');
  });
});

// ---------------------------------------------------------------------------
// Rail 4: Card Structure
// ---------------------------------------------------------------------------
describe('Rail 4: Card Structure', () => {
  it('flags a card with a missing key', () => {
    const cards = [{ title: 'Brand search up six weeks running.', anchor: 'Atlas brand search volume is up 22% over the trailing six weeks.', connect: 'Paid search CTR held flat over the same window at 3.1%.' }];
    const result = checkCardStructure(JSON.stringify(cards));
    assert.ok(result !== null, 'Expected a violation for missing body key');
    assert.equal(result.rail, 'CARD_STRUCTURE');
  });

  it('flags a card whose body does not equal anchor + connect', () => {
    const cards = [{
      title: 'Brand search up six weeks running.',
      anchor: 'Atlas brand search volume is up 22% over the trailing six weeks.',
      connect: 'Paid search CTR held flat over the same window at 3.1%.',
      body: 'Atlas brand search volume is up 22% over the trailing six weeks. Paid search CTR fell slightly.',
    }];
    const result = checkCardStructure(JSON.stringify(cards));
    assert.ok(result !== null, 'Expected a violation for body mismatch');
    assert.equal(result.rail, 'CARD_STRUCTURE');
  });

  it('passes a well-formed card array', () => {
    const anchor = 'Atlas brand search volume is up 22% over the trailing six weeks.';
    const connect = 'Paid search CTR held flat over the same window at 3.1%.';
    const cards = [{
      title: 'Brand search up six weeks running.',
      anchor,
      connect,
      body: `${anchor} ${connect}`,
    }];
    const result = checkCardStructure(JSON.stringify(cards));
    assert.equal(result, null, 'Expected no violation for clean card array');
  });
});

// ---------------------------------------------------------------------------
// Rail 5: No Problem on Card Surface
// ---------------------------------------------------------------------------
describe('Rail 5: No Problem on Card Surface', () => {
  it('flags problem language in a card title', () => {
    const anchor = 'Mid-market SQL conversion sits at 8.2% in Q1.';
    const connect = 'Q4 ran at 9.7%.';
    const cards = [{
      title: 'Conversion gap widens between mid-market and enterprise.',
      anchor,
      connect,
      body: `${anchor} ${connect}`,
    }];
    const result = checkNoProblemOnCardSurface(JSON.stringify(cards));
    assert.ok(result !== null, 'Expected a violation for "gap" in title');
    assert.equal(result.rail, 'NO_PROBLEM_ON_CARD_SURFACE');
  });

  it('passes a card with no problem language', () => {
    const anchor = 'Mid-market SQL conversion sits at 8.2% in Q1.';
    const connect = 'Q4 ran at 9.7%.';
    const cards = [{
      title: 'Mid-market SQL conversion at 8.2% in Q1.',
      anchor,
      connect,
      body: `${anchor} ${connect}`,
    }];
    const result = checkNoProblemOnCardSurface(JSON.stringify(cards));
    assert.equal(result, null, 'Expected no violation for clean card');
  });
});

// ---------------------------------------------------------------------------
// Composite: checkSafetyRails
// ---------------------------------------------------------------------------
describe('checkSafetyRails (composite)', () => {
  it('returns empty array for fully clean card output', () => {
    const anchor = 'Brand search volume is up 22% over the trailing six weeks.';
    const connect = 'Direct traffic climbed 11% over the same window.';
    const cards = [{
      title: 'Brand search up six weeks running.',
      anchor,
      connect,
      body: `${anchor} ${connect}`,
    }];
    const violations = checkSafetyRails(JSON.stringify(cards), { isCard: true, archetypeSlug: 'marketing-leader' });
    assert.equal(violations.length, 0, 'Expected zero violations for clean output');
  });

  it('collects multiple violations when several rails fire', () => {
    const output = JSON.stringify([{
      title: 'Conversion gap widens this quarter.',
      anchor: 'According to Kevin, mid-market conversion sits at 8.2%.',
      connect: 'Q4 ran at 9.7%.',
      body: 'According to Kevin, mid-market conversion sits at 8.2%. Q4 ran at 9.7%.',
    }]);
    const violations = checkSafetyRails(output, { isCard: true, archetypeSlug: 'marketing-leader' });
    const rails = violations.map((v) => v.rail);
    assert.ok(rails.includes('NO_INDIVIDUAL_NAME_AUTHORITY'), 'Expected NO_INDIVIDUAL_NAME_AUTHORITY violation');
    assert.ok(rails.includes('NO_PROBLEM_ON_CARD_SURFACE'), 'Expected NO_PROBLEM_ON_CARD_SURFACE violation');
  });
});
