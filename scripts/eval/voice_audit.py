#!/usr/bin/env python3
"""Voice audit for Phase 1.2 — scans Stage 1 card outputs against the Voice Brief.

Loads every generated_cards_seed<N>.json under scripts/eval/ and runs each card's
narrative fields (title, anchor, connect, body) through the Voice Brief's hard
and soft rules. Emits a structured report to scripts/eval/voice_audit_report.json
and prints a console summary.

Rule sources:
  - data/voice-brief.md Section 3 (Voice Spine, locked 2026-04-24)
  - Asana handoff comment 1214286488518500

Hard rules are mechanical and zero-tolerance. Soft rules are pattern-matched
and should be reviewed in context — they surface candidates, not verdicts.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPORT_PATH = EVAL_DIR / "voice_audit_report.json"
SCAN_FIELDS = ("title", "anchor", "connect", "body")


HARD_RULES = {
    "em_dash": {
        "pattern": re.compile(r"\u2014"),
        "description": "Em dash (—) — Voice Brief forbids.",
    },
    "against_as_comparison": {
        # Flag every occurrence of the standalone word "against". The Voice Brief
        # is absolute: "In comparisons between two numbers, two periods, or two
        # segments, use 'versus' or 'compared to'. Never 'against'." On Story
        # Cards, "against" is essentially always comparative.
        "pattern": re.compile(r"\bagainst\b", re.IGNORECASE),
        "description": "Used 'against' where 'versus' or 'compared to' is required.",
    },
    "banned_phrase": {
        # Handled separately via PHRASE_BLOCKLIST below so each phrase surfaces
        # with its own sub-category in the report.
        "pattern": None,
        "description": "Banned phrase from Voice Brief Ground Rules.",
    },
}

PHRASE_BLOCKLIST = [
    "leverage synergies",
    "impactful",
    "holistic",
    "thought leadership",
    "best-in-class",
    "best in class",
    "next-gen",
    "next gen",
    "crush it",
    "unlock value",
    "360-degree view",
    "360 degree view",
]

# Soft rules — pattern-matched with tolerance. Each entry gets its own category
# in the report so recurrence analysis can separate them.
PROBLEM_LANGUAGE = ["loss", "losses", "gap", "gaps", "miss", "missed", "misses", "failure", "failures"]
INSIDER_JARGON = [
    "pulled forward",
    "over-indexed",
    "over indexed",
    "tightened",
    "lifted",
    "operationalized",
    "pacing",
]


def compile_phrase_pattern(phrase: str) -> re.Pattern:
    # Use word boundaries for multi-word phrases too. Spaces between tokens are
    # kept literal so "pulled forward" doesn't match "pulled up forward".
    escaped = re.escape(phrase)
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


PHRASE_PATTERNS = {p: compile_phrase_pattern(p) for p in PHRASE_BLOCKLIST}
PROBLEM_PATTERNS = {w: compile_phrase_pattern(w) for w in PROBLEM_LANGUAGE}
JARGON_PATTERNS = {w: compile_phrase_pattern(w) for w in INSIDER_JARGON}


def snippet_around(text: str, start: int, end: int, radius: int = 40) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}".replace("\n", " ")


def scan_field(text: str, seed: int, card_index: int, field: str, violations: list) -> None:
    if not isinstance(text, str) or not text:
        return

    # Hard — em dash
    for m in HARD_RULES["em_dash"]["pattern"].finditer(text):
        violations.append({
            "seed": seed,
            "card_index": card_index,
            "field": field,
            "severity": "hard",
            "category": "em_dash",
            "rule": HARD_RULES["em_dash"]["description"],
            "match": m.group(0),
            "snippet": snippet_around(text, m.start(), m.end()),
        })

    # Hard — "against" as comparison connector
    for m in HARD_RULES["against_as_comparison"]["pattern"].finditer(text):
        violations.append({
            "seed": seed,
            "card_index": card_index,
            "field": field,
            "severity": "hard",
            "category": "against_as_comparison",
            "rule": HARD_RULES["against_as_comparison"]["description"],
            "match": m.group(0),
            "snippet": snippet_around(text, m.start(), m.end()),
        })

    # Hard — banned phrases
    for phrase, pattern in PHRASE_PATTERNS.items():
        for m in pattern.finditer(text):
            violations.append({
                "seed": seed,
                "card_index": card_index,
                "field": field,
                "severity": "hard",
                "category": "banned_phrase",
                "subcategory": phrase,
                "rule": f"Banned phrase '{phrase}' (Voice Brief Ground Rules).",
                "match": m.group(0),
                "snippet": snippet_around(text, m.start(), m.end()),
            })

    # Soft — problem/loss language
    for word, pattern in PROBLEM_PATTERNS.items():
        for m in pattern.finditer(text):
            violations.append({
                "seed": seed,
                "card_index": card_index,
                "field": field,
                "severity": "soft",
                "category": "problem_language",
                "subcategory": word,
                "rule": "Problem/loss framing — Story Cards surface only forward signal.",
                "match": m.group(0),
                "snippet": snippet_around(text, m.start(), m.end()),
            })

    # Soft — insider jargon
    for word, pattern in JARGON_PATTERNS.items():
        for m in pattern.finditer(text):
            violations.append({
                "seed": seed,
                "card_index": card_index,
                "field": field,
                "severity": "soft",
                "category": "insider_jargon",
                "subcategory": word,
                "rule": "Insider jargon — use plain-English equivalent.",
                "match": m.group(0),
                "snippet": snippet_around(text, m.start(), m.end()),
            })


def load_seed_files() -> list[tuple[int, list[dict]]]:
    files = sorted(EVAL_DIR.glob("generated_cards_seed*.json"))
    seeds: list[tuple[int, list[dict]]] = []
    for path in files:
        m = re.search(r"seed(\d+)\.json$", path.name)
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
            if len(all_violations) > card_start:
                cards_with_violations.add((seed, idx))
                seed_violations += len(all_violations) - card_start
        per_seed_counts[seed] = seed_violations

    category_key = lambda v: v.get("subcategory") or v["category"]
    category_seeds: dict[str, set[int]] = defaultdict(set)
    category_totals: Counter = Counter()
    for v in all_violations:
        key = category_key(v)
        category_seeds[key].add(v["seed"])
        category_totals[key] += 1

    recurring = []
    one_off = []
    for key, total in category_totals.most_common():
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

    severity_totals = Counter(v["severity"] for v in all_violations)
    category_by_severity: dict[str, Counter] = defaultdict(Counter)
    for v in all_violations:
        category_by_severity[v["severity"]][category_key(v)] += 1

    return {
        "generated_at_utc": None,  # filled in by caller
        "inputs": [
            {"seed": seed, "card_count": len(cards)} for seed, cards in seeds
        ],
        "totals": {
            "cards_scanned": total_cards,
            "cards_with_violations": len(cards_with_violations),
            "violations_total": len(all_violations),
            "violations_by_severity": dict(severity_totals),
            "per_seed_violation_counts": per_seed_counts,
        },
        "violations_by_category": {
            sev: [{"key": k, "count": c} for k, c in cat.most_common()]
            for sev, cat in category_by_severity.items()
        },
        "recurrence": {
            "recurring_across_seeds": recurring,
            "one_off": one_off,
        },
        "violations": all_violations,
    }


def format_summary(report: dict) -> str:
    totals = report["totals"]
    lines = [
        f"Cards scanned: {totals['cards_scanned']} across {len(report['inputs'])} seeds",
        f"Cards with at least one violation: {totals['cards_with_violations']}",
        f"Violations total: {totals['violations_total']} "
        f"(hard={totals['violations_by_severity'].get('hard', 0)}, "
        f"soft={totals['violations_by_severity'].get('soft', 0)})",
        "",
        "Per-seed violation counts:",
    ]
    for seed, count in sorted(totals["per_seed_violation_counts"].items()):
        lines.append(f"  seed {seed}: {count}")
    lines.append("")
    lines.append("Top categories:")
    flat = []
    for sev, entries in report["violations_by_category"].items():
        for e in entries:
            flat.append((e["count"], sev, e["key"]))
    for count, sev, key in sorted(flat, reverse=True)[:10]:
        lines.append(f"  [{sev}] {key}: {count}")
    lines.append("")
    lines.append("Recurring (≥ 2 seeds):")
    for e in report["recurrence"]["recurring_across_seeds"]:
        lines.append(f"  {e['key']}: {e['total_occurrences']} occurrences across seeds {e['seeds']}")
    lines.append("")
    lines.append("One-off (single seed):")
    for e in report["recurrence"]["one_off"]:
        lines.append(f"  {e['key']}: {e['total_occurrences']} occurrences in seed {e['seeds'][0]}")
    return "\n".join(lines)


def main() -> None:
    from datetime import datetime, timezone

    seeds = load_seed_files()
    if not seeds:
        raise SystemExit("No generated_cards_seed<N>.json files found in scripts/eval/")
    report = build_report(seeds)
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(format_summary(report))
    print(f"\nReport written to {REPORT_PATH.relative_to(EVAL_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
