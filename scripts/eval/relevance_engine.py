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
    optional = [
        "forecasts", "renewals", "expansion_opportunities",
        "forecast_log", "renewal_at_risk_log", "health_scores", "cohorts",
        "product_adoption", "coverage_tier", "executive_sponsor",
        # Marketing Strategist entities (Phase 2.8)
        "competitive_intel", "discovery_calls", "icp_analysis",
        "messaging_performance", "launch_attribution", "launch_enablement",
        "earned_media", "crm_hygiene", "cs_exit_interviews",
        # Marketing Builder entities (Phase 2.11)
        "mb_paid_performance", "mb_mql_sources", "mb_inbound_demos",
        "mb_seo_keywords", "mb_organic_traffic", "mb_content_attribution",
        "mb_routing_ops", "mb_attribution_accuracy", "mb_mql_hygiene",
        "mb_sales_enablement_assets",
        # Revenue Generator entities (Phase 2.14)
        "rg_deal_threads", "rg_champion_status", "rg_buying_committee",
        "rg_pipeline_coverage", "rg_win_rates", "rg_deal_hygiene",
        "rg_outbound_sequences", "rg_competitive_coverage",
        "rg_battlecard_usage", "rg_expansion_flags",
        # Revenue Developer entities (Phase 2.17)
        "rd_inbound_speed", "rd_sequence_perf", "rd_subject_test",
        "rd_segment_penetration", "rd_intent_outreach", "rd_ae_handoff",
        "rd_linkedin_inbound", "rd_call_timing", "rd_dormant_reengagement",
        "rd_enterprise_committee",
        # Revenue Operator entities (Phase 2.20)
        "ro_forecast_metrics", "ro_pipeline_governance", "ro_data_quality",
        "ro_tool_sync", "ro_stage_gate", "ro_lead_routing", "ro_attribution",
        "ro_qbr_changes", "ro_account_dedup", "ro_deal_review_presence",
        # Customer Advocate entities (Phase 2.23)
        "ca_active_book", "ca_renewal_pipeline", "ca_early_renewals",
        "ca_segment_grr", "ca_lighthouse_qbr", "ca_qbr_log",
        "ca_onboarding", "ca_advocate_pipeline",
        # Customer Operator entities (Phase 2.26)
        "co_health_model", "co_playbook_ops", "co_platform_integrations",
        "co_segmentation", "co_handoff_quality", "co_benchmark", "co_performance",
        # Customer Technician entities (Phase 2.29)
        "ct_ttfv_cohort", "ct_go_live_velocity", "ct_integration_and_activation",
        "ct_handoff_quality", "ct_nps", "ct_support_and_blockers", "ct_product_event",
    ]
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

    # MM proposal-stage time, Q2 vs trailing 4Q (RL-02)
    # Distinct from full-cycle: this isolates time spent in the proposal stage
    # specifically, which surfaces procurement / pricing-conversation dynamics
    # that whole-cycle compression numbers blur out.
    mm_q2_prop = [d["time_in_proposal"] for d in deals
                  if d["segment"] == "mid-market" and d["is_closed"]
                  and q2[0] <= cd(d) <= q2[1]
                  and d.get("time_in_proposal") is not None]
    mm_trail_prop = [d["time_in_proposal"] for d in deals
                     if d["segment"] == "mid-market" and d["is_closed"]
                     and date(2025, 4, 1) <= cd(d) <= date(2026, 3, 31)
                     and d.get("time_in_proposal") is not None]
    q2_prop_mean = _mean(mm_q2_prop)
    trail_prop_mean = _mean(mm_trail_prop)

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
    L.append(f"- Mid-market sales cycle (full create-to-close): Q2 closed deals n={len(mm_q2_closed)} mean cycle {q2_cycle:.1f} days; Q1 closed deals n={len(mm_q1_closed)} mean cycle {q1_cycle:.1f} days.")
    L.append(f"- Mid-market time-in-proposal (proposal stage only, distinct from full cycle): Q2 closed deals n={len(mm_q2_prop)} mean {q2_prop_mean:.1f} days; trailing four quarters n={len(mm_trail_prop)} mean {trail_prop_mean:.1f} days.")
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


def build_customer_summary(ds: Dict[str, list]) -> str:
    """Dense, factual snapshot oriented for the Customer Leader (VP CS / CCO).

    Same Atlas SaaS dataset, cuts tuned to the Customer Leader Goal Clusters:
    Retained Revenue Landing to Forecast, Expansion Revenue Compounding NRR,
    Portfolio-Level Retention Risk Surfacing Ahead of Churn. Cross-functional
    bridges to Revenue (renewals/expansion) and Product (launches) are surfaced
    as their own sections.
    """
    companies = ds["companies"]
    by_co = {c["id"]: c for c in companies}
    forecast_log = ds.get("forecast_log", [])
    risk_log = ds.get("renewal_at_risk_log", [])
    health = ds.get("health_scores", [])
    cohorts = ds.get("cohorts", [])
    adoption = ds.get("product_adoption", [])
    coverage = ds.get("coverage_tier", [])
    sponsor = ds.get("executive_sponsor", [])
    renewals = ds.get("renewals", [])
    expansion = ds.get("expansion_opportunities", [])
    launches = ds.get("product_launches", [])
    sponsor_by_co = {s["company_id"]: s for s in sponsor}

    cw = (date(2026, 4, 20), date(2026, 4, 26))

    # CL-01 forecast accuracy
    fl_q2_all = next((r for r in forecast_log if r["quarter"] == "Q2_2026" and r["segment"] == "all"), {})
    trailing_q = ["Q1_2026", "Q4_2025", "Q3_2025", "Q2_2025"]
    trailing_var = [r["variance_pct"] for r in forecast_log
                    if r["quarter"] in trailing_q and r["segment"] == "all"
                    and r.get("variance_pct") is not None]
    trailing_var_avg = sum(trailing_var) / len(trailing_var) if trailing_var else 0

    # CL-02 / CL-14 — risk pool snapshots
    mar = [r for r in risk_log if r["snapshot_month"] == "2026-03"]
    apr = [r for r in risk_log if r["snapshot_month"] == "2026-04"]
    mar_total = sum(r["arr_at_risk"] for r in mar)
    apr_total = sum(r["arr_at_risk"] for r in apr)
    mar_top20 = [r for r in mar if r["in_top_20_arr"]]
    apr_top20 = [r for r in apr if r["in_top_20_arr"]]
    mar_ids = {r["company_id"] for r in mar}
    apr_ids = {r["company_id"] for r in apr}
    dropped_off = mar_ids - apr_ids
    added = apr_ids - mar_ids
    cw_review_count = 0
    for r in apr_top20:
        s = sponsor_by_co.get(r["company_id"])
        if s and s.get("next_review_date"):
            d = date.fromisoformat(s["next_review_date"])
            if cw[0] <= d <= cw[1]:
                cw_review_count += 1

    # CL-03 — April ENT renewals + sponsor depth
    apr_ent_renewals = [r for r in renewals if r["segment"] == "enterprise"
                        and r.get("renewal_signed_date", "").startswith("2026-04")]
    apr_ent_deepened = [r for r in apr_ent_renewals
                        if sponsor_by_co.get(r["company_id"], {}).get("depth_change_q1_2026") == "deepened"]

    # CL-04 — Q2 segment GRR + renewing book
    fl_q2_mm = next((r for r in forecast_log if r["quarter"] == "Q2_2026" and r["segment"] == "mid-market"), {})
    fl_q2_ent = next((r for r in forecast_log if r["quarter"] == "Q2_2026" and r["segment"] == "enterprise"), {})
    fl_q2_smb = next((r for r in forecast_log if r["quarter"] == "Q2_2026" and r["segment"] == "small-business"), {})

    # CL-05 / CL-15 — Beacon renewal + product launch
    beacon = next((c for c in companies if c.get("name") == "Beacon Logistics"), None)
    beacon_renewal = next((r for r in renewals
                           if beacon and r["company_id"] == beacon["id"]
                           and r.get("original_renewal_date") == "2026-07-15"), None)
    pl_002 = next((p for p in launches if p["id"] == "PL-002"), None)

    # CL-06 — Q2 MM NRR vs trailing + Atlas Insights MM expansion
    q2_mm_ren = [r for r in renewals if r["quarter"] == "Q2_2026" and r["segment"] == "mid-market"]
    q2_mm_nrr = q2_mm_ren[0]["nrr"] if q2_mm_ren else 0
    trailing_mm_nrrs = [r["nrr"] for r in renewals if r["quarter"] in ("Q1_2026", "Q4_2025", "Q3_2025") and r["segment"] == "mid-market"]
    trailing_mm_nrr = (sum(trailing_mm_nrrs) / len(trailing_mm_nrrs)) if trailing_mm_nrrs else 0
    insights_mm = [r for r in adoption
                   if "atlas-insights" in r["products"]
                   and by_co.get(r["company_id"], {}).get("segment") == "mid-market"]
    insights_mm_expanded = sum(1 for r in insights_mm if r.get("expanded_q2_2026"))

    # CL-07 — multi-product NRR
    multi = [r for r in adoption if r["is_multi_product"]]
    single = [r for r in adoption if not r["is_multi_product"]]
    multi_q2_nrr = (sum(r["nrr_q2_2026"] for r in multi) / len(multi)) if multi else 0
    single_q2_nrr = (sum(r["nrr_q2_2026"] for r in single) / len(single)) if single else 0
    multi_q1_nrr = (sum(r["nrr_q1_2026"] for r in multi) / len(multi)) if multi else 0
    single_q1_nrr = (sum(r["nrr_q1_2026"] for r in single) / len(single)) if single else 0
    multi_share = (len(multi) / len(adoption)) if adoption else 0

    # CL-08 — MM TTFV cohorts
    mm_q2_co = next((c for c in cohorts if c["cohort_quarter"] == "Q2_2026" and c["segment"] == "mid-market"), {})
    mm_q1_co = next((c for c in cohorts if c["cohort_quarter"] == "Q1_2026" and c["segment"] == "mid-market"), {})

    # CL-09 — expansion source mix
    apr_cs = [e for e in expansion if e["source"] == "customer_health_review" and e.get("month") == "2026-04"]
    apr_cs_total = sum(e["amount"] for e in apr_cs)
    mar_cs = [e for e in expansion if e["source"] == "customer_health_review" and e.get("month") == "2026-03"]
    mar_cs_acc = sum(1 for e in mar_cs if e.get("sales_accepted"))
    mar_ob = [e for e in expansion if e["source"] == "outbound" and e.get("month") == "2026-03"]
    mar_ob_acc = sum(1 for e in mar_ob if e.get("sales_accepted"))

    # CL-10 — MM license utilization
    mm_adopt = [r for r in adoption if by_co.get(r["company_id"], {}).get("segment") == "mid-market"]
    q2_high = sum(1 for r in mm_adopt if r["license_util_q2_2026"] >= 0.80)
    q1_high = sum(1 for r in mm_adopt if r["license_util_q1_2026"] >= 0.80)

    # CL-11 — health score distribution + retention by color
    q2_h = [h for h in health if h["quarter"] == "Q2_2026"]
    q1_h = [h for h in health if h["quarter"] == "Q1_2026"]
    q2_green = sum(1 for h in q2_h if h["color"] == "green")
    q1_green = sum(1 for h in q1_h if h["color"] == "green")
    q1_yellow = [h for h in q1_h if h["color"] == "yellow"]
    q1_green_rows = [h for h in q1_h if h["color"] == "green"]
    green_renewed = sum(1 for h in q1_green_rows if h.get("renewed"))
    yellow_renewed = sum(1 for h in q1_yellow if h.get("renewed"))

    # CL-12 — cohort retention all-segments
    q1_all_co = next((c for c in cohorts if c["cohort_quarter"] == "Q1_2026" and c["segment"] == "all"), {})
    q4_all_co = next((c for c in cohorts if c["cohort_quarter"] == "Q4_2025" and c["segment"] == "all"), {})

    # CL-13 — coverage tier
    high_tier = [r for r in coverage if r["tier"] == "high-touch"]
    tech_tier = [r for r in coverage if r["tier"] == "tech-touch"]
    high_grr = high_tier[0]["grr_q2_2026"] if high_tier else 0
    tech_grr = tech_tier[0]["grr_q2_2026"] if tech_tier else 0
    high_grr_q1 = high_tier[0]["grr_q1_2026"] if high_tier else 0
    tech_grr_q1 = tech_tier[0]["grr_q1_2026"] if tech_tier else 0
    high_share = (len(high_tier) / len(coverage)) if coverage else 0

    L: List[str] = []
    L.append("ATLAS SAAS — CUSTOMER DATA SNAPSHOT (as of 2026-04-24)")
    L.append("")
    L.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. Gainsight is the system of record for renewals and health; Salesforce for renewal events; Mixpanel for product engagement; Pendo for license utilization.")
    L.append("")

    L.append("# Forecast and renewal accuracy")
    if fl_q2_all:
        var_pct = fl_q2_all.get("variance_pct", 0) * 100
        L.append(f"- Q2 2026 renewing book ARR: ${fl_q2_all.get('renewing_book_arr', 0):,}. Forecast ARR: ${fl_q2_all.get('forecast_arr', 0):,}. Actual ARR: ${fl_q2_all.get('actual_arr', 0):,}. Variance: {var_pct:.1f}%.")
    L.append(f"- Trailing four quarter forecast variance average: {trailing_var_avg*100:.1f}%.")
    if fl_q2_mm:
        L.append(f"- Q2 2026 mid-market renewing book: ${fl_q2_mm.get('renewing_book_arr', 0):,}. GRR: {fl_q2_mm.get('grr', 0)*100:.0f}%. NRR: {fl_q2_mm.get('nrr', 0)*100:.0f}%.")
    if fl_q2_ent:
        L.append(f"- Q2 2026 enterprise renewing book: ${fl_q2_ent.get('renewing_book_arr', 0):,}. GRR: {fl_q2_ent.get('grr', 0)*100:.0f}%. NRR: {fl_q2_ent.get('nrr', 0)*100:.0f}%.")
    if fl_q2_smb:
        L.append(f"- Q2 2026 small-business renewing book: ${fl_q2_smb.get('renewing_book_arr', 0):,}. GRR: {fl_q2_smb.get('grr', 0)*100:.0f}%. NRR: {fl_q2_smb.get('nrr', 0)*100:.0f}%.")
    L.append("")

    L.append("# At-risk pipeline and portfolio")
    L.append(f"- April 2026 at-risk pool: ${apr_total:,} ARR across {len(apr)} accounts. Of which top-20-ARR accounts: {len(apr_top20)}.")
    L.append(f"- March 2026 at-risk pool: ${mar_total:,} ARR across {len(mar)} accounts. Of which top-20-ARR accounts: {len(mar_top20)}.")
    L.append(f"- Net change month over month: {len(dropped_off)} dropped off; {len(added)} added.")
    L.append(f"- Top-20 at-risk accounts with executive sponsor review on the calendar this week (Apr 20-26): {cw_review_count}.")
    L.append("")

    L.append("# Renewal sentiment and signing")
    L.append(f"- April 2026 enterprise renewals signed: {len(apr_ent_renewals)}. Of those, {len(apr_ent_deepened)} have an executive sponsor whose depth deepened during Q1 2026.")
    if beacon and beacon_renewal:
        L.append(f"- Beacon Logistics: ${beacon_renewal['renewed_arr']:,} renewal signed {beacon_renewal['renewal_signed_date']}; original contract end date {beacon_renewal['original_renewal_date']}.")
    L.append("")

    L.append("# NRR composition and product breadth")
    L.append(f"- Q2 2026 mid-market NRR: {q2_mm_nrr*100:.0f}%. Trailing three-quarter mid-market NRR average: {trailing_mm_nrr*100:.1f}%.")
    L.append(f"- Mid-market customers running Atlas Insights: {len(insights_mm)}. Of those, {insights_mm_expanded} expanded ARR during Q2 2026.")
    L.append(f"- Multi-product customers Q2 2026 NRR: {multi_q2_nrr*100:.0f}% across {len(multi)} accounts. Single-product customers Q2 2026 NRR: {single_q2_nrr*100:.0f}% across {len(single)} accounts.")
    L.append(f"- Multi-product customers Q1 2026 NRR: {multi_q1_nrr*100:.0f}%. Single-product customers Q1 2026 NRR: {single_q1_nrr*100:.0f}%.")
    L.append(f"- Multi-product share of customer base: {multi_share*100:.1f}%.")
    L.append("")

    L.append("# Time to first value and cohorts")
    if mm_q2_co:
        L.append(f"- Q2 2026 mid-market new-customer cohort time to first value: {mm_q2_co.get('ttfv_days')} days across {mm_q2_co.get('n_accounts')} accounts.")
    if mm_q1_co:
        L.append(f"- Q1 2026 mid-market new-customer cohort time to first value: {mm_q1_co.get('ttfv_days')} days across {mm_q1_co.get('n_accounts')} accounts.")
        L.append(f"- Q1 2026 mid-market cohort renewal rate by TTFV: under 30 days {mm_q1_co.get('renewal_rate_under_30d_ttfv', 0)*100:.0f}%; over 60 days {mm_q1_co.get('renewal_rate_over_60d_ttfv', 0)*100:.0f}%.")
    if q1_all_co:
        L.append(f"- Q1 2026 all-segments new-customer cohort 90-day retention: {q1_all_co.get('retention_90d', 0)*100:.0f}% across {q1_all_co.get('n_accounts')} accounts. TTFV: {q1_all_co.get('ttfv_days')} days.")
    if q4_all_co:
        L.append(f"- Q4 2025 all-segments new-customer cohort 90-day retention: {q4_all_co.get('retention_90d', 0)*100:.0f}% across {q4_all_co.get('n_accounts')} accounts. TTFV: {q4_all_co.get('ttfv_days')} days.")
    L.append("")

    L.append("# Expansion sources")
    L.append(f"- April 2026 expansion opportunities sourced from customer health reviews: {len(apr_cs)}, total ${apr_cs_total:,}.")
    if mar_cs:
        L.append(f"- March 2026 customer-health-review expansion opportunities: {len(mar_cs)}, sales accepted {mar_cs_acc} ({(mar_cs_acc/len(mar_cs))*100:.0f}%).")
    if mar_ob:
        L.append(f"- March 2026 outbound expansion opportunities: {len(mar_ob)}, sales accepted {mar_ob_acc} ({(mar_ob_acc/len(mar_ob))*100:.0f}%).")
    L.append("")

    L.append("# License utilization (mid-market)")
    L.append(f"- Mid-market customers above 80% license utilization in Q2 2026: {q2_high}.")
    L.append(f"- Mid-market customers above 80% license utilization in Q1 2026: {q1_high}.")
    L.append("")

    L.append("# Health score distribution and retention")
    if q2_h:
        L.append(f"- Q2 2026 mid-market health distribution: {(q2_green/len(q2_h))*100:.0f}% green ({q2_green}/{len(q2_h)}).")
    if q1_h:
        L.append(f"- Q1 2026 mid-market health distribution: {(q1_green/len(q1_h))*100:.0f}% green ({q1_green}/{len(q1_h)}).")
    if q1_green_rows:
        L.append(f"- Q1 2026 green-health customers renewed: {(green_renewed/len(q1_green_rows))*100:.0f}% ({green_renewed}/{len(q1_green_rows)}).")
    if q1_yellow:
        L.append(f"- Q1 2026 yellow-health customers renewed: {(yellow_renewed/len(q1_yellow))*100:.0f}% ({yellow_renewed}/{len(q1_yellow)}).")
    L.append("")

    L.append("# Coverage model")
    L.append(f"- High-touch coverage Q2 2026 GRR: {high_grr*100:.0f}% across {len(high_tier)} accounts ({high_share*100:.1f}% of customer base, top by ARR).")
    L.append(f"- Tech-touch coverage Q2 2026 GRR: {tech_grr*100:.0f}% across {len(tech_tier)} accounts.")
    L.append(f"- Q1 2026 GRR by tier: high-touch {high_grr_q1*100:.0f}%; tech-touch {tech_grr_q1*100:.0f}%.")
    L.append("")

    L.append("# Product launches (downstream signal)")
    if pl_002:
        L.append(f"- {pl_002['name']} ships {pl_002['launch_date']}.")
    L.append("")

    return "\n".join(L)


