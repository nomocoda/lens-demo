#!/usr/bin/env python3
"""Energy audit for Phase 1.5 — scans Stage 1 card outputs for lean-forward gaps.

Loads every Phase 1.1 generated_cards_seed<N>.json under scripts/eval/ and
runs each card's narrative fields (title, anchor, connect) through energy
heuristics. Emits a structured report to scripts/eval/energy_audit_report.json
and prints a console summary.

This audit is calibration, not a verdict. Each match is a CANDIDATE for review;
context determines whether the framing is genuinely flat or appropriately
restrained. The output is intended to feed a Voice Brief calibration update.

Categories scanned:
  - softener:   "modest", "slight", "minor", "small" + adverb forms
  - vague_count: "some", "a few", "several" used where a number would land
  - hedger:     "might", "could", "potentially", "possibly", "appears to",
                "seems like", "looks like", "tends to"
  - passive:    "was observed", "emerged", "became apparent", and simple
                <be-verb> + <past participle> forms
  - generic_verb: "shows", "demonstrates", "indicates" — a more concrete verb
                  almost always fits

Phase 1.1 input set: seed1, seed7, seed42, seed99, seed2026 (commit 8bf8ec1).
Re-run outputs (phase1_4, phase1_5, etc.) are excluded by filename guard so
the audit is reproducible against the locked Phase 1.1 corpus.

Source-of-truth:
  - data/voice-brief.md (Voice Spine, locked 2026-04-24)
  - Locked Card vs Chat framing rule (nomocoda-operating-context skill v11):
    a card's job is to make the leader lean forward and say "tell me more."
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPORT_PATH = EVAL_DIR / "energy_audit_report.json"
SCAN_FIELDS = ("title", "anchor", "connect")

# Phase 1.1 seeds. Re-run outputs (anything with an extra suffix after the
# seed number) are excluded so the audit corpus is stable.
PHASE_1_1_SEED_FILE = re.compile(r"^generated_cards_seed(\d+)\.json$")


# Word-boundary phrase pattern. Used for both single words and multi-token
# phrases — spaces stay literal so "a few" doesn't match "saw a few hours".
def _wb(phrase: str) -> re.Pattern:
    return re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Categories and patterns
# ---------------------------------------------------------------------------

SOFTENERS = [
    "modest", "modestly",
    "slight", "slightly",
    "minor", "minorly",
    "small",  # context-dependent ("small business" is fine), but flag for review
]

VAGUE_COUNTS = ["some", "a few", "several"]

HEDGERS = [
    "might", "could", "potentially", "possibly",
    "appears to", "seems like", "looks like", "tends to",
]

# Specific weak verbs that drain agency from a card surface.
PASSIVE_PHRASES = [
    "was observed", "were observed",
    "emerged", "became apparent", "becomes apparent",
]

# Generic verbs that almost always have a more specific replacement available
# in this domain ("led", "doubled", "crossed", "trailed", etc.).
GENERIC_VERBS = ["shows", "showing", "demonstrates", "demonstrating", "indicates", "indicating"]

# Simple passive-voice heuristic: be-verb + past participle ending in -ed.
# Conservative — won't catch irregular participles (taken, done, written),
# but those are rare in card surfaces and over-flagging is worse than
# under-flagging for a calibration audit. Also won't fire on "is up", "is
# at", "is the", which is what we want.
PASSIVE_BE_PP = re.compile(
    r"\b(?:was|were|is|are|been|being)\s+(?:[a-z]+\s+)?[a-z]+ed\b",
    re.IGNORECASE,
)


SOFTENER_PATTERNS = {p: _wb(p) for p in SOFTENERS}
VAGUE_COUNT_PATTERNS = {p: _wb(p) for p in VAGUE_COUNTS}
HEDGER_PATTERNS = {p: _wb(p) for p in HEDGERS}
PASSIVE_PHRASE_PATTERNS = {p: _wb(p) for p in PASSIVE_PHRASES}
GENERIC_VERB_PATTERNS = {p: _wb(p) for p in GENERIC_VERBS}


# ---------------------------------------------------------------------------
# Reframing hints (only where a clear suggestion exists; otherwise omitted)
# ---------------------------------------------------------------------------

REFRAME_HINTS = {
    "modest": "drop or replace with the specific number that makes the signal concrete",
    "modestly": "drop the adverb; cite the specific number",
    "slight": "drop or replace with the specific number",
    "slightly": "drop the adverb; cite the specific number",
    "minor": "drop or replace with the specific number",
    "shows": "use a concrete verb (led, doubled, crossed, trailed, climbed, etc.)",
    "showing": "use a concrete verb",
    "demonstrates": "use a concrete verb",
    "indicates": "use a concrete verb",
    "appears to": "drop the hedger if the signal is concrete",
    "seems like": "drop the hedger if the signal is concrete",
    "looks like": "drop the hedger if the signal is concrete",
    "might": "drop the hedger or restate as observation",
    "could": "drop the hedger or restate as observation",
    "potentially": "drop the hedger",
    "possibly": "drop the hedger",
    "some": "use the specific number from the data",
    "a few": "use the specific number from the data",
    "several": "use the specific number from the data",
    "was observed": "rewrite active: name the subject doing the action",
    "were observed": "rewrite active: name the subject doing the action",
    "emerged": "name what the subject is and what it did",
    "became apparent": "rewrite active",
    "becomes apparent": "rewrite active",
}


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def snippet_around(text: str, start: int, end: int, radius: int = 40) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}".replace("\n", " ")


def _add(violations: list, *, seed: int, card_index: int, field: str,
         category: str, subcategory: str, match: str, snippet: str,
         text: str) -> None:
    entry = {
        "seed": seed,
        "card_index": card_index,
        "field": field,
        "category": category,
        "subcategory": subcategory,
        "match": match,
        "snippet": snippet,
        "field_value": text,
    }
    hint = REFRAME_HINTS.get(subcategory.lower())
    if hint:
        entry["reframe_hint"] = hint
    violations.append(entry)


def scan_field(text: str, seed: int, card_index: int, field: str,
               violations: list) -> None:
    if not isinstance(text, str) or not text:
        return

    for phrase, pattern in SOFTENER_PATTERNS.items():
        for m in pattern.finditer(text):
            _add(violations, seed=seed, card_index=card_index, field=field,
                 category="softener", subcategory=phrase,
                 match=m.group(0),
                 snippet=snippet_around(text, m.start(), m.end()),
                 text=text)

    for phrase, pattern in VAGUE_COUNT_PATTERNS.items():
        for m in pattern.finditer(text):
            _add(violations, seed=seed, card_index=card_index, field=field,
                 category="vague_count", subcategory=phrase,
                 match=m.group(0),
                 snippet=snippet_around(text, m.start(), m.end()),
                 text=text)

    for phrase, pattern in HEDGER_PATTERNS.items():
        for m in pattern.finditer(text):
            _add(violations, seed=seed, card_index=card_index, field=field,
                 category="hedger", subcategory=phrase,
                 match=m.group(0),
                 snippet=snippet_around(text, m.start(), m.end()),
                 text=text)

    for phrase, pattern in PASSIVE_PHRASE_PATTERNS.items():
        for m in pattern.finditer(text):
            _add(violations, seed=seed, card_index=card_index, field=field,
                 category="passive", subcategory=phrase,
                 match=m.group(0),
                 snippet=snippet_around(text, m.start(), m.end()),
                 text=text)

    # General passive-voice heuristic. Only fire when the named PASSIVE_PHRASES
    # didn't already match, to avoid double-counting "was observed".
    for m in PASSIVE_BE_PP.finditer(text):
        already = any(p.search(m.group(0)) for p in PASSIVE_PHRASE_PATTERNS.values())
        if already:
            continue
        _add(violations, seed=seed, card_index=card_index, field=field,
             category="passive", subcategory="be_verb_past_participle",
             match=m.group(0),
             snippet=snippet_around(text, m.start(), m.end()),
             text=text)

    for phrase, pattern in GENERIC_VERB_PATTERNS.items():
        for m in pattern.finditer(text):
            _add(violations, seed=seed, card_index=card_index, field=field,
                 category="generic_verb", subcategory=phrase,
                 match=m.group(0),
                 snippet=snippet_around(text, m.start(), m.end()),
                 text=text)


# ---------------------------------------------------------------------------
# Loading + report assembly
# ---------------------------------------------------------------------------

def load_seed_files() -> list[tuple[int, list[dict]]]:
    seeds: list[tuple[int, list[dict]]] = []
    for path in sorted(EVAL_DIR.iterdir()):
        m = PHASE_1_1_SEED_FILE.match(path.name)
        if not m:
            continue
        seed = int(m.group(1))
        cards = json.loads(path.read_text())
        seeds.append((seed, cards))
    return seeds


def build_report(seeds: list[tuple[int, list[dict]]]) -> dict:
    all_violations: list[dict] = []
    per_seed_counts: dict[int, int] = {}
    total_cards = 0
    cards_with_violations: set[tuple[int, int]] = set()

    for seed, cards in seeds:
        seed_violations = 0
        for idx, card in enumerate(cards):
            total_cards += 1
            card_start = len(all_violations)
            for field in SCAN_FIELDS:
                scan_field(card.get(field, ""), seed, idx, field, all_violations)
            new = len(all_violations) - card_start
            if new > 0:
                cards_with_violations.add((seed, idx))
                seed_violations += new
        per_seed_counts[seed] = seed_violations

    category_totals = Counter(v["category"] for v in all_violations)
    subcategory_totals = Counter(
        f"{v['category']}::{v['subcategory']}" for v in all_violations
    )
    category_seeds: dict[str, set[int]] = defaultdict(set)
    for v in all_violations:
        key = f"{v['category']}::{v['subcategory']}"
        category_seeds[key].add(v["seed"])

    recurring = []
    one_off = []
    for key, total in subcategory_totals.most_common():
        entry = {
            "key": key,
            "total_occurrences": total,
            "seed_count": len(category_seeds[key]),
            "seeds": sorted(category_seeds[key]),
        }
        if entry["seed_count"] >= 2:
            recurring.append(entry)
        else:
            one_off.append(entry)

    return {
        "generated_at_utc": None,
        "inputs": [
            {"seed": seed, "card_count": len(cards)} for seed, cards in seeds
        ],
        "totals": {
            "cards_scanned": total_cards,
            "cards_with_violations": len(cards_with_violations),
            "violations_total": len(all_violations),
            "violations_by_category": dict(category_totals),
            "per_seed_violation_counts": per_seed_counts,
        },
        "recurrence": {
            "recurring_across_seeds": recurring,
            "one_off": one_off,
        },
        "violations": all_violations,
    }


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------

def format_summary(report: dict) -> str:
    totals = report["totals"]
    lines = [
        f"Cards scanned: {totals['cards_scanned']} across {len(report['inputs'])} seeds",
        f"Cards with at least one candidate: {totals['cards_with_violations']}",
        f"Candidates total: {totals['violations_total']}",
        "",
        "Per-seed candidate counts:",
    ]
    for seed, count in sorted(totals["per_seed_violation_counts"].items()):
        lines.append(f"  seed {seed}: {count}")
    lines.append("")
    lines.append("By category:")
    for cat, count in sorted(totals["violations_by_category"].items(), key=lambda x: -x[1]):
        lines.append(f"  {cat}: {count}")
    lines.append("")
    lines.append("Top 10 subcategories (recurring or one-off):")
    flat = report["recurrence"]["recurring_across_seeds"] + report["recurrence"]["one_off"]
    for e in flat[:10]:
        lines.append(f"  {e['key']}: {e['total_occurrences']} occurrences "
                     f"across {e['seed_count']} seed(s) {e['seeds']}")
    lines.append("")
    lines.append("Recurring (>= 2 seeds):")
    for e in report["recurrence"]["recurring_across_seeds"]:
        lines.append(f"  {e['key']}: {e['total_occurrences']} across seeds {e['seeds']}")
    lines.append("")
    lines.append("One-off (single seed):")
    for e in report["recurrence"]["one_off"]:
        lines.append(f"  {e['key']}: {e['total_occurrences']} in seed {e['seeds'][0]}")
    return "\n".join(lines)


def main() -> None:
    from datetime import datetime, timezone

    seeds = load_seed_files()
    if not seeds:
        raise SystemExit("No Phase 1.1 generated_cards_seed<N>.json files found in scripts/eval/")
    report = build_report(seeds)
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(format_summary(report))
    print(f"\nReport written to {REPORT_PATH.relative_to(EVAL_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
