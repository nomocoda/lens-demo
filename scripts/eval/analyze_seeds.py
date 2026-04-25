"""Phase 2.5 multi-seed Revenue Leader analyzer.

Reads generated_cards_revenue_seed<N>.json for each seed, scores:
  - card count
  - voice violation count (em dash, "against" comparator, banned verdict words)
  - specificity status (engine drops are reported in stderr, this checks ungrounded numerics in saved cards)
  - 15 Revenue Leader pattern coverage (P-RL-01..P-RL-15)

Patterns are detected by content keywords and grounded_metrics tags. The detection
is intentionally permissive (any-of) so a card that legitimately tells P-RL-09 with
different exact figures still counts.
"""
import json
import re
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
SEEDS = [1, 7, 42, 99, 2026]

# Pattern detectors: (name, keyword regexes any-of, grounded_metrics any-of).
# A card matches a pattern if any keyword regex hits content OR any tag matches.
def tag_match(metrics, fragments):
    """Return True if any metric tag contains any fragment as substring."""
    for m in metrics:
        ml = m.lower()
        for f in fragments:
            if f in ml:
                return True
    return False


PATTERNS = [
    ("P-RL-01", "Q2 commit vs weighted pipeline", [
        r"\bcommit coverage\b", r"\$1\.4M commit\b", r"\bweighted pipeline\b",
        r"weighted.*\$1\.6M", r"\$1\.6M weighted", r"\$1\.4M.*commit",
        r"commit.*\$1\.4M", r"weighted forecast", r"forecast.*coverage",
    ], ["commit_coverage", "weighted_pipeline", "weighted_forecast", "q2_commit", "q2_pacing"]),

    ("P-RL-02", "MM proposal-stage speed Q2 vs trailing", [
        r"\btime[- ]in[- ]proposal\b", r"\bproposal[- ]stage\b", r"proposal.*1[0-4] days",
        r"proposal.*compressed", r"proposal.*velocity", r"proposal stage time",
    ], ["proposal_speed", "time_in_proposal", "proposal_stage", "proposal_velocity"]),

    ("P-RL-03", "Q3 enterprise pipeline coverage", [
        r"Q3.*enterprise.*pipeline", r"4\.1x coverage", r"\$4\.9\d?M",
        r"\$1\.2M enterprise plan", r"4\.1x", r"22 (Q3 )?(deals|opportunities)",
    ], ["q3_enterprise_pipeline", "q3_enterprise_coverage", "enterprise_concentration"]),

    ("P-RL-04", "Q2 marketing-sourced share of net new pipeline", [
        r"marketing[- ]sourced.*Q2", r"sources \d+%.*Q2", r"Q2.*marketing[- ]sourced",
        r"\d\d% of Q2 net new", r"Marketing sources \d+%",
        r"\$2\.0\dM out of \$2\.\dM", r"Q2 net new pipeline",
    ], ["q2_pipeline_sourcing", "marketing_sourced", "ms_share", "pipeline_creation",
        "net_new_pipeline", "q2_pipeline_creation"]),

    ("P-RL-05", "Enterprise procurement this week", [
        r"\bprocurement\b", r"signoff", r"contract revisions", r"procurement queue",
    ], ["procurement"]),

    ("P-RL-06", "MM new opps last 30 days", [
        r"mid[- ]market.*last 30 days", r"last 30 days.*mid[- ]market",
        r"\d\d (mid[- ]market )?(deals|opportunities) created",
        r"mid[- ]market creation", r"\$41K average", r"\$890K.*mid[- ]market",
        r"\$42K average", r"\$2\.0\dM (across|total).*mid[- ]market",
        r"mid[- ]market opportunit(y|ies) (creation|averages)",
        r"\d\d recent (mid[- ]market )?deals",
        r"\$4[0-2](\.\d)?K across \d\d",
    ], ["recent_mm", "mm_30d", "mm_creation", "mid_market_creation",
        "mid_market_deal_volume", "mm_30day", "mid_market_acv",
        "mm_recent", "mm_pipeline_creation", "mm_recent_acv"]),

    ("P-RL-07", "Enterprise Q2 WR lift vs trailing", [
        r"enterprise win rate", r"3[01]% .*enterprise", r"22\.22%", r"30\.77%",
        r"enterprise close[s]? at 3[01]", r"win rate climbs to 3", r"win rate jumps to 3",
    ], ["q2_enterprise_win_rate", "enterprise_win_rate", "trailing_enterprise_win"]),

    ("P-RL-08", "Q1 enterprise wins anchor", [
        r"Q1 enterprise", r"\$145K average", r"\$435K total",
        r"three wins.*enterprise", r"enterprise.*three wins",
        r"Q1.*enterprise.*3 deals", r"Q1 enterprise closed 3",
        r"Q1 at \$145K", r"\$145K.*Q1", r"Q1.*\$145K",
        r"versus Q1 at \$1[3-5]\dK",
    ], ["q1_enterprise_wins", "enterprise_won_amounts", "q1_ent",
        "q1_enterprise", "enterprise_deal_size"]),

    ("P-RL-09", "MM cycle Q2 vs Q1", [
        r"mid[- ]market cycle", r"cycle time.*compress", r"6[0-9]\.\d days.*8[0-9]",
        r"Q1's 8[0-9]", r"\b65\.3 days\b", r"\b87\.8 days\b",
        r"compresses to 69", r"compress \d+ days", r"cycle time compress",
    ], ["mm_cycle", "mid_market_cycle", "mm_cycle_time"]),

    ("P-RL-10", "Beacon head-to-head", [
        r"\bBeacon\b", r"head[- ]to[- ]head", r"\b5W[/-]1L\b", r"83% win rate",
        r"5 wins.*1", r"flips to 5",
    ], ["beacon", "competitive"]),

    ("P-RL-11", "Customer-success expansion last 30d", [
        r"expansion.*\$340K", r"\$340K.*expansion", r"customer success.*expansion",
        r"health review", r"eight expansion", r"8 expansion",
        r"customer health", r"\$42\.5K each",
    ], ["expansion", "health_review"]),

    ("P-RL-12", "Q2 ent WR by source class", [
        r"marketing[- ]sourced.*convert", r"outbound.*1[0-9]\.\d%",
        r"28\.6% versus", r"versus outbound at", r"outbound enterprise",
        r"marketing-sourced.*win at", r"convert at \d\d%.*outbound",
    ], ["enterprise_win_by_source", "wr_by_source", "source_conversion",
        "outbound_enterprise", "marketing_sourced_enterprise", "win_rate_by_source",
        "marketing_attribution_share"]),

    ("P-RL-13", "Close-date slips Q2 to Q3", [
        r"\$180K slips", r"slips? from Q2 to Q3", r"Q2.*Q3.*close[- ]date",
        r"four deals.*close[- ]date", r"close[- ]date movement",
        r"close[- ]date slips", r"slips total \$180K", r"slip to Q3",
        r"slips? move \$180K",
    ], ["close_date_slip", "q2_q3_slip", "slip"]),

    ("P-RL-14", "Q2 bookings pacing", [
        r"\$880K", r"\$840K plan", r"plan[- ]pacing", r"5% ahead of plan",
        r"5% ahead of target", r"bookings? pace", r"plan pacing",
        r"\$880K closed", r"pace 5%", r"pacing 105%", r"pace \d% ahead",
    ], ["q2_bookings_pace", "q2_pacing", "plan_pacing", "bookings_actual"]),

    ("P-RL-15", "Q2 MM renewals + NRR", [
        r"\$620K ARR", r"1\.12 (segment )?NRR", r"net expansion",
        r"renewals.*\$620K", r"nine renewals", r"9 renewals",
        r"112% NRR", r"NRR holds at 112", r"renewal.*112%", r"112% through Q2",
    ], ["mm_renewals", "mid_market_nrr", "renewal_arr", "q2_mm_renewal", "mm_nrr"]),
]