def build_marketing_strategist_summary(ds: Dict[str, list]) -> str:
    """Dense, factual snapshot for the Marketing Strategist (PMM / Director of PMM).

    Cuts tuned to the four Marketing Strategist Goal Clusters:
    Messaging and Positioning, Sales Enablement, Launch and GTM Execution,
    Generating Qualified Pipeline. Cross-functional bridges to Revenue
    (competitive outcomes, pipeline attribution) and CS (exit interview themes)
    are surfaced as their own sections.
    """
    ci = ds.get("competitive_intel", [])
    dc = ds.get("discovery_calls", [])
    icp = ds.get("icp_analysis", [])
    mp = ds.get("messaging_performance", [])
    la = ds.get("launch_attribution", [])
    le = ds.get("launch_enablement", [])
    em = ds.get("earned_media", [])
    crm = ds.get("crm_hygiene", [])
    csei = ds.get("cs_exit_interviews", [])
    launches = ds.get("product_launches", [])

    beacon = next((r for r in ci if r["competitor_id"] == "Beacon Systems" and r["period"] == "Q2_2026"), {})
    northstar = next((r for r in ci if r["competitor_id"] == "Northstar Platform" and r["period"] == "Q2_2026"), {})
    verge = next((r for r in ci if r["competitor_id"] == "Verge IO" and r["period"] == "Q2_2026"), {})
    dc_apr = next((r for r in dc if r["period"] == "2026-04"), {})
    q2_icp = next((r for r in icp if r["period"] == "Q2_2026"), {})
    q1_icp = next((r for r in icp if r["period"] == "Q1_2026"), {})
    mm_rp = next((r for r in mp if r["frame"] == "refreshed_positioning" and r["segment"] == "mid-market"), {})
    ent_rp = next((r for r in mp if r["frame"] == "refreshed_positioning" and r["segment"] == "enterprise"), {})
    ent_hook = next((r for r in mp if r["frame"] == "new_positioning_hook" and r["segment"] == "enterprise"), {})
    la_apr8 = next((r for r in la if r.get("launch_id") == "PL-MS-001" and r.get("attribution_window") == "3_weeks"), {})
    la_prior = next((r for r in la if r.get("launch_id") == "PL-000" and r.get("attribution_window") == "3_weeks"), {})
    la_q2 = next((r for r in la if r.get("period") == "Q2_2026" and r.get("attribution_window") == "quarter"), {})
    le_apr8 = next((r for r in le if r.get("launch_id") == "PL-MS-001"), {})
    le_may15 = next((r for r in le if r.get("launch_id") == "PL-MS-002"), {})
    em_apr8 = next((r for r in em if r.get("launch_id") == "PL-MS-001"), {})
    q2_crm = next((r for r in crm if r["period"] == "Q2_2026"), {})
    q1_crm = next((r for r in crm if r["period"] == "Q1_2026"), {})
    cs_apr = next((r for r in csei if r["period"] == "2026-04"), {})

    L: List[str] = []
    L.append("ATLAS SAAS — MARKETING STRATEGIST DATA SNAPSHOT (as of 2026-04-24)")
    L.append("")
    L.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. Gong for call analytics; Salesforce CRM for win/loss and deal records; Outreach for sales engagement; HubSpot for inbound tracking.")
    L.append("")

    L.append("# Messaging and positioning effectiveness")
    if dc_apr:
        frame_results = dc_apr.get("frame_results", [])
        stv = next((f for f in frame_results if f["frame"] == "speed_to_value"), {})
        pc = next((f for f in frame_results if f["frame"] == "platform_consolidation"), {})
        if stv and pc:
            L.append(f"- April 2026 Gong-sampled discovery calls: {dc_apr['calls_sampled']} calls sampled. Speed-to-value frame re-stated: {stv['resonance_rate']*100:.0f}% ({stv['count']} calls). Platform-consolidation frame re-stated: {pc['resonance_rate']*100:.0f}% ({pc['count']} calls).")
            L.append(f"- Context: Speed-to-value was the dominant frame in Q1 of last year before the rebrand.")
    if mm_rp and ent_rp:
        L.append(f"- Refreshed positioning (speed-to-value hierarchy) Q2 2026 close rates: mid-market {mm_rp['close_rate']*100:.0f}%, enterprise {ent_rp['close_rate']*100:.0f}% on the same message hierarchy.")
    if q2_icp and q1_icp:
        L.append(f"- ICP match rate on new logos: Q2 2026 {q2_icp['icp_matched']}/{q2_icp['closed_won_total']} = {q2_icp['icp_match_rate']*100:.0f}%; Q1 2026 {q1_icp['icp_matched']}/{q1_icp['closed_won_total']} = {q1_icp['icp_match_rate']*100:.0f}%.")
    if q2_icp.get("icp_cycle_advantage_days"):
        L.append(f"- ICP-aligned wins close {q2_icp['icp_cycle_advantage_days']} days faster on average than non-ICP wins.")
    L.append("")

    L.append("# Competitive intelligence — Beacon Systems (Competitor A)")
    if beacon:
        L.append(f"- Q2 2026 Beacon Systems competitive opportunities: {beacon['total_competitive_opps']} total. Head-to-head deals: {beacon['h2h_deals']}. Wins: {beacon['wins']}. Losses: {beacon['losses']}. Win rate: {beacon['win_rate']*100:.1f}%.")
        L.append(f"- Prior four-quarter average Beacon Systems win rate: {beacon['prior_4q_win_rate']*100:.0f}%.")
        L.append(f"- Battlecard opens Q2 2026: {beacon['battlecard_opens']} of {beacon['total_competitive_opps']} competitive opportunities ({beacon['battlecard_util']*100:.0f}%). Q1 2026 battlecard utilization: {beacon['prior_q_battlecard_util']*100:.0f}%.")
    L.append("")

    L.append("# Competitive intelligence — Northstar Platform (Competitor B)")
    if northstar:
        L.append(f"- Northstar Platform objection-handling section added to battlecard on {northstar['event_date']}.")
        L.append(f"- Win rate on Northstar head-to-heads: pre-April 8 {northstar['win_rate_pre_event']*100:.0f}%; post-April 8 {northstar['win_rate_post_event']*100:.0f}%.")
        L.append(f"- Northstar mentions in Gong: {abs(northstar['gong_mentions_change_pct'])*100:.0f}% decrease in the four weeks following the objection section update.")
    L.append("")

    L.append("# Competitive intelligence — Verge IO (Competitor C)")
    if verge:
        L.append(f"- Verge IO appeared in {verge['h2h_deals']} of {verge['total_competitive_opps']} Q2 2026 competitive opportunities ({verge['appearance_pct']*100:.0f}%). Q1 2026: {verge['prior_q_appearance_pct']*100:.0f}%.")
        L.append(f"- Segment concentration: highest in {verge['segment_concentration']}.")
    if verge.get("series_b_date"):
        L.append(f"- Verge IO external event: ${verge['series_b_amount_m']}M Series B raised {verge['series_b_date']}.")
    L.append("")

    L.append("# Sales enablement")
    if le_apr8 and le_apr8.get("pipeline_by_asset_openers_vs_nonopeners_multiple"):
        L.append(f"- Reps who opened launch assets produced {le_apr8['pipeline_by_asset_openers_vs_nonopeners_multiple']}x the pipeline of those who did not (April 8 launch, first 14 days).")
    if q2_crm and q1_crm:
        L.append(f"- Outcome reason capture rate in CRM: Q2 2026 {q2_crm['outcome_reason_captured']}/{q2_crm['closed_deals_total']} closed deals = {q2_crm['capture_rate']*100:.0f}%. Q1 2026: {q1_crm['capture_rate']*100:.0f}%.")
    L.append("")

    L.append("# Launch and GTM execution")
    pl_apr8 = next((p for p in launches if p.get("id") == "PL-MS-001"), {})
    pl_may15 = next((p for p in launches if p.get("id") == "PL-MS-002"), {})
    if pl_apr8:
        L.append(f"- {pl_apr8['name']} launched {pl_apr8['launch_date']} (status: {pl_apr8['status']}).")
    if la_apr8:
        L.append(f"- April 8 launch pipeline (first 3 weeks): {la_apr8['opportunities_created']} new opportunities, ${la_apr8['pipeline_usd']:,} total pipeline.")
    if la_prior:
        L.append(f"- Prior launch (October) first-3-week pipeline: ${la_prior['pipeline_usd']:,}.")
    if le_apr8 and le_apr8.get("reps_total"):
        L.append(f"- April 8 launch enablement asset adoption (first 14 days): {le_apr8['reps_opened_assets_14d']} of {le_apr8['reps_total']} reps opened battlecard or one-pager ({le_apr8['asset_adoption_rate_14d']*100:.0f}%). Prior launch adoption: {le_apr8['prior_launch_asset_adoption_rate']*100:.0f}%.")
        L.append(f"- Pipeline from asset-opening reps: {le_apr8['pipeline_by_asset_openers_vs_nonopeners_multiple']}x the pipeline from non-opening reps.")
    if pl_may15:
        L.append(f"- {pl_may15['name']} planned launch {pl_may15['launch_date']} (status: {pl_may15['status']}).")
    if le_may15 and le_may15.get("days_cleared_before_launch"):
        L.append(f"- May 15 launch readiness: {le_may15['readiness_items_cleared']}/{le_may15['readiness_items_count']} items cleared (positioning brief, battlecard update, sales briefing). Signed off {le_may15['readiness_signoff_date']}, {le_may15['days_cleared_before_launch']} days before ship. Prior launch: positioning brief signed off {le_may15['prior_launch_days_cleared_before']} days before ship.")
    L.append("")

    L.append("# Pipeline and launch attribution")
    if ent_hook:
        L.append(f"- Enterprise inbound pipeline with new positioning hook Q2 2026: ${ent_hook['pipeline_usd']:,}. Inbound-to-meeting conversion lift: {ent_hook['inbound_conversion_lift_pct']} points.")
    if la_q2:
        L.append(f"- Q2 2026 total net new pipeline: ${la_q2['total_period_pipeline_usd']:,}. Launch-attributable: ${la_q2['pipeline_usd']:,} ({la_q2['launch_share_pct']*100:.0f}% of Q2 net new).")
    L.append("")

    L.append("# Earned media")
    if em_apr8:
        L.append(f"- April 8 launch earned media: {em_apr8['publications_picked_up']} of {em_apr8['publications_outreached']} outreached publications picked up the announcement ({em_apr8['pickup_rate']*100:.0f}%). Prior launch: {em_apr8['prior_launch_pickup_rate']*100:.0f}% pickup rate.")
        L.append(f"- Launch-attributable pipeline in first 7 days: {em_apr8['pipeline_7d_vs_prior_multiple']}x the prior launch's first-7-day pipeline.")
    L.append("")

    L.append("# Cross-functional: CS exit interview themes")
    if cs_apr:
        L.append(f"- April 2026 customer exit interviews: {cs_apr['interviews_conducted']} interviews conducted, {cs_apr['themes_identified']} themes surfaced, {cs_apr['themes_feeding_positioning']} feeding the positioning revision.")
        themes = cs_apr.get("positioning_themes", [])
        if themes:
            L.append(f"- Positioning themes: \"{themes[0]}\" and \"{themes[1]}\".")
        if cs_apr.get("competitor_a_overlap_pct"):
            comp_name = cs_apr.get("competitor_a_id", "Beacon Systems")
            L.append(f"- Both themes appear in {comp_name} competitive deals {cs_apr['competitor_a_overlap_pct']*100:.0f}% of the time in Q2 2026.")
    L.append("")

    return "\n".join(L)


