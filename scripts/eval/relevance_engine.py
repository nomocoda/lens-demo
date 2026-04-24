#!/usr/bin/env python3
"""Relevance Engine MVP for Stage 1 eval.

Consumes the Atlas SaaS synthetic dataset at scripts/eval/output/ and emits
Story Cards to scripts/eval/generated_cards.json via Claude, using the locked
prompt stack from worker.js.

Data strategy (Option A per handoff): pre-compute structured summaries over
the 15 seeded patterns and feed them in place of COMPANY_DATA. A future
Option B would expose dataset query tools and let the model discover signals
through tool use — see OPTION_B_NOTE below.

Prompt stack (order matches worker.js buildCardSystemPrompt):
  1.  PERSONA                         (data/persona.md)
  2.  MARKETING_LEADER_BRIEF          (data/marketing-leader-brief.md)
  3.  IDENTITY_GUARDRAIL              (worker.js)
  4.  DATA_BOUNDARY + dataset summary (replaces COMPANY_DATA)
  5.  FABRICATION_GUARD               (worker.js)
  6.  ROLE_SCOPING                    (worker.js)
  7.  CARD_SELECTION_ROLE_SCOPED      (worker.js)
  8.  SIGNAL_VS_REPORT_GUARD          (worker.js)
  9.  COMPOSITION_COMPLETENESS_GUARD  (worker.js, adapted schema)
 10.  FORWARD_FRAMING_GUARD           (worker.js)
 11.  PEOPLE_NAMING_GUARD             (worker.js)
 12.  VOICE_BRIEF                     (data/voice-brief.md)  -- LAST BEFORE TASK
 13.  Eval card generation instructions
 14.  OUTPUT_HYGIENE_GUARD (adapted to eval schema)

FRESHNESS_GUARD is intentionally dropped. It rotates across generations using
marquee-signal letters A-H from the production atlas-saas.md, which do not
exist in this synthetic dataset. For a single eval generation the rotation
mechanism is not needed.

Local files (data/*.md, worker.js) are the source of truth. They were synced
from Notion on 2026-04-24 and are what production ships to Claude. Pulling
from Notion here would risk drift between eval and production.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent.parent.parent  # lens-demo/
EVAL_DIR = ROOT / "scripts" / "eval"
DATA_DIR = ROOT / "data"
WORKER_JS = ROOT / "worker.js"

TODAY = date(2026, 4, 24)

# Matches production /cards route in worker.js.
DEFAULT_MODEL = "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# worker.js constant extraction
# ---------------------------------------------------------------------------

def extract_js_template_const(source: str, name: str) -> str:
    """Extract the body of `const NAME = \`...\`;` from a JS source string.

    Handles escaped backticks (\\`) and escaped dollar signs (\\$) inside the
    template literal. Does not attempt full JS parsing — the guards in
    worker.js are plain template strings without embedded ${} interpolation.
    """
    marker = f"const {name} = `"
    start = source.find(marker)
    if start == -1:
        raise KeyError(f"const {name} not found in worker.js")
    i = start + len(marker)
    out_chars: List[str] = []
    while i < len(source):
        ch = source[i]
        if ch == "\\" and i + 1 < len(source):
            nxt = source[i + 1]
            if nxt in ("`", "$", "\\"):
                out_chars.append(nxt)
                i += 2
                continue
            out_chars.append(ch)
            i += 1
            continue
        if ch == "`":
            return "".join(out_chars)
        out_chars.append(ch)
        i += 1
    raise ValueError(f"const {name} body not terminated")


def load_worker_guards() -> Dict[str, str]:
    src = WORKER_JS.read_text()
    names = [
        "IDENTITY_GUARDRAIL",
        "DATA_BOUNDARY",
        "FABRICATION_GUARD",
        "ROLE_SCOPING",
        "CARD_SELECTION_ROLE_SCOPED",
        "SIGNAL_VS_REPORT_GUARD",
        "COMPOSITION_COMPLETENESS_GUARD",
        "FORWARD_FRAMING_GUARD",
        "PEOPLE_NAMING_GUARD",
    ]
    return {n: extract_js_template_const(src, n) for n in names}


# ---------------------------------------------------------------------------
# Dataset loading and summary computation
# ---------------------------------------------------------------------------

def load_dataset(output_dir: Path) -> Dict[str, list]:
    entities = [
        "companies", "contacts", "deals", "campaigns", "campaign_performance",
        "budget", "actual_spend", "engagement_events", "branded_search",
        "web_analytics", "mentions", "competitors", "analyst_mentions",
        "customer_reference_optins", "product_launches", "sdr_capacity",
    ]
    data: Dict[str, list] = {}
    for e in entities:
        p = output_dir / f"{e}.json"
        if not p.exists():
            raise FileNotFoundError(f"Missing dataset file: {p}")
        data[e] = json.loads(p.read_text())
    return data


def _mean(values) -> float:
    vs = list(values)
    return sum(vs) / len(vs) if vs else 0.0


def build_summary(ds: Dict[str, list]) -> str:
    """Compute a dense, factual snapshot of the Atlas SaaS dataset covering
    all 15 seeded patterns. Every number in this summary is grounded in the
    dataset — the model should never invent figures beyond these cuts.

    OPTION_B_NOTE: replace this fixed snapshot with a set of tool definitions
    that let Claude query the dataset on demand (by entity, segment, time
    window). That is the production shape. For Stage 1 MVP the snapshot is
    enough to prove the voice layer carries through.
    """
    deals = ds["deals"]
    companies = ds["companies"]
    contacts = ds["contacts"]
    campaigns = ds["campaigns"]
    by_co = {c["id"]: c for c in companies}

    def dtc(d: Dict) -> int:
        return (date.fromisoformat(d["close_date"]) - date.fromisoformat(d["create_date"])).days

    # Pattern windows (mirror generate_dataset.py constants)
    cw = (date(2026, 4, 20), date(2026, 4, 26))
    prior_11w = (date(2026, 2, 2), date(2026, 4, 19))
    last_60d = (date(2026, 2, 23), date(2026, 4, 24))
    q1 = (date(2026, 1, 1), date(2026, 3, 31))
    q2 = (date(2026, 4, 1), date(2026, 6, 30))
    q4_2025 = (date(2025, 10, 1), date(2025, 12, 31))
    ms_sources = {"paid_social", "paid_search", "content", "email", "events", "webinar", "nurture"}

    # P01 — marketing-sourced velocity
    cw_ms = [d for d in deals if d["is_won"] and d["lead_source"] in ms_sources
             and cw[0] <= date.fromisoformat(d["close_date"]) <= cw[1]]
    prior_ms = [d for d in deals if d["is_won"] and d["lead_source"] in ms_sources
                and prior_11w[0] <= date.fromisoformat(d["close_date"]) <= prior_11w[1]]
    cw_mm = sum(1 for d in cw_ms if d["segment"] == "mid-market")
    cw_dtc = _mean(dtc(d) for d in cw_ms)
    prior_dtc = _mean(dtc(d) for d in prior_ms)

    # P02 — April MM SQL count + ABM acceptance
    apr_start = date(2026, 4, 1)
    mm_ids = {c["id"] for c in companies if c["segment"] == "mid-market"}
    apr_mm_sqls = 0
    jfm_by_month: Dict[str, int] = {"jan": 0, "feb": 0, "mar": 0}
    abm_accepted = abm_total = non_abm_accepted = non_abm_total = 0
    for co in contacts:
        if co.get("company_id") not in mm_ids:
            continue
        sqld = co.get("became_sql_date")
        if not sqld:
            continue
        d = date.fromisoformat(sqld)
        if d >= apr_start and d <= TODAY:
            apr_mm_sqls += 1
        elif d.year == 2026 and d.month in (1, 2, 3):
            jfm_by_month[["", "jan", "feb", "mar"][d.month]] += 1
        if d >= apr_start and d <= TODAY:
            accepted = bool(co.get("sql_accepted"))
            if co.get("is_abm"):
                abm_total += 1
                abm_accepted += 1 if accepted else 0
            else:
                non_abm_total += 1
                non_abm_accepted += 1 if accepted else 0
    jfm_avg = sum(jfm_by_month.values()) / 3 if jfm_by_month else 0
    abm_rate = abm_accepted / abm_total if abm_total else 0
    non_abm_rate = non_abm_accepted / non_abm_total if non_abm_total else 0

    # P03 — enterprise win rate Q2 vs trailing 4Q
    ent_q2 = [d for d in deals if d["segment"] == "enterprise" and d["is_closed"]
              and q2[0] <= date.fromisoformat(d["close_date"]) <= q2[1]]
    ent_q2_wins = [d for d in ent_q2 if d["is_won"]]
    ent_trail_start = date(2025, 4, 1)
    ent_trail_end = date(2026, 3, 31)
    ent_trail = [d for d in deals if d["segment"] == "enterprise" and d["is_closed"]
                 and ent_trail_start <= date.fromisoformat(d["close_date"]) <= ent_trail_end]
    ent_trail_wins = [d for d in ent_trail if d["is_won"]]
    ent_q2_wr = len(ent_q2_wins) / len(ent_q2) if ent_q2 else 0
    ent_trail_wr = len(ent_trail_wins) / len(ent_trail) if ent_trail else 0
    ent_q2_avg = _mean(d["amount"] for d in ent_q2_wins)
    ent_trail_avg = _mean(d["amount"] for d in ent_trail_wins)

    # P04 — channel flip (paid_social vs paid_search, Q1 and Q2)
    def pipeline_sum(channel: str, window: Tuple[date, date]) -> int:
        qs, qe = window
        return sum(d["amount"] for d in deals
                   if d["lead_source"] == channel
                   and qs <= date.fromisoformat(d["create_date"]) <= qe)
    q2_social = pipeline_sum("paid_social", q2)
    q2_search = pipeline_sum("paid_search", q2)
    q1_social = pipeline_sum("paid_social", q1)
    q1_search = pipeline_sum("paid_search", q1)

    # P05 — Q2 digital_ads plan vs actual + reallocation
    budget = ds["budget"]
    actual_spend = ds["actual_spend"]
    q2_ads_plan = sum(b["planned_amount"] for b in budget
                      if b.get("category") == "digital_ads" and b.get("quarter") == "Q2_2026")
    q2_ads_actual_apr23 = sum(r["amount"] for r in actual_spend
                              if r["category"] == "digital_ads"
                              and q2[0] <= date.fromisoformat(r["date"]) <= date(2026, 4, 23))
    realloc = [b for b in budget if b.get("quarter") == "Q2_2026"
               and b.get("category") in ("events_saas_connect", "events_signal_summit")]
    realloc_total = sum(b["planned_amount"] for b in realloc)

    # P06 — Q1 event velocity vs Q4 event velocity
    q1_event = [d for d in deals if d["lead_source"] == "events" and d["is_won"]
                and q1[0] <= date.fromisoformat(d["create_date"]) <= q1[1]]
    q4_event = [d for d in deals if d["lead_source"] == "events" and d["is_won"]
                and q4_2025[0] <= date.fromisoformat(d["create_date"]) <= q4_2025[1]]
    q1_event_dtc = _mean(dtc(d) for d in q1_event)
    q4_event_dtc = _mean(dtc(d) for d in q4_event)
    saas_connect_ids = {c["id"] for c in campaigns if "SaaS Connect" in c.get("name", "")}
    saas_connect_q1_wins = [d for d in q1_event if d.get("campaign_source_id") in saas_connect_ids]

    # P07 — branded search 6-week WoW streak
    bs = sorted(ds["branded_search"], key=lambda r: r["date"])
    streak_end = date(2026, 4, 19)
    anchor_dates = [date(2026, 3, 8), date(2026, 3, 15), date(2026, 3, 22),
                    date(2026, 3, 29), date(2026, 4, 5), date(2026, 4, 12), streak_end]
    bs_by_date = {r["date"]: r["search_volume"] for r in bs}
    streak_values = [bs_by_date.get(d.isoformat()) for d in anchor_dates]
    streak_values_int = [v for v in streak_values if isinstance(v, int)]
    wow_increases = 0
    for i in range(1, len(streak_values_int)):
        if streak_values_int[i] > streak_values_int[i - 1]:
            wow_increases += 1
    cum_growth = 0.0
    if len(streak_values_int) == 7 and streak_values_int[0]:
        cum_growth = (streak_values_int[-1] - streak_values_int[0]) / streak_values_int[0]

    # P08 — share of voice (April mentions)
    atlas_april = sum(m["count"] if "count" in m else 1 for m in ds["mentions"]
                      if m.get("entity") == "Atlas SaaS"
                      and apr_start <= date.fromisoformat(m["date"]) <= TODAY)
    if not atlas_april:
        atlas_april = sum(1 for m in ds["mentions"]
                          if m.get("entity") == "Atlas SaaS"
                          and apr_start <= date.fromisoformat(m["date"]) <= TODAY)
    comp_counts: Dict[str, int] = Counter()
    for m in ds["mentions"]:
        ent = m.get("entity")
        if not ent or ent == "Atlas SaaS":
            continue
        if apr_start <= date.fromisoformat(m["date"]) <= TODAY:
            comp_counts[ent] += 1
    top_comp = comp_counts.most_common(1)[0] if comp_counts else ("(none)", 0)

    # P09 — direct traffic crossed organic this month
    wa = ds["web_analytics"]
    apr_traffic: Dict[str, int] = defaultdict(int)
    for r in wa:
        d = date.fromisoformat(r["date"])
        if apr_start <= d <= TODAY:
            apr_traffic[r["channel"]] += r.get("sessions", 0)
    apr_total = sum(apr_traffic.values())
    direct_share = apr_traffic.get("direct", 0) / apr_total if apr_total else 0
    organic_share = apr_traffic.get("organic_search", 0) / apr_total if apr_total else 0
    # cumulative crossover date
    by_day: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in wa:
        if apr_start <= date.fromisoformat(r["date"]) <= TODAY:
            by_day[r["date"]][r["channel"]] += r.get("sessions", 0)
    direct_cum = organic_cum = 0
    crossover: Optional[str] = None
    for d in sorted(by_day.keys()):
        direct_cum += by_day[d].get("direct", 0)
        organic_cum += by_day[d].get("organic_search", 0)
        if crossover is None and direct_cum > organic_cum:
            crossover = d

    # P10 — analyst mentions last 14 vs prior 30
    am = ds["analyst_mentions"]
    last14_start = TODAY - __import__("datetime").timedelta(days=14)
    prior30_start = last14_start - __import__("datetime").timedelta(days=30)
    last14 = [m for m in am if last14_start <= date.fromisoformat(m["date"]) <= TODAY]
    prior30 = [m for m in am if prior30_start <= date.fromisoformat(m["date"]) < last14_start]
    firm_counts = Counter(m["analyst_firm"] for m in last14)
    top_firms = firm_counts.most_common(3)

    # P11 — last 60 day MM concentration (fintech + Snowflake/dbt)
    mm_60d = [d for d in deals if d["segment"] == "mid-market" and d["is_won"]
              and last_60d[0] <= date.fromisoformat(d["close_date"]) <= last_60d[1]]
    fintech_n = sum(1 for d in mm_60d if by_co[d["company_id"]].get("industry") == "fintech")
    stack_n = sum(1 for d in mm_60d
                  if {"Snowflake", "dbt"}.issubset(set(by_co[d["company_id"]].get("tech_stack", []))))

    # P12 — reference opt-ins by product line
    optins = ds["customer_reference_optins"]
    by_line: Dict[str, List] = defaultdict(list)
    for o in optins:
        by_line[o["product_line"]].append(bool(o.get("reference_willingness")))
    ref_rates = {pl: (sum(1 for v in vs if v) / len(vs)) if vs else 0 for pl, vs in by_line.items()}

    # P13 — hot target accounts this week (5+ high-intent engagement events)
    ee = ds["engagement_events"]
    hi_per_co: Dict[str, int] = defaultdict(int)
    cw_start_iso = cw[0].isoformat()
    cw_end_iso = cw[1].isoformat()
    for e in ee:
        if cw_start_iso <= e["date"] <= cw_end_iso and e.get("intent_level") == "high":
            hi_per_co[e["company_id"]] += 1
    hot_target = [
        cid for cid in hi_per_co
        if hi_per_co[cid] >= 5 and by_co.get(cid, {}).get("is_target_account")
    ]
    named_target = [cid for cid in hot_target
                    if by_co[cid].get("target_list_name") == "Named Accounts"]

    # P14 — upcoming product launch + campaign status
    launches = ds["product_launches"]
    upcoming = sorted(
        [p for p in launches if date.fromisoformat(p["launch_date"]) >= TODAY],
        key=lambda p: p["launch_date"],
    )
    next_launch = upcoming[0] if upcoming else None
    launch_campaign = None
    if next_launch:
        for c in campaigns:
            if c.get("launch_id") == next_launch.get("id"):
                launch_campaign = c
                break

    # P15 — current-week SDR capacity vs inbound
    sdr = ds["sdr_capacity"]
    cw_row = next((r for r in sdr if r["week_ending_date"] == cw[1].isoformat()), None)

    # Assemble summary (markdown, dense, factual)
    lines: List[str] = []
    lines.append("ATLAS SAAS — COMPANY DATA SNAPSHOT (as of 2026-04-24)")
    lines.append("")
    lines.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. HubSpot is the system of record for marketing; Salesforce for pipeline; Mixpanel for product engagement; Google Analytics for web.")
    lines.append("")
    lines.append("# Deal velocity and win rate")
    lines.append(f"- Current week (Apr 20-26) marketing-sourced wins: n={len(cw_ms)}, {cw_mm} mid-market. Mean days to close: {cw_dtc:.1f}.")
    lines.append(f"- Prior 11 weeks (Feb 2 - Apr 19) marketing-sourced wins: n={len(prior_ms)}. Mean days to close: {prior_dtc:.1f}.")
    lines.append(f"- Q2 enterprise closed deals: n={len(ent_q2)}, wins={len(ent_q2_wins)}, win rate {ent_q2_wr*100:.2f}%, average won amount ${ent_q2_avg:,.0f}.")
    lines.append(f"- Trailing four quarters enterprise closed: n={len(ent_trail)}, wins={len(ent_trail_wins)}, win rate {ent_trail_wr*100:.2f}%, average won amount ${ent_trail_avg:,.0f}.")
    lines.append(f"- Q1 event-sourced wins (SaaS Connect + peer events): n={len(q1_event)}, mean days to close {q1_event_dtc:.1f}. SaaS Connect Q1 wins: {len(saas_connect_q1_wins)}.")
    lines.append(f"- Q4 2025 event-sourced wins: n={len(q4_event)}, mean days to close {q4_event_dtc:.1f}.")
    lines.append(f"- Last 60 day mid-market closed-wins: n={len(mm_60d)}. Fintech industry: {fintech_n}. Running Snowflake plus dbt: {stack_n}.")
    lines.append("")
    lines.append("# Lead volume and hand-off")
    lines.append(f"- April mid-market SQLs (month to date): {apr_mm_sqls}.")
    lines.append(f"- Jan/Feb/Mar mid-market SQLs monthly average: {jfm_avg:.0f} (Jan {jfm_by_month['jan']}, Feb {jfm_by_month['feb']}, Mar {jfm_by_month['mar']}).")
    lines.append(f"- April ABM acceptance rate (SDR-accepted / SQL-total): {abm_rate*100:.1f}% on {abm_total} ABM MQLs.")
    lines.append(f"- April non-ABM acceptance rate: {non_abm_rate*100:.1f}% on {non_abm_total} non-ABM MQLs.")
    lines.append("")
    lines.append("# Channels and paid spend")
    lines.append(f"- Q2 paid_social pipeline created: ${q2_social:,}. Q2 paid_search pipeline created: ${q2_search:,}.")
    lines.append(f"- Q1 paid_search pipeline created: ${q1_search:,}. Q1 paid_social pipeline created: ${q1_social:,}.")
    lines.append(f"- Q2 digital_ads planned spend: ${q2_ads_plan:,}. Actual through Apr 23: ${q2_ads_actual_apr23:,.0f}. Gap: ${q2_ads_plan - q2_ads_actual_apr23:,.0f}.")
    lines.append(f"- Q2 reallocation line items: {len(realloc)} ({', '.join(b['category'] for b in realloc)}) totaling ${realloc_total:,}.")
    lines.append("")
    lines.append("# Brand, mentions, and market")
    wow_pct = cum_growth * 100
    lines.append(f"- Branded search (weekly volumes): {', '.join(str(v) for v in streak_values_int)}. Weeks with week-over-week increase: {wow_increases} of {len(streak_values_int)-1}. Cumulative growth over the 6-week window ending Apr 19: {wow_pct:.1f}%.")
    lines.append(f"- April (through Apr 24) brand mentions: Atlas SaaS {atlas_april}. Top competitor: {top_comp[0]} {top_comp[1]}.")
    lines.append(f"- Analyst mentions: last 14 days n={len(last14)}. Prior 30 days n={len(prior30)}. Top firms last 14d: {', '.join(f'{f} ({c})' for f, c in top_firms)}.")
    lines.append("")
    lines.append("# Web traffic")
    lines.append(f"- April traffic share by channel: direct {direct_share*100:.1f}%, organic search {organic_share*100:.1f}%. Direct first crossed organic on a cumulative basis on {crossover}.")
    lines.append("")
    lines.append("# Customer reference and targets")
    ai = ref_rates.get("Atlas Insights", 0)
    aw = ref_rates.get("Atlas Workflow", 0)
    ac = ref_rates.get("Atlas Connect", 0)
    lines.append(f"- Reference opt-ins: Atlas Insights {ai*100:.1f}%, Atlas Workflow {aw*100:.1f}%, Atlas Connect {ac*100:.1f}%.")
    lines.append(f"- Current-week target accounts with 5+ high-intent events: n={len(hot_target)}. Of those, on the Named Accounts list: {len(named_target)}. (Target-list membership universe: {sum(1 for c in companies if c.get('is_target_account'))}.)")
    lines.append("")
    lines.append("# Product launches")
    if next_launch:
        cs = launch_campaign.get("status") if launch_campaign else "(no campaign found)"
        lines.append(f"- Next product launch: {next_launch['name']} on {next_launch['launch_date']}. Associated campaign status: {cs}. Calendar locks {TODAY.isoformat()}.")
    else:
        lines.append("- No product launch scheduled in the forward window.")
    lines.append("")
    lines.append("# SDR capacity")
    if cw_row:
        lines.append(f"- Current week (ending {cw_row['week_ending_date']}) SDR team inbound capacity: {cw_row['team_total_capacity']}. Inbound lead volume: {cw_row['inbound_lead_volume']}.")
        trailing = [r for r in sdr if r["week_ending_date"] < cw_row["week_ending_date"]][-4:]
        if trailing:
            avg_cap = _mean(r["team_total_capacity"] for r in trailing)
            avg_vol = _mean(r["inbound_lead_volume"] for r in trailing)
            lines.append(f"- Trailing 4-week average: capacity {avg_cap:.0f}, inbound volume {avg_vol:.0f}.")
    lines.append("")
    lines.append("# Competitive set (named)")
    comps = ds["competitors"]
    if comps:
        lines.append(f"- {', '.join(c['name'] for c in comps)}.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

EVAL_COMPOSITION_RULES = """COMPOSITION — EVAL OUTPUT SCHEMA

This run emits cards in an eval schema that makes the internal composition
explicit. Each card object has seven keys, in this order:

  "intelligence_area"  — always the string "marketing"
  "title"              — the headline, one sentence. Plain English, forward framing, per the Voice Spine. 6-14 words.
  "anchor"             — one sentence. Adds specificity INTERNAL to the title's primary signal (when, where it concentrates, what correlates inside the same surface).
  "connect"            — one sentence. Widens OUTWARD to a CONCRETE data point (Shape A/B/C/D from SIGNAL VS REPORT). Must not explain the title's movement or decompose it into sub-populations.
  "body"               — the anchor + connect concatenated with a single space. Exactly two sentences total.
  "grounded_metrics"   — array of 1-3 short snake_case tags naming which dataset cuts this card draws from (e.g. "cw_ms_dtc", "apr_mm_sqls", "q2_enterprise_win_rate", "branded_search_streak", "direct_vs_organic_crossover").
  "trace"              — 1-2 sentence internal note on which dataset signal triggered this card. This is the only key allowed to be commentary-flavored.

HARD RULES ON FIELD CONTENT:
- "title" must pass the headline test: a reader who IS the VP of Marketing must be able to imagine asking the question this title answers.
- "anchor" and "connect" are each a single sentence. Single terminal punctuation mark per field.
- "body" is "anchor" + " " + "connect". No other content.
- "grounded_metrics" tags are short (2-5 words each, snake_case). Do not invent metric names that aren't cuts of the dataset summary above.
- "trace" is internal — it may name patterns and dataset windows. It must still not violate the forward-framing or people-naming rules.
- All composition guards above (FORWARD FRAMING, SIGNAL VS REPORT, PEOPLE NAMING) apply to "title", "anchor", "connect", and "body". They do NOT apply to "trace" or "grounded_metrics".
"""


EVAL_OUTPUT_HYGIENE = """OUTPUT HYGIENE — PURE JSON ARRAY, EVAL SCHEMA, ZERO META-COMMENTARY

Your entire response is a single JSON array of card objects. Nothing before
it. Nothing after it. No markdown fencing. No prose preamble. No trailing
commentary.

Each card object has exactly the seven keys defined in the EVAL OUTPUT
SCHEMA above, in the order specified, and no others. String values only for
all keys except "grounded_metrics" (array of strings).

If you find yourself wanting to add "reasoning", "audit", "notes",
"category", "type", or any other key — resist. Seven keys per card. No more.

PRE-EMIT CHECK:
1. Does your response start with "["? If not, strip everything before it.
2. Does it end with "]"? If not, strip everything after.
3. Does every card object have exactly the seven keys from the schema? If not, rebuild.
4. Is there any prose anywhere in the response that isn't inside a string value? If yes, delete it.

The output is the cards. Nothing else is the output.
"""


EVAL_CARD_INSTRUCTIONS = """# Card Generation Instructions (Eval Run)

You are Lens, generating Data Stories for the marketing intelligence area.
The reader is the VP of Marketing at Atlas SaaS. Scope is defined in ROLE
SCOPING above. Voice is defined in the VP Marketing Voice Brief above.

## What the data in front of you represents

The COMPANY DATA SNAPSHOT above is the complete set of numbers you may
ground in. Every figure in every card must be citable to one of those
lines. Do not invent adjacent figures. Do not extrapolate to a metric that
isn't in the snapshot. If the snapshot says "Atlas Insights reference
opt-in 76.9%", your card says 76.9% or rounds honestly to 77%, not 78%.

## Card set shape

Produce 15-25 cards. Do not pad and do not artificially cap. Let the set
match what the data supports.

Aim for coverage across the Marketing Leader's goal clusters (Measurable
Growth and ROI; Brand and Value Proposition; Alignment with Revenue and CS;
Customer Centricity). Cross-domain connections where two unrelated cuts
line up are the highest-value cards. Vary time horizon (current week,
30-day, quarterly).

## Card structure

Each card is title + body, per the Voice Spine, but the eval schema
splits the body into anchor and connect fields plus a concatenated body
field. See the EVAL OUTPUT SCHEMA above.

## Do / don't (voice, forward-framing, and composition)

The guards above are binding. Key reminders:
- Forward framing: state the level, never the direction of decrease.
- Sentence 2 (connect) widens outward to a concrete data point, not a hedge.
- No em dashes. No slogans. No insider marketing jargon the VP's non-marketing friend wouldn't use. Plain English. "Moving faster", not "pulled forward". "Pipeline" stays.
- Functions and teams, never individual names.
- No benchmark-as-grading. If you reach for an external ratio, reach for an internal comparison instead.
"""


def build_card_system_prompt(persona: str, marketing_leader_brief: str,
                             voice_brief: str, guards: Dict[str, str],
                             dataset_summary: str) -> str:
    return (
        f"{persona}\n\n---\n\n"
        f"{marketing_leader_brief}\n\n---\n\n"
        f"{guards['IDENTITY_GUARDRAIL']}\n\n---\n\n"
        f"{guards['DATA_BOUNDARY']}\n\n{dataset_summary}\n\n---\n\n"
        f"{guards['FABRICATION_GUARD']}\n\n---\n\n"
        f"{guards['ROLE_SCOPING']}\n\n---\n\n"
        f"{guards['CARD_SELECTION_ROLE_SCOPED']}\n\n---\n\n"
        f"{guards['SIGNAL_VS_REPORT_GUARD']}\n\n---\n\n"
        f"{guards['COMPOSITION_COMPLETENESS_GUARD']}\n\n---\n\n"
        f"{guards['FORWARD_FRAMING_GUARD']}\n\n---\n\n"
        f"{guards['PEOPLE_NAMING_GUARD']}\n\n---\n\n"
        f"{voice_brief}\n\n---\n\n"
        f"{EVAL_COMPOSITION_RULES}\n\n---\n\n"
        f"{EVAL_CARD_INSTRUCTIONS}\n\n---\n\n"
        f"{EVAL_OUTPUT_HYGIENE}"
    )


def build_user_message() -> str:
    return (
        "Generate Data Stories for the Marketing intelligence area based on "
        "the Atlas SaaS company data snapshot above. Produce 15-25 cards in "
        "the eval schema. Return only the JSON array."
    )


# ---------------------------------------------------------------------------
# Anthropic API
# ---------------------------------------------------------------------------

def load_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("ANTHROPIC_API_KEY not set in env or .env")


def call_claude(system: str, user: str, model: str, max_tokens: int,
                api_key: str) -> Tuple[str, Dict]:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system}],
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    text_blocks = [b for b in data.get("content", []) if b.get("type") == "text"]
    text = text_blocks[0]["text"] if text_blocks else ""
    return text, data


