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


MB_PATTERNS = [
    ("P-MB-01", "Paid pipeline $1.18M of $1.5M target by week 3", [
        r"\$1\.18M", r"\$1\.5M.*target", r"target.*\$1\.5M",
        r"1\.18.*1\.5", r"week.?3.*pacing", r"pacing.*week.?3",
        r"78%.*target", r"79%.*target", r"paid.*pipeline.*pacing",
        r"1\.18.*paid", r"paid.*1\.18",
        r"1,180,000", r"paid.*pipeline.*week.?3", r"week.?3.*paid.*pipeline",
    ], ["pipeline_at_week3", "paid_pipeline_pacing", "week3_pacing"]),

    ("P-MB-02", "Webinar generates 42% of April MQLs in 11 days", [
        r"312.*740", r"740.*312", r"\b312\b.*MQL", r"MQL.*\b312\b",
        r"\b42%\b.*MQL", r"MQL.*\b42%\b", r"webinar.*42%", r"42%.*webinar",
        r"11 days.*MQL", r"MQL.*11 days",
        r"19%.*SQL", r"SQL.*19%", r"webinar.*SQL", r"SQL.*webinar",
    ], ["webinar_mql_share", "webinar_sql_conversion", "mql_source"]),

    ("P-MB-03", "LinkedIn CPL $138 April vs $156 March vs $174 Q1", [
        r"\$138.*CPL", r"CPL.*\$138", r"\$156.*March", r"March.*\$156",
        r"\$174.*Q1", r"Q1.*\$174", r"CPL.*flat", r"flat.*CPL",
        r"audience.*refresh.*April 1", r"April 1.*audience",
        r"62%.*paid.*budget", r"paid.*budget.*62%",
    ], ["linkedin_cpl", "cpl_trend", "audience_refresh"]),

    ("P-MB-04", "Inbound demo requests 84 April vs 61 March", [
        r"\b84\b.*demo", r"demo.*\b84\b", r"\b61\b.*demo", r"demo.*\b61\b",
        r"84.*inbound", r"inbound.*84", r"\b47\b.*mid.?market", r"\b37\b.*enterprise",
        r"22%.*conversion", r"conversion.*22%", r"CTA.*test",
    ], ["inbound_demos", "demo_requests", "cta_conversion"]),

    ("P-MB-05", "Pricing page moves from position 7 to position 2 in 9 days", [
        r"position.*7.*position.*2", r"7.*to.*2.*position",
        r"saas pricing models", r"position 2", r"position.*2.*9 days",
        r"4,400.*search", r"search.*4,400", r"4400.*search.*volume",
        r"pricing.*page.*position", r"position.*pricing.*page",
    ], ["pricing_page_seo", "keyword_ranking_move", "seo_ranking"]),

    ("P-MB-06", "Content-attributable pipeline $310K from 6 of 18 pieces", [
        r"\$310K.*content", r"content.*\$310K",
        r"6 of 18", r"6.*18.*piece", r"buyer.?s.?guide.*\$140K",
        r"\$140K.*buyer", r"41%.*view", r"view.*41%",
    ], ["content_pipeline", "content_attribution", "buyers_guide"]),

    ("P-MB-07", "Comparison hub grows 28% to 12,400 sessions; AI Overview falls 71% to 38%", [
        r"12,?400.*session", r"session.*12,?400",
        r"9,?700.*session", r"session.*9,?700",
        r"\b28%\b.*organic", r"organic.*\b28%\b",
        r"AI Overview.*71%", r"71%.*AI Overview",
        r"71%.*38%", r"38%.*AI Overview",
        r"comparison hub", r"4,?200.*session.*competitor",
    ], ["comparison_hub_traffic", "organic_traffic_growth", "ai_overview"]),

    ("P-MB-08", "Three priority keywords move into top 3 in week ending April 7", [
        r"saas attribution", r"b2b lead routing", r"marketing ops checklist",
        r"three.*keyword", r"3.*keyword.*top.?3",
        r"page.?2.*top.?3", r"top.?3.*April 7",
        r"FAQ.*section", r"structured FAQ",
    ], ["top3_keywords", "seo_keywords_move", "faq_sections"]),

    ("P-MB-09", "Routing SLA 95% in April vs 82% in March", [
        r"\b95%\b.*routing", r"routing.*\b95%\b",
        r"\b82%\b.*routing", r"routing.*\b82%\b",
        r"412.*433", r"433.*412", r"357.*435", r"435.*357",
        r"5.?minute.*SLA", r"SLA.*5.?minute",
        r"routing.*update.*April 6", r"April 6.*routing",
    ], ["routing_sla", "sla_compliance", "inbound_routing"]),

    ("P-MB-10", "Marketo-Salesforce attribution variance 2.1% Q2 vs 4.8% Q1", [
        r"2\.1%.*variance", r"variance.*2\.1%",
        r"4\.8%.*Q1", r"Q1.*4\.8%",
        r"47.*2,?240", r"2,?240.*47", r"sourcing.*mismatch",
        r"UTM.*cleanup", r"cleanup.*UTM",
        r"attribution.*variance", r"variance.*attribution",
    ], ["attribution_variance", "marketo_sfdc_mismatch", "utm_cleanup"]),

    ("P-MB-11", "MQL field completeness 91% April vs 73% March", [
        r"\b91%\b.*MQL", r"MQL.*\b91%\b",
        r"\b73%\b.*MQL", r"MQL.*\b73%\b",
        r"678.*745", r"745.*678", r"form.*scoring",
        r"field.*complet", r"complet.*field",
        r"completeness.*91", r"91.*completeness",
    ], ["mql_completeness", "field_completeness", "form_scoring"]),

    ("P-MB-12", "Battlecard library 480 opens from 38 of 47 reps", [
        r"\b480\b.*battlecard", r"battlecard.*\b480\b",
        r"38.*47.*rep", r"47.*38.*rep",
        r"38 of 47", r"162.*Competitor A", r"Competitor A.*162",
        r"battlecard.*open", r"open.*battlecard",
    ], ["battlecard_opens", "battlecard_adoption", "rep_engagement"]),

    ("P-MB-13", "ROI calculator in 22 of 36 mid-market deals; $48K vs $39K deal size", [
        r"ROI calculator", r"roi calculator",
        r"22.*36.*deal", r"36.*deal.*22", r"22 of 36",
        r"\$48K.*\$39K", r"\$39K.*\$48K",
        r"calculator.*deal.*size", r"deal.*size.*calculator",
        r"7.*proposal", r"proposal.*7.*deal",
    ], ["roi_calculator", "calculator_adoption", "deal_size_lift"]),

    ("P-MB-14", "Speed-to-lead 4.2 minutes April vs 11.6 minutes March; 2.1x SQL lift", [
        r"4\.2.*minute", r"minute.*4\.2",
        r"11\.6.*minute", r"minute.*11\.6",
        r"2\.1x.*SQL", r"SQL.*2\.1x",
        r"speed.?to.?lead", r"first.*touch.*minute",
    ], ["speed_to_lead", "median_speed", "sql_conversion_multiple"]),

    ("P-MB-15", "Attribution coverage 88% ($2.4M of $2.7M); Q1 was 71%", [
        r"\$2\.4M.*\$2\.7M", r"\$2\.7M.*\$2\.4M",
        r"\b88%\b.*attribution", r"attribution.*\b88%\b",
        r"71%.*Q1.*attribution", r"Q1.*71%.*coverage",
        r"clean.*attribution.*chain", r"attribution.*chain",
        r"14.*campaign.*type", r"campaign.*type.*14",
    ], ["attribution_coverage", "closed_loop_attribution", "pipeline_coverage"]),
]