def build_marketing_builder_summary(ds: Dict[str, list]) -> str:
    """Dense, factual snapshot for the Marketing Builder (Demand Gen / MOps / Campaigns).

    Cuts tuned to the four Marketing Builder Goal Clusters:
    Demand Generation, Content and Organic Growth, Marketing Operations,
    Sales Enablement Support. Cross-functional bridges to Revenue Developer
    (speed-to-lead) and Revenue Operator (attribution chain) surfaced as
    their own sections.
    """
    paid = ds.get("mb_paid_performance", [])
    mql_src = ds.get("mb_mql_sources", [])
    demos = ds.get("mb_inbound_demos", [])
    seo = ds.get("mb_seo_keywords", [])
    organic = ds.get("mb_organic_traffic", [])
    content = ds.get("mb_content_attribution", [])
    routing = ds.get("mb_routing_ops", [])
    attr = ds.get("mb_attribution_accuracy", [])
    hygiene = ds.get("mb_mql_hygiene", [])
    assets = ds.get("mb_sales_enablement_assets", [])

    apr_paid = next((r for r in paid if r["period"] == "2026-04"), {})
    apr_mql = next((r for r in mql_src if r["period"] == "2026-04"), {})
    apr_demos = next((r for r in demos if r["period"] == "2026-04"), {})
    mar_demos = next((r for r in demos if r["period"] == "2026-03"), {})
    kw_pricing = next((r for r in seo if r["keyword"] == "saas pricing models"), {})
    kw_attr = next((r for r in seo if r["keyword"] == "saas attribution"), {})
    kw_routing = next((r for r in seo if r["keyword"] == "b2b lead routing"), {})
    kw_checklist = next((r for r in seo if r["keyword"] == "marketing ops checklist"), {})
    comp_hub = next((r for r in organic if r["page"] == "comparison_hub"), {})
    q2_content = next((r for r in content if r["period"] == "Q2_2026"), {})
    apr_routing = next((r for r in routing if r["period"] == "2026-04"), {})
    mar_routing = next((r for r in routing if r["period"] == "2026-03"), {})
    q2_attr = next((r for r in attr if r["period"] == "Q2_2026"), {})
    q1_attr = next((r for r in attr if r["period"] == "Q1_2026"), {})
    apr_hygiene = next((r for r in hygiene if r["period"] == "2026-04"), {})
    mar_hygiene = next((r for r in hygiene if r["period"] == "2026-03"), {})
    battlecard = next((r for r in assets if r["asset_type"] == "battlecard"), {})
    calculator = next((r for r in assets if r["asset_type"] == "roi_calculator"), {})

    L: List[str] = []
    L.append("ATLAS SAAS — MARKETING BUILDER DATA SNAPSHOT (as of 2026-04-24)")
    L.append("")
    L.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. Marketo for marketing automation; Salesforce CRM for pipeline and attribution; HubSpot for inbound tracking; Highspot for sales asset management; LinkedIn for paid ABM.")
    L.append("")

    L.append("# Demand generation — paid channel")
    if apr_paid:
        L.append(f"- April paid pipeline pacing: ${apr_paid['pipeline_at_week3_usd']:,} of ${apr_paid['pipeline_target_usd']:,} monthly target landed by {apr_paid['week3_date']} (week 3).")
        L.append(f"- LinkedIn CPL across weeks 1-3 of April: ${apr_paid['week3_cpl_linkedin']}. Full-month April CPL: ${apr_paid['full_month_cpl_linkedin']}. March CPL: ${apr_paid['prior_month_cpl']} (month-over-month climb {apr_paid['march_cpl_mom_climb_pct']*100:.0f}%). Q1 average CPL: ${apr_paid['q1_avg_cpl']}.")
        L.append(f"- April 1 LinkedIn audience refresh applied to {apr_paid['campaigns_in_refresh']} campaigns covering {apr_paid['budget_share_refreshed']*100:.0f}% of paid budget.")
    L.append("")

    L.append("# Demand generation — MQL sources")
    if apr_mql:
        webinar_src = next((s for s in apr_mql.get("sources", []) if s["source"] == "webinar_apr9"), {})
        paid_src = next((s for s in apr_mql.get("sources", []) if s["source"] == "paid_social"), {})
        if webinar_src:
            L.append(f"- April 2026 total MQLs: {apr_mql['total_mqls']}. Webinar campaign (April 9): {webinar_src['mqls']} MQLs in {webinar_src['window_days']} days = {webinar_src['share']*100:.0f}% of April total. Highest concentration in {webinar_src['segment_concentration']}.")
            L.append(f"- Webinar-sourced MQL-to-SQL conversion rate: {webinar_src['sql_conversion_rate']*100:.0f}%. Paid social MQL-to-SQL: {paid_src['sql_conversion_rate']*100:.0f}% in the same window.")
    L.append("")

    L.append("# Demand generation — inbound demo requests")
    if apr_demos and mar_demos:
        L.append(f"- April 2026 inbound demo requests: {apr_demos['demo_requests']} ({apr_demos['mid_market']} mid-market, {apr_demos['enterprise']} enterprise). March 2026: {mar_demos['demo_requests']}.")
        L.append(f"- Homepage CTA test live {apr_demos['cta_test_live_date']}. Demo-form conversion lift: {apr_demos['cta_conversion_lift_pct']*100:.0f}%.")
    L.append("")

    L.append("# Content and organic growth — SEO keyword rankings")
    if kw_pricing:
        L.append(f"- \"saas pricing models\": moved from position {kw_pricing['position_before']} to position {kw_pricing['position_after']} in {kw_pricing['days_to_move']} days (week ending {kw_pricing['week_ending']}). Monthly search volume: {kw_pricing['monthly_search_volume']:,}. Post refreshed {kw_pricing['page_refresh_date']}.")
    top3_kws = [r for r in [kw_attr, kw_routing, kw_checklist] if r]
    if top3_kws:
        kw_names = ", ".join(f"\"{r['keyword']}\"" for r in top3_kws)
        L.append(f"- {kw_names}: all moved into top-3 positions in week ending {top3_kws[0]['week_ending']}. All started from page-2 positions. All pages rewritten with structured FAQ sections in March.")
    L.append("")

    L.append("# Content and organic growth — comparison hub traffic")
    if comp_hub:
        L.append(f"- Comparison hub sessions: {comp_hub['sessions']:,} in April vs {comp_hub['prior_sessions']:,} in March ({comp_hub['change_pct']*100:.0f}% increase).")
        L.append(f"- {comp_hub['top_subpage'].replace('_', ' ').title()} comparison page: {comp_hub['top_subpage_sessions']:,} sessions.")
        L.append(f"- AI Overview presence on \"{comp_hub['ai_overview_query_type']}\" queries: {comp_hub['ai_overview_coverage_before']*100:.0f}% before comparison hub refresh, {comp_hub['ai_overview_coverage_after']*100:.0f}% after.")
    L.append("")

    L.append("# Content and organic growth — content pipeline attribution")
    if q2_content:
        L.append(f"- Q2 2026 content-attributable pipeline: {q2_content['pieces_with_pipeline']} of {q2_content['pieces_total_published']} published pieces carry a touched-deal flag. Total: ${q2_content['pipeline_total_usd']:,}.")
        L.append(f"- Top piece (buyer's guide): ${q2_content['top_piece_pipeline_usd']:,} in pipeline. Week-over-week view growth since gated download went live: {q2_content['top_piece_wow_view_growth_pct']*100:.0f}%.")
    L.append("")

    L.append("# Marketing operations — inbound routing SLA")
    if apr_routing and mar_routing:
        L.append(f"- April 2026 inbound routing SLA (5-minute threshold): {apr_routing['demos_routed']} of {apr_routing['demos_total']} demos routed inside SLA = {apr_routing['sla_pct']*100:.0f}%. March: {mar_routing['demos_routed']} of {mar_routing['demos_total']} = {mar_routing['sla_pct']*100:.0f}%.")
        if apr_routing.get("routing_update_date"):
            L.append(f"- Routing update {apr_routing['routing_update_date']}: {apr_routing['routing_update_description']}.")
    L.append("")

    L.append("# Marketing operations — MQL field completeness")
    if apr_hygiene and mar_hygiene:
        L.append(f"- April 2026 MQL field completeness (UTM, channel, persona): {apr_hygiene['mqls_complete']} of {apr_hygiene['mqls_total']} MQLs complete = {apr_hygiene['completeness_pct']*100:.0f}%. March: {mar_hygiene['completeness_pct']*100:.0f}%.")
        if apr_hygiene.get("form_scoring_date"):
            L.append(f"- Form-fill scoring threshold went live {apr_hygiene['form_scoring_date']} across {apr_hygiene['forms_updated']} forms.")
    L.append("")

    L.append("# Marketing operations — attribution accuracy")
    if q2_attr and q1_attr:
        L.append(f"- Q2 2026 Marketo-Salesforce sourcing mismatch: {q2_attr['mismatch_opps']} of {q2_attr['sourced_opps_total']} sourced opportunities = {q2_attr['variance_pct']*100:.1f}% variance. Q1 2026 variance: {q1_attr['variance_pct']*100:.1f}%.")
        if q2_attr.get("utm_cleanup_date"):
            L.append(f"- UTM-stamping cleanup {q2_attr['utm_cleanup_date']} applied to {q2_attr['campaigns_cleaned']} paid campaigns.")
    L.append("")

    L.append("# Sales enablement support — battlecard adoption")
    if battlecard:
        L.append(f"- Battlecard library April 2026: {battlecard['total_opens']} opens from {battlecard['unique_reps']} of {battlecard['total_reps']} active reps. Competitor A card: {battlecard['top_card_opens']} opens.")
        if battlecard.get("refresh_date"):
            L.append(f"- Competitor A battlecard refresh shipped {battlecard['refresh_date']}.")
    L.append("")

    L.append("# Sales enablement support — ROI calculator adoption")
    if calculator:
        L.append(f"- ROI calculator (live {calculator['asset_live_date']}, first {calculator['days_since_launch']} days): {calculator['deals_with_asset']} of {calculator['deals_total_active']} active {calculator['segment']} deals carry a calculator-attached note. {calculator['deals_to_proposal']} progressing to proposal stage.")
        L.append(f"- Average deal size: ${calculator['deal_size_with_asset_usd']:,} with calculator versus ${calculator['deal_size_without_asset_usd']:,} without.")
    L.append("")

    L.append("# Cross-functional: speed-to-lead (Marketing Builder → Revenue Developer)")
    if apr_routing:
        L.append(f"- Median speed-to-lead on inbound demos: {apr_routing['median_speed_to_lead_minutes']} minutes in April vs {mar_routing['median_speed_to_lead_minutes'] if mar_routing else 'N/A'} minutes in March.")
        if apr_routing.get("sql_conversion_under5min_multiple"):
            L.append(f"- SQL conversion on under-5-minute touches: {apr_routing['sql_conversion_under5min_multiple']}x the rate of over-15-minute touches in the same window.")
    L.append("")

    L.append("# Cross-functional: closed-loop attribution (Marketing Builder → Revenue Operator)")
    if q2_attr and q1_attr:
        L.append(f"- April pipeline with clean Marketo-to-Salesforce attribution chain: ${q2_attr['pipeline_with_clean_attribution_usd']:,} of ${q2_attr['pipeline_total_usd']:,} = {q2_attr['attribution_coverage_pct']*100:.0f}%. Q1 average coverage: {q1_attr['attribution_coverage_pct']*100:.0f}%.")
        if q2_attr.get("attribution_mapping_date"):
            L.append(f"- Shared attribution mapping with RevOps locked {q2_attr['attribution_mapping_date']}, covering {q2_attr['campaign_types_covered']} campaign types.")
    L.append("")

    return "\n".join(L)


