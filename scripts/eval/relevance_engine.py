#!/usr/bin/env python3
"""Relevance Engine MVP for Stage 1 eval.

Consumes the Atlas SaaS synthetic dataset at scripts/eval/output/ and emits
Story Cards to scripts/eval/generated_cards.json via Claude, using the locked
prompt stack from worker.js.

Data strategy (Option A per handoff): pre-compute structured summaries over
the 15 seeded patterns and feed them in place of COMPANY_DATA. A future
Option B would expose dataset query tools and let the model discover signals
through tool use — see OPTION_B_NOTE below.

Prompt stack order (adapted from worker.js buildCardSystemPrompt for cache
efficiency — DATA_BOUNDARY + dataset summary moved from middle to tail, so
the ~100K stable prefix caches cleanly across seeds via a cache_control
breakpoint between blocks 14 and 15):

  STABLE PREFIX (cached):
  1.  PERSONA                         (data/persona.md)
  2.  MARKETING_LEADER_BRIEF          (data/marketing-leader-brief.md)
  3.  IDENTITY_GUARDRAIL              (worker.js)
  4.  FABRICATION_GUARD               (worker.js)
  5.  ROLE_SCOPING                    (worker.js)
  6.  CARD_SELECTION_ROLE_SCOPED      (worker.js)
  7.  SIGNAL_VS_REPORT_GUARD          (worker.js)
  8.  COMPOSITION_COMPLETENESS_GUARD  (worker.js, adapted schema)
  9.  FORWARD_FRAMING_GUARD           (worker.js)
 10.  PEOPLE_NAMING_GUARD             (worker.js)
 11.  VOICE_BRIEF                     (data/voice-brief.md)
 12.  Eval card generation instructions (EVAL_COMPOSITION_RULES)
 13.  Eval card instructions body     (EVAL_CARD_INSTRUCTIONS)
 14.  OUTPUT_HYGIENE_GUARD            (adapted to eval schema)
  ---- cache_control breakpoint ----
  DATASET BLOCK (per-seed):
 15.  DATA_BOUNDARY + dataset summary (replaces COMPANY_DATA)

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
    required = [
        "companies", "contacts", "deals", "campaigns", "campaign_performance",
        "budget", "actual_spend", "engagement_events", "branded_search",
        "web_analytics", "mentions", "competitors", "analyst_mentions",
        "customer_reference_optins", "product_launches", "sdr_capacity",
    ]
    optional = ["forecasts", "renewals", "expansion_opportunities"]
    data: Dict[str, list] = {}
    for e in required:
        p = output_dir / f"{e}.json"
        if not p.exists():
            raise FileNotFoundError(f"Missing dataset file: {p}")
        data[e] = json.loads(p.read_text())
    for e in optional:
        p = output_dir / f"{e}.json"
        data[e] = json.loads(p.read_text()) if p.exists() else []
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
    # Bucket by target_list_name so every hot account shows up in the summary.
    # Earlier versions only surfaced the Named Accounts count, which made the
    # March ABM Add account invisible to the model and produced cards that
    # under-counted the active target set (P13 ground truth: 2 Named + 1 March
    # ABM Add = 3 hot accounts).
    hot_by_list: Dict[str, int] = defaultdict(int)
    for cid in hot_target:
        list_name = by_co[cid].get("target_list_name") or "(unlisted)"
        hot_by_list[list_name] += 1

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
    # Render every list bucket explicitly so each hot account is visible to
    # the model with equivalent framing. Sort alphabetically for stable output.
    if hot_by_list:
        bucket_str = ", ".join(f"{name} {n}" for name, n in sorted(hot_by_list.items()))
    else:
        bucket_str = "(none)"
    lines.append(f"- Current-week target accounts with 5+ high-intent events: n={len(hot_target)}. Breakdown by target list: {bucket_str}. (Target-list membership universe: {sum(1 for c in companies if c.get('is_target_account'))}.)")
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


def build_revenue_summary(ds: Dict[str, list]) -> str:
    """Dense, factual snapshot oriented for the Revenue Leader (CRO/VP Sales).

    Same Atlas SaaS dataset as build_summary, but the cuts are tuned to the
    Revenue Leader Goal Clusters: Quarter Attainment & Forecast Reliability,
    Pipeline Coverage & Health, Win Rate & Competitive Position. Cross-
    functional bridges to Marketing (lead conversion) and CS (renewals,
    expansion) are surfaced as their own sections.
    """
    deals = ds["deals"]
    companies = ds["companies"]
    by_co = {c["id"]: c for c in companies}
    forecasts = ds.get("forecasts", [])
    renewals = ds.get("renewals", [])
    expansion = ds.get("expansion_opportunities", [])

    def fc(q: str) -> Dict:
        return next((f for f in forecasts if f["quarter"] == q), {})

    def cd(d: Dict, key: str = "close_date"):
        return date.fromisoformat(d[key]) if d.get(key) else None

    cw = (date(2026, 4, 20), date(2026, 4, 26))
    last_30d = (date(2026, 3, 25), date(2026, 4, 24))
    q1 = (date(2026, 1, 1), date(2026, 3, 31))
    q2 = (date(2026, 4, 1), date(2026, 6, 30))
    q3 = (date(2026, 7, 1), date(2026, 9, 30))
    ms_sources = {"paid_social", "paid_search", "content", "email", "events", "webinar", "nurture"}

    # Forecast / commit / pacing (RL-01, RL-14)
    f_q2 = fc("Q2_2026")
    f_q3 = fc("Q3_2026")
    f_q1 = fc("Q1_2026")

    # Q3 enterprise pipeline coverage (RL-03)
    q3_open_ent = [d for d in deals if d["segment"] == "enterprise" and not d["is_closed"]
                   and d["close_date"] and q3[0] <= cd(d) <= q3[1]]
    q3_pipeline = sum(d["amount"] for d in q3_open_ent)
    q3_plan = f_q3.get("enterprise_plan", 0)
    q3_coverage = q3_pipeline / q3_plan if q3_plan else 0

    # Q2 net new pipeline + MS share (RL-04)
    q2_open = [d for d in deals if not d["is_closed"]
               and q2[0] <= date.fromisoformat(d["create_date"]) <= q2[1]]
    q2_total = sum(d["amount"] for d in q2_open)
    q2_ms = sum(d["amount"] for d in q2_open if d["lead_source"] in ms_sources)
    ms_share = q2_ms / q2_total if q2_total else 0

    # Procurement-cleared deals (RL-05)
    proc_cleared = [d for d in deals if d["segment"] == "enterprise"
                    and d.get("procurement_signoff") and d.get("contract_revisions")
                    and not d["is_closed"]]

    # Last-30d MM opps (RL-06)
    mm_30d = [d for d in deals if d["segment"] == "mid-market" and not d["is_closed"]
              and last_30d[0] <= date.fromisoformat(d["create_date"]) <= last_30d[1]]
    mm_30d_total = sum(d["amount"] for d in mm_30d)
    mm_30d_avg = mm_30d_total / len(mm_30d) if mm_30d else 0

    # Enterprise WR — Q2 vs trailing 4Q (RL-07)
    ent_q2 = [d for d in deals if d["segment"] == "enterprise" and d["is_closed"]
              and q2[0] <= cd(d) <= q2[1]]
    ent_q2_wins = [d for d in ent_q2 if d["is_won"]]
    q2_wr = len(ent_q2_wins) / len(ent_q2) if ent_q2 else 0
    ent_trail = [d for d in deals if d["segment"] == "enterprise" and d["is_closed"]
                 and date(2025, 4, 1) <= cd(d) <= date(2026, 3, 31)]
    ent_trail_wins = [d for d in ent_trail if d["is_won"]]
    trail_wr = len(ent_trail_wins) / len(ent_trail) if ent_trail else 0
    q2_avg_won = _mean(d["amount"] for d in ent_q2_wins)
    trail_avg_won = _mean(d["amount"] for d in ent_trail_wins)

    # Q1 enterprise wins anchor (RL-08)
    q1_ent_wins = [d for d in deals if d["segment"] == "enterprise" and d["is_won"]
                   and q1[0] <= cd(d) <= q1[1]]
    q1_ent_avg = _mean(d["amount"] for d in q1_ent_wins)

    # MM cycle (RL-09)
    def cycle(d: Dict) -> int:
        return (cd(d) - date.fromisoformat(d["create_date"])).days
    mm_q2_closed = [d for d in deals if d["segment"] == "mid-market" and d["is_closed"]
                    and q2[0] <= cd(d) <= q2[1]]
    mm_q1_closed = [d for d in deals if d["segment"] == "mid-market" and d["is_closed"]
                    and q1[0] <= cd(d) <= q1[1]]
    q2_cycle = _mean(cycle(d) for d in mm_q2_closed)
    q1_cycle = _mean(cycle(d) for d in mm_q1_closed)

    # H2H vs Beacon (RL-10)
    h2h = [d for d in deals if d.get("head_to_head") and d.get("competitor_id") == "Beacon Systems"]
    q2_h2h = [d for d in h2h if d["is_closed"] and q2[0] <= cd(d) <= q2[1]]
    q1_h2h = [d for d in h2h if d["is_closed"] and q1[0] <= cd(d) <= q1[1]]
    q2_h2h_w = sum(1 for d in q2_h2h if d["is_won"])
    q2_h2h_l = sum(1 for d in q2_h2h if not d["is_won"])
    q1_h2h_w = sum(1 for d in q1_h2h if d["is_won"])
    q1_h2h_l = sum(1 for d in q1_h2h if not d["is_won"])

    # Expansion from health reviews (RL-11)
    chr_30d = [e for e in expansion if e.get("source") == "customer_health_review"
               and last_30d[0] <= date.fromisoformat(e["create_date"]) <= last_30d[1]]
    chr_total = sum(e["amount"] for e in chr_30d)
    chr_avg = chr_total / len(chr_30d) if chr_30d else 0

    # Q2 enterprise WR by source class (RL-12)
    ms_set12 = ms_sources
    ob_set = {"outbound"}
    def wr(deals_in, sources):
        n = sum(1 for d in deals_in if d["lead_source"] in sources)
        w = sum(1 for d in deals_in if d["lead_source"] in sources and d["is_won"])
        return (w / n if n else 0), n, w
    ms_wr, ms_n, ms_w = wr(ent_q2, ms_set12)
    ob_wr, ob_n, ob_w = wr(ent_q2, ob_set)

    # Close-date slips Q2→Q3 this week (RL-13)
    cw_start, cw_end = cw
    slips = [d for d in deals if d.get("stage_change_history")
             and any(ev.get("from_quarter") == "Q2_2026" and ev.get("to_quarter") == "Q3_2026"
                     and cw_start <= date.fromisoformat(ev["change_date"]) <= cw_end
                     for ev in d["stage_change_history"])]
    slip_total = sum(d["amount"] for d in slips)

    # Q2 MM renewals (RL-15)
    q2_mm_ren = [r for r in renewals if r["quarter"] == "Q2_2026" and r["segment"] == "mid-market"]
    q2_mm_arr = sum(r["renewed_arr"] for r in q2_mm_ren)
    q2_mm_nrr = next((r["nrr"] for r in q2_mm_ren), None)
    q1_mm_ren = [r for r in renewals if r["quarter"] == "Q1_2026" and r["segment"] == "mid-market"]
    q1_mm_arr = sum(r["renewed_arr"] for r in q1_mm_ren)
    q1_mm_nrr = next((r["nrr"] for r in q1_mm_ren), None)

    L: List[str] = []
    L.append("ATLAS SAAS — REVENUE DATA SNAPSHOT (as of 2026-04-24)")
    L.append("")
    L.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. Salesforce is the system of record for pipeline; HubSpot for marketing; Gainsight for renewals; Mixpanel for product engagement.")
    L.append("")

    L.append("# Forecast and quarter pacing")
    if f_q2:
        L.append(f"- Q2 2026 commit: ${f_q2.get('commit', 0):,}. Q2 weighted pipeline at 80% confidence: ${f_q2.get('weighted_pipeline_80pct', 0):,}. Q2 plan total: ${f_q2.get('plan_total', 0):,}.")
        L.append(f"- Q2 plan-pacing target through Apr 24: ${f_q2.get('plan_pacing_target_through_apr24', 0):,}. Q2 bookings closed-won through Apr 24: ${f_q2.get('bookings_actual_through_apr24', 0):,}.")
    if f_q3:
        L.append(f"- Q3 2026 commit: ${f_q3.get('commit', 0):,}. Q3 weighted pipeline at 80% confidence: ${f_q3.get('weighted_pipeline_80pct', 0):,}. Q3 plan total: ${f_q3.get('plan_total', 0):,}.")
        L.append(f"- Q3 enterprise plan: ${f_q3.get('enterprise_plan', 0):,}.")
    if f_q1:
        L.append(f"- Q1 2026 final commit: ${f_q1.get('commit', 0):,}. Q1 plan total: ${f_q1.get('plan_total', 0):,}.")
    L.append("")

    L.append("# Pipeline coverage and shape")
    L.append(f"- Q3 enterprise open pipeline: ${q3_pipeline:,} across {len(q3_open_ent)} deals. Q3 enterprise plan: ${q3_plan:,}. Coverage ratio: {q3_coverage:.2f}x.")
    L.append(f"- Q2 net new pipeline created (open opportunities, by create_date): ${q2_total:,} across {len(q2_open)} deals. Marketing-sourced share: {ms_share*100:.1f}% (${q2_ms:,}).")
    L.append(f"- Mid-market opportunities created in last 30 days (Mar 25 - Apr 24): n={len(mm_30d)}, total ${mm_30d_total:,}, average ACV ${mm_30d_avg:,.0f}.")
    L.append(f"- Enterprise deals through procurement review with signoff and contract revisions, currently open: n={len(proc_cleared)}, total amount ${sum(d['amount'] for d in proc_cleared):,}.")
    L.append(f"- Close-date slips this week (Apr 20-26), Q2 → Q3 movement: n={len(slips)}, total deal amount ${slip_total:,}.")
    L.append("")

    L.append("# Win rate and deal cycle")
    L.append(f"- Q2 enterprise win rate: {q2_wr*100:.2f}% ({len(ent_q2_wins)}/{len(ent_q2)} deals). Average won amount: ${q2_avg_won:,.0f}.")
    L.append(f"- Trailing four quarters enterprise win rate: {trail_wr*100:.2f}% ({len(ent_trail_wins)}/{len(ent_trail)} deals). Average won amount: ${trail_avg_won:,.0f}.")
    L.append(f"- Q2 enterprise win rate by source class: marketing-sourced {ms_wr*100:.1f}% ({ms_w}/{ms_n}); outbound {ob_wr*100:.1f}% ({ob_w}/{ob_n}).")
    L.append(f"- Q1 2026 enterprise wins: n={len(q1_ent_wins)}, average won amount ${q1_ent_avg:,.0f}.")
    L.append(f"- Mid-market sales cycle: Q2 closed deals n={len(mm_q2_closed)} mean cycle {q2_cycle:.1f} days; Q1 closed deals n={len(mm_q1_closed)} mean cycle {q1_cycle:.1f} days.")
    L.append("")

    L.append("# Competitive position")
    L.append(f"- Head-to-head deals tagged versus Beacon Systems, Q2 2026: {q2_h2h_w}W/{q2_h2h_l}L (n={len(q2_h2h)}). Q1 2026: {q1_h2h_w}W/{q1_h2h_l}L (n={len(q1_h2h)}).")
    competitors = ds.get("competitors", [])
    if competitors:
        L.append(f"- Named competitive set: {', '.join(c['name'] for c in competitors)}.")
    L.append("")

    L.append("# Renewals and expansion (Customer Success bridge)")
    if q2_mm_ren:
        L.append(f"- Q2 2026 mid-market renewals to date: n={len(q2_mm_ren)}, renewed ARR ${q2_mm_arr:,}, segment NRR {q2_mm_nrr}.")
    if q1_mm_ren:
        L.append(f"- Q1 2026 mid-market renewals: n={len(q1_mm_ren)}, renewed ARR ${q1_mm_arr:,}, segment NRR {q1_mm_nrr}.")
    L.append(f"- Expansion opportunities sourced from customer health reviews in last 30 days: n={len(chr_30d)}, total ${chr_total:,}, average ${chr_avg:,.0f}.")
    L.append("")

    return "\n".join(L)


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

EVAL_COMPOSITION_RULES_TEMPLATE = """COMPOSITION — EVAL OUTPUT SCHEMA