# Revenue Generator pattern detectors (P-RG-01..15) for Phase 2.15.
# Source: scripts/eval/generate_dataset.py canonical P-RG anchors (lines ~3003-3313)
# and grounded_metrics tags emitted by relevance_engine.py for the AE archetype.
RG_PATTERNS = [
    ("P-RG-01", "Q2 thread depth 4.2 contacts on $250K+ deals", [
        r"\bthread depth\b", r"4\.2 contacts", r"multi[- ]thread depth",
        r"thread depth.*doubled", r"contact depth.*doubled",
        r"large deal.*thread", r"\$250K\+.*thread",
    ], ["large_deal_thread_depth", "multi_thread_win_rates", "multi_thread_depth",
        "large_deal_threading", "multi_thread_close_correlation",
        "multi_thread_improvement", "contact_depth", "contact_depth_trend",
        "contact_count_win_rates", "win_rate_by_contacts", "win_rate_by_threading",
        "multi_thread_wins", "q2_contact_depth"]),

    ("P-RG-02", "April 14 champion re-engagements vs March 6", [
        r"champion re[- ]?engagement", r"champion[- ]reengag",
        r"re[- ]?engaging.*champion", r"champion.*lapsed",
        r"14 champion", r"champion.*stage movement",
    ], ["champion_reengagement", "champion_reengagement_advances",
        "champion_lapse_events", "stage_advancement", "stage_advancement_timing",
        "deal_acceleration"]),

    ("P-RG-03", "Sterling executive demo grew committee 4 to 7", [
        r"\bSterling\b", r"executive demo.*committee", r"committee.*4 to 7",
        r"buying committee.*expand", r"committee expand",
        r"Sterling.*committee", r"Sterling executive",
    ], ["sterling_committee", "sterling_committee_expansion", "sterling_deal",
        "sterling_deal_committee", "committee_expansion", "committee_expansion_rates",
        "committee_growth_win_rate", "executive_demo_impact"]),

    ("P-RG-04", "Enterprise Proposal-to-Closed cycle compresses Q2 vs Q1", [
        r"proposal[- ]to[- ]closed?", r"proposal cycle.*compress",
        r"enterprise.*proposal.*38", r"38 days.*49", r"49 days.*Q1",
        r"enterprise proposal.*compress", r"proposal[- ]to[- ]close.*cycle",
        r"compresses 11 days", r"proposal[- ]to[- ]close cycle",
    ], ["enterprise_proposal_cycle", "enterprise_cycle_compression",
        "enterprise_cycle", "proposal_to_close"]),

    ("P-RG-05", "Q3 pipeline coverage 3.4x quota", [
        r"3\.4x", r"3\.4 x", r"Q3.*coverage.*3\.4", r"Q3 pipeline coverage",
        r"\$4\.2M.*pipeline", r"\$1\.24M.*quota", r"Q3 quota.*\$1\.2",
        r"pipeline coverage sits at 3", r"3\.4x quota",
    ], ["q3_coverage", "q3_coverage_ratio", "q3_pipeline_coverage",
        "pipeline_engagement", "pipeline_engagement_rate", "quota_tracking"]),

    ("P-RG-06", "Proposal-stage aged deals advance/close in 30d", [
        r"proposal[- ]stage aged", r"proposal aging", r"aged proposal",
        r"11 of 14.*proposal", r"proposal.*advanced", r"proposal stage time",
        r"proposal.*aging clears", r"reissue", r"proposal-stage aging",
    ], ["proposal_aging", "proposal_stage_aging", "aged_proposal_advances",
        "reissue_correlation", "reissue_timing", "proposal_reissue_timing",
        "reissued_proposal_velocity"]),

    ("P-RG-07", "Q2 mid-market win rate 27% vs Q1 19%", [
        r"mid[- ]market win rate.*27", r"MM win rate.*27", r"27%.*mid[- ]market",
        r"Q2.*MM.*27", r"win rate climbs to 27", r"Q2 mid[- ]market.*27",
        r"mid[- ]market.*ICP[- ]aligned", r"27% this quarter",
    ], ["mm_win_rate", "mid_market_win_rate", "mm_win_rate_q2", "q2_performance",
        "icp_alignment", "icp_alignment_contribution", "icp_alignment_impact"]),

    ("P-RG-08", "Champion-documented win rate Q2 38% vs undocumented 21%", [
        r"champion[- ]document", r"champion documentation.*win",
        r"documented win rate", r"champion.*38%.*undocument",
        r"champion documentation crosses", r"50%.*champion document",
    ], ["champion_documentation", "champion_documentation_rate",
        "champion_win_rates", "champion_win_correlation"]),

    ("P-RG-09", "Active deal documentation 17 of 18 updated in 5 days", [
        r"active deal.*94", r"active deal.*92", r"active deal documentation",
        r"freshness.*Q4", r"17 of 18.*updated", r"18 active deals",
        r"deal freshness.*highest",
    ], ["active_deal_documentation", "active_deal_hygiene", "deal_freshness",
        "deal_hygiene", "stage_documentation", "stage_note_currency",
        "deal_tracking", "documentation_improvement"]),

    ("P-RG-10", "Q2 closed-deal capture 88% (23 of 26)", [
        r"CRM activity capture.*88", r"88%.*closed deals",
        r"closed[- ]deal capture", r"23.*26.*activity", r"23 of 26",
        r"CRM capture", r"outcome reason.*capture",
    ], ["crm_capture_completeness", "crm_capture", "closed_deal_capture",
        "outcome_field_impact", "outcome_field_adoption", "outcome_reason_capture",
        "outcome_reason_adoption", "outcome_tracking", "activity_capture_rate",
        "operational_discipline"]),

    ("P-RG-11", "Revised outbound cadence converts 14% (42/300)", [
        r"Revised outbound", r"revised.*sequence", r"outbound.*cadence",
        r"14%.*outbound", r"outbound.*convert.*14", r"42.*300", r"42/300",
        r"revised cadence", r"outbound sequence.*14",
    ], ["outbound_sequence_conversion", "revised_outbound_conversion",
        "outbound_sequence_improvement", "outbound_conversion",
        "outbound_improvement", "outbound_comparison", "prior_sequence_conversion",
        "sequence_optimization", "sequence_performance", "cadence_performance",
        "discovery_booking", "inbound_comparison", "inbound_conversion",
        "inbound_conversion_rate", "inbound_conversion_stable"]),

    ("P-RG-12", "Q2 Beacon h2h 11W/7L (61%); trailing 4Q 24%", [
        r"Beacon.*head[- ]to[- ]head", r"Beacon h2h", r"Beacon.*61%",
        r"61%.*Beacon", r"Beacon win rate", r"Beacon.*head to head",
        r"Beacon head[- ]to[- ]head win rate", r"head[- ]to[- ]head.*Beacon",
        r"11W.*7L", r"11 wins.*7",
    ], ["beacon_h2h_wins", "beacon_h2h_win_rate", "beacon_win_rate",
        "beacon_win_rate_lift", "historical_beacon_rate", "h2h_results"]),

    ("P-RG-13", "Meridian AI in 26% of Q2 deals (12/47) up from 10%", [
        r"Meridian", r"Meridian AI", r"26%.*active", r"Meridian.*Q2",
        r"Meridian.*26", r"12 of 47", r"Series B.*Meridian",
    ], ["meridian_deal_presence", "meridian_presence",
        "meridian_competitive_frequency", "meridian_series_b",
        "meridian_series_b_acceleration", "series_b_correlation",
        "funding_deal_velocity", "funding_impact", "funding_momentum"]),

    ("P-RG-14", "Beacon battlecard utilization 72% (13 of 18)", [
        r"Beacon battlecard", r"battlecard.*72", r"battlecard.*open",
        r"battlecard utilization", r"13 of 18.*Beacon", r"battlecard.*Beacon",
        r"battlecard.*correlate.*win", r"battlecard.*win rate",
    ], ["beacon_battlecard_usage", "battlecard_usage", "battlecard_utilization",
        "beacon_competitive_presence", "beacon_competitive_frequency",
        "beacon_competition", "beacon_frequency", "beacon_deal_presence",
        "q1_beacon_comparison", "beacon_win_correlation", "utilization_correlation",
        "competitive_deals", "competitive_frequency", "competitive_landscape",
        "competitive_performance", "competitive_share"]),

    ("P-RG-15", "Expansion-ready flags surface $310K (5 of 9 onboardings)", [
        r"expansion[- ]ready", r"expansion-ready flag", r"\$310K.*expansion",
        r"expansion.*\$310K", r"5 of 9.*onboarding",
        r"expansion[- ]ready flags",
    ], ["expansion_flags", "expansion_ready_accounts", "expansion_ready_flags",
        "csm_discovery_touches", "csm_expansion_handoff", "cs_handoff",
        "cs_contact_depth", "onboarding_to_expansion", "onboarding_conversion",
        "demo_expansion_rate"]),
]