def build_revenue_generator_summary(ds: Dict[str, list]) -> str:
    """Dense, factual snapshot for the Revenue Generator (AE / Account Executive).

    Cuts tuned to the four Revenue Generator Goal Clusters: Closing Deals in
    Flight, Pipeline Quality and Coverage, Deal Execution Efficiency, Competitive
    Winning. Cross-functional bridges to Marketing Strategist (battlecards) and
    Customer Advocate (expansion handoff) are surfaced as their own sections.
    """
    threads = ds.get("rg_deal_threads", [])
    champion = ds.get("rg_champion_status", [])
    committee = ds.get("rg_buying_committee", [])
    coverage = ds.get("rg_pipeline_coverage", [])
    win_rates = ds.get("rg_win_rates", [])
    hygiene = ds.get("rg_deal_hygiene", [])
    sequences = ds.get("rg_outbound_sequences", [])
    competitive = ds.get("rg_competitive_coverage", [])
    battlecard = ds.get("rg_battlecard_usage", [])
    expansion = ds.get("rg_expansion_flags", [])

    def _get(lst, key, val):
        return next((r for r in lst if r.get(key) == val), {})

    thr_q2 = _get(threads, "period", "Q2_2026")
    thr_q1 = _get(threads, "period", "Q1_2026")
    champ_apr = _get(champion, "period", "2026-04")
    champ_mar = _get(champion, "period", "2026-03")
    sterling = next((r for r in committee if r.get("company") == "Sterling"), {})
    prop_q2 = next((r for r in committee if r.get("period") == "Q2_2026"
                    and r.get("event_type") == "proposal_advancement"), {})
    prop_q1 = next((r for r in committee if r.get("period") == "Q1_2026"
                    and r.get("event_type") == "proposal_advancement"), {})
    pipe_cov = _get(coverage, "metric", "q3_pipeline_coverage")
    aging = _get(coverage, "metric", "deal_aging_clearance")
    wr_q2 = _get(win_rates, "period", "Q2_2026")
    wr_q1 = _get(win_rates, "period", "Q1_2026")
    freshness = _get(hygiene, "metric", "deal_update_freshness")
    crm_q2 = next((r for r in hygiene if r.get("metric") == "crm_activity_capture"
                   and r.get("period") == "Q2_2026"), {})
    crm_q1 = next((r for r in hygiene if r.get("metric") == "crm_activity_capture"
                   and r.get("period") == "Q1_2026"), {})
    seq_rev = _get(sequences, "cadence_version", "revised_apr5")
    seq_pri = _get(sequences, "cadence_version", "prior")
    beacon_q2 = next((r for r in competitive if r.get("competitor_label") == "competitor_a"
                      and r.get("period") == "Q2_2026"), {})
    beacon_t4q = next((r for r in competitive if r.get("competitor_label") == "competitor_a"
                       and r.get("period") == "trailing_4q"), {})
    comp_b_q2 = next((r for r in competitive if r.get("competitor_label") == "competitor_b"
                      and r.get("period") == "Q2_2026"), {})
    comp_b_q1 = next((r for r in competitive if r.get("competitor_label") == "competitor_b"
                      and r.get("period") == "Q1_2026"), {})
    bc_apr = _get(battlecard, "period", "2026-04")
    bc_feb = _get(battlecard, "period", "2026-02")
    exp = expansion[0] if expansion else {}

    L: List[str] = []
    L.append("ATLAS SAAS — ACCOUNT EXECUTIVE DATA SNAPSHOT (as of 2026-04-24)")
    L.append("")
    L.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. Salesforce is the system of record for pipeline and deal activity; HubSpot for marketing attribution; Gong for call activity.")
    L.append("")

    L.append("# Closing deals in flight — multi-thread and champion depth")
    if thr_q2:
        L.append(f"- Active opportunities above ${thr_q2['avc_threshold_usd']:,} ACV: {thr_q2['active_opps_above_threshold']}. Opps with 4+ engaged contacts (Q2 2026): {thr_q2['opps_with_4plus_contacts']} of {thr_q2['active_opps_above_threshold']}. Q1 2026: {thr_q1.get('opps_with_4plus_contacts', 'n/a')} of {thr_q1.get('active_opps_above_threshold', 'n/a')}.")
        L.append(f"- Average multi-thread depth on $250K+ deals: Q2 {thr_q2['avg_thread_depth']} contacts, Q1 {thr_q1.get('avg_thread_depth', 'n/a')} contacts.")
        L.append(f"- Win rate at 4+ contacts: {thr_q2['win_rate_4plus_contacts']*100:.0f}%. Win rate at 1-2 contacts: {thr_q2['win_rate_1_to_2_contacts']*100:.0f}%.")
    if champ_apr:
        L.append(f"- Champion re-engagement events (champion contact lapse >{champ_apr['champion_gap_threshold_days']} days without a logged interaction): April {champ_apr['reengaged_deals']}, March {champ_mar.get('reengaged_deals', 'n/a')}.")
        L.append(f"- Deals that advanced a stage within 21 days of champion re-engagement (April): {champ_apr['advanced_within_21_days']} of {champ_apr['reengaged_deals']}.")
    if sterling:
        new_roles = ", ".join(sterling.get("new_contacts", []))
        L.append(f"- Sterling enterprise deal: executive demo {sterling['event_date']}. Buying committee before: {sterling['committee_before']} contacts. After: {sterling['committee_after']} contacts ({new_roles} added). Historical close rate for committees that grow during evaluation: {sterling['committee_growth_close_lift_pct']*100:.0f}% above flat committees.")
    if prop_q2:
        L.append(f"- Enterprise Proposal-to-Closed-Won median days: Q2 {prop_q2['enterprise_proposal_to_close_median_days']} days, Q1 {prop_q1.get('enterprise_proposal_to_close_median_days', 'n/a')} days.")
        L.append(f"- Q2 enterprise closes with multi-thread depth 5+: {prop_q2['enterprise_closes_5plus_threads']} of {prop_q2['enterprise_closes_total']}.")
    L.append("")

    L.append("# Pipeline quality and coverage")
    if pipe_cov:
        L.append(f"- Q3 2026 AE quota aggregate: ${pipe_cov['quota_usd']:,}. Open Q3 pipeline: ${pipe_cov['open_pipeline_usd']:,} ({pipe_cov['coverage_ratio']:.1f}x coverage).")
        L.append(f"- Q3 pipeline with live engagement in last 14 days: ${pipe_cov['pipeline_with_live_engagement_14d_usd']:,} ({pipe_cov['live_engagement_share']*100:.0f}% of open pipeline).")
        L.append(f"- Single-threaded coverage share: Q2 {pipe_cov['single_threaded_share']*100:.0f}%, Q1 {pipe_cov['prior_single_threaded_share']*100:.0f}%.")
    if aging:
        L.append(f"- Proposal-stage deals aged >{aging['proposal_stage_aging_threshold_days']} days (as of April): {aging['deals_above_threshold']}. Advanced or closed in last 30 days: {aging['deals_advanced_or_closed']} of {aging['deals_above_threshold']}.")
        L.append(f"- Of those advances, {aging['deals_advanced_within_5d_reissued_proposal']} of {aging['deals_advanced_or_closed']} came within 5 days of a re-issued proposal.")
    if wr_q2:
        L.append(f"- Mid-market win rate: Q2 {wr_q2['win_rate']*100:.1f}% ({wr_q2['wins']}/{wr_q2['total_opps']}), Q1 {wr_q1.get('win_rate', 0)*100:.1f}% ({wr_q1.get('wins', 'n/a')}/{wr_q1.get('total_opps', 'n/a')}). ICP-aligned share of Q2 lift: {wr_q2['icp_aligned_lift_share']*100:.0f}%.")
    if champ_apr:
        L.append(f"- Q2 deals with named Champion field in CRM: {champ_apr['deals_with_champion_field']}, win rate {champ_apr['champion_win_rate']*100:.0f}% ({champ_apr['champion_wins']}/{champ_apr['deals_with_champion_field']}). Without Champion field: {champ_apr['deals_without_champion_field']}, win rate {champ_apr['no_champion_win_rate']*100:.0f}% ({champ_apr['no_champion_wins']}/{champ_apr['deals_without_champion_field']}).")
        L.append(f"- Champion documentation rate (% of active opps with named Champion): {champ_apr['champion_doc_rate_active_opps']*100:.0f}% in Q2 — first time above 50%.")
    L.append("")

    L.append("# Deal execution efficiency")
    if freshness:
        L.append(f"- Active deals (as of {freshness['period']}): {freshness['active_deals']}. Stage notes and next-steps updated in last 5 days: {freshness['updated_within_5_days']} of {freshness['active_deals']} ({freshness['freshness_rate']*100:.0f}%).")
    if crm_q2:
        L.append(f"- CRM activity capture completeness on closed Q2 deals: {crm_q2['fully_captured']} of {crm_q2['closed_deals']} ({crm_q2['capture_rate']*100:.0f}%) carry full activity history, outcome reason, and stakeholder map. Q1 capture rate: {crm_q1.get('capture_rate', 0)*100:.0f}%.")
        L.append(f"- Outcome reason field went live {crm_q2['outcome_reason_field_live_date']}. {crm_q2['captured_post_field_live']} of {crm_q2['fully_captured']} full captures landed after that date.")
    if seq_rev:
        L.append(f"- Outbound sequence-to-meeting conversion (revised cadence, live {seq_rev['cadence_live_date']}): {seq_rev['discovery_meetings_booked']} of {seq_rev['sequenced_contacts']} contacts booked discovery ({seq_rev['conversion_rate']*100:.0f}%). Prior cadence: {seq_pri.get('conversion_rate', 0)*100:.0f}%.")
        L.append(f"- Inbound-to-meeting conversion same window: {seq_rev['inbound_to_meeting_rate']*100:.0f}%.")
    L.append("")

    L.append("# Competitive position")
    if beacon_q2:
        L.append(f"- Head-to-head deals versus Beacon Systems: Q2 {beacon_q2['h2h_wins']}W/{beacon_q2['h2h_losses']}L of {beacon_q2['h2h_total']} ({beacon_q2['h2h_win_rate']*100:.1f}%). Trailing four quarters Beacon h2h win rate: {beacon_t4q.get('h2h_win_rate', 0)*100:.0f}%.")
        L.append(f"- Beacon Systems appeared in {beacon_q2['competitor_appearances']} of {beacon_q2['competitive_opps_total']} competitive opps Q2 ({beacon_q2['competitor_share']*100:.0f}%), versus {beacon_t4q.get('competitor_appearances', 'n/a')} of {beacon_t4q.get('competitive_opps_total', 'n/a')} Q1.")
    if comp_b_q2:
        L.append(f"- Meridian AI (Competitor B) appeared in {comp_b_q2['competitor_appearances']} of {comp_b_q2['active_deals_total']} active deals Q2 ({comp_b_q2['competitor_share']*100:.0f}%), up from {comp_b_q1.get('competitor_appearances', 'n/a')} of {comp_b_q1.get('active_deals_total', 'n/a')} Q1 ({comp_b_q1.get('competitor_share', 0)*100:.0f}%).")
        L.append(f"- Meridian AI Series B: ${comp_b_q2['series_b_amount_usd']:,} announced {comp_b_q2['series_b_date']}. {comp_b_q2['deals_to_negotiation_within_30d_of_series_b']} of {comp_b_q2['competitor_appearances']} Meridian deals reached negotiation within 30 days of announcement.")
    L.append("")

    L.append("# Cross-functional — Marketing Strategist (battlecard) and Customer Advocate (expansion)")
    if bc_apr:
        L.append(f"- Beacon Systems battlecard utilization in active h2h deals: April {bc_apr['battlecard_opened']} of {bc_apr['h2h_deals_active']} ({bc_apr['utilization_rate']*100:.0f}%). February: {bc_feb.get('utilization_rate', 0)*100:.0f}%.")
        L.append(f"- H2h win rate on Beacon deals climbed {bc_apr['h2h_win_rate_change_points']} points same window as utilization increase.")
    if exp:
        L.append(f"- Customer Advocate expansion-ready flags from Q2 onboarding completions: {exp['expansion_ready_flagged']} of {exp['onboarding_completions']} accounts flagged; ${exp['expansion_arr_potential_usd']:,} expansion ARR potential.")
        L.append(f"- Of the {exp['expansion_ready_flagged']} flagged accounts, {exp['with_logged_discovery_touch']} have a logged discovery touch. Avg CSM contacts per expansion-ready account: {exp['avg_csm_contacts_per_expansion_account']}.")
    L.append("")

    return "\n".join(L)


def build_revenue_developer_summary(ds: Dict[str, list]) -> str:
    """Dense, factual snapshot for the Revenue Developer (SDR / BDR).

    Cuts tuned to the four Revenue Developer Goal Clusters: Pipeline Creation
    and Inbound Response, Sequence and Outreach Effectiveness, ICP Targeting
    and Segment Penetration, AE Handoff Quality.
    """
    inbound_speed = ds.get("rd_inbound_speed", [])
    sequence_perf = ds.get("rd_sequence_perf", [])
    subject_test = ds.get("rd_subject_test", [])
    segment_penetration = ds.get("rd_segment_penetration", [])
    intent_outreach = ds.get("rd_intent_outreach", [])
    ae_handoff = ds.get("rd_ae_handoff", [])
    linkedin_inbound = ds.get("rd_linkedin_inbound", [])
    call_timing = ds.get("rd_call_timing", [])
    dormant_reengagement = ds.get("rd_dormant_reengagement", [])
    enterprise_committee = ds.get("rd_enterprise_committee", [])

    def _get(lst, key, val):
        return next((r for r in lst if r.get(key) == val), {})

    stl = _get(inbound_speed, "metric", "current_week_speed_to_lead")
    wkd = _get(inbound_speed, "metric", "weekend_inbound_coverage")
    ch_cmp = _get(sequence_perf, "metric", "channel_comparison")
    touch_dist = _get(sequence_perf, "metric", "touch_step_distribution")
    subj = _get(subject_test, "metric", "subject_line_variant_test")
    first_ln = _get(subject_test, "metric", "first_line_personalization_lift")
    new_vert = _get(segment_penetration, "metric", "new_vertical_penetration")
    vert_conv = _get(segment_penetration, "metric", "vertical_conversion_comparison")
    intent = _get(intent_outreach, "metric", "intent_platform_first_touch")
    trigger = _get(intent_outreach, "metric", "trigger_event_outreach")
    handoff_apr = _get(ae_handoff, "metric", "ae_accepted_rate")
    morning_block = _get(call_timing, "time_window", "8am_to_9am")
    afternoon_block = _get(call_timing, "time_window", "post_lunch_1pm_to_3pm")
    dormant = dormant_reengagement[0] if dormant_reengagement else {}
    committee = enterprise_committee[0] if enterprise_committee else {}

    L: List[str] = []
    L.append("ATLAS SAAS — SDR / REVENUE DEVELOPER DATA SNAPSHOT (as of 2026-04-24)")
    L.append("")
    L.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. Salesforce is the system of record for leads and meetings; Outreach for sequencing; 6sense for intent scoring; HubSpot for inbound demo routing.")
    L.append("")

    L.append("# Pipeline creation and inbound response")
    if stl:
        L.append(f"- Current week inbound demo requests: {stl['total_inbound_leads']}. Reached within {stl['sla_window_minutes']}-minute window: {stl['reached_within_5min']} of {stl['total_inbound_leads']}. Within-window meeting rate: {stl['within_5min_meeting_rate']*100:.0f}%. Meeting rate for leads reached after 30 minutes: {stl['over_30min_meeting_rate']*100:.0f}%.")
    if wkd:
        L.append(f"- Weekend inbound demo requests ({wkd['period'].replace('_to_', ' to ')}): {wkd['total_weekend_requests']}. All {wkd['reached_by_monday_915am']} reached by 9:15 AM Monday. Meetings booked same day: {wkd['booked_same_day']} of {wkd['total_weekend_requests']}.")
    if intent:
        L.append(f"- {intent['platform']} high-intent accounts crossing threshold this week: {intent['accounts_above_threshold']}. Replied on first touch: {intent['first_touch_replies']} of {intent['accounts_above_threshold']}. Booked meetings within 48 hours: {intent['booked_within_48h']}.")
    if trigger:
        L.append(f"- Trigger-event outreach (Series B announcement, within {trigger['outreach_window_days']} days of announcement): {trigger['booked_meetings']} booked meetings this month. Response rate versus cold-list average: {trigger['response_rate_vs_cold_multiplier']:.0f}x.")
    if linkedin_inbound:
        weeks = linkedin_inbound
        L.append(f"- LinkedIn ad-sourced inbound demo requests per week: {weeks[0]['linkedin_inbound_demos_per_week']} ({weeks[0]['period']}) → {weeks[1]['linkedin_inbound_demos_per_week']} ({weeks[1]['period']}) → {weeks[2]['linkedin_inbound_demos_per_week']} ({weeks[2]['period']}). AE-accepted rate on LinkedIn inbound matches form-fill inbound.")
    L.append("")

    L.append("# Sequence and outreach effectiveness")
    if ch_cmp:
        L.append(f"- Multi-channel sequence meeting rate versus email-only: {ch_cmp['multi_channel_meeting_rate_multiplier']}x across {ch_cmp['active_prospects']} active prospects this month. Breakthrough touch in multi-channel sequences: step {ch_cmp['multi_channel_breakthrough_touch_range']}.")
    if touch_dist:
        L.append(f"- Touch-step distribution on {touch_dist['active_sequences']} active sequences: {touch_dist['pct_replies_at_touch_7_or_8']*100:.0f}% of meeting-producing replies land on touch 7 or 8. Prior quarter breakthrough step: touch {touch_dist['prior_quarter_breakthrough_step']}.")
    if subj:
        L.append(f"- Subject-line variant test ('{subj['variant_name'].replace('_', ' ')}', launched {subj['launch_date']}): {subj['sends']} sends. Variant reply rate: {subj['variant_reply_rate']*100:.1f}%. Prior opener reply rate: {subj['prior_reply_rate']*100:.1f}%. Replies converted to booked meetings: {subj['replies_to_booked_meetings']}.")
    if first_ln:
        L.append(f"- Personalized first-line reply rate (account-specific research): {first_ln['personalized_reply_rate']*100:.1f}% versus {first_ln['generic_reply_rate']*100:.1f}% on generic openers. Lift concentrated in {first_ln['lift_mechanism'].replace('_', '-')} first lines.")
    if morning_block and afternoon_block:
        L.append(f"- Call connect rate by time window: {morning_block['time_window'].replace('_', ' ')} {morning_block['connect_rate']*100:.0f}%, {afternoon_block['time_window'].replace('_', ' ')} {afternoon_block['connect_rate']*100:.0f}%. Morning block producing the majority of this week's discovery-meeting bookings.")
    if dormant:
        L.append(f"- Dormant account re-engagement sequence '{dormant['sequence_name'].replace('_', '-')}' (launched {dormant['launch_date']}): {dormant['accounts_replied']} accounts silent for >{dormant['dormancy_threshold_days']} days replied. Meetings booked with assigned AE: {dormant['meetings_booked']}.")
    L.append("")

    L.append("# ICP targeting and segment penetration")
    if new_vert:
        L.append(f"- {new_vert['segment'].replace('_', ' ').title()} segment opened {new_vert['opened_weeks_ago']} weeks ago ({new_vert['open_date']}). AE-accepted meetings booked: {new_vert['ae_accepted_meetings']}. Of those, {new_vert['first_touch_responses']} came from accounts that responded on the first cold sequence touch.")
    if vert_conv:
        L.append(f"- {vert_conv['vertical'].title()} vertical demo-to-held-meeting conversion: {vert_conv['healthcare_demo_to_held_rate']*100:.0f}% (trailing {vert_conv['period'].replace('_', ' ')}). All-verticals rate: {vert_conv['all_verticals_demo_to_held_rate']*100:.0f}%. Average deal size on meetings advanced to opportunity: {vert_conv['healthcare_avg_deal_size_multiplier']:.0f}x all-vertical average.")
    if committee:
        L.append(f"- Enterprise target accounts with a second responsive buying-committee contact this week: {committee['accounts_with_second_contact']}. Seniority pattern: {committee['second_contact_seniority_combo'].replace('_', ' ')}. All {committee['in_coordinated_ae_motion']} in coordinated outreach motion with their assigned AE.")
    L.append("")

    L.append("# AE handoff quality")
    if handoff_apr:
        L.append(f"- AE-accepted rate on booked meetings (April 2026): {handoff_apr['ae_accepted']} of {handoff_apr['meetings_booked']} meetings advanced past AE qualification ({handoff_apr['accepted_rate']*100:.0f}%). Prior month accepted rate: {handoff_apr['prior_month_accepted_rate']*100:.0f}%. Lift concentrated in segment criteria refined {handoff_apr['segment_criteria_refined_date']}.")
    L.append("")

    return "\n".join(L)