def parse_cards(text: str) -> List[Dict]:
    trimmed = text.strip()
    if trimmed.startswith("```"):
        trimmed = re.sub(r"^```(?:json)?\s*", "", trimmed)
        trimmed = re.sub(r"\s*```$", "", trimmed)
    match = re.search(r"\[[\s\S]*\]", trimmed)
    if not match:
        raise ValueError("Could not find JSON array in response")
    return json.loads(match.group(0))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Relevance Engine MVP (Stage 1 eval)")
    ap.add_argument("--input", default=str(EVAL_DIR / "output"),
                    help="Dataset directory (default scripts/eval/output)")
    ap.add_argument("--output", default=str(EVAL_DIR / "generated_cards.json"),
                    help="Output card file (default scripts/eval/generated_cards.json)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Anthropic model id (default {DEFAULT_MODEL})")
    ap.add_argument("--max-tokens", type=int, default=8192,
                    help="Max response tokens")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the assembled prompt and dataset summary, do not call the API")
    args = ap.parse_args(argv)

    ds = load_dataset(Path(args.input))
    guards = load_worker_guards()
    persona = (DATA_DIR / "persona.md").read_text()
    marketing_leader_brief = (DATA_DIR / "marketing-leader-brief.md").read_text()
    voice_brief = (DATA_DIR / "voice-brief.md").read_text()

    summary = build_summary(ds)
    system_prompt = build_card_system_prompt(persona, marketing_leader_brief,
                                             voice_brief, guards, summary)
    user_message = build_user_message()

    if args.dry_run:
        print("=== DATASET SUMMARY ===")
        print(summary)
        print()
        print(f"=== SYSTEM PROMPT LENGTH: {len(system_prompt)} chars ===")
        print(f"=== USER MESSAGE ===\n{user_message}")
        return 0

    api_key = load_api_key()
    print(f"Calling Claude ({args.model}) with system prompt of "
          f"{len(system_prompt):,} chars / summary of {len(summary):,} chars...",
          file=sys.stderr)
    text, response = call_claude(system_prompt, user_message,
                                 args.model, args.max_tokens, api_key)

    usage = response.get("usage", {})
    print(f"tokens: input={usage.get('input_tokens', 0)} "
          f"output={usage.get('output_tokens', 0)} "
          f"cache_read={usage.get('cache_read_input_tokens', 0)} "
          f"cache_created={usage.get('cache_creation_input_tokens', 0)}",
          file=sys.stderr)

    try:
        cards = parse_cards(text)
    except Exception as exc:
        print(f"Failed to parse cards: {exc}", file=sys.stderr)
        print("--- raw response ---", file=sys.stderr)
        print(text, file=sys.stderr)
        return 2

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cards, indent=2) + "\n")
    print(f"Wrote {len(cards)} cards to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