# Revenue Developer pattern detectors (P-RD-01..15) for Phase 2.18.
# Source: scripts/eval/generate_dataset.py canonical P-RD anchors (lines ~3337-3563).
RD_PATTERNS = [
    ("P-RD-01", "17 of 18 inbound leads reached within 5-min window", [
        r"5[- ]minute", r"17 of 18", r"speed[- ]to[- ]lead",
        r"inbound.*5 minutes?", r"within 5 minute",
        r"5[- ]?minute.*inbound", r"inbound demo.*5",
    ], ["inbound_speed_to_lead", "speed_to_lead", "speed_to_lead_performance",
        "response_time_conversion", "response_window_conversion",
        "within_window_conversion", "first_touch_response",
        "first_touch_response_rate", "first_touch_response_segment"]),

    ("P-RD-02", "Multi-channel sequences 2.3x meeting rate of email-only", [
        r"multi[- ]channel.*2\.3", r"2\.3x.*meeting", r"email[- ]only",
        r"multi[- ]channel sequence", r"multi-channel.*breakthrough",
        r"sequences breakthrough", r"touch 7[- ]8",
    ], ["multi_channel_lift", "multi_channel_meeting_rate",
        "multi_channel_sequence_performance", "multi_channel_breakthrough_touch",
        "multi_channel_sequence_depth", "multi_channel_touch_distribution",
        "channel_breakthrough_timing", "channel_strategy_comparison",
        "email_vs_multichannel_lift", "channel_quality_match"]),

    ("P-RD-03", "Mid-market manufacturing segment: 4 AE-accepted in 3 weeks", [
        r"manufacturing", r"mid[- ]market manufacturing", r"Manufacturing",
        r"4 AE[- ]accepted", r"Mid Market Manufacturing",
        r"manufacturing.*launch", r"3 weeks.*manufacturing",
    ], ["mid_market_manufacturing", "mid_market_manufacturing_launch",
        "manufacturing_vertical", "new_segment_performance",
        "segment_criteria_impact", "segment_criteria_refinement"]),

    ("P-RD-04", "Subject variant 'what changed at' 4.7% reply rate", [
        r"subject line", r"what changed at", r"4\.7%.*reply",
        r"subject variant", r"Subject line variant",
        r"variant.*4\.7", r"4\.7% reply rate",
    ], ["subject_line_variant_test", "subject_line_test",
        "subject_line_meeting_conversion", "opener_reply_rate",
        "opener_test_volume", "variant_reply_lift", "reply_rate_comparison",
        "reply_rate_conversion"]),

    ("P-RD-05", "3 of 5 6sense high-intent threshold accounts booked", [
        r"6sense", r"high[- ]intent threshold", r"6sense.*intent",
        r"intent.*threshold", r"high[- ]intent accounts",
        r"threshold crossing", r"3 meetings.*48 hour",
    ], ["sixsense_high_intent_conversion", "sixsense_threshold_crossing",
        "sixsense_intent_response", "sixsense_first_touch",
        "intent_threshold_response", "intent_to_meeting_velocity",
        "intent_to_meeting", "intent_first_touch"]),

    ("P-RD-06", "26 of 31 meetings AE-accepted (84%)", [
        r"AE[- ]accept", r"84%.*April", r"AE.*qualification",
        r"AE acceptance", r"AE[- ]accepted rate.*84",
        r"84%.*AE", r"qualification refresh",
    ], ["ae_acceptance_rate", "ae_accepted_rate", "ae_acceptance_parity",
        "ae_accepted_parity", "qualification_criteria_refresh",
        "qualification_refinement", "april_meetings_qualified",
        "meeting_quality_trend"]),

    ("P-RD-07", "5 booked meetings within 7 days of trigger event", [
        r"trigger event", r"trigger[- ]event", r"Series B.*trigger",
        r"within 7 days", r"4x.*cold", r"trigger.*outreach",
        r"trigger[- ]event.*4x", r"Trigger[- ]event",
    ], ["trigger_event_lift", "trigger_event_conversion",
        "trigger_event_personalization", "trigger_event_messaging",
        "trigger_event_response_rate", "trigger_response_rate",
        "series_b_timing", "series_b_timing_advantage", "series_b_trigger",
        "timing_advantage", "research_driven_engagement"]),

    ("P-RD-08", "LinkedIn inbound demos 4/week to 13/week", [
        r"LinkedIn", r"LinkedIn ad[- ]source", r"LinkedIn.*demo.*triple",
        r"LinkedIn inbound", r"LinkedIn.*tripl",
        r"LinkedIn ad-sourced", r"4/week.*13/week",
    ], ["linkedin_inbound_growth", "linkedin_inbound_volume",
        "linkedin_acceptance_parity", "linkedin_ae_acceptance"]),

    ("P-RD-09", "41% meeting-producing replies on touch 7-8", [
        r"touch 7", r"touch 8", r"touch 7[- ]8", r"deeper sequence",
        r"sequence depth", r"breakthrough.*touch", r"touch 7 or 8",
        r"meeting[- ]producing replies",
    ], ["sequence_depth_shift", "breakthrough_touch_distribution",
        "touch_step_distribution", "touch_depth_comparison",
        "active_sequence_performance", "sequence_effectiveness"]),

    ("P-RD-10", "Personalized first-line openers convert at 5.1%", [
        r"personalized first[- ]line", r"first[- ]line", r"5\.1%.*reply",
        r"first line opener", r"Personalized first[- ]line",
        r"first[- ]line opener", r"5\.1% reply",
    ], ["personalized_first_line", "personalized_first_line_lift",
        "personalized_first_line_performance", "first_line_effectiveness",
        "generic_opener_baseline"]),

    ("P-RD-11", "All 11 weekend demo requests reached by Monday 9:15", [
        r"weekend", r"Monday 9:15", r"weekend inbound",
        r"11 demo requests.*Monday", r"weekend demo",
        r"Weekend inbound coverage", r"all 11.*demo",
    ], ["weekend_inbound_coverage", "weekend_coverage_effectiveness",
        "monday_conversion_rate", "monday_booking_rate",
        "monday_meeting_conversion"]),

    ("P-RD-12", "Healthcare vertical demo conversion 81% vs 64%", [
        r"Healthcare", r"healthcare", r"81%.*Healthcare", r"Healthcare.*81",
        r"Healthcare vertical", r"healthcare.*81",
        r"healthcare deal", r"Healthcare vertical converts",
    ], ["healthcare_demo_conversion", "healthcare_vertical_conversion",
        "healthcare_deal_value", "vertical_deal_size",
        "vertical_deal_size_multiple", "vertical_opportunity_size",
        "deal_size_by_vertical"]),

    ("P-RD-13", "8-9 AM call block 11% connect vs 5% post-lunch", [
        r"8[- ]9 AM", r"morning call", r"11% connect",
        r"call connect.*morning", r"Morning call window",
        r"morning.*window connect", r"call connect by time",
    ], ["call_connect_by_time", "call_connect_rate_by_time",
        "call_connect_rate_timing", "call_connect_rates",
        "time_window_performance", "morning_discovery_bookings",
        "discovery_booking_concentration"]),

    ("P-RD-14", "6 dormant accounts (>90 days) replied to re-engagement", [
        r"dormant", r"re[- ]engagement.*account", r"6 dormant",
        r"90 days quiet", r"dormant.*replied",
        r"6 dormant accounts", r"dormant accounts replied",
    ], ["dormant_reengagement", "dormant_reengagement_sequence",
        "silent_account_replies", "silent_account_conversion",
        "long_term_nurture", "reengagement_to_meeting"]),

    ("P-RD-15", "3 enterprise accounts produced 2nd buying committee", [
        r"buying committee", r"enterprise.*multi[- ]contact",
        r"3 multi[- ]contact", r"enterprise.*committee",
        r"second.*committee", r"enterprise accounts.*develop",
        r"3 multi-contact", r"multi[- ]contact opportunit",
    ], ["enterprise_committee_expansion", "buying_committee_expansion",
        "buying_committee_seniority", "enterprise_multi_contact",
        "enterprise_multi_threading", "coordinated_ae_outreach"]),
]