def build_revenue_operator_summary(ds: Dict[str, list]) -> str:
    """Dense, factual snapshot for the Revenue Operator (RevOps / Sales Ops Director)."""
    forecast_metrics = ds.get("ro_forecast_metrics", [])
    pipeline_governance = ds.get("ro_pipeline_governance", [])
    data_quality = ds.get("ro_data_quality", [])
    tool_sync = ds.get("ro_tool_sync", [])
    stage_gate = ds.get("ro_stage_gate", [])
    lead_routing = ds.get("ro_lead_routing", [])
    attribution = ds.get("ro_attribution", [])
    qbr_changes = ds.get("ro_qbr_changes", [])
    account_dedup = ds.get("ro_account_dedup", [])
    deal_review_presence = ds.get("ro_deal_review_presence", [])

    def _get(lst, key, val):
        return next((r for r in lst if r.get(key) == val), {})

    fa = _get(forecast_metrics, "metric", "forecast_accuracy_after_validation_rule")
    fd = _get(forecast_metrics, "metric", "forecast_call_duration")
    pdl = _get(pipeline_governance, "metric", "pipeline_definition_lock")
    pcr = _get(pipeline_governance, "metric", "pipeline_coverage_ratio")
    scdf = _get(data_quality, "metric", "stale_close_date_autoflag")
    s4fc = _get(data_quality, "metric", "stage_4_mandatory_field_completion")
    sync = _get(tool_sync, "metric", "crm_sync_integrity")
    dash = _get(tool_sync, "metric", "dashboard_consolidation")
    sg = stage_gate[0] if stage_gate else {}
    lr = _get(lead_routing, "metric", "lead_routing_exception_rate")
    mql = _get(lead_routing, "metric", "mql_to_sql_lifecycle_governance")
    attr = attribution[0] if attribution else {}
    qbr = qbr_changes[0] if qbr_changes else {}
    dedup = account_dedup[0] if account_dedup else {}
    drp = deal_review_presence[0] if deal_review_presence else {}

    L: List[str] = []
    L.append("ATLAS SAAS — REVENUE OPERATOR DATA SNAPSHOT (as of 2026-04-24)")
    L.append("")
    L.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. Salesforce is the CRM system of record; Clari for forecasting; HubSpot for marketing handoff; Outreach for sequencing; Looker for reporting.")
    L.append("")

    L.append("# Forecast accuracy and data quality")
    if fa:
        L.append(f"- Stage 4 close-date validation rule deployed {fa['rule_deployed_date']}. Forecast-to-actual accuracy across {fa['forecast_windows_measured']} forecast windows: {fa['prior_forecast_accuracy']*100:.0f}% before deployment to {fa['current_forecast_accuracy']*100:.0f}% after. Strongest improvement on {fa['strongest_segment'].replace('_', ' ')} deals.")
    if fd:
        L.append(f"- Tuesday pipeline health report prep moved from manual to automated ({fd['automation_deployed'].replace('_', ' ')}, deployed {fd['automation_deployed_date']}). Wednesday forecast call duration: {fd['current_call_minutes']} minutes this week versus {fd['prior_avg_call_minutes']}-minute average across prior {fd['prior_period_calls_in_sample']} weeks.")
    if scdf:
        L.append(f"- Stale close-date auto-flag rule (deployed {scdf['rule_deployed_date']}): surfaces deals with close dates older than {scdf['close_date_staleness_threshold_days']} days at {scdf['stage_gate_applied'].replace('_', ' ')} entry. Deals flagged since deployment: {scdf['deals_flagged_at_entry']}. Cleared at the entry gate: {scdf['pct_cleared_at_gate']*100:.0f}%. Replaces {scdf['manual_triage_minutes_per_week_replaced']}-minute weekly manual triage.")
    if s4fc:
        L.append(f"- Stage 4 mandatory-field validation (required: {', '.join(s4fc['required_fields'])}): {s4fc['deals_through_stage_4_gate']} deals moved through Stage 4 since gate deployed {s4fc['gate_deployed_date']}. Field completion: {s4fc['pct_full_completion']*100:.0f}% across all three required fields.")
    if drp:
        L.append(f"- RevOps deal review attendance this forecast cycle: {drp['revops_attended']} of {drp['deal_review_calls_total']} calls. Prior cycle: {drp['prior_cycle_revops_attended']} of {drp['deal_review_calls_total']}. Commit-tier forecast accuracy lift on reviewed deals: {drp['commit_forecast_accuracy_lift_pct']*100:.0f}% versus prior cycle.")
    L.append("")

    L.append("# Pipeline governance and definitional alignment")
    if pdl:
        teams = ', '.join(pdl['teams_aligned'])
        L.append(f"- Pipeline definition adopted by {teams} on {pdl['lock_date']}. All {pdl['reports_now_matching']} weekly reports now produce one matching number. Marketing-influenced and pipeline-sourced figures reconcile within {pdl['reconciliation_tolerance_pct']*100:.0f}%.")
    if pcr:
        L.append(f"- Q3 pipeline coverage ratio: {pcr['coverage_ratio']}x against plan. Target band: {pcr['target_band_low']:.0f}-{pcr['target_band_high']:.0f}x. Strongest concentration in {pcr['strongest_segment'].replace('_', ' ')} segment where stage progression has been reliable across the last {pcr['mid_market_reliable_progression_weeks']} weeks.")
    if attr:
        L.append(f"- Multi-touch attribution model locked at {attr['governance_event'].replace('_', ' ')} ({attr['model_locked_date']}). Attribution disputes from prior QBR: {attr['disputes_from_prior_qbr']}. Resolved on first pass: {attr['disputes_resolved_first_pass']}. Marketing-sourced and influenced pipeline now matching across {' and '.join(attr['alignment_surfaces'])}.")
    if dedup:
        L.append(f"- Account dedup rule deployed {dedup['rule_deployed_date']}: {dedup['duplicate_records_merged']} duplicate company records merged. Active account count tightened from {dedup['prior_active_account_count']} to {dedup['current_active_account_count']}.")
    L.append("")

    L.append("# Process and tooling efficiency")
    if sync:
        L.append(f"- {sync['sync_pair'].replace('_', '/')} bidirectional sync deployed {sync['sync_deployed_date']}: {sync['match_rate']*100:.1f}% deal-state match across {sync['active_deals_synced']:,} active records. Wednesday forecast call opens from {sync['forecast_call_source'].replace('_', ' ')}.")
    if dash:
        tools = ', '.join(dash['tools_consolidated'])
        L.append(f"- Dashboard consolidation audit completed {dash['audit_completed_date']}: {dash['dashboards_retired']} redundant dashboards retired across {tools}. Reporting consolidated into {dash['dashboards_remaining']} dashboards. Admin hours cleared weekly: {dash['admin_hours_cleared_weekly']}.")
    if sg:
        reqs = ' and '.join(sg['new_gate_requirements'])
        L.append(f"- Stage 3 gate definition refresh deployed {sg['gate_refresh_deployed_date']} (requires {reqs}): {sg['deals_through_new_gate']} deals processed under new gate. Stage 3-to-Stage 4 conversion: {sg['prior_conversion_rate']*100:.0f}% before versus {sg['current_conversion_rate']*100:.0f}% after.")
    if qbr:
        locked = ', '.join(qbr['changes_locked_names']).replace('_', ' ')
        L.append(f"- Q2 QBR completed {qbr['qbr_completed_date']}: {qbr['changes_locked']} of {qbr['changes_proposed']} proposed process changes locked ({locked}). All {qbr['changes_locked']} now in production.")
    L.append("")

    L.append("# Lifecycle governance")
    if lr:
        L.append(f"- Lead routing rule simplification deployed {lr['simplification_deployed_date']}: {lr['leads_processed_since_deployment']:,} leads processed since deployment. Manual routing exception rate: {lr['prior_exception_rate']*100:.0f}% before versus {lr['current_exception_rate']*100:.1f}% after. Largest improvement in {lr['largest_improvement_segment'].replace('_', ' ')} ({lr['rules_collapsed_from']} overlapping rules collapsed to {lr['rules_collapsed_to']}).")
    if mql:
        L.append(f"- Lead lifecycle governance refresh ({mql['governance_refresh_date']}): {mql['leads_through_new_framework']:,} leads processed. {mql['pct_under_validated_rules']*100:.0f}% of MQL-to-SQL transitions now under validated automation rules. Median handoff timing: {mql['median_handoff_days']} days.")
    L.append("")

    return "\n".join(L)