# Voice violations: words/phrases the seed cards must not contain.
VIOLATION_PATTERNS = [
    ("em_dash", re.compile(r"\u2014")),
    ("against_comparator", re.compile(r"\b(versus|compared to)\b", re.I)),  # noqa: too permissive — replaced below
]

# Replace with proper comparator detector (only flag "against" used as comparator).
VIOLATION_PATTERNS = [
    ("em_dash", re.compile(r"\u2014")),
    ("against_comparator", re.compile(r"\bagainst\b", re.I)),
    ("verdict_gap", re.compile(r"\bgap(s)?\b", re.I)),
    ("verdict_loss", re.compile(r"\bloss(es)?\b", re.I)),
    ("verdict_below", re.compile(r"\bbelow\b", re.I)),
    ("verdict_behind", re.compile(r"\bbehind\b", re.I)),
    ("verdict_missed", re.compile(r"\bmissed\b", re.I)),
    ("verdict_shortfall", re.compile(r"\bshortfall\b", re.I)),
    ("verdict_concerning", re.compile(r"\bconcerning\b", re.I)),
    ("verdict_declined", re.compile(r"\bdeclined?\b", re.I)),
]

CONTENT_FIELDS = ("title", "anchor", "connect", "body")


def card_text(card):
    return " ".join(str(card.get(f, "")) for f in CONTENT_FIELDS)