This run emits cards in an eval schema that makes the internal composition
explicit. Each card object has seven keys, in this order:

  "intelligence_area"  — always the string "{intelligence_area}"
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


def render_composition_rules(intelligence_area: str) -> str:
    return EVAL_COMPOSITION_RULES_TEMPLATE.format(intelligence_area=intelligence_area)


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


_MARKETING_GOAL_CLUSTERS = (
    "Measurable Growth and ROI; Brand and Value Proposition; "
    "Alignment with Revenue and CS; Customer Centricity"
)
_REVENUE_GOAL_CLUSTERS = (
    "Quarter Attainment and Forecast Reliability; Pipeline Coverage and Health; "
    "Win Rate and Competitive Position"
)


_ARCHETYPE_CONFIG = {
    "marketing": {
        "intelligence_area": "marketing",
        "audience_label": "VP of Marketing at Atlas SaaS",
        "voice_brief_label": "VP Marketing Voice Brief",
        "leader_label": "Marketing Leader",
        "goal_clusters": _MARKETING_GOAL_CLUSTERS,
        "snapshot_label": "COMPANY DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"Atlas Insights reference opt-in 76.9%\", "
            "your card says 76.9% or rounds honestly to 77%, not 78%."
        ),
        "brief_filename": "marketing-leader-brief.md",
        "user_prompt_subject": "Marketing",
    },
    "revenue": {
        "intelligence_area": "revenue",
        "audience_label": "Chief Revenue Officer at Atlas SaaS",
        "voice_brief_label": "Voice Brief",
        "leader_label": "Revenue Leader",
        "goal_clusters": _REVENUE_GOAL_CLUSTERS,
        "snapshot_label": "REVENUE DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"Q2 enterprise win rate 30.77%\", your card "
            "says 30.77% or rounds honestly to 31%, not 32%."
        ),
        "brief_filename": "revenue-leader-brief.md",
        "user_prompt_subject": "Revenue",
    },
}