# Revenue Operator pattern detectors (P-RO-01..15) for Phase 2.21.
# Source: scripts/eval/generate_dataset.py canonical P-RO anchors (lines ~3942-4116).
RO_PATTERNS = [
    ("P-RO-01", "Forecast accuracy lift after Stage 4 close-date validation", [
        r"forecast accuracy", r"close[- ]date validation",
        r"Stage 4 validation", r"18 points.*forecast",
        r"forecast accuracy jumped", r"Stage 4.*validation",
    ], ["forecast_accuracy", "forecast_accuracy_lift",
        "forecast_accuracy_improvement", "forecast_accuracy_commit_tier",
        "stage_4_validation", "stage_4_close_date_validation",
        "commit_tier_accuracy", "commit_tier_deals", "reviewed_deal_accuracy"]),

    ("P-RO-02", "Pipeline definition lock produces unified view", [
        r"pipeline definition lock", r"one matching number",
        r"pipeline definition", r"unified.*pipeline",
        r"matching number.*team", r"pipeline definition.*lock",
    ], ["pipeline_definition", "pipeline_definition_alignment",
        "single_reconciled_view", "unified_forecast_view",
        "cross_team_alignment", "cross_function_alignment",
        "cross_function_reconciliation", "forecast_call_reconciled_view"]),

    ("P-RO-03", "Stale close-date auto-flag rule (247 deals since Apr 17)", [
        r"stale close[- ]date", r"auto[- ]flag", r"247 deals",
        r"stale close-date.*surface", r"stale.*flag",
        r"Stale close[- ]date flags", r"close[- ]date flag",
    ], ["stale_close_dates", "stale_close_date", "stale_close_date_flags",
        "auto_flag_rule", "auto_flag_clearing", "stale_date_automation"]),

    ("P-RO-04", "Pipeline coverage 4.1x vs plan in Q3", [
        r"4\.1x.*Q3", r"Q3.*4\.1x", r"pipeline coverage.*4\.1",
        r"4\.1x versus plan", r"Pipeline coverage sits at 4\.1",
        r"coverage.*4\.1", r"Q3 plan",
    ], ["pipeline_coverage", "pipeline_coverage_ratio", "q3_pipeline_coverage",
        "q3_plan", "coverage_calculation"]),

    ("P-RO-05", "Multi-touch attribution model lock + QBR dispute resolution", [
        r"attribution.*dispute", r"attribution model",
        r"QBR.*resolv", r"Multi[- ]touch attribution",
        r"attribution.*first pass", r"attribution disputes",
        r"Multi-touch attribution", r"resolved on first pass",
    ], ["attribution_model", "attribution_model_lock",
        "attribution_model_governance", "attribution_dispute_resolution",
        "attribution_matching", "qbr_dispute_resolution", "qbr_disputes",
        "qbr_resolution", "marketing_pipeline_reconcile",
        "marketing_pipeline_reconciliation",
        "marketing_pipeline_system_match", "marketing_reconciliation"]),

    ("P-RO-06", "Clari-Salesforce sync 99.4% deal-state match", [
        r"Clari", r"Salesforce sync", r"99\.4",
        r"Clari[- ]Salesforce", r"deal[- ]state match",
        r"Clari[- ]?Salesforce sync", r"Clari/SFDC", r"99\.4%",
    ], ["clari_sync", "clari_salesforce_sync", "clari_sfdc_sync",
        "clari_sfdc_sync_match", "deal_state_match", "system_sync_reliability"]),

    ("P-RO-07", "Stage 3 conversion 32% to 47% after gate refresh", [
        r"Stage 3 conversion", r"gate refresh", r"32%.*47%",
        r"47%.*gate", r"Stage 3.*47", r"Stage[- ]3 conversion rate",
        r"gate definition", r"Stage 3 gate",
    ], ["stage_3_conversion", "stage_3_gate_conversion",
        "stage_3_gate_refresh", "gate_refresh", "gate_definition",
        "gate_definition_refresh", "gate_enforcement", "stage_conversion",
        "stage_conversion_improvement", "stage_4_gate_enforcement",
        "stage_gate_requirements"]),

    ("P-RO-08", "Six redundant dashboards retired", [
        r"Six redundant dashboards", r"dashboard.*retired",
        r"6 dashboards", r"dashboard.*consolidat",
        r"dashboards.*retired", r"redundant dashboard",
        r"Six.*dashboards", r"6 redundant dashboards",
    ], ["dashboard_consolidation", "admin_hours", "admin_hours_cleared",
        "admin_hours_reclaimed", "admin_efficiency",
        "automation_time_savings"]),

    ("P-RO-09", "Lead routing exception rate 12% to 1.8%", [
        r"lead routing", r"routing exception", r"1\.8%",
        r"12%.*1\.8", r"routing.*exception",
        r"Lead routing exception rate", r"Routing.*1\.8",
    ], ["lead_routing", "lead_routing_exception", "lead_routing_exceptions",
        "lead_routing_optimization", "exception_rate", "routing_exception_rate",
        "mid_market_routing", "mid_market_concentration", "mid_market_segment",
        "mid_market_territory", "territory_exceptions",
        "territory_rule_consolidation", "territory_rule_simplification",
        "territory_rules", "rule_consolidation", "manual_triage",
        "manual_triage_elimination", "manual_triage_replacement"]),

    ("P-RO-10", "Stage 4 mandatory fields 100% completion across 60 deals", [
        r"Stage 4 mandatory", r"mandatory field.*100",
        r"100% completion", r"60 deals.*mandatory",
        r"Stage[- ]4 mandatory fields", r"mandatory fields.*100%",
    ], ["stage_4_fields", "stage_4_mandatory_fields", "mandatory_fields",
        "mandatory_field_completion", "field_completion",
        "field_completion_rate", "data_completion", "data_completeness",
        "data_quality_lift"]),

    ("P-RO-11", "RevOps in all 14 deal review calls", [
        r"RevOps deal review", r"14 of 14", r"RevOps.*attend",
        r"deal review attendance", r"RevOps.*14",
        r"RevOps attendance", r"deal review.*RevOps",
    ], ["deal_review_attendance", "deal_review", "revops_attendance",
        "revops_attendance_rate", "revops_review_attendance",
        "forecast_call_attendance"]),

    ("P-RO-12", "Account dedup 1320 to 1290", [
        r"account dedup", r"1,320 to 1,290", r"1320.*1290",
        r"duplicate.*record", r"deduplication",
        r"Account deduplication", r"dedup.*active",
        r"1,?320.*1,?290",
    ], ["account_dedup", "account_deduplication", "account_dedup_results",
        "active_account_count", "active_count", "duplicate_records"]),

    ("P-RO-13", "Wednesday forecast call 28 min vs 90 min baseline", [
        r"Wednesday forecast", r"28 minutes?.*90", r"90[- ]minute baseline",
        r"forecast call.*28", r"28 minutes?",
        r"Wednesday forecast call", r"forecast call duration",
    ], ["forecast_call_duration", "pipeline_prep_automation",
        "tuesday_pipeline_prep", "tuesday_pipeline_prep_automation",
        "pipeline_health_automation", "forecast_efficiency"]),

    ("P-RO-14", "Q2 QBR locks 5 of 7 process changes", [
        r"Q2 QBR", r"5 of 7.*process", r"QBR.*process change",
        r"process changes.*locked", r"Q2 QBR locks",
        r"QBR process changes", r"5.*7 proposed process",
    ], ["q2_qbr", "qbr_governance_outcomes", "qbr_process_changes",
        "qbr_process_locks", "process_changes_locked",
        "process_change_deployment", "production_deployment",
        "production_deployment_status"]),

    ("P-RO-15", "MQL-to-SQL transitions 73% under validated automation", [
        r"MQL[- ]to[- ]SQL", r"73%.*automation",
        r"MQL.*SQL.*automation", r"lifecycle automation",
        r"MQL[- ]to[- ]SQL transitions", r"validated automation",
    ], ["mql_sql_automation", "mql_sql_automation_rate", "mql_sql_handoff",
        "handoff_timing", "handoff_timing_median", "lifecycle_governance",
        "lifecycle_governance_automation"]),
]