def build_customer_advocate_summary(ds: Dict[str, list]) -> str:
    """Dense, factual snapshot for the Customer Advocate (CSM / Account Manager).

    Covers all 15 P-CA patterns across four goal clusters:
    Account Health and Relationship Depth (P-CA-01 to P-CA-04),
    Renewal Execution (P-CA-05 to P-CA-08),
    Expansion Identification (P-CA-09 to P-CA-11),
    Value Delivery and QBR (P-CA-12 to P-CA-13),
    Cross-functional bridges (P-CA-14 to P-CA-15).
    """
    book = ds.get("ca_active_book", [{}])[0]
    renewal_q3 = ds.get("ca_renewal_pipeline", [{}])[0]
    early_ren = ds.get("ca_early_renewals", [{}])[0]
    segment_grr = ds.get("ca_segment_grr", [])
    lighthouse = ds.get("ca_lighthouse_qbr", [{}])[0]
    qbr_log = ds.get("ca_qbr_log", [{}])[0]
    onboarding = ds.get("ca_onboarding", [])
    advocate = ds.get("ca_advocate_pipeline", [{}])[0]

    grr_q2 = next((r for r in segment_grr if r.get("quarter") == "Q2_2026"), {})
    grr_q1 = next((r for r in segment_grr if r.get("quarter") == "Q1_2026"), {})
    onb_q2 = next((r for r in onboarding
                   if r.get("cohort_quarter") == "Q2_2026" and "ttfv_median_days" in r), {})
    onb_q1 = next((r for r in onboarding
                   if r.get("cohort_quarter") == "Q1_2026" and "ttfv_median_days" in r), {})
    handoff_q2 = next((r for r in onboarding
                       if r.get("cohort_quarter") == "Q2_2026" and "handoff_completeness_pct" in r), {})
    handoff_q1 = next((r for r in onboarding
                       if r.get("cohort_quarter") == "Q1_2026" and "handoff_completeness_pct" in r), {})

    L: List[str] = []
    L.append("ATLAS SAAS — CUSTOMER ADVOCATE DATA SNAPSHOT (as of 2026-04-24)")
    L.append("")
    L.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. CSM book of 47 active accounts. Gainsight is the CS platform (health scores, playbooks); Salesforce for CRM records, stakeholder maps, and renewal pipeline; Mixpanel for product engagement and usage signals.")
    L.append("")

    # --- Goal 1: Account Health and Relationship Depth ---
    L.append("# Account health and relationship depth")
    if book:
        L.append(f"- Active book: {book.get('total_active_accounts', 47)} accounts.")
        L.append(
            f"- Multi-thread contact depth (book-wide): average {book.get('contact_count_avg_current')} contacts per account this quarter, "
            f"up from {book.get('contact_count_avg_prior_quarter')} last quarter. "
            f"Accounts at 4-plus engaged contacts: {book.get('accounts_4plus_contacts_current')} of {book.get('total_active_accounts')}, "
            f"up from {book.get('accounts_4plus_contacts_prior_quarter')} of {book.get('total_active_accounts')} last quarter. "
            f"Accounts at 4-plus contacts renew at {book.get('renewal_rate_4plus_contacts', 0)*100:.0f}%, "
            f"compared to {book.get('renewal_rate_1to2_contacts', 0)*100:.0f}% at 1-2 contacts."
        )
        L.append(
            f"- Champion re-engagement: {book.get('champion_reengaged_april')} accounts where champion contacts had gone "
            f"{book.get('champion_gap_threshold_days', 14)}-plus days without a logged interaction received a confirmed "
            f"champion response in April, up from {book.get('champion_reengaged_march')} in March. "
            f"{book.get('champion_reengaged_crossed_green_within_21d')} of those "
            f"{book.get('champion_reengaged_april')} accounts crossed back to a green health score within 21 days of re-engagement."
        )
        strat_total = book.get('strategic_tier_total', 25)
        strat_fresh = book.get('strategic_map_fresh_30d_current', 21)
        strat_feb = book.get('strategic_map_fresh_30d_february', 14)
        strat_feb_pct = book.get('strategic_map_fresh_pct_february', 0.56)
        lift_pts = book.get('renewal_rate_lift_fresh_stakeholder_map_pts', 22)
        L.append(
            f"- Stakeholder map freshness (strategic tier, {strat_total} accounts): "
            f"{strat_fresh} of {strat_total} updated within the last 30 days, "
            f"up from {strat_feb} of {strat_total} ({strat_feb_pct*100:.0f}%) in February. "
            f"Strategic accounts with fresh stakeholder maps renew {lift_pts} points higher than those without."
        )
        outreach = book.get('accounts_outreach_14d', 44)
        total = book.get('total_active_accounts', 47)
        L.append(
            f"- Outreach coverage: {outreach} of {total} active accounts show a CSM-logged interaction within the past 14 calendar days. "
            f"Highest two-week outreach coverage recorded since {book.get('outreach_14d_highest_since', 'Q4_2025').replace('_', ' ')}."
        )
    L.append("")

    # --- Goal 2: Renewal Execution ---
    L.append("# Renewal execution")
    if renewal_q3:
        L.append(
            f"- Q3 2026 renewal pipeline: {renewal_q3.get('renewal_accounts_total')} accounts, "
            f"${renewal_q3.get('renewal_arr_total', 0):,} total ARR. "
            f"Executive sponsor touch logged in last 30 days: {renewal_q3.get('exec_sponsor_touch_last_30d')} of {renewal_q3.get('renewal_accounts_total')}. "
            f"Renewals with executive engagement in the 90 days before renewal close at {renewal_q3.get('renewal_rate_with_exec_touch_90d', 0)*100:.0f}%, "
            f"compared to {renewal_q3.get('renewal_rate_without_exec_touch', 0)*100:.0f}% without."
        )
    if early_ren:
        L.append(
            f"- Early-renewal pull-forward Q2 2026: {early_ren.get('early_renewal_accounts')} accounts originally tracking to Q3 or Q4 "
            f"closed early renewals in Q2; combined ARR ${early_ren.get('early_renewal_arr', 0):,}. "
            f"{early_ren.get('accounts_green_two_consecutive_months_before')} of {early_ren.get('early_renewal_accounts')} "
            f"had been flagged green for two consecutive months before the early-commit conversation."
        )
    if grr_q2 and grr_q1:
        L.append(
            f"- Mid-market segment GRR: Q2 2026 {grr_q2.get('renewals_won')} of {grr_q2.get('renewals_total')} renewed "
            f"({grr_q2.get('grr', 0)*100:.0f}% GRR), up from {grr_q1.get('renewals_won')} of {grr_q1.get('renewals_total')} in Q1 "
            f"({grr_q1.get('grr', 0)*100:.0f}% GRR). "
            f"ICP-aligned mid-market accounts carried {grr_q2.get('icp_aligned_lift_share', 0)*100:.0f}% of the Q2 lift."
        )
    if lighthouse:
        L.append(
            f"- Lighthouse executive QBR ({lighthouse.get('qbr_date')}): buying committee expanded from "
            f"{lighthouse.get('contacts_before_qbr')} to {lighthouse.get('contacts_after_qbr')} contacts, "
            f"adding {', '.join(lighthouse.get('new_contacts_added', []))}. "
            f"Buying committees that grow during the renewal window close "
            f"{lighthouse.get('buying_committee_growth_renewal_uplift_pts')} points higher than those that stay flat."
        )
    L.append("")

    # --- Goal 3: Expansion Identification ---
    L.append("# Expansion identification")
    if book:
        adoption_ceil = book.get('accounts_80pct_adoption_ceiling', 7)
        adoption_arr = book.get('adoption_ceiling_expansion_arr_potential', 0)
        adoption_exec = book.get('adoption_ceiling_exec_sponsor_on_expansion', 4)
        L.append(
            f"- Feature-adoption ceiling signals: {adoption_ceil} accounts crossed the 80% feature-adoption ceiling on their current tier in April; "
            f"combined expansion ARR potential ${adoption_arr:,} based on next-tier list pricing. "
            f"{adoption_exec} of {adoption_ceil} accounts carry a logged executive sponsor on the expansion conversation track."
        )
        contacts_5plus = book.get('accounts_5plus_contacts_current', 12)
        contacts_5plus_prior = book.get('accounts_5plus_contacts_prior_quarter', 4)
        exp_rate_5plus = book.get('expansion_rate_5plus_contacts_12mo', 0)
        exp_rate_single = book.get('expansion_rate_single_thread_12mo', 0)
        L.append(
            f"- Multi-thread expansion depth (5-plus contacts): {contacts_5plus} active accounts carry 5-plus engaged contacts in CRM, "
            f"up from {contacts_5plus_prior} last quarter. "
            f"Accounts at 5-plus contacts expand at {exp_rate_5plus*100:.0f}% in the next 12 months, "
            f"compared to {exp_rate_single*100:.0f}% at single-thread."
        )
        spike_accounts = book.get('accounts_usage_spike_14d', 8)
        spike_on_track = book.get('usage_spike_on_expansion_track', 6)
        spike_faster = book.get('expansion_close_cycle_faster_pct', 0)
        L.append(
            f"- Usage spike signals (40% week-over-week increase, last 14 days): {spike_accounts} accounts crossed the usage-spike threshold; "
            f"{spike_on_track} of {spike_accounts} carry an active expansion track in CRM. "
            f"Usage spikes preceding expansion conversations correlate with a {spike_faster*100:.0f}% faster close-cycle on the expansion deal."
        )
    L.append("")

    # --- Goal 4: Value Delivery and QBR ---
    L.append("# Value delivery and QBR")
    if qbr_log:
        strat = qbr_log.get('strategic_tier_total', 25)
        completed = qbr_log.get('qbr_completed_with_value_story', 22)
        pct = qbr_log.get('qbr_completion_pct', 0)
        feb_pct = qbr_log.get('february_completion_pct', 0)
        lift = qbr_log.get('renewal_commit_lift_pts_with_value_story', 18)
        L.append(
            f"- April QBR completion (strategic tier, {strat} accounts): {completed} of {strat} completed with a value-story summary logged in CRM "
            f"({pct*100:.0f}%), up from {feb_pct*100:.0f}% in February. "
            f"QBRs with structured value summaries correlate with {lift}-point higher renewal commit rates in the 90 days that follow."
        )
    if onb_q2 and onb_q1:
        L.append(
            f"- Time to first value: Q2 2026 median {onb_q2.get('ttfv_median_days')} days across {onb_q2.get('onboardings_total')} onboardings, "
            f"down from {onb_q1.get('ttfv_median_days')} days across {onb_q1.get('onboardings_total')} Q1 onboardings. "
            f"Accounts hitting first activated success criterion within {onb_q2.get('ttfv_threshold_days')} days renew "
            f"{onb_q2.get('renewal_rate_lift_under_threshold_pts')} points higher."
        )
    L.append("")

    # --- Cross-functional bridges ---
    L.append("# Cross-functional bridges")
    if handoff_q2 and handoff_q1:
        q2_complete = handoff_q2.get('handoff_complete', 19)
        q2_total = handoff_q2.get('closed_won_deals_total', 24)
        q2_pct = handoff_q2.get('handoff_completeness_pct', 0)
        q1_complete = handoff_q1.get('handoff_complete', 11)
        q1_total = handoff_q1.get('closed_won_deals_total', 27)
        faster = handoff_q2.get('ttfv_faster_days_complete_vs_incomplete', 19)
        fields = ', '.join(handoff_q2.get('handoff_complete_fields', []))
        L.append(
            f"- CRM handoff completeness (closed-won to CSM): {q2_complete} of {q2_total} Q2 deals "
            f"({q2_pct*100:.0f}%) carried full {fields} at handoff, "
            f"up from {q1_complete} of {q1_total} in Q1. "
            f"Onboardings with complete handoff context hit first activated success criterion "
            f"{faster} days faster than those without."
        )
    if advocate:
        pool = advocate.get('advocate_pool_current', 11)
        pool_feb = advocate.get('advocate_pool_february', 5)
        commits = advocate.get('q2_case_study_commits', 4)
        distinct = advocate.get('q2_case_study_accounts_distinct', 4)
        L.append(
            f"- Marketing-Customer advocate pipeline: {commits} case-study commits from {distinct} distinct accounts in Q2. "
            f"Advocate pool now {pool} named accounts with logged reference willingness, up from {pool_feb} in February."
        )
    L.append("")

    return "\n".join(L)