def render_card_instructions(archetype: str) -> str:
    cfg = _ARCHETYPE_CONFIG[archetype]
    return f"""# Card Generation Instructions (Eval Run)

You are Lens, generating Data Stories for the {cfg['intelligence_area']} intelligence area.
The reader is the {cfg['audience_label']}. Scope is defined in ROLE
SCOPING above. Voice is defined in the {cfg['voice_brief_label']} above.

## What the data in front of you represents

The {cfg['snapshot_label']} above is the complete set of numbers you may
ground in. Every figure in every card must be citable to one of those
lines. Do not invent adjacent figures. Do not extrapolate to a metric that
isn't in the snapshot. {cfg['snapshot_example']}

## Card set shape

Produce 15-25 cards. Do not pad and do not artificially cap. Let the set
match what the data supports.

Aim for coverage across the {cfg['leader_label']}'s goal clusters ({cfg['goal_clusters']}).
Cross-domain connections where two unrelated cuts line up are the highest-
value cards. Vary time horizon (current week, 30-day, quarterly).

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

## Problem-word substitutions (lexical, zero-tolerance)

Story Cards never contain the words "gap", "gaps", "loss", "losses", "miss",
"missed", "misses", "failure", "failures" anywhere in title, anchor, connect,
or body. The Voice Brief already forbids problem framing; this is the
lexical floor. If the underlying data point is an under-spend, an under-
attainment, or a delta versus plan, surface it as forward signal:

- "$84K gap" / "the gap" → "$84K of unspent budget" or "$84K of headroom"
  or simply name what the dollars went to ("$84K reallocated to SaaS Connect
  and Signal Summit"). Never the word "gap".
- "missed plan" → "tracking at $X versus the $Y plan" (state the level).
- "X is a gap" / "X represents a gap" → "X is where the next read lives" or
  rewrite around what is now visible because of it.

PRE-EMIT CHECK: scan every title, anchor, connect, and body string for the
words above. If any appear, rewrite that field before emitting.
"""