# Customer Advocate pattern detectors (P-CA-01..15) for Phase 2.24.
# Source: scripts/eval/generate_dataset.py canonical P-CA anchors (lines ~3591-3737)
# and the cluster mapping in relevance_engine.py (lines ~1485-1490).
CA_PATTERNS = [
    ("P-CA-01", "Multi-thread depth (book-wide, 4+ contacts)", [
        r"multi[- ]thread depth", r"4[+] contacts", r"thread depth.*book",
        r"multi[- ]thread.*depth", r"Multi[- ]thread contact depth",
        r"thread depth doubled",
    ], ["multi_thread_depth", "multi_threading", "contact_depth",
        "contact_engagement", "contact_depth_correlation",
        "contact_count_win_rates"]),

    ("P-CA-02", "Champion re-engagement events", [
        r"Champion re[- ]?engage", r"champion reengagement",
        r"champion.*green health", r"Champion.*health",
        r"re[- ]engagement events.*green",
    ], ["champion_reengagement", "health_score_recovery"]),

    ("P-CA-03", "Stakeholder map freshness (strategic tier)", [
        r"stakeholder map", r"strategic[- ]tier.*84", r"stakeholder maps.*current",
        r"Strategic[- ]tier stakeholder", r"stakeholder map freshness",
        r"Fresh stakeholder maps",
    ], ["stakeholder_map_freshness", "stakeholder_map_currency",
        "stakeholder_map_correlation", "stakeholder_freshness_correlation",
        "strategic_tier", "strategic_coverage"]),

    ("P-CA-04", "Outreach coverage (14-day window)", [
        r"outreach coverage", r"14[- ]day.*outreach",
        r"two[- ]week outreach", r"outreach.*two weeks",
        r"Two[- ]week outreach coverage",
    ], ["outreach_coverage", "csm_interaction_frequency",
        "csm_interactions", "interaction_frequency"]),

    ("P-CA-05", "Q3 renewal pipeline + executive engagement 78%", [
        r"Q3 renewal pipeline", r"Q3.*renewal.*executive",
        r"78%.*executive sponsor", r"Q3 renewal",
        r"Q3 renewal pipeline carries", r"executive sponsor engagement",
    ], ["q3_renewal_pipeline", "q3_pipeline_coverage", "q3_renewal_value",
        "executive_engagement", "executive_engagement_correlation",
        "renewal_executive_engagement", "renewal_pipeline"]),

    ("P-CA-06", "Q2 early-renewal pull-forward $420K", [
        r"early[- ]renewal pull[- ]forward", r"early renewal",
        r"\$420K", r"pull[- ]forward.*Q2", r"pull-forward",
        r"Early[- ]renewal pull[- ]forward",
    ], ["early_renewal_pullforward", "early_renewals",
        "early_renewal_conversion", "renewal_close_rates",
        "health_score_correlation"]),

    ("P-CA-07", "Mid-market GRR Q2 vs Q1 with ICP breakdown", [
        r"mid[- ]market.*GRR", r"mid[- ]market segment GRR",
        r"94%.*GRR", r"GRR.*94", r"mid-market.*GRR",
        r"GRR climbed",
    ], ["mid_market_grr", "icp_alignment", "icp_alignment_impact"]),

    ("P-CA-08", "Lighthouse executive QBR stakeholder expansion", [
        r"Lighthouse", r"Lighthouse buying committee", r"Lighthouse QBR",
        r"buying committee expanded.*Lighthouse",
        r"Lighthouse.*committee", r"buying committee expanded from 3 to 6",
    ], ["lighthouse_qbr", "lighthouse_committee_expansion",
        "buying_committee_expansion", "committee_expansion",
        "committee_growth_correlation"]),

    ("P-CA-09", "Feature adoption ceiling — 7 accounts, $290K", [
        r"feature[- ]adoption ceiling", r"adoption ceiling",
        r"7 accounts.*feature[- ]adoption", r"\$290K",
        r"feature-adoption ceiling",
    ], ["feature_adoption_ceiling", "expansion_potential",
        "expansion_track_coverage", "expansion_track_conversion",
        "expansion_track_correlation", "expansion_threshold_coverage",
        "expansion_tracks", "activation_threshold_correlation"]),

    ("P-CA-10", "5+ contact multi-thread depth (12 accounts)", [
        r"5[- ]plus engaged", r"5[+] engaged contacts",
        r"12 accounts.*5", r"expansion.*5[+]",
        r"5-plus engaged contacts",
    ], ["multi_thread_expansion", "expansion_multi_thread",
        "expansion_multi_threading", "expansion_multithread",
        "expansion_depth_contacts", "expansion_correlation",
        "expansion_contact_correlation"]),

    ("P-CA-11", "Usage spike signals (8 accounts, 14-day window)", [
        r"usage spike", r"Usage spike", r"8 accounts.*14 days",
        r"usage.*spike.*14", r"Usage spike signals",
        r"Usage spikes preceding",
    ], ["usage_spike_signals", "usage_spikes", "usage_spike_correlation",
        "usage_spike_acceleration", "usage_spike_velocity",
        "usage_spike_conversion", "expansion_velocity",
        "expansion_close_speed"]),

    ("P-CA-12", "April QBR completion 88% strategic-tier", [
        r"QBR completion", r"value stor",
        r"strategic.*QBR.*88", r"88%.*April",
        r"Strategic QBR completion", r"value stories reach",
    ], ["qbr_completion", "qbr_completion_strategic",
        "qbr_completion_value", "qbr_value_correlation",
        "value_story_capture", "value_story_impact",
        "strategic_renewal_correlation"]),

    ("P-CA-13", "Q2 TTFV 41 days for onboardings", [
        r"time to first value", r"\bTTFV\b", r"41 days",
        r"first value.*compress", r"Time to first value",
        r"TTFV compressed",
    ], ["time_to_first_value", "time_to_value", "time_to_value_correlation",
        "ttfv_correlation", "onboarding_velocity", "onboarding_acceleration",
        "onboarding_impact", "onboarding_renewal_correlation"]),

    ("P-CA-14", "Sales-to-CS handoff 79% completeness", [
        r"handoff completeness", r"Sales[- ]to[- ]CS", r"handoff.*Sales",
        r"handoff context", r"79%.*Sales", r"Handoff completeness",
        r"complete handoff context",
    ], ["handoff_completeness", "crm_handoff_completeness", "handoff_impact",
        "sales_to_cs_bridge", "sales_to_cs", "sales_to_csm"]),

    ("P-CA-15", "Marketing-Customer reference + advocate pipeline", [
        r"case study", r"advocate pool", r"Case study advocate",
        r"5 to 11.*advocate", r"reference.*pipeline",
        r"Case study advocate pool", r"named accounts",
    ], ["advocate_pool", "advocate_pipeline", "case_study_pipeline",
        "case_study_commits", "reference_commitments", "reference_willingness"]),
]