def build_customer_operator_summary(ds: Dict[str, list]) -> str:
    """Dense, factual snapshot for the Customer Operator (Director of CS Ops).

    Covers all 15 P-CO patterns across three goal clusters:
    Health Score Model Integrity (P-CO-01, P-CO-05, P-CO-10),
    Playbook Governance and Adoption (P-CO-02, P-CO-11),
    Data Infrastructure and Integration (P-CO-03, P-CO-06, P-CO-07, P-CO-08, P-CO-14),
    Segmentation (P-CO-04),
    Performance and Cross-entity Attribution (P-CO-09, P-CO-12, P-CO-13, P-CO-15).
    """
    health = ds.get("co_health_model", [{}])[0]
    playbook = ds.get("co_playbook_ops", [{}])[0]
    integrations = ds.get("co_platform_integrations", [])
    segmentation = ds.get("co_segmentation", [{}])[0]
    handoff = ds.get("co_handoff_quality", [{}])[0]
    benchmark = ds.get("co_benchmark", [{}])[0]
    performance = ds.get("co_performance", [])

    telemetry = next((r for r in integrations if r.get("integration") == "mixpanel_to_cs_platform"), {})
    sf_sync = next((r for r in integrations if r.get("integration") == "salesforce_to_cs_platform"), {})
    tool_consol = next((r for r in integrations if r.get("event") == "cs_tool_consolidation_q1_2026"), {})
    bq_pipeline = next((r for r in integrations if r.get("event") == "bigquery_pipeline_approved"), {})

    nrr_row = next((r for r in performance if r.get("metric") == "nrr"), {})
    onb_row = next((r for r in performance if r.get("metric") == "onboarding_completion_rate"), {})
    xentity = next((r for r in performance if r.get("event") == "custom_permissions_launch_to_beacon_renewal"), {})

    L: List[str] = []
    L.append("ATLAS SAAS — CUSTOMER OPERATOR DATA SNAPSHOT (as of 2026-04-24)")
    L.append("")
    L.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. Gainsight is the CS platform (health scores, playbooks, segmentation); Salesforce for CRM records, stakeholder maps, and renewal pipeline; Mixpanel for product engagement and usage signals; BigQuery as the data warehouse target for feature-usage extracts.")
    L.append("")

    # --- Goal 1: Health Score Model Integrity ---
    L.append("# Health score model integrity")
    _MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"]

    def _hr_date(iso: str) -> str:
        """Convert YYYY-MM-DD to 'Month Day, YYYY' for guardrail-friendly output."""
        try:
            y, m, d = iso.split("-")
            return f"{_MONTH_NAMES[int(m)-1]} {int(d)}, {y}"
        except Exception:
            return iso

    def _hr_quarter(q: str) -> str:
        """Convert 'Q3_2026' or 'Q3 2026' to 'Q3 2026'."""
        return q.replace("_", " ")

    if health:
        auc = health.get("health_score_auc_current_quarter", 0.81)
        auc_prior = health.get("health_score_auc_prior_quarter", 0.74)
        auc_2q = health.get("health_score_auc_two_quarters_ago", 0.67)
        consec = health.get("auc_consecutive_quarters_of_lift", 3)
        L.append(
            f"- Health score AUC: {auc} this quarter, up from {auc_prior} last quarter and {auc_2q} two quarters ago. "
            f"{consec} consecutive quarters of AUC lift. Renewal-correlation lift versus prior model confirmed."
        )
        ltr_status = health.get("ltr_model_status", "shadow_production").replace("_", " ")
        ltr_start = _hr_date(health.get("ltr_model_shadow_start_date", "2026-04-21"))
        L.append(
            f"- Likelihood-to-renew probabilistic layer: status {ltr_status} (started {ltr_start}). "
            f"Runs alongside the composite score and produces its own pass-fail history for direct comparison."
        )
        override_curr = health.get("override_rate_current", 0.11)
        override_prior = health.get("override_rate_prior_quarter", 0.17)
        override_peak = health.get("override_rate_peak", 0.24)
        L.append(
            f"- Health score override rate: {override_curr*100:.0f}% across all tiers, "
            f"down from {override_prior*100:.0f}% last quarter (peak {override_peak*100:.0f}%). "
            f"Trajectory: declining."
        )
    L.append("")

    # --- Goal 2: Playbook Governance and Adoption ---
    L.append("# Playbook governance and adoption")
    if playbook:
        completions = playbook.get("playbook_executions_completed_end_to_end", 312)
        period_days = playbook.get("measurement_period_days", 30)
        L.append(
            f"- Playbook executions completed end-to-end in the last {period_days} days: {completions}. "
            f"Completion-rate visibility is newly available -- prior periods not measured."
        )
        attr_date = _hr_date(playbook.get("attribution_feature_release_date", "2026-04-18"))
        L.append(
            f"- Playbook completion attribution feature released {attr_date} in the latest CS platform update. "
            f"Platform now exports completion events, enabling outcome attribution at the playbook level for the first time."
        )
    L.append("")

    # --- Goal 3: Data Infrastructure and Integration ---
    L.append("# Data infrastructure and integration")
    if telemetry:
        event_date = _hr_date(telemetry.get("event_date", "2026-04-18"))
        prior_latency = telemetry.get("prior_latency_days", 3)
        L.append(
            f"- Product telemetry sync (Mixpanel to CS platform): moved to real-time on {event_date}. "
            f"Prior batch-nightly mode carried a {prior_latency}-day ({prior_latency * 24}-hour) latency; "
            f"signals now reach the health model within minutes of the underlying event."
        )
    if sf_sync:
        uptime = sf_sync.get("uptime_pct", 0.997)
        month = sf_sync.get("measurement_month", "2026-03")
        threshold = sf_sync.get("uptime_threshold_pct", 0.99)
        L.append(
            f"- Salesforce-to-CS-platform sync uptime: {uptime*100:.1f}% in March 2026, above the {threshold*100:.0f}% threshold. "
            f"Nightly handoff freshness holds, supporting current health model signal reliability."
        )
    if tool_consol:
        tools = tool_consol.get("tools_retired", 3)
        quarter = _hr_quarter(tool_consol.get("tools_retired_quarter", "Q1_2026"))
        load_drop = tool_consol.get("connector_load_reduction_pct", 0.40)
        L.append(
            f"- Tech stack consolidation: {tools} CS tools retired in {quarter}. "
            f"Connector load reduced by {load_drop*100:.0f}%. Admin bandwidth freed for model improvement work."
        )
    if handoff:
        complete_pct = handoff.get("handoff_complete_pct", 0.84)
        deals_total = handoff.get("closed_won_deals_total", 24)
        prior_pct = handoff.get("prior_quarter_complete_pct", 0.41)
        fields = handoff.get("fields_tracked", [])
        L.append(
            f"- Handoff data completeness (closed-won to CS): {complete_pct*100:.0f}% of fields populated at close "
            f"across {deals_total} Q2 deals ({', '.join(fields[:3])} tracked). "
            f"Up from {prior_pct*100:.0f}% in Q1. Day-0 health score accuracy improves with richer handoff records."
        )
    if bq_pipeline:
        approved_date = _hr_date(bq_pipeline.get("approval_date", "2026-04-22"))
        approved_q = _hr_quarter(bq_pipeline.get("approved_for_quarter", "Q2_2026"))
        replaces = bq_pipeline.get("replaces_proxy_signal", "login_frequency")
        L.append(
            f"- BigQuery feature-usage pipeline: approved {approved_date} for {approved_q}. "
            f"Scheduled to replace proxy {replaces} signals in the health score model."
        )
    L.append("")

    # --- Segmentation ---
    L.append("# Segmentation")
    if segmentation:
        accts = segmentation.get("accounts_reclassified_mid_to_high_touch", 47)
        history = segmentation.get("data_history_months", 14)
        new_routing = _hr_quarter(segmentation.get("new_playbook_routing_starts", "Q3_2026"))
        L.append(
            f"- Coverage tier refresh: {accts} accounts reclassified from Mid-Touch to High-Touch "
            f"based on {history} months of actual usage and renewal data (prior basis: onboarding tier assignment). "
            f"New playbook routing begins {new_routing}."
        )
    L.append("")

    # --- Performance and Cross-entity Attribution ---
    L.append("# Performance and cross-entity attribution")
    if benchmark:
        bname = benchmark.get("benchmark_name", "2026_Annual_CS_Benchmark").replace("_", " ")
        release = _hr_date(benchmark.get("expected_release_date", "2026-04-30"))
        curr_year = benchmark.get("current_model_calibrated_on_year", 2025)
        L.append(
            f"- {bname} expected {release}. "
            f"Current segmentation model calibrated on {curr_year} data; fresh ratio data enables tuning coverage tiers against updated industry baseline."
        )
    if nrr_row:
        nrr = nrr_row.get("nrr", 1.17)
        segment = nrr_row.get("segment", "mid-market")
        quarter = _hr_quarter(nrr_row.get("quarter", "Q1_2026"))
        bench = nrr_row.get("benchmark_nrr_above", 1.10)
        consec = nrr_row.get("consecutive_quarters_above_benchmark", 3)
        L.append(
            f"- NRR ({segment}): {nrr*100:.0f}% for {quarter}, above the {bench*100:.0f}% benchmark for {consec} consecutive quarters "
            f"(Q3 2025, Q4 2025, Q1 2026)."
        )
    if onb_row:
        rate = onb_row.get("completion_rate", 0.89)
        cohort = _hr_quarter(onb_row.get("cohort_quarter", "Q1_2026"))
        total = onb_row.get("total_onboardings", 9)
        L.append(
            f"- Onboarding completion rate: {rate*100:.0f}% across the {cohort} cohort ({total} onboardings). "
            f"Activation milestones feed back as enriched signals into the health model."
        )
    if xentity:
        feature = xentity.get("product_feature", "Custom Permissions")
        launch = _hr_date(xentity.get("feature_launch_date", "2026-03-08"))
        account = xentity.get("account_name", "Beacon Logistics")
        green_days = xentity.get("health_score_green_days_consecutive", 21)
        renewal_signed = _hr_date(xentity.get("renewal_signed_date", "2026-04-14"))
        early_conv = _hr_date(xentity.get("early_renewal_conversation_date", "2026-04-02"))
        L.append(
            f"- Cross-entity attribution: {feature} launch ({launch}) connects directly to {account} early renewal "
            f"(conversation {early_conv}, contract signed {renewal_signed}). "
            f"Health model pipeline traces: feature launch, {green_days} consecutive days green, "
            f"early renewal conversation opened, contract signed. End-to-end product-event-to-renewal attribution."
        )
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
_MARKETING_STRATEGIST_GOAL_CLUSTERS = (
    "Messaging and Positioning; Sales Enablement; "
    "Launch and GTM Execution; Generating Qualified Pipeline"
)
_MARKETING_BUILDER_GOAL_CLUSTERS = (
    "Demand Generation; Content and Organic Growth; "
    "Marketing Operations; Sales Enablement Support"
)
_REVENUE_GOAL_CLUSTERS = (
    "Quarter Attainment and Forecast Reliability; Pipeline Coverage and Health; "
    "Win Rate and Competitive Position"
)
_REVENUE_GENERATOR_GOAL_CLUSTERS = (
    "Closing Deals in Flight; Pipeline Quality and Coverage; "
    "Deal Execution Efficiency; Competitive Winning"
)
_REVENUE_DEVELOPER_GOAL_CLUSTERS = (
    "Pipeline Creation and Inbound Response; Sequence and Outreach Effectiveness; "
    "ICP Targeting and Segment Penetration; AE Handoff Quality"
)
_REVENUE_OPERATOR_GOAL_CLUSTERS = (
    "Forecast Accuracy and Data Quality; Pipeline Governance and Definitional Alignment; "
    "Process and Tooling Efficiency; Lifecycle Governance"
)
_CUSTOMER_GOAL_CLUSTERS = (
    "Retained Revenue Landing to Forecast; Expansion Revenue Compounding NRR; "
    "Portfolio-Level Retention Risk Surfacing Ahead of Churn"
)
_CUSTOMER_ADVOCATE_GOAL_CLUSTERS = (
    "Account Health and Relationship Depth; Renewal Execution; "
    "Expansion Identification; Value Delivery and QBR"
)
_CUSTOMER_OPERATOR_GOAL_CLUSTERS = (
    "Health Score Model Integrity; Playbook Governance and Adoption; "
    "Data Infrastructure and Integration"
)
_CUSTOMER_TECHNICIAN_GOAL_CLUSTERS = (
    "Time-to-Value and Onboarding Velocity; Stakeholder Activation and Adoption; "
    "Cross-functional Handoffs and Integration Quality"
)