def build_stable_prefix(persona: str, archetype_brief: str,
                        voice_brief: str, guards: Dict[str, str],
                        archetype: str) -> str:
    """Everything in the system prompt that does NOT vary across seeds.

    Kept first so it caches as a single prefix across every run. The dataset
    summary is appended as a separate (uncached) system block at call time.
    Structure diverges slightly from worker.js buildCardSystemPrompt() —
    DATA_BOUNDARY + dataset are placed at the END rather than the middle, so
    the ~100K stable stack caches cleanly. The model still sees the full
    guard context before the data; only the ordering within the system prompt
    is batched for cache efficiency.
    """
    cfg = _ARCHETYPE_CONFIG[archetype]
    composition_rules = render_composition_rules(cfg["intelligence_area"])
    card_instructions = render_card_instructions(archetype)
    return (
        f"{persona}\n\n---\n\n"
        f"{archetype_brief}\n\n---\n\n"
        f"{guards['IDENTITY_GUARDRAIL']}\n\n---\n\n"
        f"{guards['FABRICATION_GUARD']}\n\n---\n\n"
        f"{guards['ROLE_SCOPING']}\n\n---\n\n"
        f"{guards['CARD_SELECTION_ROLE_SCOPED']}\n\n---\n\n"
        f"{guards['SIGNAL_VS_REPORT_GUARD']}\n\n---\n\n"
        f"{guards['COMPOSITION_COMPLETENESS_GUARD']}\n\n---\n\n"
        f"{guards['FORWARD_FRAMING_GUARD']}\n\n---\n\n"
        f"{guards['PEOPLE_NAMING_GUARD']}\n\n---\n\n"
        f"{voice_brief}\n\n---\n\n"
        f"{composition_rules}\n\n---\n\n"
        f"{card_instructions}\n\n---\n\n"
        f"{EVAL_OUTPUT_HYGIENE}"
    )