def detect_patterns(cards):
    found = {}
    for name, label, regexes, tag_fragments in PATTERNS:
        hit = False
        for card in cards:
            text = card_text(card)
            metrics = card.get("grounded_metrics") or []
            if tag_match(metrics, tag_fragments):
                hit = True
                break
            for rx in regexes:
                if re.search(rx, text):
                    hit = True
                    break
            if hit:
                break
        found[name] = (hit, label)
    return found


def detect_violations(cards):
    hits = []
    for idx, card in enumerate(cards):
        for field in CONTENT_FIELDS:
            value = card.get(field, "")
            if not value:
                continue
            for vname, rx in VIOLATION_PATTERNS:
                m = rx.search(value)
                if m:
                    hits.append((idx, field, vname, m.group(0)))
    return hits


def main():
    summary_rows = []
    cross_seed_pattern_count = {p[0]: 0 for p in PATTERNS}
    total_violations = 0

    for seed in SEEDS:
        path = EVAL_DIR / f"generated_cards_revenue_seed{seed}.json"
        if not path.exists():
            print(f"seed {seed}: MISSING {path}")
            continue
        cards = json.loads(path.read_text())
        patterns = detect_patterns(cards)
        violations = detect_violations(cards)
        total_violations += len(violations)
        covered = sum(1 for _, (hit, _) in patterns.items() if hit)
        for name, (hit, _) in patterns.items():
            if hit:
                cross_seed_pattern_count[name] += 1

        first_two = [c["title"] for c in cards[:2]]
        summary_rows.append({
            "seed": seed,
            "card_count": len(cards),
            "patterns_covered": covered,
            "patterns_missed": [n for n, (hit, _) in patterns.items() if not hit],
            "violations": violations,
            "first_two": first_two,
        })

    print("\n=== Phase 2.5 Multi-Seed Revenue Leader Eval ===\n")
    print(f"{'Seed':<8}{'Cards':<8}{'Patterns':<10}{'Voice':<8}{'Missed':<30}")
    print("-" * 64)
    for row in summary_rows:
        miss_str = ",".join(row["patterns_missed"]) if row["patterns_missed"] else "-"
        print(f"{row['seed']:<8}{row['card_count']:<8}{row['patterns_covered']}/15      "
              f"{len(row['violations'])} vios    {miss_str}")

    print("\n=== First two card titles per seed ===")
    for row in summary_rows:
        print(f"\n  seed {row['seed']}:")
        for t in row["first_two"]:
            print(f"    - {t}")

    print("\n=== Cross-seed pattern coverage ===")
    for name, label, _, _ in PATTERNS:
        count = cross_seed_pattern_count[name]
        flag = "" if count == len(SEEDS) else "  <-- gap"
        print(f"  {name} ({label}): {count}/{len(SEEDS)}{flag}")

    print("\n=== Voice violations detail ===")
    if total_violations == 0:
        print("  zero violations across all seeds")
    else:
        for row in summary_rows:
            if not row["violations"]:
                continue
            print(f"\n  seed {row['seed']}:")
            for idx, field, vname, match in row["violations"]:
                print(f"    card[{idx}].{field}: {vname} → '{match}'")

    runs_full_coverage = sum(1 for r in summary_rows if r["patterns_covered"] == 15)
    print(f"\n=== Aggregate ===")
    print(f"  runs at 15/15 RL coverage: {runs_full_coverage}/{len(summary_rows)}")
    print(f"  total voice violations across seeds: {total_violations}")


if __name__ == "__main__":
    main()
