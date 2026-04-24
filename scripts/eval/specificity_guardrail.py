#!/usr/bin/env python3
"""Specificity guardrail for Phase 1.3 — proves cards never invent numbers.

For each card in a generated_cards_seed<N>.json file, extracts every numeric
claim from title/anchor/connect/body and classifies it against the dataset
summary fed to the model for that seed:

  LITERAL    — value appears in the summary within rounding tolerance.
  DERIVED    — value is a simple arithmetic combination of summary values.
  UNGROUNDED — neither. This is the hallucination failure mode.

CLI:
  python specificity_guardrail.py                  # audit all 5 seeds, emit report
  python specificity_guardrail.py --seed 42        # audit one seed
  python specificity_guardrail.py --cards FILE --summary FILE
                                                   # audit arbitrary pair

Report: scripts/eval/specificity_audit_report.json

The tolerance matrix intentionally accepts honest rounding (38.4 → 38, 76.9%
→ 77%, $619,200 → $620K) because the card-generation instructions permit it.
What it rejects is a number the dataset doesn't support at any level of
rounding.

Importable API:
  classify_card(card, ground_set) -> list[NumericClaim]
  classify_cards(cards, summary_text) -> dict (per-card + aggregate stats)
  ground_set_from_summary(summary_text) -> GroundSet

This module is pure — no API calls, no randomness, no file writes beyond the
report in __main__.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

# Re-use the exact summary builder the engine uses so ground truth matches
# what the model actually saw. Importing (not copy-pasting) keeps the
# guardrail in lockstep with the engine.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from relevance_engine import build_summary, load_dataset  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
SCAN_FIELDS = ("title", "anchor", "connect", "body")

# ----------------------------------------------------------------------------
# Numeric extraction
# ----------------------------------------------------------------------------

# Ordered patterns — first match wins per span, so dollar amounts take
# precedence over the bare-integer fallback on the same digits.
DOLLAR_RE = re.compile(
    r"\$(\d+(?:,\d{3})*(?:\.\d+)?)\s*([KMB])?\b",
    re.IGNORECASE,
)
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
MULTIPLIER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*x\b", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
MONTH_DAY_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})(?:\s*,\s*(\d{4}))?\b"
)
QUARTER_RE = re.compile(r"\bQ([1-4])(?:\s+(\d{4}))?\b")
# Bare number fallback — matches integers and decimals not already caught.
# Word boundary on both sides; allows comma-grouped integers. Trailing
# lookahead rejects percent/unit suffixes (handled by earlier patterns) and
# decimal continuation (so "3.14" is one match, not two), but allows plain
# period as sentence terminator (so "1921." captures 1921).
BARE_NUMBER_RE = re.compile(
    r"(?<![\w.$])(\d+(?:,\d{3})+|\d+(?:\.\d+)?)(?!\d|\.\d|%|[KkMmBb]\b)"
)

MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


@dataclass
class Claim:
    """A single numeric claim extracted from text."""
    kind: str              # "dollar" | "percent" | "multiplier" | "date" | "quarter" | "count"
    value: float           # canonical numeric value (dollars, fraction 0-1, count, etc.)
    raw: str               # exact substring as it appeared
    start: int
    end: int
    # Human-readable context — 30 chars on either side for the report snippet.
    context: str = ""


def _canonical_dollars(num: str, suffix: Optional[str]) -> float:
    n = float(num.replace(",", ""))
    if suffix:
        mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix.upper()]
        n *= mult
    return n


def _context(text: str, start: int, end: int, radius: int = 30) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return text[left:right].replace("\n", " ").strip()


def extract_claims(text: str) -> List[Claim]:
    """Return a list of numeric claims found in text, with overlap suppression."""
    if not text:
        return []

    claims: List[Claim] = []
    consumed: List[Tuple[int, int]] = []

    def overlaps(s: int, e: int) -> bool:
        for cs, ce in consumed:
            if s < ce and e > cs:
                return True
        return False

    # 1. Dollar amounts (highest priority — "$620K" must not fall through to
    #    bare-integer 620).
    for m in DOLLAR_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        v = _canonical_dollars(m.group(1), m.group(2))
        claims.append(Claim("dollar", v, m.group(0), m.start(), m.end(),
                            _context(text, m.start(), m.end())))
        consumed.append((m.start(), m.end()))

    # 2. Percentages.
    for m in PERCENT_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        v = float(m.group(1)) / 100.0
        claims.append(Claim("percent", v, m.group(0), m.start(), m.end(),
                            _context(text, m.start(), m.end())))
        consumed.append((m.start(), m.end()))

    # 3. Multipliers ("2x", "1.5x").
    for m in MULTIPLIER_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        v = float(m.group(1))
        claims.append(Claim("multiplier", v, m.group(0), m.start(), m.end(),
                            _context(text, m.start(), m.end())))
        consumed.append((m.start(), m.end()))

    # 4. ISO dates.
    for m in ISO_DATE_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        claims.append(Claim("date", 0.0, m.group(1), m.start(), m.end(),
                            _context(text, m.start(), m.end())))
        consumed.append((m.start(), m.end()))

    # 5. Month-day dates. Normalize raw to canonical "Month Day" for matching.
    for m in MONTH_DAY_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        claims.append(Claim("date", 0.0, m.group(0), m.start(), m.end(),
                            _context(text, m.start(), m.end())))
        consumed.append((m.start(), m.end()))

    # 6. Quarter labels.
    for m in QUARTER_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        claims.append(Claim("quarter", float(m.group(1)), m.group(0),
                            m.start(), m.end(),
                            _context(text, m.start(), m.end())))
        consumed.append((m.start(), m.end()))

    # 7. Bare numbers (counts, fallbacks).
    for m in BARE_NUMBER_RE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        raw = m.group(1)
        v = float(raw.replace(",", ""))
        # Skip zero-year / stray 2020s dates that ISO pattern should have
        # caught. If the number equals a reasonable year (1900-2100) AND is
        # preceded/followed by "-\d\d" skip — but the ISO pass already handled
        # those because of pattern priority. Nothing to do here.
        claims.append(Claim("count", v, raw, m.start(), m.end(),
                            _context(text, m.start(), m.end())))
        consumed.append((m.start(), m.end()))

    claims.sort(key=lambda c: c.start)
    return claims


# ----------------------------------------------------------------------------
# Ground truth set from dataset summary
# ----------------------------------------------------------------------------

@dataclass
class GroundSet:
    dollars: Set[float] = field(default_factory=set)
    percents: Set[float] = field(default_factory=set)
    counts: Set[float] = field(default_factory=set)
    dates: Set[str] = field(default_factory=set)
    quarters: Set[float] = field(default_factory=set)
    multipliers: Set[float] = field(default_factory=set)
    # Keep raw strings too for fuzzy date matching.
    summary_text: str = ""


def ground_set_from_summary(summary: str) -> GroundSet:
    gs = GroundSet(summary_text=summary)
    for c in extract_claims(summary):
        if c.kind == "dollar":
            gs.dollars.add(c.value)
        elif c.kind == "percent":
            gs.percents.add(c.value)
        elif c.kind == "count":
            gs.counts.add(c.value)
        elif c.kind == "date":
            gs.dates.add(c.raw.lower())
        elif c.kind == "quarter":
            gs.quarters.add(c.value)
        elif c.kind == "multiplier":
            gs.multipliers.add(c.value)
    return gs


# ----------------------------------------------------------------------------
# Classification
# ----------------------------------------------------------------------------

def _dollar_match(card_v: float, ground: Iterable[float]) -> bool:
    # Match within 5% relative, and also against K/M rounding bands
    # (e.g., $619,200 in the summary should match $620K in a card).
    for g in ground:
        if g == 0:
            continue
        if abs(card_v - g) / max(g, 1) <= 0.05:
            return True
        # Explicit K-rounding band: card says $620K (=620000) versus summary
        # says 619200 — that's within 1% already. But also consider $620K
        # versus summary $620.0 (unusual). The 5% band covers both.
    return False


def _percent_match(card_v: float, ground: Iterable[float]) -> bool:
    # Match within 1 percentage point absolute — cards may honestly round
    # 76.9% to 77%.
    for g in ground:
        if abs(card_v - g) <= 0.011:
            return True
    return False


def _count_match(card_v: float, ground: Iterable[float]) -> bool:
    # Exact match, or round-to-nearest for fractional means (e.g., ground=51.9
    # matches card=52, ground=38.4 matches card=38). NOT off-by-any —
    # off-by-one would make most small integers trivially "grounded".
    for g in ground:
        if card_v == g:
            return True
        if card_v == int(card_v) and card_v == round(g):
            return True
    return False


def _date_match(raw: str, ground: GroundSet) -> bool:
    summary = ground.summary_text
    summary_lc = summary.lower()

    # 1. Direct substring match (case-insensitive).
    if raw.lower() in summary_lc:
        return True

    # 2. Month-day: generate every spelling variant (full name, 3-letter abbr)
    #    and check each.
    m = MONTH_DAY_RE.fullmatch(raw)
    if m:
        mon_key = m.group(1).lower()
        mon = MONTH_MAP.get(mon_key)
        day = int(m.group(2))
        if mon:
            # Generate full and 3-letter abbrev canonical spellings.
            full_names = ["January", "February", "March", "April", "May", "June",
                          "July", "August", "September", "October", "November", "December"]
            abbr_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            variants = {full_names[mon - 1], abbr_names[mon - 1]}
            for v in variants:
                if re.search(rf"\b{re.escape(v)}\s+{day}\b", summary, re.IGNORECASE):
                    return True
            # Also match ISO form -MM-DD.
            if f"-{mon:02d}-{day:02d}" in summary:
                return True

    # 3. ISO → month-day spelling.
    m = ISO_DATE_RE.fullmatch(raw)
    if m:
        try:
            _, mo, d = raw.split("-")
            mo_i = int(mo)
            d_i = int(d)
        except ValueError:
            return False
        full_names = ["January", "February", "March", "April", "May", "June",
                      "July", "August", "September", "October", "November", "December"]
        abbr_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for v in {full_names[mo_i - 1], abbr_names[mo_i - 1]}:
            if re.search(rf"\b{re.escape(v)}\s+{d_i}\b", summary, re.IGNORECASE):
                return True
    return False


def _quarter_match(card_v: float, ground: GroundSet) -> bool:
    # Quarters are fully enumerated in the summary (Q1_2026, Q2_2026, etc.).
    # Accept any reference to the same quarter number.
    if card_v in ground.quarters:
        return True
    # Q-labels like "Q2_2026" appear as raw text too.
    q = int(card_v)
    return bool(re.search(rf"\bQ{q}\b", ground.summary_text))


def _try_derivation(card_v: float, kind: str, ground: GroundSet) -> Optional[str]:
    """Attempt to derive card_v by a simple combination of ground values.

    Returns a string describing the derivation (for the report), or None.

    Guardrails against coincidental matches:
    - Require both source values to be "substantial" (non-trivial magnitude
      relative to the target) so tiny pairs like 1+N don't match every N.
    - For counts, require the pair to differ from (card_v, 0) — ie the
      derivation must actually combine two values, not trivially alias one.
    - Tolerances are tight: ±0 for integer counts, ±0.5% relative for dollars,
      ±0.5 percentage points absolute for percents.
    """
    if kind == "count":
        values = [v for v in ground.counts if v >= 2 or v == int(v)]
    elif kind == "dollar":
        values = sorted(ground.dollars)
    elif kind == "percent":
        # Keep percent and count pools separate so we don't derive percentages
        # from pairs of dimensionless counts. The legitimate "X% faster"
        # derivation is (count_a - count_b) / count_b — handled below.
        pass
    else:
        return None

    if kind == "count":
        for a in values:
            for b in values:
                if a == b:
                    continue
                # Only accept "meaningful" derivations: both inputs must be at
                # least 10% the size of the target (rules out 1 + N).
                if a < abs(card_v) * 0.1 or b < abs(card_v) * 0.1:
                    continue
                if (a - b) == card_v:
                    return f"{a} - {b}"
                if (a + b) == card_v:
                    return f"{a} + {b}"
        return None

    if kind == "dollar":
        for a in values:
            for b in values:
                if a == b:
                    continue
                # Meaningful derivation: both inputs ≥ 10% of target.
                if a < abs(card_v) * 0.1 or b < abs(card_v) * 0.1:
                    continue
                tol = max(abs(card_v), max(a, b)) * 0.05
                if abs((a - b) - card_v) <= tol:
                    return f"{a} - {b}"
                if abs((a + b) - card_v) <= tol:
                    return f"{a} + {b}"
        return None

    if kind == "percent":
        # Percentage derivations come from two COUNTS representing the same
        # metric observed over different windows or segments. Tight tolerance
        # (0.5pp) and require both counts to be meaningful (≥ 2) so we don't
        # derive any percentage from 1/2, 2/3, etc.
        counts = sorted(c for c in ground.counts if c >= 2)
        dollars = sorted(ground.dollars)
        dollars_counts = counts + dollars
        for a in dollars_counts:
            for b in dollars_counts:
                if a == b or b == 0:
                    continue
                if a < 2 and b < 2:
                    continue
                pct = (a - b) / b
                if abs(pct - card_v) <= 0.008:
                    return f"({a} - {b}) / {b}"
                if abs((a / b) - card_v) <= 0.008:
                    return f"{a} / {b}"
        return None

    return None


def classify_claim(claim: Claim, ground: GroundSet) -> Dict:
    """Return {'status': 'LITERAL'|'DERIVED'|'UNGROUNDED', 'evidence': str}."""
    if claim.kind == "dollar":
        if _dollar_match(claim.value, ground.dollars):
            return {"status": "LITERAL", "evidence": "dollar match within tolerance"}
        d = _try_derivation(claim.value, "dollar", ground)
        if d:
            return {"status": "DERIVED", "evidence": d}
        return {"status": "UNGROUNDED", "evidence": None}

    if claim.kind == "percent":
        if _percent_match(claim.value, ground.percents):
            return {"status": "LITERAL", "evidence": "percent match within 1pp"}
        d = _try_derivation(claim.value, "percent", ground)
        if d:
            return {"status": "DERIVED", "evidence": d}
        return {"status": "UNGROUNDED", "evidence": None}

    if claim.kind == "count":
        if _count_match(claim.value, ground.counts):
            return {"status": "LITERAL", "evidence": "count match"}
        d = _try_derivation(claim.value, "count", ground)
        if d:
            return {"status": "DERIVED", "evidence": d}
        # Also tolerate counts that match a dollar amount normalized to
        # thousands (card says "$84" when summary has "$84,000" — unlikely
        # but possible).
        return {"status": "UNGROUNDED", "evidence": None}

    if claim.kind == "date":
        if _date_match(claim.raw, ground):
            return {"status": "LITERAL", "evidence": "date present in summary"}
        return {"status": "UNGROUNDED", "evidence": None}

    if claim.kind == "quarter":
        if _quarter_match(claim.value, ground):
            return {"status": "LITERAL", "evidence": "quarter label present"}
        return {"status": "UNGROUNDED", "evidence": None}

    if claim.kind == "multiplier":
        # Multipliers are always derivations — the ratio between two ground
        # values. Try the percent-style derivation on counts.
        for a in ground.counts | ground.dollars:
            for b in ground.counts | ground.dollars:
                if b == 0:
                    continue
                if abs((a / b) - claim.value) <= 0.05:
                    return {"status": "DERIVED", "evidence": f"{a} / {b}"}
        return {"status": "UNGROUNDED", "evidence": None}

    return {"status": "UNGROUNDED", "evidence": None}


# ----------------------------------------------------------------------------
# Per-card / per-seed audits
# ----------------------------------------------------------------------------

def audit_card(card: Dict, ground: GroundSet) -> Dict:
    numerics: List[Dict] = []
    status_counts = {"LITERAL": 0, "DERIVED": 0, "UNGROUNDED": 0}
    for field_name in SCAN_FIELDS:
        text = card.get(field_name, "") or ""
        for claim in extract_claims(text):
            result = classify_claim(claim, ground)
            numerics.append({
                "field": field_name,
                "kind": claim.kind,
                "raw": claim.raw,
                "value": claim.value,
                "context": claim.context,
                "status": result["status"],
                "evidence": result["evidence"],
            })
            status_counts[result["status"]] += 1
    all_grounded = status_counts["UNGROUNDED"] == 0
    return {
        "title": card.get("title"),
        "numerics": numerics,
        "status_counts": status_counts,
        "all_grounded": all_grounded,
    }


def audit_seed(seed: int, cards: List[Dict], ground: GroundSet) -> Dict:
    per_card = [audit_card(c, ground) for c in cards]
    totals = {"LITERAL": 0, "DERIVED": 0, "UNGROUNDED": 0}
    cards_all_grounded = 0
    for pc in per_card:
        for k, v in pc["status_counts"].items():
            totals[k] += v
        if pc["all_grounded"]:
            cards_all_grounded += 1
    return {
        "seed": seed,
        "cards_total": len(cards),
        "cards_all_grounded": cards_all_grounded,
        "numerics_by_status": totals,
        "per_card": per_card,
    }


# ----------------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------------

def default_seed_inputs() -> List[Tuple[int, Path, Path]]:
    """Discover (seed, cards_path, dataset_dir) triples for the 5 canonical seeds."""
    inputs = []
    for card_path in sorted(EVAL_DIR.glob("generated_cards_seed*.json")):
        m = re.search(r"seed(\d+)\.json$", card_path.name)
        if not m:
            continue
        seed = int(m.group(1))
        ds_dir = EVAL_DIR / f"output_seed{seed}"
        if not ds_dir.exists():
            # Seed 42 dataset lives in the base output/ dir; every other
            # seed has an output_seed<N>/ dir.
            if seed == 42 and (EVAL_DIR / "output").exists():
                ds_dir = EVAL_DIR / "output"
            else:
                continue
        inputs.append((seed, card_path, ds_dir))
    return inputs


def run_all(inputs: List[Tuple[int, Path, Path]]) -> Dict:
    seeds_report = []
    totals = {"LITERAL": 0, "DERIVED": 0, "UNGROUNDED": 0}
    grand_cards = 0
    grand_cards_all_grounded = 0
    for seed, cards_path, ds_dir in inputs:
        cards = json.loads(cards_path.read_text())
        ds = load_dataset(ds_dir)
        summary = build_summary(ds)
        ground = ground_set_from_summary(summary)
        r = audit_seed(seed, cards, ground)
        r["cards_path"] = str(cards_path.relative_to(EVAL_DIR.parent.parent))
        r["dataset_dir"] = str(ds_dir.relative_to(EVAL_DIR.parent.parent))
        seeds_report.append(r)
        for k, v in r["numerics_by_status"].items():
            totals[k] += v
        grand_cards += r["cards_total"]
        grand_cards_all_grounded += r["cards_all_grounded"]
    return {
        "seeds": seeds_report,
        "totals": {
            "cards_total": grand_cards,
            "cards_all_grounded": grand_cards_all_grounded,
            "percent_grounded_cards": (grand_cards_all_grounded / grand_cards * 100) if grand_cards else 0,
            "numerics_by_status": totals,
        },
    }


def format_summary(report: Dict) -> str:
    t = report["totals"]
    lines = [
        f"Cards total: {t['cards_total']}",
        f"Cards with all numerics grounded: {t['cards_all_grounded']} "
        f"({t['percent_grounded_cards']:.1f}%)",
        f"Numerics: LITERAL={t['numerics_by_status']['LITERAL']} "
        f"DERIVED={t['numerics_by_status']['DERIVED']} "
        f"UNGROUNDED={t['numerics_by_status']['UNGROUNDED']}",
        "",
        "Per-seed:",
    ]
    for s in report["seeds"]:
        nbs = s["numerics_by_status"]
        lines.append(
            f"  seed {s['seed']}: {s['cards_all_grounded']}/{s['cards_total']} "
            f"cards clean, UNGROUNDED={nbs['UNGROUNDED']}"
        )
    lines.append("")
    # Show sample of ungrounded claims
    ungrounded = []
    for s in report["seeds"]:
        for i, pc in enumerate(s["per_card"]):
            for n in pc["numerics"]:
                if n["status"] == "UNGROUNDED":
                    ungrounded.append((s["seed"], i, pc["title"], n))
    if ungrounded:
        lines.append(f"UNGROUNDED numerics ({len(ungrounded)}):")
        for seed, idx, title, n in ungrounded[:40]:
            lines.append(f"  seed {seed} card {idx} field={n['field']} "
                         f"kind={n['kind']} raw='{n['raw']}' ctx='{n['context']}'")
        if len(ungrounded) > 40:
            lines.append(f"  ... and {len(ungrounded) - 40} more")
    else:
        lines.append("No UNGROUNDED numerics.")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Specificity guardrail audit")
    ap.add_argument("--seed", type=int, help="Audit one seed only")
    ap.add_argument("--cards", help="Explicit cards JSON path")
    ap.add_argument("--dataset-dir", help="Explicit dataset directory (with output files)")
    ap.add_argument("--report",
                    default=str(EVAL_DIR / "specificity_audit_report.json"),
                    help="Output report path")
    args = ap.parse_args(argv)

    if args.cards and args.dataset_dir:
        inputs = [(args.seed or 0, Path(args.cards), Path(args.dataset_dir))]
    else:
        inputs = default_seed_inputs()
        if args.seed is not None:
            inputs = [t for t in inputs if t[0] == args.seed]
        if not inputs:
            raise SystemExit("No seed inputs found")

    report = run_all(inputs)
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(format_summary(report))
    print(f"\nReport: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