def build_dataset_block(data_boundary: str, dataset_summary: str) -> str:
    """The variable, per-seed tail of the system prompt. Lives OUTSIDE the
    cached prefix so it can change per seed without invalidating the cache."""
    return f"{data_boundary}\n\n{dataset_summary}"


def build_user_message(archetype: str) -> str:
    cfg = _ARCHETYPE_CONFIG[archetype]
    snapshot_word = "company data" if archetype == "marketing" else "revenue data"
    return (
        f"Generate Data Stories for the {cfg['user_prompt_subject']} intelligence area based on "
        f"the Atlas SaaS {snapshot_word} snapshot above. Produce 15-25 cards in "
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


def call_claude(system_blocks: List[Dict], user: str, model: str,
                max_tokens: int, api_key: str) -> Tuple[str, Dict]:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_blocks,
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


# Voice rules (Phase 1.4 + 1.4b) — belt-and-braces normalizer for user-facing
# card fields when Sonnet drifts despite the Voice Brief calibration note.
# Trace is internal commentary and is intentionally NOT normalized.
#
# Two-tier strategy:
#   Tier 1 (mechanical rewrite): "against" → "versus" is a clean lexical swap
#     in comparison contexts, so we apply it automatically.
#   Tier 2 (fail-and-regenerate): problem-framing words (loss/gap/miss/failure)
#     have no clean single-word substitute that preserves meaning. Forcing a
#     swap (e.g. gap→shift) produces semantically off copy ("freed up the
#     shift", "Q1 shift ran $310K"). Story Cards surface forward signal only,
#     so the right move is to surface unresolved hits and let the caller
#     regenerate the seed. The CLI exits non-zero when any are present.
_USER_FACING_FIELDS = ("title", "anchor", "connect", "body")
_AGAINST_RE = re.compile(r"\bagainst\b", re.IGNORECASE)
_PROBLEM_WORDS_RE = re.compile(
    r"\b(?:loss|losses|gap|gaps|miss|missed|misses|failure|failures)\b",
    re.IGNORECASE,
)


def normalize_voice(
    cards: List[Dict],
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """Apply post-generation voice fixes.

    Returns (cards, edits, unresolved):
      edits     — Tier 1 mechanical rewrites applied in place.
      unresolved — Tier 2 problem-word hits the caller must regenerate.
    """
    edits: List[Dict] = []
    unresolved: List[Dict] = []
    for idx, card in enumerate(cards):
        for field in _USER_FACING_FIELDS:
            value = card.get(field)
            if not isinstance(value, str):
                continue
            new_value = value
            if _AGAINST_RE.search(new_value):
                rewritten = _AGAINST_RE.sub("versus", new_value)
                edits.append({"card_index": idx, "field": field,
                              "rule": "against→versus",
                              "before": new_value, "after": rewritten})
                new_value = rewritten
            if new_value != value:
                card[field] = new_value
            for m in _PROBLEM_WORDS_RE.finditer(new_value):
                start = max(0, m.start() - 30)
                end = min(len(new_value), m.end() + 30)
                unresolved.append({
                    "card_index": idx, "field": field,
                    "match": m.group(0),
                    "snippet": new_value[start:end],
                })
    return cards, edits, unresolved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Relevance Engine MVP (Stage 1 eval)")
    ap.add_argument("--archetype", choices=sorted(_ARCHETYPE_CONFIG.keys()),
                    default="marketing",
                    help="Which archetype's intelligence brief and dataset summary to use (default marketing)")
    ap.add_argument("--input", default=str(EVAL_DIR / "output"),
                    help="Dataset directory (default scripts/eval/output)")
    ap.add_argument("--output", default=None,
                    help="Output card file (default generated_cards_<archetype>_seed<N>.json or generated_cards.json for marketing)")
    ap.add_argument("--seed", type=int, default=None,
                    help="Seed label for the output filename — does not regenerate the dataset.")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Anthropic model id (default {DEFAULT_MODEL})")
    ap.add_argument("--max-tokens", type=int, default=8192,
                    help="Max response tokens")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the assembled prompt and dataset summary, do not call the API")
    args = ap.parse_args(argv)

    archetype = args.archetype
    cfg = _ARCHETYPE_CONFIG[archetype]

    ds = load_dataset(Path(args.input))
    guards = load_worker_guards()
    persona = (DATA_DIR / "persona.md").read_text()
    archetype_brief = (DATA_DIR / cfg["brief_filename"]).read_text()
    voice_brief = (DATA_DIR / "voice-brief.md").read_text()

    summary = build_revenue_summary(ds) if archetype == "revenue" else build_summary(ds)
    stable_prefix = build_stable_prefix(persona, archetype_brief,
                                        voice_brief, guards, archetype)
    dataset_block = build_dataset_block(guards["DATA_BOUNDARY"], summary)
    # Two system blocks: stable prefix is cached (cache_control breakpoint),
    # dataset block varies per seed.
    system_blocks = [
        {"type": "text", "text": stable_prefix,
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dataset_block},
    ]
    user_message = build_user_message(archetype)

    if args.dry_run:
        print("=== DATASET SUMMARY ===")
        print(summary)
        print()
        print(f"=== STABLE PREFIX LENGTH: {len(stable_prefix):,} chars "
              f"(cached) ===")
        print(f"=== DATASET BLOCK LENGTH: {len(dataset_block):,} chars "
              f"(uncached, per-seed) ===")
        print(f"=== USER MESSAGE ===\n{user_message}")
        return 0

    api_key = load_api_key()
    total_len = len(stable_prefix) + len(dataset_block)
    print(f"Calling Claude ({args.model}) with system prompt of "
          f"{total_len:,} chars "
          f"(prefix {len(stable_prefix):,} cached + dataset {len(dataset_block):,} per-seed)...",
          file=sys.stderr)
    text, response = call_claude(system_blocks, user_message,
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

    cards, voice_edits, voice_unresolved = normalize_voice(cards)
    if voice_edits:
        print(f"voice normalizer applied {len(voice_edits)} edit(s):",
              file=sys.stderr)
        for e in voice_edits:
            print(f"  card[{e['card_index']}].{e['field']}: {e['rule']}",
                  file=sys.stderr)
    if voice_unresolved:
        print(f"voice normalizer found {len(voice_unresolved)} unresolved "
              f"problem-word hit(s) — regenerate the seed:",
              file=sys.stderr)
        for u in voice_unresolved:
            print(f"  card[{u['card_index']}].{u['field']}: '{u['match']}' "
                  f"in '…{u['snippet']}…'", file=sys.stderr)
        return 3

    # Phase 1.3 specificity guardrail — pre-flight drop. Every numeric claim
    # in title/anchor/connect/body must be LITERAL (present in the dataset
    # summary, within rounding tolerance) or DERIVED (a simple arithmetic
    # combination of summary values). Any card containing an UNGROUNDED
    # numeric is dropped before write so hallucinated figures never reach a
    # reader. The baseline Phase 1.1 run showed 86/86 cards clean at this
    # check; the guardrail runs as an always-on safety net.
    from specificity_guardrail import (  # noqa: E402
        audit_card, ground_set_from_summary,
    )
    ground = ground_set_from_summary(summary)
    kept: List[Dict] = []
    dropped: List[Dict] = []
    for idx, card in enumerate(cards):
        audit = audit_card(card, ground)
        if audit["all_grounded"]:
            kept.append(card)
        else:
            dropped.append({
                "index": idx,
                "title": card.get("title"),
                "ungrounded": [n for n in audit["numerics"]
                               if n["status"] == "UNGROUNDED"],
            })
    if dropped:
        print(f"specificity guardrail dropped {len(dropped)} card(s):",
              file=sys.stderr)
        for d in dropped:
            tags = ", ".join(f"{n['field']}:{n['raw']}"
                             for n in d["ungrounded"][:3])
            print(f"  card[{d['index']}] '{d['title']}' — {tags}",
                  file=sys.stderr)
    cards = kept

    if args.output:
        out_path = Path(args.output)
    else:
        if archetype == "marketing" and args.seed is None:
            out_path = EVAL_DIR / "generated_cards.json"
        else:
            seed_tag = f"_seed{args.seed}" if args.seed is not None else ""
            out_path = EVAL_DIR / f"generated_cards_{archetype}{seed_tag}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cards, indent=2) + "\n")
    print(f"Wrote {len(cards)} cards to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