# Customer Operator pattern detectors (P-CO-01..15) for Phase 2.27.
# Source: scripts/eval/generate_dataset.py canonical P-CO anchors (lines ~3755-3924)
# and the cluster mapping in relevance_engine.py (lines ~1677-1682).
CO_PATTERNS = [
    ("P-CO-01", "Health score model AUC 0.81, third quarter of lift", [
        r"\bAUC\b", r"0\.81", r"health.*score.*model",
        r"Health score model.*AUC", r"0\.81 AUC",
        r"three.*straight quarter", r"third.*quarter.*lift",
    ], ["health_score_auc", "auc_improvement_cycle", "auc_trajectory",
        "model_iteration_success", "quarterly_model_performance",
        "health_score_correlation"]),

    ("P-CO-02", "312 playbooks completed end-to-end in 30 days", [
        r"312 playbook", r"playbook.*30 days", r"playbooks completed",
        r"playbook.*end[- ]to[- ]end", r"312 playbooks",
        r"playbook completions",
    ], ["playbook_completions", "playbook_completion", "playbook_baseline",
        "playbook_completion_attribution", "playbook_governance",
        "playbook_effectiveness", "completion_count"]),

    ("P-CO-03", "Real-time product telemetry goes live", [
        r"real[- ]time.*telemetry", r"real-time product telemetry",
        r"Mixpanel", r"telemetry.*live", r"real-time telemetry",
        r"Real[- ]time.*telemetry", r"telemetry.*signals.*minutes",
    ], ["real_time_telemetry", "real_time_processing",
        "real_time_integration", "mixpanel_sync_timing",
        "telemetry_latency", "telemetry_sync", "telemetry_sync_latency",
        "telemetry_sync_upgrade", "signal_response_time", "signal_latency",
        "signal_window_compression", "signal_timing"]),

    ("P-CO-04", "47 accounts reclassified Mid-Touch to High-Touch", [
        r"47 accounts", r"mid[- ]touch.*high[- ]touch",
        r"Coverage tier", r"47.*reclassif", r"high[- ]touch based on",
        r"Coverage tier refresh", r"Coverage tier realignment",
        r"realignment moves 47",
    ], ["account_reclassification", "coverage_tier_realignment",
        "coverage_tier_refresh", "coverage_tiers",
        "coverage_refresh_timeline", "tier_realignment",
        "tier_reclassification", "behavior_based_segmentation",
        "behavioral_segmentation", "segmentation_recalibration",
        "segmentation_refresh", "segmentation_calibration",
        "data_driven_segmentation", "tier_accuracy", "tier_performance"]),

    ("P-CO-05", "Likelihood-to-renew shadow production model", [
        r"Likelihood[- ]to[- ]renew", r"shadow production",
        r"likelihood-to-renew", r"shadow model",
        r"Shadow production setup", r"Shadow.*production",
    ], ["likelihood_to_renew", "shadow_model", "shadow_model_production",
        "shadow_model_deployment", "shadow_production",
        "shadow_production_model", "parallel_prediction",
        "parallel_prediction_streams", "parallel_scoring",
        "parallel_validation", "model_comparison", "model_correlation",
        "model_validation", "model_development",
        "scoring_approach_comparison", "model_architecture_comparison",
        "model_enrichment"]),

    ("P-CO-06", "Salesforce-to-CS sync uptime 99.7%", [
        r"Salesforce.*99\.7", r"99\.7% uptime",
        r"Salesforce[- ]to[- ]CS sync", r"sync uptime", r"99\.7%",
        r"Salesforce-to-CS sync",
    ], ["salesforce_sync", "salesforce_sync_uptime", "sync_uptime",
        "signal_reliability", "data_pipeline_reliability",
        "data_reliability"]),

    ("P-CO-07", "Handoff data completeness 84% across Q2 deals", [
        r"Handoff data complete", r"84%.*Q2 deals",
        r"field.*populat.*close", r"Handoff completeness.*84",
        r"Handoff data completeness", r"24 Q2 deals",
    ], ["handoff_data_completeness", "handoff_completeness",
        "handoff_enrichment", "day_zero_health_accuracy",
        "day_zero_accuracy", "day_zero_health", "health_enrichment",
        "initial_scoring_accuracy"]),

    ("P-CO-08", "Tech stack consolidation, 40% bandwidth freed", [
        r"tool consolidation", r"CS tool", r"40%.*bandwidth",
        r"consolidat.*connector", r"tech stack consolidation",
        r"CS tool consolidation", r"connector maintenance",
    ], ["tool_consolidation", "tech_stack_consolidation",
        "connector_reduction", "admin_bandwidth",
        "admin_bandwidth_reallocation", "admin_capacity",
        "operational_efficiency"]),

    ("P-CO-09", "2026 Annual CS Benchmark drops next week", [
        r"Annual CS Benchmark", r"Annual Benchmark", r"April 30",
        r"2026 Annual", r"industry data.*year",
        r"2026 Annual CS Benchmark", r"benchmark.*April 30",
    ], ["annual_benchmark", "annual_benchmark_timing", "cs_benchmark_2026",
        "benchmark_calibration", "benchmark_comparison",
        "benchmark_performance", "benchmark_refresh"]),

    ("P-CO-10", "Health score override rate decline (24% to 11%)", [
        r"Override rate", r"override.*decline", r"11% from 24%",
        r"CSM.*trust", r"24% peak", r"override rate",
        r"Override rate trajectory", r"3-quarter decline",
    ], ["override_rate", "override_rate_decline", "override_rate_trajectory",
        "override_rate_trend", "health_score_overrides", "csm_model_trust",
        "csm_trust_metrics", "csm_trust_pattern", "override_auc_correlation",
        "model_trust", "health_score_trust"]),

    ("P-CO-11", "CS platform shipped completion attribution feature", [
        r"Completion attribution", r"playbook outcome measurement",
        r"completion attribution feature", r"CS platform.*ship",
        r"Completion attribution unlocks",
    ], ["completion_attribution", "completion_attribution_feature",
        "playbook_completion_attribution", "platform_features",
        "platform_capability", "measurement_capability",
        "platform_attribution"]),

    ("P-CO-12", "Mid-market NRR 117% third consecutive quarter above benchmark", [
        r"Mid[- ]market NRR", r"117%", r"NRR.*117",
        r"third consecutive quarter.*NRR", r"Mid[- ]market NRR holds",
        r"NRR holds at 117",
    ], ["mid_market_nrr", "nrr_midmarket", "benchmark_performance",
        "benchmark_comparison"]),

    ("P-CO-13", "Onboarding completion 89% Q1 cohort of 9 accounts", [
        r"Onboarding completion.*89", r"89%.*Q1",
        r"Onboarding completion rate", r"Q1 cohort.*9 accounts",
        r"89%.*onboarding", r"Onboarding completion sits",
    ], ["onboarding_completion", "onboarding_completion_rate",
        "activation_signals", "retention_correlation"]),

    ("P-CO-14", "BigQuery feature-usage pipeline approved", [
        r"BigQuery", r"feature[- ]usage pipeline",
        r"BigQuery.*approve", r"feature[- ]usage.*pipeline",
        r"BigQuery feature-usage", r"login[- ]frequency proxy",
    ], ["bigquery_pipeline", "bigquery_pipeline_approval",
        "feature_usage_pipeline", "feature_usage_signals",
        "feature_usage_upgrade", "proxy_signal_replacement",
        "proxy_signals", "proxy_elimination", "proxy_replacement_timeline",
        "data_pipeline", "data_infrastructure", "data_quality",
        "dual_infrastructure_improvement", "parallel_infrastructure_improvement",
        "signal_quality", "signal_quality_improvement", "usage_data_upgrade"]),

    ("P-CO-15", "Custom Permissions launch traces to Beacon early renewal", [
        r"Custom Permissions", r"Beacon Logistics",
        r"Custom Permissions.*Beacon", r"feature.*renewal trace",
        r"Beacon.*early renewal", r"Custom Permissions launch",
    ], ["cross_entity_attribution", "feature_to_renewal_trace",
        "feature_launch_attribution", "feature_renewal",
        "attribution_demonstration", "product_attribution",
        "product_event_to_renewal", "platform_update_april_18",
        "production_validation"]),
]