def build_customer_technician_summary(ds: Dict[str, list]) -> str:
    """Dense, factual snapshot for the Customer Technician (Implementation Manager).

    Covers all 15 P-CT patterns across three goal clusters:
    Time-to-Value and Onboarding Velocity (P-CT-01, P-CT-02, P-CT-03, P-CT-05, P-CT-08, P-CT-14),
    Stakeholder Activation and Adoption (P-CT-04, P-CT-10, P-CT-11, P-CT-15),
    Cross-functional Handoffs and Integration Quality (P-CT-06, P-CT-07, P-CT-09, P-CT-12, P-CT-13).
    """
    ttfv = ds.get("ct_ttfv_cohort", [{}])[0]
    velocity = ds.get("ct_go_live_velocity", [])
    integration = ds.get("ct_integration_and_activation", [{}])[0]
    handoffs = ds.get("ct_handoff_quality", [])
    nps_data = ds.get("ct_nps", [{}])[0]
    support = ds.get("ct_support_and_blockers", [])
    product_event = ds.get("ct_product_event", [{}])[0]

    mm_velocity = next((r for r in velocity if r.get("segment") == "mid-market"), {})
    ent_velocity = next((r for r in velocity if r.get("segment") == "enterprise"), {})
    healthcare = next((r for r in velocity if r.get("vertical") == "healthcare"), {})

    use_case_handoff = next((r for r in handoffs if "use_case" in r.get("driver", "")), {})
    csm_handoff = next((r for r in handoffs if "handoff_brief" in str(r.get("handoff_brief_feature", ""))), {})

    blocker = next((r for r in support if r.get("metric") == "product_blocker_resolution_median_days"), {})
    support_response = next((r for r in support if r.get("metric") == "implementation_support_first_response"), {})

    _MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"]

    def _hr_date(iso: str) -> str:
        try:
            y, m, d = iso.split("-")
            return f"{_MONTH_NAMES[int(m)-1]} {int(d)}, {y}"
        except Exception:
            return iso

    def _hr_quarter(q: str) -> str:
        return q.replace("_", " ")

    L: List[str] = []
    L.append("ATLAS SAAS — CUSTOMER TECHNICIAN DATA SNAPSHOT (as of 2026-04-24)")
    L.append("")
    L.append("Company profile: B2B SaaS, mid-market focus, approximately 250 employees. Implementation team manages onboarding across Tier-1 (simplest), Tier-2, and Enterprise complexity tiers. Tools: project management platform, product sandbox, Salesforce for handoff records, support queue for implementation-tagged tickets.")
    L.append("")

    # --- Goal 1: Time-to-Value and Onboarding Velocity ---
    L.append("# Time-to-value and onboarding velocity")
    if ttfv:
        total = ttfv.get("cohort_implementations_total", 47)
        connected_48h = ttfv.get("implementations_connected_first_integration_within_48h", 26)
        mult = ttfv.get("retention_90day_multiplier_vs_late_integrators", 2.3)
        tier2_curr = ttfv.get("tier_2_activation_current_quarter_pct", 0.78)
        tier2_prior = ttfv.get("tier_2_activation_prior_quarter_pct", 0.54)
        day_thresh = ttfv.get("tier_2_first_value_day_threshold", 14)
        L.append(
            f"- TTFV cohort ({total} implementations, Q1 2026): accounts connecting first integration within 48 hours "
            f"of kickoff ({connected_48h} of {total}) retained at {mult}x the 90-day rate versus accounts that integrated "
            f"after the first week."
        )
        L.append(
            f"- Tier-2 complexity activation: {tier2_curr*100:.0f}% of Tier-2 implementations reached first value inside "
            f"{day_thresh} days this quarter, up from {tier2_prior*100:.0f}% in Q4 across the same complexity segment."
        )
    if mm_velocity:
        total_mm = mm_velocity.get("implementations_completed", 22)
        curr_days = mm_velocity.get("avg_kickoff_to_golive_days_current", 45)
        plan_days = mm_velocity.get("avg_kickoff_to_golive_days_plan", 51)
        ahead = mm_velocity.get("days_ahead_of_plan", 6)
        L.append(
            f"- Mid-market go-live velocity ({total_mm} implementations completed Q1 2026): average kickoff-to-go-live "
            f"moved from Day {plan_days} (plan) to Day {curr_days} — {ahead} days ahead of plan."
        )
    if ent_velocity:
        total_ent = ent_velocity.get("implementations_completed", 14)
        curr_config = ent_velocity.get("config_signoff_median_days_current", 11)
        prior_config = ent_velocity.get("config_signoff_median_days_prior_quarter", 18)
        template_date = _hr_date(ent_velocity.get("template_launch_date", "2026-03-01"))
        L.append(
            f"- Enterprise configuration sign-off ({total_ent} implementations Q1 2026): median moved from Day {prior_config} "
            f"to Day {curr_config} after pre-kickoff configuration template launched {template_date}."
        )
    if healthcare:
        total_hc = healthcare.get("implementations_completed", 11)
        median_days = healthcare.get("kickoff_to_golive_median_days", 38)
        L.append(
            f"- Healthcare vertical: {total_hc} go-lives this quarter at a {median_days}-day kickoff-to-go-live median — "
            f"fastest segment median in the portfolio."
        )
    if integration:
        int_curr = integration.get("integration_milestone_completion_pct_current", 0.71)
        int_prior = integration.get("integration_milestone_completion_pct_prior_quarter", 0.58)
        active = integration.get("active_implementations_in_period", 38)
        day_t = integration.get("integration_milestone_day_threshold", 10)
        L.append(
            f"- Data integration milestone completion: {int_curr*100:.0f}% of {active} active implementations cleared "
            f"the integration milestone inside {day_t} days of kickoff this quarter, up from {int_prior*100:.0f}% "
            f"in Q4."
        )
    L.append("")

    # --- Goal 2: Stakeholder Activation and Adoption ---
    L.append("# Stakeholder activation and adoption")
    if ttfv:
        multiuser_3 = ttfv.get("implementations_reaching_3_users_by_day_30", 31)
        cohort_total = ttfv.get("cohort_implementations_total", 47)
        mult_3user = ttfv.get("retention_90day_multiplier_3user_vs_single_user", 3.0)
        L.append(
            f"- Multi-stakeholder activation ({cohort_total}-account Q1 cohort): implementations crossing the "
            f"3-user activation threshold by Day 30 ({multiuser_3} of {cohort_total}) showed 90-day retention "
            f"{mult_3user}x stronger than single-user activations."
        )
    if integration:
        checklist_curr = integration.get("checklist_completion_pct_current", 0.34)
        checklist_prior = integration.get("checklist_completion_pct_prior", 0.22)
        checklist_date = _hr_date(integration.get("checklist_template_launch_date", "2026-03-01"))
        industry = integration.get("industry_baseline_checklist_completion_pct", 0.192)
        L.append(
            f"- Onboarding checklist completion: rose from {checklist_prior*100:.0f}% to "
            f"{checklist_curr*100:.0f}% after the configuration template launched {checklist_date}, "
            f"versus the UserGuiding industry baseline of {industry*100:.1f}%."
        )
    if integration:
        kickoffs_total = integration.get("kickoffs_total", 51)
        stakeholder_curr = integration.get("kickoffs_with_3plus_stakeholders_pct_current", 0.64)
        stakeholder_prior = integration.get("kickoffs_with_3plus_stakeholders_pct_prior_quarter", 0.39)
        L.append(
            f"- Stakeholder breadth at kickoff: {stakeholder_curr*100:.0f}% of {kickoffs_total} kickoffs this quarter "
            f"listed 3 or more named stakeholders on the project plan, versus {stakeholder_prior*100:.0f}% "
            f"the prior quarter."
        )
    if product_event:
        feature = product_event.get("product_feature", "Self-Serve Sandbox")
        launch_date = _hr_date(product_event.get("feature_launch_date", "2026-03-12"))
        cohort_sz = product_event.get("cohort_size", 36)
        act_after = product_event.get("activation_pct_after_launch", 0.81)
        act_before = product_event.get("activation_pct_before_launch", 0.62)
        lift_pp = product_event.get("activation_lift_percentage_points", 19)
        day_t2 = product_event.get("first_value_day_threshold", 14)
        L.append(
            f"- {feature} launch ({launch_date}): Tier-1 implementations reached first value inside {day_t2} days "
            f"at {act_after*100:.0f}%, up from {act_before*100:.0f}% prior to launch across {cohort_sz} Tier-1 accounts "
            f"({lift_pp} percentage point lift)."
        )
    L.append("")

    # --- Goal 3: Cross-functional Handoffs and Integration Quality ---
    L.append("# Cross-functional handoffs and integration quality")
    if use_case_handoff:
        cohort_uc = use_case_handoff.get("implementations_in_cohort", 34)
        days_faster = use_case_handoff.get("complete_use_case_capture_golive_days_faster", 12)
        L.append(
            f"- Sales-to-implementation use-case capture: across {cohort_uc} implementations Q1 2026, accounts "
            f"with complete pre-close use-case documentation reached go-live {days_faster} days earlier than "
            f"accounts without one."
        )
    if nps_data:
        seg = nps_data.get("segment", "mid-market")
        surveyed = nps_data.get("surveyed_go_lives", 28)
        nps_curr = nps_data.get("nps_current_quarter", 59)
        nps_prior = nps_data.get("nps_prior_quarter", 41)
        nps_lift = nps_data.get("nps_improvement_points", 18)
        L.append(
            f"- Implementation NPS ({seg}): moved from {nps_prior} to {nps_curr} (+{nps_lift} points) "
            f"across {surveyed} surveyed go-lives this quarter — largest segment-level jump on record."
        )
    if blocker:
        issues = blocker.get("issues_logged", 17)
        curr_days = blocker.get("resolution_median_days_current", 4)
        prior_days = blocker.get("resolution_median_days_prior_quarter", 9)
        L.append(
            f"- Product-blocker resolution: median tightened from {prior_days} days to {curr_days} days "
            f"across {issues} implementation-tagged Engineering issues this quarter."
        )
    if csm_handoff:
        golives = csm_handoff.get("golives_in_cohort", 26)
        ack_pct = csm_handoff.get("handoff_brief_acknowledged_pct", 0.92)
        ack_hours = csm_handoff.get("acknowledgement_window_hours", 48)
        L.append(
            f"- Implementation-to-CSM handoff brief: {ack_pct*100:.0f}% of {golives} enterprise go-lives "
            f"had the structured handoff brief acknowledged by the receiving CSM inside {ack_hours} hours."
        )
    if support_response:
        tickets = support_response.get("tickets_logged", 142)
        curr_hrs = support_response.get("first_response_median_hours_current", 2.4)
        prior_hrs = support_response.get("first_response_median_hours_prior", 6.0)
        L.append(
            f"- Implementation support response: first-response median tightened from {prior_hrs:.0f} hours "
            f"to {curr_hrs} hours across {tickets} implementation-tagged support tickets this quarter, "
            f"after the dedicated implementation support queue launched."
        )
    L.append("")

    return "\n".join(L)


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
    "customer": {
        "intelligence_area": "customer",
        "audience_label": "VP of Customer Success at Atlas SaaS",
        "voice_brief_label": "Voice Brief",
        "leader_label": "Customer Leader",
        "goal_clusters": _CUSTOMER_GOAL_CLUSTERS,
        "snapshot_label": "CUSTOMER DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"Q2 mid-market GRR 91%\", your card says "
            "91% or rounds honestly to 91%, not 92%."
        ),
        "brief_filename": "customer-leader-brief.md",
        "user_prompt_subject": "Customer Success",
    },
    "marketing_strategist": {
        "intelligence_area": "marketing",
        "audience_label": "Director of Product Marketing at Atlas SaaS",
        "voice_brief_label": "Voice Brief",
        "leader_label": "Marketing Strategist",
        "goal_clusters": _MARKETING_STRATEGIST_GOAL_CLUSTERS,
        "snapshot_label": "MARKETING STRATEGIST DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"Beacon Systems Q2 h2h win rate 63.6%\", "
            "your card says 63.6% or rounds honestly to 64%, not 65%."
        ),
        "brief_filename": "marketing-strategist-brief.md",
        "user_prompt_subject": "Marketing Strategy",
    },
    "marketing_builder": {
        "intelligence_area": "marketing",
        "audience_label": "Demand Generation Manager at Atlas SaaS",
        "voice_brief_label": "Voice Brief",
        "leader_label": "Marketing Builder",
        "goal_clusters": _MARKETING_BUILDER_GOAL_CLUSTERS,
        "snapshot_label": "MARKETING BUILDER DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"April LinkedIn CPL $138\", "
            "your card says $138 or rounds honestly, not $140."
        ),
        "brief_filename": "marketing-builder-brief.md",
        "user_prompt_subject": "Marketing Execution",
    },
    "revenue_generator": {
        "intelligence_area": "revenue",
        "audience_label": "Account Executive at Atlas SaaS",
        "voice_brief_label": "Voice Brief",
        "leader_label": "Revenue Generator",
        "goal_clusters": _REVENUE_GENERATOR_GOAL_CLUSTERS,
        "snapshot_label": "ACCOUNT EXECUTIVE DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"Q2 Beacon h2h win rate 61.1%\", "
            "your card says 61.1% or rounds honestly to 61%, not 62%."
        ),
        "brief_filename": "revenue-generator-brief.md",
        "user_prompt_subject": "Account Executive",
    },
    "revenue_developer": {
        "intelligence_area": "revenue",
        "audience_label": "Sales Development Representative at Atlas SaaS",
        "voice_brief_label": "Voice Brief",
        "leader_label": "Revenue Developer",
        "goal_clusters": _REVENUE_DEVELOPER_GOAL_CLUSTERS,
        "snapshot_label": "SDR / REVENUE DEVELOPER DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"Healthcare demo-to-held rate 81%\", "
            "your card says 81% or rounds honestly to 81%, not 82%."
        ),
        "brief_filename": "revenue-developer-brief.md",
        "user_prompt_subject": "Sales Development",
    },
    "revenue_operator": {
        "intelligence_area": "revenue",
        "audience_label": "Director of Revenue Operations at Atlas SaaS",
        "voice_brief_label": "Voice Brief",
        "leader_label": "Revenue Operator",
        "goal_clusters": _REVENUE_OPERATOR_GOAL_CLUSTERS,
        "snapshot_label": "REVENUE OPERATOR DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"Stage 3-to-4 conversion 47%\", "
            "your card says 47% or rounds honestly to 47%, not 48%."
        ),
        "brief_filename": "revenue-operator-brief.md",
        "user_prompt_subject": "Revenue Operations",
    },
    "customer_advocate": {
        "intelligence_area": "customer",
        "audience_label": "Customer Success Manager at Atlas SaaS",
        "voice_brief_label": "Voice Brief",
        "leader_label": "Customer Advocate",
        "goal_clusters": _CUSTOMER_ADVOCATE_GOAL_CLUSTERS,
        "snapshot_label": "CUSTOMER ADVOCATE DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"Q2 mid-market GRR 94%\", "
            "your card says 94% or rounds honestly to 94%, not 95%."
        ),
        "brief_filename": "customer-advocate-brief.md",
        "user_prompt_subject": "Customer Success Management",
    },
    "customer_operator": {
        "intelligence_area": "customer",
        "audience_label": "Director of CS Operations at Atlas SaaS",
        "voice_brief_label": "Voice Brief",
        "leader_label": "Customer Operator",
        "goal_clusters": _CUSTOMER_OPERATOR_GOAL_CLUSTERS,
        "snapshot_label": "CUSTOMER OPERATOR DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"health score AUC 0.81\", "
            "your card says 0.81 or rounds honestly to 0.81, not 0.82."
        ),
        "brief_filename": "customer-operator-brief.md",
        "user_prompt_subject": "Customer Success Operations",
    },
    "customer_technician": {
        "intelligence_area": "customer",
        "audience_label": "Implementation Manager at Atlas SaaS",
        "voice_brief_label": "Voice Brief",
        "leader_label": "Customer Technician",
        "goal_clusters": _CUSTOMER_TECHNICIAN_GOAL_CLUSTERS,
        "snapshot_label": "CUSTOMER TECHNICIAN DATA SNAPSHOT",
        "snapshot_example": (
            "If the snapshot says \"Tier-2 activation 78%\", "
            "your card says 78% or rounds honestly to 78%, not 79%."
        ),
        "brief_filename": "customer-technician-brief.md",
        "user_prompt_subject": "Implementation",
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
    snapshot_word = {
        "marketing": "company data",
        "revenue": "revenue data",
        "customer": "customer data",
        "marketing_strategist": "marketing strategy data",
        "marketing_builder": "marketing execution data",
        "revenue_generator": "account executive data",
        "revenue_developer": "sales development data",
        "revenue_operator": "revenue operations data",
        "customer_advocate": "customer success management data",
        "customer_operator": "customer success operations data",
        "customer_technician": "implementation data",
    }[archetype]
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


def _load_env_key(name: str) -> Optional[str]:
    """Read a named key from the .env file (returns None if not found)."""
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


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
#   Tier 1 (mechanical rewrite): swaps that preserve meaning AND clear voice.
#     - "against" → "versus" in comparison contexts.
#     - "X wins and Y loss(es)" → "X-Y record" (Phase 2.5b). The model reliably
#       reaches for "wins and losses" framing on competitive-record patterns
#       (P-RL-10 etc.); the rewrite drops the loss-as-noun problem framing
#       without losing the underlying numbers and is a structural translation,
#       not a lexical swap.
#   Tier 2 (fail-and-regenerate): problem-framing words (loss/gap/miss/failure)
#     that survive Tier 1 rewrites have no clean single-word substitute that
#     preserves meaning. Forcing a swap (e.g. gap→shift) produces semantically
#     off copy ("freed up the shift", "Q1 shift ran $310K"). Story Cards
#     surface forward signal only, so the right move is to surface unresolved
#     hits and let the caller regenerate the seed. The CLI exits non-zero
#     when any are present.
_USER_FACING_FIELDS = ("title", "anchor", "connect", "body")
_AGAINST_RE = re.compile(r"\bagainst\b", re.IGNORECASE)
_EM_DASH_RE = re.compile(r"\s*\u2014\s*")
# Wins/losses idiom rewrite (P-RL-10, P-MS-01 etc.). Handles model variants:
#   "5 wins and 1 loss"      — digits + "and"
#   "5 wins, 1 loss"         — digits + comma
#   "5 wins versus 1 loss"   — digits + "versus" (P-MS-01 competitive patterns)
#   "Five wins and one loss" — written-number forms 0-10
# Connector matches "and", comma, or "versus" (with optional surrounding whitespace).
_WORD_TO_DIGIT = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}
_NUM_TOKEN = r"\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten"
_WINS_LOSSES_RE = re.compile(
    rf"\b(?P<w>{_NUM_TOKEN})\s+wins?\s*(?:,\s*|\s+and\s+|\s+versus\s+|\s+against\s+)(?P<l>{_NUM_TOKEN})\s+loss(?:es)?\b",
    re.IGNORECASE,
)


def _wins_losses_sub(match: "re.Match") -> str:
    def to_digit(token: str) -> str:
        t = token.lower()
        return _WORD_TO_DIGIT.get(t, token)
    return f"{to_digit(match.group('w'))}-{to_digit(match.group('l'))} record"
# Tier 1: "closing/closes the gap" → "narrowing/narrows the distance" (forward framing)
_CLOSING_GAP_RE = re.compile(r"\bclos(?:ing|es)\s+the\s+gap\b", re.IGNORECASE)

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
            if _WINS_LOSSES_RE.search(new_value):
                rewritten = _WINS_LOSSES_RE.sub(_wins_losses_sub, new_value)
                edits.append({"card_index": idx, "field": field,
                              "rule": "X wins and/,/versus/against Y loss(es)→X-Y record",
                              "before": new_value, "after": rewritten})
                new_value = rewritten
            if _CLOSING_GAP_RE.search(new_value):
                def _gap_sub(m: "re.Match") -> str:
                    return "narrowing the distance" if m.group(0).lower().startswith("closing") else "narrows the distance"
                rewritten = _CLOSING_GAP_RE.sub(_gap_sub, new_value)
                edits.append({"card_index": idx, "field": field,
                              "rule": "closing/closes the gap→narrowing/narrows the distance",
                              "before": new_value, "after": rewritten})
                new_value = rewritten
            if _EM_DASH_RE.search(new_value):
                rewritten = _EM_DASH_RE.sub(", ", new_value)
                edits.append({"card_index": idx, "field": field,
                              "rule": "em-dash→comma",
                              "before": new_value, "after": rewritten})
                new_value = rewritten
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
    ap.add_argument(
        "--source", choices=["local-json", "hubspot-composio"],
        default="local-json",
        help=(
            "Data source. local-json (default): load from --input directory of JSON files. "
            "hubspot-composio: read from live HubSpot via Composio proxy. Requires "
            "COMPOSIO_API_KEY in .env (from app.composio.dev/settings -> API Keys). "
            "Optionally set COMPOSIO_ENTITY_ID (default travis@nomocoda.com) and "
            "COMPOSIO_ACCOUNT_ID to skip connection discovery."
        ),
    )
    args = ap.parse_args(argv)

    archetype = args.archetype
    cfg = _ARCHETYPE_CONFIG[archetype]

    if args.source == "hubspot-composio":
        api_key = os.environ.get("COMPOSIO_API_KEY") or _load_env_key("COMPOSIO_API_KEY")
        if not api_key:
            print(
                "ERROR: COMPOSIO_API_KEY not set. Add it to .env "
                "(from app.composio.dev/settings -> API Keys).",
                file=sys.stderr,
            )
            return 1
        entity_id = (
            os.environ.get("COMPOSIO_ENTITY_ID")
            or _load_env_key("COMPOSIO_ENTITY_ID")
            or "travis@nomocoda.com"
        )
        account_id = (
            os.environ.get("COMPOSIO_ACCOUNT_ID")
            or _load_env_key("COMPOSIO_ACCOUNT_ID")
            or None
        )
        from hubspot_adapter import load_hubspot_dataset  # noqa: E402
        ds = load_hubspot_dataset(
            api_key=api_key,
            entity_id=entity_id,
            connected_account_id=account_id,
        )
    else:
        ds = load_dataset(Path(args.input))
    guards = load_worker_guards()
    persona = (DATA_DIR / "persona.md").read_text()
    archetype_brief = (DATA_DIR / cfg["brief_filename"]).read_text()
    voice_brief = (DATA_DIR / "voice-brief.md").read_text()

    if archetype == "revenue":
        summary = build_revenue_summary(ds)
    elif archetype == "customer":
        summary = build_customer_summary(ds)
    elif archetype == "marketing_strategist":
        summary = build_marketing_strategist_summary(ds)
    elif archetype == "marketing_builder":
        summary = build_marketing_builder_summary(ds)
    elif archetype == "revenue_generator":
        summary = build_revenue_generator_summary(ds)
    elif archetype == "revenue_developer":
        summary = build_revenue_developer_summary(ds)
    elif archetype == "revenue_operator":
        summary = build_revenue_operator_summary(ds)
    elif archetype == "customer_advocate":
        summary = build_customer_advocate_summary(ds)
    elif archetype == "customer_operator":
        summary = build_customer_operator_summary(ds)
    elif archetype == "customer_technician":
        summary = build_customer_technician_summary(ds)
    else:
        summary = build_summary(ds)
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
