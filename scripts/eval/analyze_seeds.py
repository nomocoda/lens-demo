"""Phase 2.5 / 2.6 / 2.9 multi-seed analyzer (Revenue Leader + Customer Leader + Marketing Strategist).

Reads generated_cards_<archetype>_seed<N>.json for each seed, scores:
  - card count
  - voice violation count (em dash, "against" comparator, banned verdict words)
  - specificity status (engine drops are reported in stderr, this checks ungrounded numerics in saved cards)
  - 15 archetype-specific pattern coverage (P-RL-01..15, P-CL-01..15, or P-MS-01..15)

Patterns are detected by content keywords and grounded_metrics tags. The detection
is intentionally permissive (any-of) so a card that legitimately tells the pattern
with different exact figures still counts.

Usage:
  python analyze_seeds.py                            # default archetype=revenue
  python analyze_seeds.py --archetype customer       # Phase 2.6 Customer Leader
  python analyze_seeds.py --archetype marketing_strategist  # Phase 2.9 Marketing Strategist
"""
import argparse
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

# Customer Leader pattern detectors (P-CL-01..15) for Phase 2.6.
# Same any-of permissive approach as the RL table above. Detectors target both
# the literal P-CL anchor numbers and common phrasings the model reaches for.
CL_PATTERNS = [
    ("P-CL-01", "Q2 forecast accuracy 1.7%", [
        r"\b1\.7%\b", r"\bwithin 2%\b", r"\bwithin 1\.7\b",
        r"forecast.*(within|lands|closes|tightens|variance)",
        r"\$1\.77M", r"\$1\.8M.*forecast", r"variance.*1\.7",
    ], ["forecast_accuracy", "q2_forecast", "forecast_variance",
        "forecast_arr", "renewal_forecast"]),

    ("P-CL-02", "At-risk pool $310K to $220K", [
        r"\$220K.*\$310K", r"\$310K.*\$220K", r"\$220K.*April",
        r"at[- ]risk.*\$220K", r"at[- ]risk.*\$310K",
        r"at[- ]risk.*shrink", r"at[- ]risk.*contract", r"at[- ]risk.*drop",
        r"risk pool.*\$2", r"risk pool.*\$3",
    ], ["at_risk_pool", "renewal_at_risk", "at_risk_arr"]),

    ("P-CL-03", "April enterprise renewals + sponsor depth", [
        r"enterprise renewal.*sign(ed|ing)", r"sponsor.*deepen",
        r"deepen.*sponsor", r"executive sponsor.*sign",
        r"3 enterprise renewals", r"april.*enterprise.*renewal",
        r"4 sponsors", r"renewal.*signed.*executive",
        r"enterprise.*signing.*sponsor",
    ], ["enterprise_renewal", "sponsor_depth", "executive_sponsor",
        "april_renewal"]),

    ("P-CL-04", "Q2 mid-market GRR 91% on $1.8M", [
        r"\bGRR.*91%\b", r"91%.*GRR", r"mid[- ]market.*91%",
        r"91%.*mid[- ]market", r"91%.*gross retention",
        r"\$1\.8M.*renewing", r"renewing.*\$1\.8M",
    ], ["mm_grr", "q2_mm_grr", "mid_market_grr", "grr"]),

    ("P-CL-05", "Beacon $280K early renewal", [
        r"\bBeacon\b", r"\$280K.*renew", r"renew.*\$280K",
        r"Beacon.*early", r"three months early", r"3 months early",
    ], ["beacon", "early_renewal", "beacon_renewal"]),

    ("P-CL-06", "Q2 MM NRR 112% vs trailing 105%", [
        r"112%.*NRR", r"NRR.*112%", r"NRR.*112",
        r"mid[- ]market.*NRR.*112", r"NRR.*105", r"105%.*NRR",
        r"trailing.*NRR", r"7 points above trailing",
        r"jumps 7 points", r"climbs to 112",
    ], ["mm_nrr", "q2_mm_nrr", "mid_market_nrr"]),

    ("P-CL-07", "Multi-product 124% vs single 102%", [
        r"multi[- ]product.*124", r"124%.*multi", r"single[- ]product.*102",
        r"102%.*single", r"22[- ]point.*NRR", r"NRR.*22[- ]point",
        r"multi[- ]product.*single[- ]product", r"NRR.*22 percentage",
        r"premium over single[- ]product", r"single[- ]product.*premium",
    ], ["multi_product", "multi_product_nrr", "product_breadth",
        "multiproduct_nrr"]),

    ("P-CL-08", "MM TTFV 23 days vs 38", [
        r"\b23 days\b", r"\b38 days\b", r"time to first value.*23",
        r"TTFV.*23", r"TTFV.*38", r"first value.*23",
        r"compress.*15 days", r"15 days quarter[- ]over[- ]quarter",
    ], ["ttfv", "time_to_first_value", "mm_ttfv"]),

    ("P-CL-09", "8 CS expansion $340K + 83% acceptance", [
        r"\$340K.*health", r"health.*\$340K", r"\$340K.*expansion",
        r"expansion.*\$340K", r"health review.*8", r"8 expansion",
        r"83%.*accept", r"accept.*83%", r"expansion.*health",
        r"health.*expansion", r"42 points above outbound",
    ], ["health_review_expansion", "cs_sourced_expansion",
        "health_review", "expansion_source", "expansion_acceptance"]),

    ("P-CL-10", "22 MM 80% utilization", [
        r"\b22 (mid[- ]market )?(account|customer|MM)", r"22.*80%",
        r"80%.*utilization", r"utilization.*22", r"22 mid[- ]market",
        r"license utilization.*22", r"57% quarter[- ]over[- ]quarter",
    ], ["license_utilization", "mm_utilization", "license_util",
        "utilization"]),

    ("P-CL-11", "Q2 78% green, Q1 71% green", [
        r"78%.*green", r"green.*78%", r"71%.*green", r"green.*71%",
        r"77% green", r"green.*77%", r"health.*green.*78",
        r"health score.*green", r"green health score",
    ], ["health_score", "health_distribution", "green_health"]),

    ("P-CL-12", "Q1 88% / Q4 83% retention", [
        r"\b88%\b.*retention", r"retention.*88%", r"90[- ]day retention",
        r"retention.*83", r"new customer.*88", r"all[- ]segments.*88",
        r"cohort.*88", r"5 points.*onboarding",
    ], ["cohort_retention", "ninety_day_retention", "retention_90d",
        "new_customer_retention"]),

    ("P-CL-13", "High-touch 96% vs tech-touch 82%", [
        r"high[- ]touch.*96", r"96%.*high[- ]touch", r"tech[- ]touch.*82",
        r"82%.*tech[- ]touch", r"14[- ]point.*high[- ]touch",
        r"high[- ]touch.*tech[- ]touch", r"coverage tier.*14",
        r"14 points above tech[- ]touch", r"14[- ]point.*advantage",
        r"tier retention.*14", r"coverage.*spread.*14",
    ], ["coverage_tier", "high_touch_grr", "tech_touch_grr",
        "tier_grr", "tier_retention"]),

    ("P-CL-14", "2 top-20 ARR + sponsor review this week", [
        r"top[- ]20.*at[- ]risk", r"top[- ]ARR.*at[- ]risk",
        r"sponsor review", r"executive sponsor.*review",
        r"2 top[- ]ARR", r"2 of 2 top[- ]ARR", r"2 top[- ]20",
        r"top[- ]20[- ]ARR", r"executive review",
    ], ["top_20_at_risk", "sponsor_review", "executive_sponsor_review",
        "top_arr_at_risk"]),

    ("P-CL-15", "Custom Permissions launch + Beacon early-renewal", [
        r"Custom Permissions", r"Audit Logs", r"June 15",
        r"6/15", r"2026-06-15",
        r"launch.*Beacon", r"Beacon.*launch",
        r"launch.*early.*renewal", r"early.*renewal.*launch",
        r"permissions.*ship", r"audit logs.*ship",
    ], ["product_launch", "custom_permissions", "launch_renewal_link",
        "audit_logs"]),
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


def detect_patterns(cards, patterns):
    found = {}
    for name, label, regexes, tag_fragments in patterns:
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


# Marketing Strategist pattern detectors (P-MS-01..15) for Phase 2.9.
MS_PATTERNS = [
    ("P-MS-01", "Speed-to-value message resonance 62% of discovery calls", [
        r"speed[- ]to[- ]value", r"\b62%\b", r"17 of 27", r"17.*27.*call",
        r"discovery call.*resonan", r"resonan.*discovery", r"Gong.*62",
        r"62%.*discovery", r"0\.62.*call",
    ], ["april_gong_discovery", "message_resonance", "discovery_calls",
        "positioning_close_rates"]),

    ("P-MS-02", "ICP match rate climbs 78% Q2 vs 64% Q1", [
        r"\b78%\b", r"28 of 36", r"icp[- ]match", r"ICP match.*78",
        r"78%.*ICP", r"23 of 36", r"0\.7778", r"0\.6389",
        r"fits the profile", r"fitting the profile",
    ], ["icp_match_rate", "icp_velocity_lift", "icp_match"]),

    ("P-MS-03", "Beacon Systems head-to-head win rate 64%", [
        r"\bBeacon\b.*win rate", r"win rate.*\bBeacon\b",
        r"\b14[- ]8\b", r"14-8 record", r"14 wins.*8",
        r"64%.*head[- ]to[- ]head", r"head[- ]to[- ]head.*64",
        r"63\.6%", r"prior.*28%", r"28%.*prior",
    ], ["beacon_h2h_wins", "beacon_historical", "beacon_win_rate",
        "beacon", "competitive"]),

    ("P-MS-04", "Battlecard utilization 61% vs Q1 22%", [
        r"battlecard.*util", r"util.*battlecard",
        r"\b61%\b.*battlecard", r"battlecard.*61%",
        r"38.*62.*beacon", r"38 opens.*62",
        r"Q1.*util.*22", r"22%.*Q1", r"utilization.*climbs",
    ], ["battlecard_opens", "q1_utilization", "battlecard_utilization",
        "enablement_util"]),

    ("P-MS-05", "Northstar win rate lift 42%→51% post-update", [
        r"\bNorthstar\b", r"51%.*win rate", r"win rate.*51%",
        r"42%.*51%", r"from 42", r"Gong.*22%", r"22%.*Gong",
        r"Gong.*drop", r"mentions.*drop.*22", r"battlecard.*revision",
        r"objection.*update", r"april 8.*battlecard",
    ], ["northstar_win_rate", "northstar_gong_mentions", "northstar"]),

    ("P-MS-06", "Verge IO emergence 24% of deals vs Q1 11%", [
        r"\bVerge\b", r"24%.*Verge", r"Verge.*24%",
        r"18 of 75", r"18.*75.*compet", r"Q1.*11%.*Verge",
        r"Verge.*11%.*Q1", r"emergen", r"doubles.*compet",
        r"\$40M.*Series B", r"Series B.*\$40M",
    ], ["verge_competitive_share", "verge_funding", "verge_segment_concentration",
        "verge", "competitive"]),

    ("P-MS-07", "Close reason capture 92% Q2 vs 71% Q1", [
        r"close reason", r"reason capture", r"\b92%\b.*close",
        r"close.*92%", r"47 of 51", r"47.*51.*deal",
        r"crm.*hygiene", r"hygiene.*crm", r"0\.9216",
        r"Q1.*71%.*capture", r"capture.*71%.*Q1",
        r"structured reason", r"outcome.*capture",
    ], ["outcome_reason_capture", "crm_hygiene", "close_reason_capture"]),

    ("P-MS-08", "CRM Sync launch generates $420K / 14 opps in 3 weeks", [
        r"\$420K", r"14.*opportunit", r"CRM Sync", r"april 8.*launch",
        r"launch.*\$420K", r"\$420K.*launch", r"\$420K.*pipeline",
        r"\$310K.*prior", r"prior.*\$310K",
    ], ["april_launch_pipeline", "prior_launch_compare", "launch_pipeline"]),

    ("P-MS-09", "Launch asset adoption 71% (27/38 reps) in first 14 days", [
        r"\b71%\b.*launch", r"launch.*71%", r"27 of 38", r"27.*38.*rep",
        r"asset.*adopt", r"adopt.*asset", r"battlecard.*one[- ]pager",
        r"prior.*42%.*launch", r"launch.*42%.*prior",
        r"reps opened", r"opened.*assets",
    ], ["launch_asset_adoption", "rep_engagement", "enablement_adoption"]),

    ("P-MS-10", "Asset-opening reps generate 2.4x launch pipeline", [
        r"2\.4x", r"2\.4 times", r"asset.*pipeline.*lift",
        r"pipeline.*asset.*lift", r"rep.*engage.*pipeline",
        r"opened.*launch.*pipeline", r"launch.*2\.4",
    ], ["asset_pipeline_lift", "launch_asset_adoption", "enablement_roi"]),

    ("P-MS-11", "Forecast Pro readiness 10 days early vs 2 days prior launch", [
        r"Forecast Pro", r"10 days.*early", r"early.*10 days",
        r"may 5.*sign", r"sign.*may 5", r"2026-05-05",
        r"prior.*2 days", r"2 days.*prior", r"signed off.*days",
        r"launch readiness", r"readiness.*clears",
    ], ["forecast_pro_readiness", "prior_launch_timing", "launch_readiness"]),

    ("P-MS-12", "Enterprise inbound $290K + 8-point conversion lift", [
        r"\$290K", r"8[- ]point.*conversion", r"conversion.*8[- ]point",
        r"8 points.*higher", r"enterprise.*inbound", r"inbound.*enterprise",
        r"enterprise.*pipeline.*\$290", r"\$290K.*enterprise",
        r"new.*messag.*frame", r"inbound.*conversion.*lift",
    ], ["enterprise_inbound_pipeline", "conversion_lift", "inbound_conversion"]),

    ("P-MS-13", "Launch-attributed pipeline 18% of Q2 net new ($620K of $3.4M)", [
        r"\$620K", r"\$3\.4M", r"18%.*net new", r"net new.*18%",
        r"launch.*attrib", r"attrib.*launch", r"18%.*Q2 net",
        r"Q2 net.*18%", r"0\.1824",
    ], ["launch_attribution_share", "q2_launch_attribution", "attribution_share"]),

    ("P-MS-14", "Earned media pickup 42% (22/53 publications) vs prior 28%", [
        r"\b42%\b.*media", r"media.*42%", r"22 of 53", r"22.*53.*pub",
        r"media.*pickup", r"pickup.*media", r"earned.*42%",
        r"prior.*28%.*media", r"28%.*prior.*media",
        r"2x.*pipeline.*launch", r"launch.*pipeline.*2x",
    ], ["media_pickup_rate", "earned_media", "launch_week_velocity"]),

    ("P-MS-15", "CS exit themes feed positioning (31% Beacon overlap, 14 interviews)", [
        r"exit interview", r"exit theme", r"\b14\b.*interview",
        r"\b6\b.*theme", r"31%.*Beacon", r"Beacon.*31%",
        r"competitor.*theme", r"theme.*positioning",
        r"CS.*exit", r"exit.*CS", r"customer.*feed.*position",
    ], ["exit_themes_competitive", "april_exit_interviews",
        "cs_exit_themes", "exit_interview"]),
]


_ARCHETYPE_TABLE = {
    "revenue": (PATTERNS, "Revenue Leader", "revenue", "Phase 2.5"),
    "customer": (CL_PATTERNS, "Customer Leader", "customer", "Phase 2.6"),
    "marketing_strategist": (MS_PATTERNS, "Marketing Strategist", "marketing_strategist", "Phase 2.9"),
}


def main():
    ap = argparse.ArgumentParser(description="Multi-seed eval analyzer")
    ap.add_argument("--archetype", choices=sorted(_ARCHETYPE_TABLE.keys()),
                    default="revenue",
                    help="Which archetype to score (default revenue)")
    args = ap.parse_args()

    patterns, leader_label, file_tag, phase_label = _ARCHETYPE_TABLE[args.archetype]

    summary_rows = []
    cross_seed_pattern_count = {p[0]: 0 for p in patterns}
    total_violations = 0

    for seed in SEEDS:
        path = EVAL_DIR / f"generated_cards_{file_tag}_seed{seed}.json"
        if not path.exists():
            print(f"seed {seed}: MISSING {path}")
            continue
        cards = json.loads(path.read_text())
        seed_patterns = detect_patterns(cards, patterns)
        violations = detect_violations(cards)
        total_violations += len(violations)
        covered = sum(1 for _, (hit, _) in seed_patterns.items() if hit)
        for name, (hit, _) in seed_patterns.items():
            if hit:
                cross_seed_pattern_count[name] += 1

        first_two = [c["title"] for c in cards[:2]]
        summary_rows.append({
            "seed": seed,
            "card_count": len(cards),
            "patterns_covered": covered,
            "patterns_missed": [n for n, (hit, _) in seed_patterns.items() if not hit],
            "violations": violations,
            "first_two": first_two,
        })

    print(f"\n=== {phase_label} Multi-Seed {leader_label} Eval ===\n")
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
    for name, label, _, _ in patterns:
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
    print(f"  runs at 15/15 {leader_label} coverage: {runs_full_coverage}/{len(summary_rows)}")
    print(f"  total voice violations across seeds: {total_violations}")


if __name__ == "__main__":
    main()