# Customer Technician pattern detectors (P-CT-01..15) for Phase 2.30.
# Source: scripts/eval/generate_dataset.py canonical P-CT anchors (lines ~4154-4322)
# and the cluster mapping in relevance_engine.py (lines ~1973-1976).
CT_PATTERNS = [
    ("P-CT-01", "48-hour integration cohort 2.3x 90-day retention", [
        r"48[- ]hour", r"2\.3x.*retain",
        r"48 hour integration", r"48-hour integration",
        r"48[- ]hour integration accounts",
    ], ["48_hour_integration", "ttfv_48hr_cohort", "ttfv_cohort",
        "q1_integration_timing", "q1_integration_retention",
        "q1_implementation_cohort", "q1_cohort_analysis",
        "q1_vs_q4_comparison", "q1_vs_q4_integration", "q4_baseline",
        "integration_speed", "integration_speed_retention",
        "integration_timing_correlation", "early_integration_pattern",
        "early_integration_retention", "retention_predictor",
        "retention_comparison", "cohort_retention_analysis"]),

    ("P-CT-02", "Mid-market 6 days ahead of plan", [
        r"Mid[- ]market implement.*6 days", r"6 days ahead",
        r"mid[- ]market.*go[- ]live.*ahead", r"go-live 6 days",
        r"6 days ahead of plan", r"mid[- ]market.*cleared go[- ]live",
    ], ["mm_golive_velocity", "midmarket_golive_velocity",
        "midmarket_velocity", "segment_velocity", "velocity_improvement"]),

    ("P-CT-03", "71% integration milestone within 10 days", [
        r"integration milestone", r"71%.*10 days",
        r"milestone.*71", r"Data integration milestone",
        r"71% within 10 days", r"integration milestone completion",
    ], ["integration_milestone_completion", "integration_milestone_q1",
        "integration_milestone_q4", "integration_milestone_rate",
        "milestone_completion", "data_integration_milestone"]),

    ("P-CT-04", "3-user activation by Day 30 = 3x retention", [
        r"3[- ]user activation", r"Day 30",
        r"3x.*retain.*Day 30", r"3 user.*Day 30",
        r"3-user activation", r"multi[- ]user activation.*Day 30",
        r"3 users.*Day 30",
    ], ["multiuser_activation", "multiuser_activation_day30",
        "multiuser_day30", "multiuser_correlation",
        "multiuser_retention_advantage", "multiuser_retention_correlation",
        "day30_activation_rate", "day30_threshold", "activation_threshold"]),

    ("P-CT-05", "Enterprise config sign-off Day 11 (template launch)", [
        r"Day 11", r"enterprise sign[- ]off",
        r"Configuration template.*sign[- ]off",
        r"Enterprise.*Day 11", r"config sign-off",
        r"Configuration template moved", r"enterprise.*config.*sign[- ]off",
    ], ["ent_config_signoff", "enterprise_config_signoff",
        "enterprise_signoff", "enterprise_signoff_velocity",
        "enterprise_config_acceleration", "enterprise_timeline_compression",
        "enterprise_golives_q1", "config_template_impact",
        "config_template_launch", "configuration_template"]),

    ("P-CT-06", "Pre-close use-case capture shortens go-live by 12 days", [
        r"use[- ]case capture", r"\b12 days\b",
        r"use case.*go[- ]live.*12", r"Complete use[- ]case",
        r"use-case capture", r"use[- ]case capture shortened",
    ], ["usecase_capture", "usecase_capture_impact", "usecase_capture_velocity",
        "usecase_documentation_impact", "golive_correlation"]),

    ("P-CT-07", "Mid-market implementation NPS 41 to 59", [
        r"implementation NPS", r"NPS.*59", r"59.*NPS",
        r"18 points.*NPS", r"Mid[- ]market.*NPS",
        r"NPS jumped 18", r"NPS jumped",
    ], ["midmarket_implementation_nps", "mm_implementation_nps",
        "midmarket_nps", "implementation_nps", "implementation_satisfaction",
        "midmarket_satisfaction", "segment_nps_record",
        "nps_historical_record"]),

    ("P-CT-08", "Tier-2 activation 78% within 14 days", [
        r"Tier[- ]2 activation", r"78%.*14 days",
        r"Tier-2 activation", r"Tier 2.*78",
        r"Tier[- ]2 reached 78", r"Tier[- ]2.*78%",
    ], ["tier2_activation", "tier2_activation_q1", "tier2_activation_q4",
        "tier2_activation_rate", "activation_improvement"]),

    ("P-CT-09", "Product-blocker resolution 9 days to 4 days", [
        r"product[- ]blocker", r"Product[- ]blocker resolution",
        r"9 days to 4", r"blocker.*4 days",
        r"Product-blocker", r"product[- ]blocker resolution",
        r"blocker resolution.*4",
    ], ["product_blocker_resolution", "blocker_resolution",
        "blocker_resolution_time", "engineering_velocity",
        "engineering_response", "engineering_response_time",
        "engineering_responsiveness", "engineering_support_volume"]),

    ("P-CT-10", "Onboarding checklist 22% to 34%", [
        r"checklist", r"Onboarding checklist", r"22%.*34%",
        r"checklist.*completion", r"checklist completion",
        r"Onboarding checklist completion",
    ], ["checklist_completion", "checklist_completion_lift",
        "checklist_completion_vs_baseline"]),

    ("P-CT-11", "64% kickoffs with 3+ named stakeholders", [
        r"kickoff", r"64%.*kickoff", r"3[+] named",
        r"Kickoff stakeholder", r"stakeholder breadth",
        r"Kickoff stakeholder breadth", r"3-plus named",
        r"Multi[- ]stakeholder kickoff",
    ], ["stakeholder_breadth", "stakeholder_breadth_q1",
        "stakeholder_breadth_prior", "kickoff_coverage", "kickoff_planning",
        "stakeholder_activation", "stakeholder_expansion",
        "stakeholder_performance", "multi_stakeholder_activation",
        "breadth_correlation"]),

    ("P-CT-12", "92% enterprise handoff brief acknowledged in 48 hours", [
        r"handoff brief", r"92%.*48 hour", r"Enterprise handoff brief",
        r"handoff.*acknowledg", r"Enterprise.*handoff.*92",
        r"Enterprise handoff briefs acknowledged", r"92% acknowledg",
    ], ["enterprise_handoff_acknowledgment", "enterprise_handoff_quality",
        "csm_acknowledgment", "csm_acknowledgment_rate",
        "csm_handoff_brief", "csm_handoff_quality", "handoff_brief",
        "handoff_brief_ack", "handoff_brief_completion", "handoff_quality",
        "sales_handoff_quality"]),

    ("P-CT-13", "Implementation support response 6 hours to 2.4 hours", [
        r"support response", r"2\.4 hours", r"Implementation support",
        r"support.*compress", r"support response.*compress",
        r"Implementation support response", r"2\.4 hours median",
    ], ["implementation_support_response", "support_response",
        "support_response_time", "queue_optimization", "dedicated_queue",
        "dedicated_queue_impact", "dedicated_queue_launch",
        "cross_functional", "cross_functional_response"]),

    ("P-CT-14", "Healthcare vertical 38-day median (13 days faster)", [
        r"Healthcare vertical", r"\bHealthcare\b",
        r"Healthcare.*38", r"Healthcare implement",
        r"13 days faster.*Healthcare", r"Healthcare.*portfolio",
        r"Healthcare vertical implementations",
    ], ["healthcare_vertical", "healthcare_vertical_median",
        "healthcare_vertical_pace", "healthcare_velocity",
        "healthcare_segment_cycle", "healthcare_segment_timing",
        "healthcare_golive_median"]),

    ("P-CT-15", "Sandbox launch March 12 lifted Tier-1 by 19pp", [
        r"sandbox", r"Self[- ]serve sandbox",
        r"Tier[- ]1 activation 19", r"19 percentage points",
        r"self-serve sandbox", r"March 12",
        r"Self[- ]serve sandbox lifted",
    ], ["sandbox_launch", "sandbox_launch_impact",
        "sandbox_activation_lift", "sandbox_tier1_lift",
        "sandbox_tier1_impact", "sandbox_preexploration",
        "self_serve_exploration", "tier1_activation",
        "tier1_activation_jump", "tier1_activation_lift",
        "tier1_baseline_cohort", "tier1_pre_sandbox", "tier1_sandbox_lift"]),
]


_ARCHETYPE_TABLE = {
    "revenue": (PATTERNS, "Revenue Leader", "revenue", "Phase 2.5"),
    "customer": (CL_PATTERNS, "Customer Leader", "customer", "Phase 2.6"),
    "marketing_strategist": (MS_PATTERNS, "Marketing Strategist", "marketing_strategist", "Phase 2.9"),
    "marketing_builder": (MB_PATTERNS, "Marketing Builder", "marketing_builder", "Phase 2.11"),
    "revenue_generator": (RG_PATTERNS, "Revenue Generator", "rg", "Phase 2.15"),
    "revenue_developer": (RD_PATTERNS, "Revenue Developer", "revenue_developer", "Phase 2.18"),
    "revenue_operator": (RO_PATTERNS, "Revenue Operator", "ro", "Phase 2.21"),
    "customer_advocate": (CA_PATTERNS, "Customer Advocate", "ca", "Phase 2.24"),
    "customer_operator": (CO_PATTERNS, "Customer Operator", "customer_operator", "Phase 2.27"),
    "customer_technician": (CT_PATTERNS, "Customer Technician", "customer_technician", "Phase 2.30"),
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
