#!/usr/bin/env python3
"""
Atlas SaaS synthetic dataset generator — Stage 1 Relevance Engine eval seed.

Generates a deterministic synthetic dataset for a fictional B2B SaaS company
("Atlas SaaS", ~250 employees, mid-market focus) covering 12 months of
operating activity ending 2026-04-24. Output feeds directly into the Stage 1
Relevance Engine eval; a secondary CSV mode maps to HubSpot imports for Stage 2.

The dataset is reverse-engineered from the 15 locked VP Marketing Story Cards
in lens-demo/index.html (insightData.marketing.cards, idx 0..14). Each card
implies a data pattern; the seeder functions below plant those patterns
deterministically so the eval can verify the Relevance Engine surfaces them.

Card → seeder map (card index in marketing.cards, implied pattern, line number):
  idx 0  Three target accounts high-intent this week   → seed_p13_target_account_intent    (L1033)
  idx 1  Branded search 6-week streak                  → seed_p07_branded_search_streak    (L904)
  idx 2  Digital ads under plan, events reallocation   → seed_p05_digital_ads_reallocation (L790)
  idx 3  MM wins tech-stack + industry concentration   → seed_p11_mm_wins_concentration    (L608)
  idx 4  Launch two weeks out, campaign ready          → seed_p14_launch_ready             (L1106)
  idx 5  Marketing deals closing faster this week      → seed_p01_marketing_velocity       (L551)
  idx 6  Analyst mentions spike                        → seed_p10_analyst_spike            (L992)
  idx 7  Paid social > paid search pipeline (Q-flip)   → seed_p04_channel_flip             (L720)
  idx 8  SDR capacity underused                        → seed_p15_sdr_capacity             (L1199)
  idx 9  Share of voice beats top competitor           → seed_p08_share_of_voice           (L924)
  idx 10 Reference opt-ins concentrated                → seed_p12_reference_optins         (L1028)
  idx 11 Enterprise win rate lift                      → seed_p03_enterprise_winrate       (L664)
  idx 12 Direct traffic crossed organic                → seed_p09_direct_vs_organic        (L965)
  idx 13 April MM SQL surge + ABM acceptance           → seed_p02_mm_sql_abm               (L1121)
  idx 14 Q1 event deals closing faster than Q4         → seed_p06_event_velocity           (L834)

Run:
  python generate_dataset.py --seed 42 --format json --output ./output
  python generate_dataset.py --seed 42 --format csv --output ./output_csv
  python generate_dataset.py --validate --output ./output   # re-validate existing files

Validation asserts each of the 15 patterns is present in the generated data.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

from faker import Faker


# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

TODAY = date(2026, 4, 24)
WINDOW_START = date(2025, 4, 24)

CURRENT_WEEK = (date(2026, 4, 20), date(2026, 4, 26))
PRIOR_11_WEEKS = (date(2026, 2, 2), date(2026, 4, 19))
LAST_60_DAYS = (date(2026, 2, 23), date(2026, 4, 24))
LAST_30_DAYS = (date(2026, 3, 25), date(2026, 4, 24))

Q3_2026 = (date(2026, 7, 1), date(2026, 9, 30))
Q2_2026 = (date(2026, 4, 1), date(2026, 6, 30))
Q1_2026 = (date(2026, 1, 1), date(2026, 3, 31))
Q4_2025 = (date(2025, 10, 1), date(2025, 12, 31))
Q3_2025 = (date(2025, 7, 1), date(2025, 9, 30))
Q2_2025 = (date(2025, 4, 1), date(2025, 6, 30))

INDUSTRIES = [
    "fintech", "healthtech", "retail", "logistics", "manufacturing",
    "edtech", "cybersecurity", "media", "proptech", "traveltech",
]

BASE_TECH_POOL = [
    "Salesforce", "HubSpot", "Marketo", "Segment", "Looker",
    "Tableau", "Redshift", "BigQuery", "Databricks", "Airflow",
    "Slack", "Asana", "Notion", "Zendesk", "Okta",
]

SEGMENTS = ["small-business", "mid-market", "enterprise"]

LIFECYCLE_STAGES = [
    "subscriber", "lead", "mql", "sql", "opportunity", "customer",
]

DEAL_STAGES_OPEN = ["appointmentscheduled", "qualifiedtobuy", "presentationscheduled", "contractsent"]
DEAL_STAGE_WON = "closedwon"
DEAL_STAGE_LOST = "closedlost"

MARKETING_SOURCES = ["paid_social", "paid_search", "content", "email", "events", "webinar", "nurture"]
# Pattern ownership of lead_source values:
#   paid_social / paid_search → exclusive to p04 (channel-flip pipeline math)
#   events                    → exclusive to p06 (event-velocity DTC math)
#   content / email / webinar / nurture → general pool for p01 / p11 / filler
GENERAL_MARKETING_SOURCES = ["content", "email", "webinar", "nurture"]
NON_MARKETING_SOURCES = ["outbound", "referral", "direct", "partner"]

PRODUCT_LINES = ["Atlas Insights", "Atlas Workflow", "Atlas Connect", "Atlas Monitor", "Atlas Signal"]

COMPETITOR_NAMES = ["Beacon Systems", "Northstar Platform", "Verge IO", "Pinion Suite", "Orbit Cloud"]
TOP_THREE_COMPETITORS = {"Beacon Systems", "Northstar Platform", "Verge IO"}

ANALYST_FIRMS = ["Forrester", "G2", "Gartner", "IDC", "451 Research", "Ventana"]

ENGAGEMENT_TYPES = [
    "page_view", "form_fill", "email_open", "content_download",
    "ad_click", "demo_request", "pricing_page_view",
]
HIGH_INTENT_TYPES = {"pricing_page_view", "demo_request", "content_download"}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def iso(d: date) -> str:
    return d.isoformat()


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def week_end(d: date) -> date:
    """Sunday of the week containing d (ISO week: Monday=1..Sunday=7)."""
    return d + timedelta(days=(6 - d.weekday()))


def quarter_of(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"Q{q}_{d.year}"


def pick_weighted(rng: random.Random, items: List[Tuple[Any, float]]):
    total = sum(w for _, w in items)
    r = rng.uniform(0, total)
    acc = 0.0
    for val, w in items:
        acc += w
        if r <= acc:
            return val
    return items[-1][0]


# ----------------------------------------------------------------------------
# Generators
# ----------------------------------------------------------------------------

def gen_competitors() -> List[Dict]:
    return [{"name": n, "is_top_three": n in TOP_THREE_COMPETITORS} for n in COMPETITOR_NAMES]


def gen_companies(rng: random.Random, fake: Faker, n: int = 800) -> List[Dict]:
    companies: List[Dict] = []

    # Customer and target-account counts (hit the seeded patterns downstream)
    n_customers = 120
    n_targets = 50
    # March-added ABM target (for pattern 13)
    march_added_idx = n_targets - 1

    for i in range(n):
        company_id = f"CO-{i+1:05d}"
        segment = pick_weighted(rng, [("small-business", 0.40), ("mid-market", 0.45), ("enterprise", 0.15)])
        employees = {
            "small-business": rng.randint(10, 199),
            "mid-market": rng.randint(200, 1999),
            "enterprise": rng.randint(2000, 20000),
        }[segment]
        industry = rng.choice(INDUSTRIES)
        # Tech stack: 2-5 items from pool
        stack = rng.sample(BASE_TECH_POOL, k=rng.randint(2, 5))
        is_customer = i < n_customers
        is_target_account = (not is_customer) and (n_customers <= i < n_customers + n_targets)

        target_list_name = None
        created_date = fake.date_between(start_date=WINDOW_START - timedelta(days=365), end_date=TODAY - timedelta(days=30))
        if is_target_account:
            idx_in_targets = i - n_customers
            if idx_in_targets == march_added_idx:
                target_list_name = "March ABM Add"
                created_date = date(2026, 3, rng.randint(1, 28))
            else:
                # Mix named accounts + ABM program
                target_list_name = "Named Accounts" if idx_in_targets % 2 == 0 else "ABM Program"

        lifecycle_stage = "customer" if is_customer else rng.choice(["subscriber", "lead", "mql", "sql", "opportunity"])

        companies.append({
            "id": company_id,
            "name": fake.unique.company(),
            "segment": segment,
            "industry": industry,
            "employees": employees,
            "tech_stack": stack,
            "is_customer": is_customer,
            "is_target_account": is_target_account,
            "target_list_name": target_list_name,
            "created_date": iso(created_date),
            "lifecycle_stage": lifecycle_stage,
        })

    return companies


def gen_contacts(rng: random.Random, fake: Faker, companies: List[Dict], n: int = 3000) -> List[Dict]:
    contacts: List[Dict] = []
    titles_by_role = {
        "marketing": ["CMO", "VP Marketing", "Marketing Director", "Demand Gen Manager", "Content Lead"],
        "sales": ["VP Sales", "AE", "SDR Manager", "Sales Director"],
        "ops": ["RevOps Lead", "Marketing Ops", "Sales Ops Manager"],
        "exec": ["CEO", "COO", "CFO"],
        "product": ["VP Product", "PM", "Engineering Lead"],
    }
    roles = list(titles_by_role.keys())

    per_company = max(1, n // len(companies))
    idx = 0
    for company in companies:
        count = per_company + (1 if idx % 4 == 0 else 0)
        for _ in range(count):
            if len(contacts) >= n:
                break
            role = rng.choice(roles)
            title = rng.choice(titles_by_role[role])
            first = fake.first_name()
            last = fake.last_name()
            email = f"{first.lower()}.{last.lower()}{len(contacts)}@{company['name'].split()[0].lower()}.com"
            contacts.append({
                "id": f"CT-{len(contacts)+1:06d}",
                "company_id": company["id"],
                "first_name": first,
                "last_name": last,
                "email": email,
                "title": title,
                "role_category": role,
                "created_date": iso(fake.date_between(start_date=WINDOW_START, end_date=TODAY - timedelta(days=1))),
                # lifecycle_stage and became_sql_date get set by seeders below for MM SQL pattern
                "lifecycle_stage": "lead",
                "became_sql_date": None,
                "is_abm": False,
                "sql_accepted": False,
            })
            idx += 1
        if len(contacts) >= n:
            break

    return contacts


def gen_campaigns(rng: random.Random, fake: Faker) -> List[Dict]:
    campaigns: List[Dict] = []
    channels = ["paid_social", "paid_search", "email", "events", "content", "direct_mail"]

    # Regular campaigns spread across the window (3 per month average)
    months = []
    cur = WINDOW_START.replace(day=1)
    while cur <= TODAY:
        months.append(cur)
        # step to next month
        y, m = cur.year, cur.month + 1
        if m == 13:
            y += 1; m = 1
        cur = date(y, m, 1)

    base_names = {
        "paid_social": ["LinkedIn Always-On", "Meta Retargeting", "Reddit Awareness"],
        "paid_search": ["Google Brand", "Google Non-Brand", "Bing Capture"],
        "email": ["Monthly Nurture", "Product Newsletter", "Win-Back"],
        "events": ["SaaS Connect", "SignalSummit", "Regional Roadshow", "Industry Breakfast"],
        "content": ["Benchmark Report", "Buyer Guide", "Solution Brief"],
        "direct_mail": ["Executive Gifting"],
    }

    cid = 1
    for month_start in months:
        for channel in channels:
            if rng.random() < 0.55:
                continue
            name = rng.choice(base_names[channel]) + f" {month_start.strftime('%b %Y')}"
            start = month_start + timedelta(days=rng.randint(0, 10))
            end = start + timedelta(days=rng.randint(14, 45))
            spend = rng.randint(8000, 60000)
            campaigns.append({
                "id": f"CAM-{cid:04d}",
                "name": name,
                "channel": channel,
                "start_date": iso(start),
                "end_date": iso(end),
                "spend": spend,
                "is_launch_campaign": False,
                "launch_id": None,
                "status": "complete" if end < TODAY else "active",
            })
            cid += 1

    return campaigns


def gen_campaign_performance(rng: random.Random, campaigns: List[Dict]) -> List[Dict]:
    rows: List[Dict] = []
    for c in campaigns:
        start = date.fromisoformat(c["start_date"])
        end = date.fromisoformat(c["end_date"])
        days = max(1, (end - start).days + 1)
        daily_spend = c["spend"] / days
        for d in daterange(start, min(end, TODAY)):
            impressions = int(rng.uniform(500, 15000))
            clicks = int(impressions * rng.uniform(0.005, 0.05))
            conversions = int(clicks * rng.uniform(0.01, 0.08))
            rows.append({
                "campaign_id": c["id"],
                "date": iso(d),
                "impressions": impressions,
                "clicks": clicks,
                "conversions": conversions,
                "spend": round(daily_spend, 2),
            })
    return rows


def gen_budget() -> List[Dict]:
    """Base budget. Pattern 5 mutates digital_ads / events entries."""
    categories = ["digital_ads", "events", "content", "email", "ops_tools", "headcount"]
    quarters = ["Q2_2025", "Q3_2025", "Q4_2025", "Q1_2026", "Q2_2026"]
    base = {
        "digital_ads": 320000,
        "events": 180000,
        "content": 90000,
        "email": 40000,
        "ops_tools": 65000,
        "headcount": 520000,
    }
    rows: List[Dict] = []
    for q in quarters:
        for cat in categories:
            planned = base[cat]
            if q == "Q2_2026" and cat == "digital_ads":
                planned = 340000  # pattern 5
            rows.append({"category": cat, "quarter": q, "planned_amount": planned, "notes": ""})
    return rows


def gen_actual_spend(rng: random.Random, budget: List[Dict]) -> List[Dict]:
    """Daily actual spend per category. Pattern 5 shapes digital_ads and events in Q2."""
    rows: List[Dict] = []
    cat_by_q = {(b["category"], b["quarter"]): b["planned_amount"] for b in budget}

    def q_bounds(q: str) -> Tuple[date, date]:
        name, year = q.split("_")
        year = int(year)
        idx = int(name[1:])
        start = date(year, (idx - 1) * 3 + 1, 1)
        end_month = idx * 3
        end_day = {3: 31, 6: 30, 9: 30, 12: 31}[end_month]
        return start, date(year, end_month, end_day)

    for (cat, q), planned in cat_by_q.items():
        qs, qe = q_bounds(q)
        if qs > TODAY:
            continue
        effective_end = min(qe, TODAY)
        # Default: distribute spend evenly across quarter days, cap at effective_end share
        total_days = (qe - qs).days + 1
        daily = planned / total_days
        for d in daterange(qs, effective_end):
            amt = daily * rng.uniform(0.7, 1.3)
            rows.append({"category": cat, "date": iso(d), "amount": round(amt, 2)})
    return rows


def gen_engagement_events(rng: random.Random, companies: List[Dict], contacts: List[Dict]) -> List[Dict]:
    by_company: Dict[str, List[Dict]] = defaultdict(list)
    for c in contacts:
        by_company[c["company_id"]].append(c)

    rows: List[Dict] = []
    for co in companies:
        base_rate = {"enterprise": 25, "mid-market": 14, "small-business": 6}[co["segment"]]
        if co["is_target_account"]:
            base_rate = 30
        # events across 12 months
        n_events = int(base_rate * rng.uniform(0.6, 1.4))
        cts = by_company.get(co["id"], [])
        if not cts:
            continue
        for _ in range(n_events):
            d = WINDOW_START + timedelta(days=rng.randint(0, (TODAY - WINDOW_START).days))
            ev_type = rng.choices(
                ENGAGEMENT_TYPES,
                weights=[40, 15, 20, 8, 10, 3, 4],
                k=1,
            )[0]
            intent = "high" if ev_type in HIGH_INTENT_TYPES else rng.choice(["low", "medium"])
            rows.append({
                "company_id": co["id"],
                "contact_id": rng.choice(cts)["id"],
                "date": iso(d),
                "event_type": ev_type,
                "intent_level": intent,
            })
    return rows


def gen_branded_search(rng: random.Random) -> List[Dict]:
    """Weekly branded search volume. Pattern 7 seeds a 6-week run ending Apr 19."""
    rows: List[Dict] = []
    # generate weekly from WINDOW_START through TODAY (week-ending Sundays)
    first_sunday = week_end(WINDOW_START)
    d = first_sunday
    base = 1000
    while d <= TODAY:
        vol = int(base * rng.uniform(0.85, 1.15))
        rows.append({"date": iso(d), "search_volume": vol})
        d += timedelta(days=7)
    return rows


def gen_web_analytics(rng: random.Random) -> List[Dict]:
    """Daily analytics. Pattern 9 shapes April direct vs organic cross-over."""
    rows: List[Dict] = []
    channels = ["direct", "organic_search", "paid_search", "paid_social", "referral", "email", "other"]
    for d in daterange(WINDOW_START, TODAY):
        total = int(rng.uniform(4000, 6000))
        # default shares (April gets overridden by pattern 9)
        shares = {"direct": 0.18, "organic_search": 0.34, "paid_search": 0.14, "paid_social": 0.12, "referral": 0.08, "email": 0.08, "other": 0.06}
        for ch in channels:
            sessions = int(total * shares[ch])
            new_sessions = int(sessions * rng.uniform(0.35, 0.55))
            rows.append({"date": iso(d), "channel": ch, "sessions": sessions, "new_sessions": new_sessions})
    return rows


def gen_mentions(rng: random.Random, fake: Faker, competitors: List[Dict]) -> List[Dict]:
    """Daily mentions. Pattern 8 seeds April distribution: Atlas >> top competitor."""
    rows: List[Dict] = []
    sources = ["linkedin", "podcast", "press", "news", "twitter", "analyst"]
    # default background: low daily volume everywhere
    all_entities = ["Atlas SaaS"] + [c["name"] for c in competitors]
    for d in daterange(WINDOW_START, TODAY):
        # baseline 3-15 mentions per entity per day; month of April for Atlas/top competitor handled by seeder
        for ent in all_entities:
            base_daily = 6 if ent == "Atlas SaaS" else (4 if ent in TOP_THREE_COMPETITORS else 2)
            count = max(0, int(rng.gauss(base_daily, 2)))
            for _ in range(count):
                rows.append({
                    "date": iso(d),
                    "source_type": rng.choice(sources),
                    "entity": ent,
                    "headline": fake.sentence(nb_words=8),
                    "sentiment": rng.choice(["positive", "neutral", "neutral", "negative"]),
                })
    return rows


def gen_analyst_mentions(rng: random.Random, fake: Faker) -> List[Dict]:
    rows: List[Dict] = []
    # baseline older coverage (before Mar 12)
    for _ in range(20):
        d = WINDOW_START + timedelta(days=rng.randint(0, (date(2026, 3, 11) - WINDOW_START).days))
        firm = rng.choice(ANALYST_FIRMS)
        rows.append({
            "date": iso(d),
            "analyst_firm": firm,
            "title": fake.catch_phrase(),
            "url": f"https://{firm.lower().replace(' ', '')}.com/{fake.slug()}",
        })
    return rows


def gen_customer_reference_optins(rng: random.Random, companies: List[Dict]) -> List[Dict]:
    """Pattern 12 shapes opt-in rates per product line."""
    rows: List[Dict] = []
    customers = [c for c in companies if c["is_customer"]]
    # Seeded rates per product line
    target_rates = {
        "Atlas Insights": 0.76,
        "Atlas Workflow": 0.71,
        "Atlas Connect": 0.28,
        "Atlas Monitor": 0.17,
        "Atlas Signal": 0.11,
    }
    # Assign each customer 1-3 product lines
    n = len(customers)
    per_line = {pl: [] for pl in PRODUCT_LINES}
    for co in customers:
        k = rng.choice([1, 1, 2, 2, 3])
        lines = rng.sample(PRODUCT_LINES, k=k)
        for pl in lines:
            per_line[pl].append(co)

    # For each (customer, line) pair, decide opt-in deterministically to match target rate
    for pl, custs in per_line.items():
        target = target_rates[pl]
        want_yes = round(len(custs) * target)
        rng.shuffle(custs)
        for i, co in enumerate(custs):
            willing = i < want_yes
            rows.append({
                "customer_id": co["id"],
                "product_line": pl,
                "reference_willingness": willing,
                "recorded_date": iso(TODAY - timedelta(days=rng.randint(1, 120))),
            })
    return rows


def gen_product_launches() -> List[Dict]:
    return [
        {"id": "PL-001", "name": "Atlas Assist", "launch_date": iso(date(2026, 5, 8)), "status": "ready"},
        {"id": "PL-000", "name": "Atlas Monitor GA", "launch_date": iso(date(2025, 11, 4)), "status": "shipped"},
    ]


def gen_sdr_capacity(rng: random.Random) -> List[Dict]:
    """Pattern 15 seeds current-week shortfall."""
    rows: List[Dict] = []
    d = week_end(WINDOW_START)
    while d <= TODAY + timedelta(days=6):
        if d == week_end(TODAY):
            # current week — seed exact values
            rows.append({"week_ending_date": iso(d), "team_total_capacity": 210, "inbound_lead_volume": 142})
        else:
            cap = rng.randint(195, 220)
            inbound = rng.randint(165, 215)
            rows.append({"week_ending_date": iso(d), "team_total_capacity": cap, "inbound_lead_volume": inbound})
        d += timedelta(days=7)
    return rows


# ----------------------------------------------------------------------------
# Revenue Leader entities (Phase 2.3)
# ----------------------------------------------------------------------------

def gen_forecasts() -> List[Dict]:
    """Per-quarter commit, weighted pipeline at 80% confidence, plan, pacing.

    Static seeded rows feed RL patterns 01, 03, 14. Validators read these
    directly rather than recomputing them from deals — these are leadership
    artefacts produced by the forecast process, not derived sums.
    """
    return [
        {
            "quarter": "Q2_2026",
            "commit": 1_400_000,
            "weighted_pipeline_80pct": 1_600_000,
            "plan_total": 5_000_000,
            "plan_pacing_target_through_apr24": 840_000,
            "bookings_actual_through_apr24": 880_000,
            "enterprise_plan": 2_400_000,
        },
        {
            "quarter": "Q3_2026",
            "commit": 1_600_000,
            "weighted_pipeline_80pct": 1_750_000,
            "plan_total": 5_400_000,
            "plan_pacing_target_through_apr24": 0,
            "bookings_actual_through_apr24": 0,
            "enterprise_plan": 1_200_000,
        },
        {
            "quarter": "Q1_2026",
            "commit": 1_300_000,
            "weighted_pipeline_80pct": 1_350_000,
            "plan_total": 4_600_000,
            "plan_pacing_target_through_apr24": 0,
            "bookings_actual_through_apr24": 0,
            "enterprise_plan": 1_100_000,
        },
    ]


def gen_renewals(rng: random.Random, companies: List[Dict]) -> List[Dict]:
    """Renewal events with ARR by segment + computed NRR. RL P15 seeds Q2 MM."""
    rows: List[Dict] = []
    customers = [c for c in companies if c["is_customer"]]
    by_seg = defaultdict(list)
    for c in customers:
        by_seg[c["segment"]].append(c)

    # Quarter target ARR (renewed) per segment.
    targets = {
        ("Q2_2026", "mid-market"): 620_000,
        ("Q1_2026", "mid-market"): 540_000,
        ("Q4_2025", "mid-market"): 555_000,
        ("Q3_2025", "mid-market"): 568_000,
        ("Q2_2025", "mid-market"): 550_000,
        ("Q2_2026", "enterprise"): 380_000,
        ("Q1_2026", "enterprise"): 390_000,
        ("Q4_2025", "enterprise"): 420_000,
        ("Q3_2025", "enterprise"): 405_000,
        ("Q2_2025", "enterprise"): 395_000,
        ("Q2_2026", "small-business"): 210_000,
        ("Q1_2026", "small-business"): 220_000,
        ("Q4_2025", "small-business"): 215_000,
        ("Q3_2025", "small-business"): 205_000,
        ("Q2_2025", "small-business"): 200_000,
    }
    # Quarter NRR (renewed_arr / starting_arr) per segment-quarter.
    nrr_map = {
        ("Q2_2026", "mid-market"): 1.12,
        ("Q1_2026", "mid-market"): 1.10,
        ("Q4_2025", "mid-market"): 1.16,
        ("Q3_2025", "mid-market"): 1.18,
        ("Q2_2025", "mid-market"): 1.14,
        ("Q2_2026", "enterprise"): 1.06,
        ("Q1_2026", "enterprise"): 1.08,
        ("Q4_2025", "enterprise"): 1.11,
        ("Q3_2025", "enterprise"): 1.10,
        ("Q2_2025", "enterprise"): 1.09,
        ("Q2_2026", "small-business"): 1.02,
        ("Q1_2026", "small-business"): 1.03,
        ("Q4_2025", "small-business"): 1.04,
        ("Q3_2025", "small-business"): 1.02,
        ("Q2_2025", "small-business"): 1.01,
    }

    def q_bounds(q: str) -> Tuple[date, date]:
        name, year = q.split("_")
        year = int(year)
        idx = int(name[1:])
        start = date(year, (idx - 1) * 3 + 1, 1)
        end_month = idx * 3
        end_day = {3: 31, 6: 30, 9: 30, 12: 31}[end_month]
        return start, date(year, end_month, end_day)

    rid = 1
    for (q, seg), target_arr in targets.items():
        qs, qe = q_bounds(q)
        # Q2_2026 is the active quarter — events through TODAY only
        effective_end = min(qe, TODAY)
        if qs > TODAY:
            continue
        # Spread the target across 4-9 renewal events
        n_events = rng.randint(4, 9)
        amounts = _split_total(rng, target_arr, n_events)
        seg_pool = by_seg.get(seg, [])
        if not seg_pool:
            continue
        for amt in amounts:
            co = rng.choice(seg_pool)
            d = qs + timedelta(days=rng.randint(0, (effective_end - qs).days))
            rows.append({
                "id": f"RN-{rid:05d}",
                "company_id": co["id"],
                "quarter": q,
                "segment": seg,
                "renewal_date": iso(d),
                "renewed_arr": amt,
                "nrr": nrr_map[(q, seg)],
            })
            rid += 1
    return rows


def gen_expansion_opportunities() -> List[Dict]:
    """Default empty list. Pattern P-RL-11 seeds 8 in last 30 days."""
    return []


# ----------------------------------------------------------------------------
# Pattern seeders (mutate generated dataset to plant signal patterns)
# ----------------------------------------------------------------------------

def _new_deal_id(existing: List[Dict]) -> str:
    return f"DL-{len(existing)+1:05d}"


def _pick_company_by_segment(rng: random.Random, companies: List[Dict], segment: str, exclude_customers: bool = True) -> Dict:
    pool = [c for c in companies if c["segment"] == segment and (not exclude_customers or not c["is_customer"])]
    return rng.choice(pool)


def seed_p01_marketing_velocity(rng: random.Random, deals: List[Dict], companies: List[Dict]) -> None:
    """Card 5 — marketing-sourced deals closing faster this week (38d vs 52d avg)."""
    # Current-week MS wins: 9 total, 7 mid-market, avg 38 days
    cw_start, cw_end = CURRENT_WEEK
    cw_span = (cw_end - cw_start).days + 1

    # Current week: 7 MM + 2 SMB (spec says "bulk MM, 7 of 9"). No enterprise here —
    # p03 owns all Q2 enterprise closed deals so its avg-won mean stays on target.
    cw_segments = ["mid-market"] * 7 + ["small-business", "small-business"]
    rng.shuffle(cw_segments)
    cw_dtcs = [35, 36, 37, 38, 38, 39, 40, 41, 38]  # mean 38
    # Cap close-date at TODAY so all cw wins land inside LAST_60_DAYS (which
    # ends at TODAY); p11's MM-60d count depends on this.
    cw_close_cap_days = (TODAY - cw_start).days  # 4 → close in {Apr 20..24}
    for seg, dtc in zip(cw_segments, cw_dtcs):
        co = _pick_company_by_segment(rng, companies, seg)
        close = cw_start + timedelta(days=rng.randint(0, cw_close_cap_days))
        create = close - timedelta(days=dtc)
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": rng.randint(8000, 120000),
            "stage": DEAL_STAGE_WON,
            "create_date": iso(create),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": True,
            "lead_source": rng.choice(GENERAL_MARKETING_SOURCES),
            "campaign_source_id": None,
            "segment": seg,
            "_pattern": "p01_cw",
        })

    # Prior 11 weeks MS wins: 35 deals avg 52d, SMB only. Enterprise closed deals
    # are the exclusive territory of p03; MM closed deals in last 60d are the
    # exclusive territory of p11 (card 11's fintech concentration). The prior-11w
    # window overlaps last-60d heavily (Feb 23 - Apr 19), so making these SMB
    # keeps p11's MM-60d count at the 14 target. Velocity math is segment-agnostic.
    prior_start, prior_end = PRIOR_11_WEEKS
    prior_span = (prior_end - prior_start).days + 1
    for i in range(35):
        seg = "small-business"
        close = prior_start + timedelta(days=rng.randint(0, prior_span - 1))
        dtc = int(rng.gauss(52, 3))
        dtc = max(40, min(65, dtc))
        create = close - timedelta(days=dtc)
        co = _pick_company_by_segment(rng, companies, seg)
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": rng.randint(8000, 140000),
            "stage": DEAL_STAGE_WON,
            "create_date": iso(create),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": True,
            "lead_source": rng.choice(GENERAL_MARKETING_SOURCES),
            "campaign_source_id": None,
            "segment": seg,
            "_pattern": "p01_prior",
        })


def seed_p11_mm_wins_concentration(rng: random.Random, deals: List[Dict], companies: List[Dict]) -> None:
    """Card 4 — last 60 days MM wins share tech-stack + industry concentration.

    Requirement: of MM wins in last 60 days, >=8 in 'fintech' industry and
    >=11 running both Snowflake and dbt. Pattern 1 already seeded 7 MM wins
    in the current week; we boost those plus add 7 more MM wins Feb 23-Apr 19.
    """
    # Mutate the current-week MM wins' companies: all 7 get fintech industry + Snowflake/dbt
    # stack. Over-seed (vs. the 8-fintech / 11-stack targets) so accidental company overlap
    # between cw_mm_wins and p11_mm_60d can't drop us under target.
    cw_mm_wins = [d for d in deals if d.get("_pattern") == "p01_cw" and d["segment"] == "mid-market"]
    for i, d in enumerate(cw_mm_wins):
        co = next(c for c in companies if c["id"] == d["company_id"])
        if i < 5:
            co["industry"] = "fintech"
        stack = set(co["tech_stack"]) | {"Snowflake", "dbt"}
        co["tech_stack"] = list(stack)

    # Add 7 more MM wins in Feb 23 - Apr 19 to reach 14 MM wins in last 60d window
    feb23 = date(2026, 2, 23)
    apr19 = date(2026, 4, 19)
    span = (apr19 - feb23).days
    for i in range(7):
        co = _pick_company_by_segment(rng, companies, "mid-market")
        # 5 fintech, all 7 with Snowflake+dbt → combined 10+ fintech, 14 Snowflake+dbt
        # covers the 8-fintech / 11-stack card targets with margin.
        if i < 5:
            co["industry"] = "fintech"
        co["tech_stack"] = list(set(co["tech_stack"]) | {"Snowflake", "dbt"})
        close = feb23 + timedelta(days=rng.randint(0, span))
        dtc = rng.randint(35, 60)
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": rng.randint(15000, 90000),
            "stage": DEAL_STAGE_WON,
            "create_date": iso(close - timedelta(days=dtc)),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": True,
            "lead_source": rng.choice(NON_MARKETING_SOURCES + GENERAL_MARKETING_SOURCES),
            "campaign_source_id": None,
            "segment": "mid-market",
            "_pattern": "p11_mm_60d",
        })


def _amounts_at_mean(rng: random.Random, n: int, mean: int, spread: int) -> List[int]:
    """n positive ints with exact-target mean, each within mean±spread. Guards small-sample drift."""
    vals = [mean + rng.randint(-spread, spread) for _ in range(n)]
    # Correct any residual drift from integer rounding
    diff = mean * n - sum(vals)
    vals[0] += diff
    return vals


def seed_p03_enterprise_winrate(rng: random.Random, deals: List[Dict], companies: List[Dict]) -> None:
    """Marketing card 12 — enterprise WR 31% Q2 vs 22% trailing-4Q; avg won $187K vs $142K.

    Phase 2.3 expansion: source-stratify Q2 enterprise so RL-12's MS-vs-outbound
    win-rate split is grounded (14 MS / 7 outbound / 5 partner-or-referral, with
    4/1/3 wins respectively → 8/26 = 30.8% aggregate). Also pin Q1_2026
    enterprise wins to avg ~$145K so RL-08 (Q2 vs Q1 won-deal size delta)
    reads cleanly.
    """
    q2_start = Q2_2026[0]
    q2_effective_end = min(Q2_2026[1], TODAY)
    span_q2 = (q2_effective_end - q2_start).days
    q2_win_amounts = _amounts_at_mean(rng, 8, 187000, 15000)

    # Q2 enterprise breakdown by source (RL-12):
    #   MS-sourced (14): 4 wins, 10 lost. lead_source from
    #     {content, email, webinar, nurture} — paid_social/paid_search reserved
    #     for p04, events for p06.
    #   Outbound (7): 1 win, 6 lost.
    #   Partner / referral / direct (5): 3 wins, 2 lost.
    # Won amounts come from q2_win_amounts (sequence stable across runs).
    ms_ent_sources = ["content", "email", "webinar", "nurture"]
    q2_strata = (
        [("ms", True)] * 4 + [("ms", False)] * 10
        + [("outbound", True)] * 1 + [("outbound", False)] * 6
        + [("partner", True)] * 3 + [("partner", False)] * 2
    )
    win_amount_iter = iter(q2_win_amounts)
    for stratum, is_won in q2_strata:
        co = _pick_company_by_segment(rng, companies, "enterprise")
        # MS-sourced enterprise wins must close BEFORE Apr 20 so they don't
        # leak into p01's current-week MS-velocity cohort.
        if stratum == "ms" and is_won:
            cw_floor_offset = (CURRENT_WEEK[0] - q2_start).days  # 19
            close = q2_start + timedelta(days=rng.randint(0, max(0, cw_floor_offset - 1)))
        else:
            close = q2_start + timedelta(days=rng.randint(0, span_q2))
        amount = next(win_amount_iter) if is_won else int(rng.gauss(160000, 25000))
        amount = max(60000, amount)
        dtc = rng.randint(45, 95)
        if stratum == "ms":
            lead_source = rng.choice(ms_ent_sources)
        elif stratum == "outbound":
            lead_source = "outbound"
        else:
            lead_source = rng.choice(["partner", "referral", "direct"])
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": amount,
            "stage": DEAL_STAGE_WON if is_won else DEAL_STAGE_LOST,
            "create_date": iso(close - timedelta(days=dtc)),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": is_won,
            "lead_source": lead_source,
            "campaign_source_id": None,
            "segment": "enterprise",
            "_pattern": f"p03_q2_{stratum}",
        })

    # Trailing 4Q enterprise closed (Apr 1, 2025 - Mar 31, 2026): 180 deals,
    # 40 wins. Pin 3 of those wins inside Q1_2026 with avg $145K (RL-08); the
    # remaining 37 wins distribute across Q2_2025-Q4_2025 with avg ~$141.8K so
    # the four-quarter trailing average lands at $142K.
    trailing_start = date(2025, 4, 1)
    trailing_end = date(2026, 3, 31)
    pre_q1_2026_end = date(2025, 12, 31)
    pre_q1_span = (pre_q1_2026_end - trailing_start).days
    q1_2026_span = (trailing_end - Q1_2026[0]).days

    # 3 Q1_2026 wins: avg $145K (RL-08).
    q1_win_amounts = _amounts_at_mean(rng, 3, 145000, 8000)
    for amt in q1_win_amounts:
        co = _pick_company_by_segment(rng, companies, "enterprise")
        close = Q1_2026[0] + timedelta(days=rng.randint(0, q1_2026_span))
        dtc = rng.randint(50, 110)
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": amt,
            "stage": DEAL_STAGE_WON,
            "create_date": iso(close - timedelta(days=dtc)),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": True,
            "lead_source": rng.choice(NON_MARKETING_SOURCES),
            "campaign_source_id": None,
            "segment": "enterprise",
            "_pattern": "p03_trailing_q1won",
        })

    # 37 trailing wins outside Q1_2026 (avg ~$141.8K so 4Q trailing holds at $142K).
    other_trailing_amounts = _amounts_at_mean(rng, 37, 141800, 20000)
    for amt in other_trailing_amounts:
        co = _pick_company_by_segment(rng, companies, "enterprise")
        close = trailing_start + timedelta(days=rng.randint(0, pre_q1_span))
        dtc = rng.randint(50, 110)
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": amt,
            "stage": DEAL_STAGE_WON,
            "create_date": iso(close - timedelta(days=dtc)),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": True,
            "lead_source": rng.choice(NON_MARKETING_SOURCES),
            "campaign_source_id": None,
            "segment": "enterprise",
            "_pattern": "p03_trailing_otherwon",
        })

    # 140 trailing losses to fill out the 180-deal cohort.
    for _ in range(140):
        co = _pick_company_by_segment(rng, companies, "enterprise")
        close = trailing_start + timedelta(days=rng.randint(0, (trailing_end - trailing_start).days))
        amount = max(50000, int(rng.gauss(150000, 25000)))
        dtc = rng.randint(50, 110)
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": amount,
            "stage": DEAL_STAGE_LOST,
            "create_date": iso(close - timedelta(days=dtc)),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": False,
            "lead_source": rng.choice(NON_MARKETING_SOURCES),
            "campaign_source_id": None,
            "segment": "enterprise",
            "_pattern": "p03_trailing_loss",
        })


def seed_p04_channel_flip(rng: random.Random, deals: List[Dict], campaigns: List[Dict], companies: List[Dict]) -> None:
    """Card 8 — Q2 paid_social > paid_search; Q1 inverted.

    Targets: Q2 paid_social pipeline $620K, paid_search $380K;
             Q1 paid_search $720K, paid_social $410K.
    """
    # Find campaigns by channel and quarter (pick one per channel per quarter to attribute deals to)
    def pick_campaign(channel: str, qstart: date, qend: date) -> Dict:
        candidates = [c for c in campaigns if c["channel"] == channel and qstart <= date.fromisoformat(c["start_date"]) <= qend]
        return candidates[0] if candidates else None

    q1_social = pick_campaign("paid_social", *Q1_2026)
    q1_search = pick_campaign("paid_search", *Q1_2026)
    q2_social = pick_campaign("paid_social", *Q2_2026)
    q2_search = pick_campaign("paid_search", *Q2_2026)

    def seed_bucket(total: int, n_deals: int, quarter_bounds: Tuple[date, date], lead_source: str, cam: Dict, tag: str):
        qs, qe = quarter_bounds
        qe_eff = min(qe, TODAY)
        span = max(0, (qe_eff - qs).days)
        amounts = _split_total(rng, total, n_deals)
        for amt in amounts:
            # MM/SMB only — if an enterprise closes here it would leak into p03's win-rate math.
            co = _pick_company_by_segment(rng, companies, rng.choice(["mid-market", "small-business"]))
            create = qs + timedelta(days=rng.randint(0, span))
            # leave most open (pipeline = created)
            is_closed = rng.random() < 0.25
            is_won = is_closed and rng.random() < 0.35
            close = create + timedelta(days=rng.randint(25, 75)) if is_closed else None
            if close and close > TODAY:
                close = None
                is_closed = False
                is_won = False
            # Reopen (keep as pipeline) if the closed-win would contaminate another pattern:
            #   - MM closed-wins in last 60d muddy p11's fintech concentration
            #   - any MS closed-win landing in current week inflates p01's cw mean DTC
            if is_closed and is_won and (
                (co["segment"] == "mid-market" and close and LAST_60_DAYS[0] <= close <= LAST_60_DAYS[1])
                or (close and CURRENT_WEEK[0] <= close <= CURRENT_WEEK[1])
            ):
                is_closed = False
                is_won = False
                close = None
            deals.append({
                "id": _new_deal_id(deals),
                "company_id": co["id"],
                "amount": amt,
                "stage": (DEAL_STAGE_WON if is_won else DEAL_STAGE_LOST) if is_closed else rng.choice(DEAL_STAGES_OPEN),
                "create_date": iso(create),
                "close_date": iso(close) if close else None,
                "is_closed": is_closed,
                "is_won": bool(is_won),
                "lead_source": lead_source,
                "campaign_source_id": cam["id"] if cam else None,
                "segment": co["segment"],
                "_pattern": tag,
            })

    seed_bucket(620_000, 20, Q2_2026, "paid_social", q2_social, "p04_q2_social")
    seed_bucket(380_000, 14, Q2_2026, "paid_search", q2_search, "p04_q2_search")
    seed_bucket(720_000, 25, Q1_2026, "paid_search", q1_search, "p04_q1_search")
    seed_bucket(410_000, 14, Q1_2026, "paid_social", q1_social, "p04_q1_social")


def _split_total(rng: random.Random, total: int, n: int) -> List[int]:
    """Split total into n positive integers, roughly even with some variance."""
    if n <= 0:
        return []
    avg = total // n
    raw = [int(rng.gauss(avg, avg * 0.20)) for _ in range(n)]
    raw = [max(5000, v) for v in raw]
    # scale to exact total
    s = sum(raw)
    scaled = [round(v * total / s) for v in raw]
    # fix rounding drift
    diff = total - sum(scaled)
    scaled[0] += diff
    return scaled


def seed_p05_digital_ads_reallocation(budget: List[Dict], actual_spend: List[Dict]) -> None:
    """Card 3 — Q2 digital_ads $84K under plan; $84K reallocated to events (SaaS Connect + SignalSummit)."""
    # Budget: add two reallocation line items for events in Q2_2026
    budget.append({
        "category": "events_saas_connect",
        "quarter": "Q2_2026",
        "planned_amount": 42000,
        "notes": "Reallocation from digital_ads (pattern 5).",
    })
    budget.append({
        "category": "events_signal_summit",
        "quarter": "Q2_2026",
        "planned_amount": 42000,
        "notes": "Reallocation from digital_ads (pattern 5).",
    })

    # Rewrite Q2 digital_ads actual_spend so Apr 1-23 cumulative = ~$256K
    target_through_apr23 = 256000
    # Remove any existing Q2_2026 digital_ads rows
    q2_start = Q2_2026[0]
    q2_end = Q2_2026[1]
    to_keep = []
    for r in actual_spend:
        d = date.fromisoformat(r["date"])
        if r["category"] == "digital_ads" and q2_start <= d <= q2_end:
            continue
        to_keep.append(r)
    actual_spend.clear()
    actual_spend.extend(to_keep)

    # Seed Apr 1-23 with sum 256000 spread evenly with mild variance
    days = list(daterange(q2_start, date(2026, 4, 23)))
    base = target_through_apr23 / len(days)
    pieces = []
    rng = random.Random(2026)  # local deterministic for daily noise
    for d in days:
        amt = base * rng.uniform(0.85, 1.15)
        pieces.append((d, amt))
    s = sum(a for _, a in pieces)
    scale = target_through_apr23 / s
    for d, amt in pieces:
        actual_spend.append({"category": "digital_ads", "date": iso(d), "amount": round(amt * scale, 2)})


def seed_p06_event_velocity(rng: random.Random, deals: List[Dict], campaigns: List[Dict], companies: List[Dict]) -> None:
    """Card 15 — Q1 event-sourced DTC avg 47d, Q4 event-sourced DTC avg 71d; SaaS Connect drives Q1 speed."""
    # Find a Q1 SaaS Connect campaign + other Q1 event campaigns + Q4 event campaigns
    q1_events = [c for c in campaigns if c["channel"] == "events" and Q1_2026[0] <= date.fromisoformat(c["start_date"]) <= Q1_2026[1]]
    q4_events = [c for c in campaigns if c["channel"] == "events" and Q4_2025[0] <= date.fromisoformat(c["start_date"]) <= Q4_2025[1]]
    saas_connect_q1 = next((c for c in q1_events if "SaaS Connect" in c["name"]), None)
    if not saas_connect_q1:
        # Always ensure a SaaS Connect Q1 campaign exists; the card calls it out by name.
        saas_connect_q1 = {
            "id": "CAM-SCQ1-001",
            "name": "SaaS Connect Feb 2026",
            "channel": "events",
            "start_date": iso(date(2026, 2, 10)),
            "end_date": iso(date(2026, 2, 12)),
            "spend": 55000,
            "is_launch_campaign": False,
            "launch_id": None,
            "status": "complete",
        }
        campaigns.append(saas_connect_q1)
        q1_events.append(saas_connect_q1)

    # Q1 event deals: 25 total, 12 SaaS Connect, avg DTC 47. Close dates in Q1 or shortly after.
    # All closed-wins are SMB: keeping MM out of the event pool preserves p11's last-60d
    # MM concentration signal (Q1 event wins can land inside the last-60d window).
    q1_event_campaigns = q1_events or []
    for i in range(25):
        cam = saas_connect_q1 if i < 12 else (rng.choice(q1_event_campaigns) if q1_event_campaigns else None)
        co = _pick_company_by_segment(rng, companies, "small-business")
        create = Q1_2026[0] + timedelta(days=rng.randint(5, 85))
        dtc = max(35, min(60, int(rng.gauss(47, 4))))
        close = create + timedelta(days=dtc)
        if close > TODAY:
            continue
        # p01 invariant: events is a marketing source, so a q1 event deal that closes
        # inside the current week would inflate p01's cw DTC mean. Clip to Apr 19 (last
        # day of prior-11w) so the deal still counts in the prior-window denominator.
        if CURRENT_WEEK[0] <= close <= CURRENT_WEEK[1]:
            close = PRIOR_11_WEEKS[1]
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": rng.randint(12000, 95000),
            "stage": DEAL_STAGE_WON,
            "create_date": iso(create),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": True,
            "lead_source": "events",
            "campaign_source_id": cam["id"] if cam else None,
            "segment": co["segment"],
            "_pattern": "p06_q1",
        })

    # Q4 event deals: 15 total, avg DTC 71 (Q4 closes are pre-last-60d but kept SMB for symmetry)
    for i in range(15):
        cam = rng.choice(q4_events) if q4_events else None
        co = _pick_company_by_segment(rng, companies, "small-business")
        create = Q4_2025[0] + timedelta(days=rng.randint(5, 85))
        dtc = max(60, min(84, int(rng.gauss(71, 4))))
        close = create + timedelta(days=dtc)
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": rng.randint(12000, 90000),
            "stage": DEAL_STAGE_WON,
            "create_date": iso(create),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": True,
            "lead_source": "events",
            "campaign_source_id": cam["id"] if cam else None,
            "segment": co["segment"],
            "_pattern": "p06_q4",
        })


def seed_p07_branded_search_streak(rng: random.Random, branded_search: List[Dict]) -> None:
    """Card 2 — branded search 6 consecutive WoW increases ending week of Apr 13-19, cumulative ~92%."""
    # Week-ending Sundays for the 7 anchor points: Mar 8, Mar 15, Mar 22, Mar 29, Apr 5, Apr 12, Apr 19
    anchor_ends = [date(2026, 3, 8), date(2026, 3, 15), date(2026, 3, 22),
                   date(2026, 3, 29), date(2026, 4, 5), date(2026, 4, 12), date(2026, 4, 19)]
    base = 1000
    mult = 1.14  # WoW growth
    vals = [int(base * (mult ** i)) for i in range(7)]  # last value ~2195, cumulative ~+120%
    # dial to target ~92% cumulative by using 1.115 WoW
    mult = 1.115
    vals = [int(base * (mult ** i)) for i in range(7)]  # last ~1916 → +91.6%

    index = {date.fromisoformat(r["date"]): r for r in branded_search}
    for d, v in zip(anchor_ends, vals):
        if d in index:
            index[d]["search_volume"] = v
        else:
            branded_search.append({"date": iso(d), "search_volume": v})


def seed_p08_share_of_voice(rng: random.Random, fake: Faker, mentions: List[Dict]) -> None:
    """Card 10 — April (through Apr 24): Atlas 1840 mentions, top competitor 1210."""
    # Strip any existing April mentions for Atlas SaaS and the top competitor; rebuild
    apr_start = date(2026, 4, 1)
    keep: List[Dict] = []
    for m in mentions:
        d = date.fromisoformat(m["date"])
        if apr_start <= d <= TODAY and m["entity"] in ({"Atlas SaaS"} | TOP_THREE_COMPETITORS):
            continue
        keep.append(m)
    mentions.clear()
    mentions.extend(keep)

    apr_days = list(daterange(apr_start, TODAY))
    # Atlas SaaS: 1840 mentions across 24 days
    sources = ["linkedin", "podcast", "press", "news", "twitter", "analyst"]
    src_weights = [0.40, 0.22, 0.10, 0.14, 0.12, 0.02]
    def _add(entity: str, total: int):
        per_day_base = total / len(apr_days)
        remaining = total
        for i, d in enumerate(apr_days):
            if i == len(apr_days) - 1:
                count = remaining
            else:
                count = max(0, int(rng.gauss(per_day_base, per_day_base * 0.15)))
                count = min(count, remaining)
            remaining -= count
            for _ in range(count):
                mentions.append({
                    "date": iso(d),
                    "source_type": rng.choices(sources, weights=src_weights)[0],
                    "entity": entity,
                    "headline": fake.sentence(nb_words=8),
                    "sentiment": rng.choice(["positive", "positive", "neutral", "neutral", "negative"]),
                })
    _add("Atlas SaaS", 1840)
    _add("Beacon Systems", 1210)
    _add("Northstar Platform", 780)
    _add("Verge IO", 640)


def seed_p09_direct_vs_organic(rng: random.Random, web_analytics: List[Dict]) -> None:
    """Card 13 — April direct 42% of new_sessions, organic 38%; crossed on Apr 8."""
    apr_start = date(2026, 4, 1)
    # Drop existing April rows and rebuild
    kept = [r for r in web_analytics if not (apr_start <= date.fromisoformat(r["date"]) <= TODAY)]
    web_analytics.clear()
    web_analytics.extend(kept)

    # Days: Apr 1-7 before cross (direct<organic), Apr 8 cross day, Apr 9-24 after cross (direct>organic)
    for d in daterange(apr_start, TODAY):
        total_sessions = int(rng.gauss(5000, 250))
        total_sessions = max(3500, total_sessions)
        if d <= date(2026, 4, 7):
            shares = {"direct": 0.30, "organic_search": 0.44, "paid_search": 0.10,
                      "paid_social": 0.08, "referral": 0.04, "email": 0.02, "other": 0.02}
        elif d == date(2026, 4, 8):
            shares = {"direct": 0.38, "organic_search": 0.38, "paid_search": 0.10,
                      "paid_social": 0.08, "referral": 0.04, "email": 0.01, "other": 0.01}
        else:
            shares = {"direct": 0.48, "organic_search": 0.33, "paid_search": 0.08,
                      "paid_social": 0.06, "referral": 0.03, "email": 0.01, "other": 0.01}
        for ch, sh in shares.items():
            sess = int(total_sessions * sh)
            new_sess = int(sess * rng.uniform(0.85, 0.95))  # high new-visitor rate since we're tracking new_sessions
            web_analytics.append({"date": iso(d), "channel": ch, "sessions": sess, "new_sessions": new_sess})


def seed_p10_analyst_spike(rng: random.Random, fake: Faker, analyst_mentions: List[Dict]) -> None:
    """Card 7 — past 14 days 9 analyst mentions; prior 30 days 6; Forrester + G2 lead; cluster on Apr 9."""
    # Prior 30 days (Mar 12 - Apr 10): 6 entries
    prior_start = date(2026, 3, 12)
    prior_end = date(2026, 4, 10)
    firms_prior = ["Forrester", "G2", "Gartner", "IDC", "451 Research", "Ventana"]
    for firm in firms_prior:
        d = prior_start + timedelta(days=rng.randint(0, (prior_end - prior_start).days))
        analyst_mentions.append({
            "date": iso(d),
            "analyst_firm": firm,
            "title": fake.catch_phrase(),
            "url": f"https://{firm.lower().replace(' ', '')}.com/{fake.slug()}",
        })

    # Past 14 days (Apr 11 - Apr 24): 9 entries, Forrester + G2 lead (3 each), cluster Apr 9-12
    last14_entries = [
        ("Forrester", date(2026, 4, 11)),
        ("Forrester", date(2026, 4, 12)),
        ("Forrester", date(2026, 4, 18)),
        ("G2", date(2026, 4, 11)),
        ("G2", date(2026, 4, 13)),
        ("G2", date(2026, 4, 22)),
        ("Gartner", date(2026, 4, 15)),
        ("IDC", date(2026, 4, 20)),
        ("451 Research", date(2026, 4, 23)),
    ]
    for firm, d in last14_entries:
        analyst_mentions.append({
            "date": iso(d),
            "analyst_firm": firm,
            "title": fake.catch_phrase(),
            "url": f"https://{firm.lower().replace(' ', '')}.com/{fake.slug()}",
        })


def seed_p12_reference_optins() -> None:
    """Already seeded in gen_customer_reference_optins; no-op placeholder for mapping clarity."""
    return


def seed_p13_target_account_intent(rng: random.Random, companies: List[Dict], contacts: List[Dict], engagement: List[Dict]) -> None:
    """Card 1 — exactly 3 target accounts hit 5+ high-intent events in current week (Apr 20-26)."""
    cw_start, cw_end = CURRENT_WEEK

    # 1. Cap all other target accounts at <5 high-intent events in current week (drop excess).
    targets = [c for c in companies if c["is_target_account"]]

    # Remove ALL current-week high-intent events on target accounts first
    def in_cw(d_str: str) -> bool:
        d = date.fromisoformat(d_str)
        return cw_start <= d <= cw_end

    kept = []
    for e in engagement:
        if e["event_type"] in HIGH_INTENT_TYPES and in_cw(e["date"]):
            # keep only for non-target-account companies
            co = next(c for c in companies if c["id"] == e["company_id"])
            if co["is_target_account"]:
                continue
        kept.append(e)
    engagement.clear()
    engagement.extend(kept)

    # 2. Pick 3 specific target accounts to seed with 5+ high-intent events.
    # Two on Named Accounts list, one on March ABM Add list.
    named = [c for c in targets if c["target_list_name"] == "Named Accounts"]
    march = [c for c in targets if c["target_list_name"] == "March ABM Add"]
    assert len(named) >= 2, "Need at least 2 Named Accounts"
    assert len(march) >= 1, "Need at least 1 March ABM Add"
    chosen = rng.sample(named, 2) + [march[0]]

    by_company_contacts: Dict[str, List[Dict]] = defaultdict(list)
    for c in contacts:
        by_company_contacts[c["company_id"]].append(c)

    cw_days = list(daterange(cw_start, cw_end))
    for co in chosen:
        n_events = rng.randint(5, 8)
        cts = by_company_contacts.get(co["id"], [])
        if not cts:
            # ensure at least one contact
            continue
        for _ in range(n_events):
            d = rng.choice(cw_days)
            ev = rng.choice(list(HIGH_INTENT_TYPES))
            engagement.append({
                "company_id": co["id"],
                "contact_id": rng.choice(cts)["id"],
                "date": iso(d),
                "event_type": ev,
                "intent_level": "high",
            })

    # 3. Cap other target accounts to at most 4 current-week high-intent events.
    # (We removed them all above; add back up to 4 on some, and <=4 on others.)
    other_targets = [c for c in targets if c["id"] not in {x["id"] for x in chosen}]
    for co in other_targets:
        cap = rng.randint(0, 4)
        cts = by_company_contacts.get(co["id"], [])
        if not cts:
            continue
        for _ in range(cap):
            d = rng.choice(cw_days)
            ev = rng.choice(list(HIGH_INTENT_TYPES))
            engagement.append({
                "company_id": co["id"],
                "contact_id": rng.choice(cts)["id"],
                "date": iso(d),
                "event_type": ev,
                "intent_level": "high",
            })


def seed_p14_launch_ready(campaigns: List[Dict], fake: Faker) -> None:
    """Card 5 — Atlas Assist launch May 8 with ready campaign."""
    campaigns.append({
        "id": "CAM-LAUNCH-001",
        "name": "Atlas Assist Launch Campaign",
        "channel": "email",
        "start_date": iso(date(2026, 5, 1)),
        "end_date": iso(date(2026, 5, 22)),
        "spend": 85000,
        "is_launch_campaign": True,
        "launch_id": "PL-001",
        "status": "ready",
    })


def seed_p02_mm_sql_abm(rng: random.Random, companies: List[Dict], contacts: List[Dict]) -> None:
    """Card 14 — April MM SQLs 147; Jan/Feb/Mar avg 98. ABM acceptance 62% vs non-ABM 41%.

    Model: set contact.lifecycle_stage='sql' and became_sql_date on MM contacts.
    ABM companies are those on Named Accounts / ABM Program / March ABM Add lists.
    Acceptance = sql_accepted flag (would have downstream deal).
    """
    # Build pools
    mm_companies = [c for c in companies if c["segment"] == "mid-market"]
    abm_company_ids = {c["id"] for c in mm_companies if c.get("target_list_name") in {"Named Accounts", "ABM Program", "March ABM Add"}}

    # Also need a wider pool of ABM MM companies, since most MM aren't target accounts.
    # Upgrade ~120 additional MM companies to ABM Program membership so we have room for
    # 70 ABM MM SQLs in April plus Jan/Feb/Mar history.
    non_abm_mm = [c for c in mm_companies if c["id"] not in abm_company_ids]
    rng.shuffle(non_abm_mm)
    for c in non_abm_mm[:120]:
        c["target_list_name"] = "ABM Program"
        abm_company_ids.add(c["id"])

    contacts_by_company = defaultdict(list)
    for ct in contacts:
        contacts_by_company[ct["company_id"]].append(ct)

    # Build per-pool unused-contact queues so every SQL becomes a unique contact.
    def _flatten(pool: set) -> List[Dict]:
        pooled = [ct for co_id in pool for ct in contacts_by_company.get(co_id, [])]
        rng.shuffle(pooled)
        return pooled

    abm_pool = _flatten(abm_company_ids)
    non_abm_pool = _flatten({c["id"] for c in mm_companies if c["id"] not in abm_company_ids})

    def pick_mm_contact(abm: bool) -> Dict:
        pool = abm_pool if abm else non_abm_pool
        if not pool:
            return None
        return pool.pop()

    monthly_counts = {
        (2026, 1): 95,
        (2026, 2): 98,
        (2026, 3): 101,
        (2026, 4): 147,  # through Apr 23
    }

    for (y, m), total in monthly_counts.items():
        month_start = date(y, m, 1)
        if y == 2026 and m == 4:
            month_end = date(2026, 4, 23)
        else:
            next_m = date(y + (1 if m == 12 else 0), (m % 12) + 1, 1)
            month_end = next_m - timedelta(days=1)

        # April split: 70 ABM, 77 non-ABM
        if y == 2026 and m == 4:
            abm_n, non_abm_n = 70, 77
        else:
            # Historic months: roughly 40/60 ABM split
            abm_n = int(total * 0.42)
            non_abm_n = total - abm_n

        def seed_batch(is_abm: bool, count: int, accept_rate: float):
            accept_n = round(count * accept_rate)
            span = (month_end - month_start).days
            for i in range(count):
                ct = pick_mm_contact(is_abm)
                if ct is None:
                    continue
                ct["lifecycle_stage"] = "sql"
                ct["became_sql_date"] = iso(month_start + timedelta(days=rng.randint(0, span)))
                ct["is_abm"] = is_abm
                ct["sql_accepted"] = i < accept_n

        seed_batch(True, abm_n, 0.62)
        seed_batch(False, non_abm_n, 0.41)


def seed_p15_sdr_capacity(sdr_capacity: List[Dict]) -> None:
    """Card 9 — already seeded in gen_sdr_capacity; no-op placeholder."""
    return


# ----------------------------------------------------------------------------
# Revenue Leader pattern seeders (Phase 2.3) — P-RL-01..P-RL-15
# ----------------------------------------------------------------------------
#
# Card → seeder map (Phase 2.1 placeholder cards 1..15):
#   1  Q2 forecast tracking $200K above commit         → seed_p_rl_01_q2_forecast (forecasts.json static)
#   2  MM proposal stage 10 days faster                → seed_p_rl_02_proposal_speed
#   3  Q3 enterprise pipeline coverage 4.1x            → seed_p_rl_03_q3_ent_coverage
#   4  Q2 marketing-sourced share crossed 40%          → seed_p_rl_04_q2_ms_share
#   5  Three enterprise deals through procurement      → seed_p_rl_05_proc_review
#   6  18 MM opps in last 30 days totaling $890K       → seed_p_rl_06_mm_30d
#   7  Q2 enterprise WR 31% vs trailing 22%            → reuses p03 (validator only)
#   8  Q1 vs Q2 enterprise won-deal size delta         → reuses p03 (validator only, p03 pinned Q1)
#   9  Q2 MM sales cycle compressed                    → seed_p_rl_09_mm_cycle
#  10  H2H deals vs Beacon: Q2 5/6, Q1 3/3             → seed_p_rl_10_h2h
#  11  8 expansion opps from health reviews            → seed_p_rl_11_expansion
#  12  Q2 enterprise WR by source (MS 28% / OB 14%)    → reuses p03 (validator only, p03 source-split)
#  13  4 deals close-date moved Q2→Q3 this week        → seed_p_rl_13_close_date_slips
#  14  Q2 bookings pacing 105% of plan                 → seed_p_rl_14_q2_pacing (forecasts.json static)
#  15  Q2 MM renewal ARR / NRR                         → reuses gen_renewals (validator only)


def seed_p_rl_01_q2_forecast() -> None:
    """RL-01 / RL-14 — already seeded statically in gen_forecasts; no-op."""
    return


def seed_p_rl_02_proposal_speed(rng: random.Random, deals: List[Dict]) -> None:
    """RL-02 — Q2 mid-market avg time-in-proposal-stage 12 days, trailing 4Q 22 days.

    Add `time_in_proposal` field to MM closed deals. Q2 MM (close_date in Q2)
    get values around 12 days; trailing 4Q MM get values around 22 days.
    """
    for d in deals:
        if d["segment"] != "mid-market" or not d["is_closed"]:
            continue
        close = date.fromisoformat(d["close_date"])
        if Q2_2026[0] <= close <= Q2_2026[1]:
            d["time_in_proposal"] = max(7, int(rng.gauss(12, 2)))
        elif date(2025, 4, 1) <= close <= date(2026, 3, 31):
            d["time_in_proposal"] = max(15, int(rng.gauss(22, 3)))


def seed_p_rl_03_q3_ent_coverage(rng: random.Random, deals: List[Dict], companies: List[Dict]) -> None:
    """RL-03 — Q3 enterprise pipeline coverage 4.1x of $1.2M plan.

    Seed open enterprise deals with close_date in Q3_2026 totaling ~$4.92M.
    Coverage = (sum open Q3 enterprise pipeline) / (Q3 enterprise plan in
    forecasts.json). Plan is $1.2M; target pipeline $4.92M.
    """
    target = 4_920_000
    n = 22
    amounts = _split_total(rng, target, n)
    q3_start, q3_end = Q3_2026
    span = (q3_end - q3_start).days
    today_to_q3 = (q3_start - TODAY).days
    for amt in amounts:
        co = _pick_company_by_segment(rng, companies, "enterprise")
        close = q3_start + timedelta(days=rng.randint(0, span))
        # create_date between 30-90 days before TODAY (open pipeline being worked)
        create = TODAY - timedelta(days=rng.randint(20, 90))
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": amt,
            "stage": rng.choice(DEAL_STAGES_OPEN),
            "create_date": iso(create),
            "close_date": iso(close),
            "is_closed": False,
            "is_won": False,
            "lead_source": rng.choice(NON_MARKETING_SOURCES + ["content", "email"]),
            "campaign_source_id": None,
            "segment": "enterprise",
            "_pattern": "p_rl_03_q3_ent",
        })


def seed_p_rl_04_q2_ms_share(rng: random.Random, deals: List[Dict], companies: List[Dict]) -> None:
    """RL-04 — Q2 marketing-sourced share of net new pipeline crossed 40%.

    p04 already seeds $1M of paid_social/paid_search Q2 pipeline. Add another
    ~$500K of MS pipeline (content/email/webinar/nurture) so MS share lands
    cleanly above 40%. All open MM/SMB pipeline (won deals would conflict
    with p01 cw and p11 mm_60d).
    """
    target = 500_000
    n = 12
    amounts = _split_total(rng, target, n)
    ms_sources = ["content", "email", "webinar", "nurture"]
    q2_start = Q2_2026[0]
    q2_eff = min(Q2_2026[1], TODAY)
    span = max(0, (q2_eff - q2_start).days)
    for amt in amounts:
        seg = rng.choice(["mid-market", "small-business"])
        co = _pick_company_by_segment(rng, companies, seg)
        create = q2_start + timedelta(days=rng.randint(0, span))
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": amt,
            "stage": rng.choice(DEAL_STAGES_OPEN),
            "create_date": iso(create),
            "close_date": None,
            "is_closed": False,
            "is_won": False,
            "lead_source": rng.choice(ms_sources),
            "campaign_source_id": None,
            "segment": seg,
            "_pattern": "p_rl_04_q2_ms",
        })


def seed_p_rl_05_proc_review(rng: random.Random, deals: List[Dict], companies: List[Dict]) -> None:
    """RL-05 — 3 enterprise deals cleared procurement review this week.

    All three open enterprise deals in stage_proposal/contractsent with
    contract_revisions=true and procurement_signoff=true, close in Q2.
    """
    cw_start, cw_end = CURRENT_WEEK
    cw_span = (cw_end - cw_start).days
    for i in range(3):
        co = _pick_company_by_segment(rng, companies, "enterprise")
        # Close target: 30-60 days from now within Q2
        close = TODAY + timedelta(days=rng.randint(20, 60))
        if close > Q2_2026[1]:
            close = Q2_2026[1]
        create = TODAY - timedelta(days=rng.randint(40, 90))
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": rng.randint(120_000, 240_000),
            "stage": "contractsent",
            "create_date": iso(create),
            "close_date": iso(close),
            "is_closed": False,
            "is_won": False,
            "lead_source": rng.choice(["outbound", "referral", "partner"]),
            "campaign_source_id": None,
            "segment": "enterprise",
            "contract_revisions": True,
            "procurement_signoff": True,
            "procurement_cleared_date": iso(cw_start + timedelta(days=rng.randint(0, cw_span))),
            "_pattern": "p_rl_05_proc",
        })


def seed_p_rl_06_mm_30d(rng: random.Random, deals: List[Dict], companies: List[Dict]) -> None:
    """RL-06 — 18 mid-market opportunities created Mar 25 - Apr 24 totaling $890K.

    Top up to 18 NEW MM opps in last 30d, total ~$890K, avg ~$49K. Existing
    seeders may already create some MM opps in this window; this seeder adds
    enough new ones to hit the count and total. Open opps only — closed-won
    MM in last 30d would conflict with p11.
    """
    last30_start, last30_end = LAST_30_DAYS
    span = (last30_end - last30_start).days
    target_total = 890_000
    target_count = 18
    # All 18 are this seeder's; previous seeders' MM opps in this window
    # remain in the dataset but don't inflate this count (validator looks at
    # MM opps tagged with this seeder's _pattern OR uses dataset-wide cuts).
    amounts = _split_total(rng, target_total, target_count)
    for amt in amounts:
        co = _pick_company_by_segment(rng, companies, "mid-market")
        create = last30_start + timedelta(days=rng.randint(0, span))
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": amt,
            "stage": rng.choice(DEAL_STAGES_OPEN),
            "create_date": iso(create),
            "close_date": None,
            "is_closed": False,
            "is_won": False,
            "lead_source": rng.choice(["outbound", "referral", "content", "email"]),
            "campaign_source_id": None,
            "segment": "mid-market",
            "_pattern": "p_rl_06_mm_30d",
        })


def seed_p_rl_09_mm_cycle(rng: random.Random, deals: List[Dict], companies: List[Dict]) -> None:
    """RL-09 — Q2 MM avg sales cycle 67d, Q1 MM avg sales cycle 85d.

    Sales cycle = create→close days for closed MM deals. p01/p11 seeded short
    Q2 MM cycles (38-50d). To pull the Q2 MM aggregate average to ~67d, add
    20 Q2 MM closed-LOST deals at avg ~80d. For Q1, add 18 MM closed deals
    (mix of won/lost) at avg ~85d.
    """
    # Q2 MM closed-lost (avg 80d) — pull Q2 MM aggregate to ~67d.
    q2_start = Q2_2026[0]
    q2_eff = min(Q2_2026[1], TODAY)
    for _ in range(20):
        co = _pick_company_by_segment(rng, companies, "mid-market")
        close = q2_start + timedelta(days=rng.randint(0, (q2_eff - q2_start).days))
        dtc = max(70, int(rng.gauss(82, 5)))
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": rng.randint(15_000, 80_000),
            "stage": DEAL_STAGE_LOST,
            "create_date": iso(close - timedelta(days=dtc)),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": False,
            "lead_source": rng.choice(NON_MARKETING_SOURCES + ["content", "email"]),
            "campaign_source_id": None,
            "segment": "mid-market",
            "_pattern": "p_rl_09_q2_mm_lost",
        })

    # Q1 MM closed deals (avg ~100d) — small mix of won and lost. Pushed up
    # vs. the headline 85d target so filler MM Q1 closeds (avg ~55d) don't
    # dilute the aggregate below the validator floor.
    q1_start, q1_end = Q1_2026
    for i in range(28):
        co = _pick_company_by_segment(rng, companies, "mid-market")
        close = q1_start + timedelta(days=rng.randint(0, (q1_end - q1_start).days))
        dtc = max(85, int(rng.gauss(100, 5)))
        is_won = i < 7  # ~39% WR
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": rng.randint(15_000, 85_000),
            "stage": DEAL_STAGE_WON if is_won else DEAL_STAGE_LOST,
            "create_date": iso(close - timedelta(days=dtc)),
            "close_date": iso(close),
            "is_closed": True,
            "is_won": is_won,
            "lead_source": rng.choice(NON_MARKETING_SOURCES + ["content", "email"]),
            "campaign_source_id": None,
            "segment": "mid-market",
            "_pattern": "p_rl_09_q1_mm",
        })


def seed_p_rl_10_h2h(rng: random.Random, deals: List[Dict]) -> None:
    """RL-10 — Q2 h2h vs Beacon: 5W/1L; Q1 h2h vs Beacon: 3W/3L.

    Tag existing p03 enterprise deals with competitor_id and head_to_head=True.
    Q2: take 5 of the 8 Q2 enterprise wins + 1 of the Q2 enterprise losses.
    Q1: take 3 of the Q1_2026 trailing wins + 3 trailing Q1_2026 losses.
    """
    beacon = "Beacon Systems"

    # Q2 enterprise from p03 (any q2_<stratum> _pattern)
    q2_ent_won = [d for d in deals if d.get("_pattern", "").startswith("p03_q2_") and d["is_won"]]
    q2_ent_lost = [d for d in deals if d.get("_pattern", "").startswith("p03_q2_") and not d["is_won"]]

    # Stable-sort by id for determinism (rng.sample re-orders unstably otherwise).
    q2_ent_won.sort(key=lambda d: d["id"])
    q2_ent_lost.sort(key=lambda d: d["id"])
    for d in q2_ent_won[:5]:
        d["head_to_head"] = True
        d["competitor_id"] = beacon
        d["_h2h_quarter"] = "Q2_2026"
    for d in q2_ent_lost[:1]:
        d["head_to_head"] = True
        d["competitor_id"] = beacon
        d["_h2h_quarter"] = "Q2_2026"

    # Q1_2026 trailing wins/losses
    q1_2026_won = [d for d in deals if d.get("_pattern") == "p03_trailing_q1won" and d["is_won"]]
    q1_2026_lost = [d for d in deals
                    if d.get("_pattern") == "p03_trailing_loss"
                    and Q1_2026[0] <= date.fromisoformat(d["close_date"]) <= Q1_2026[1]]
    q1_2026_won.sort(key=lambda d: d["id"])
    q1_2026_lost.sort(key=lambda d: d["id"])
    for d in q1_2026_won[:3]:
        d["head_to_head"] = True
        d["competitor_id"] = beacon
        d["_h2h_quarter"] = "Q1_2026"
    for d in q1_2026_lost[:3]:
        d["head_to_head"] = True
        d["competitor_id"] = beacon
        d["_h2h_quarter"] = "Q1_2026"


def seed_p_rl_11_expansion(rng: random.Random, expansion_opportunities: List[Dict], companies: List[Dict]) -> None:
    """RL-11 — 8 expansion opportunities from customer health reviews, last 30 days, total $340K, avg $42K."""
    customers = [c for c in companies if c["is_customer"]]
    last30_start, last30_end = LAST_30_DAYS
    span = (last30_end - last30_start).days
    target_total = 340_000
    n = 8
    amounts = _amounts_at_mean(rng, n, 42_500, 8_000)
    # Adjust to hit exact total (drift from rounding).
    diff = target_total - sum(amounts)
    amounts[0] += diff
    for i, amt in enumerate(amounts):
        co = rng.choice(customers)
        d = last30_start + timedelta(days=rng.randint(0, span))
        expansion_opportunities.append({
            "id": f"EX-{i+1:04d}",
            "company_id": co["id"],
            "create_date": iso(d),
            "amount": amt,
            "source": "customer_health_review",
            "stage": rng.choice(["qualifiedtobuy", "presentationscheduled"]),
        })


def seed_p_rl_13_close_date_slips(rng: random.Random, deals: List[Dict], companies: List[Dict]) -> None:
    """RL-13 — 4 deals stage-changed (close_date moved from Q2 to Q3) week of Apr 20-26, total $180K.

    Open MM/SMB deals (avoid p03 enterprise + p11 MM cw conflicts). Each
    carries a stage_change_history entry showing close_date moved Q2→Q3.
    """
    cw_start, cw_end = CURRENT_WEEK
    cw_span = (cw_end - cw_start).days
    target_total = 180_000
    n = 4
    amounts = _split_total(rng, target_total, n)
    for amt in amounts:
        seg = rng.choice(["mid-market", "small-business"])
        co = _pick_company_by_segment(rng, companies, seg)
        old_close = Q2_2026[0] + timedelta(days=rng.randint(15, 65))  # Q2
        new_close = Q3_2026[0] + timedelta(days=rng.randint(0, 60))    # Q3
        change_date = cw_start + timedelta(days=rng.randint(0, cw_span))
        create = TODAY - timedelta(days=rng.randint(35, 90))
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": amt,
            "stage": rng.choice(DEAL_STAGES_OPEN),
            "create_date": iso(create),
            "close_date": iso(new_close),
            "is_closed": False,
            "is_won": False,
            "lead_source": rng.choice(NON_MARKETING_SOURCES + ["content", "email"]),
            "campaign_source_id": None,
            "segment": seg,
            "stage_change_history": [
                {
                    "change_date": iso(change_date),
                    "field": "close_date",
                    "from_value": iso(old_close),
                    "to_value": iso(new_close),
                    "from_quarter": "Q2_2026",
                    "to_quarter": "Q3_2026",
                }
            ],
            "_pattern": "p_rl_13_slip",
        })


def seed_p_rl_14_q2_pacing() -> None:
    """RL-14 — Q2 bookings pacing — already in gen_forecasts as static row."""
    return


def seed_p_rl_15_renewals() -> None:
    """RL-15 — Q2 MM renewals — already in gen_renewals as targeted distribution."""
    return


def apply_deal_field_defaults(deals: List[Dict]) -> None:
    """Backfill new Phase 2.3 deal fields with safe defaults across all deals.

    Earlier seeders (p01/p04/p06/p11/filler/etc.) wrote deals without the
    Revenue Leader fields. Apply defaults so downstream validators and the
    relevance engine never have to do `.get("competitor_id", None)` style
    fallbacks. A handful of deals (p03 h2h-tagged, p_rl_05 procurement, p_rl_13
    slipped) already carry real values — leave those alone.
    """
    for d in deals:
        d.setdefault("competitor_id", None)
        d.setdefault("head_to_head", False)
        d.setdefault("contract_revisions", False)
        d.setdefault("procurement_signoff", False)
        d.setdefault("time_in_proposal", None)
        d.setdefault("stage_change_history", [])


# ----------------------------------------------------------------------------
# Top-level build
# ----------------------------------------------------------------------------

def build_dataset(seed: int) -> Dict[str, List[Dict]]:
    rng = random.Random(seed)
    fake = Faker()
    Faker.seed(seed)
    fake.seed_instance(seed)

    competitors = gen_competitors()
    companies = gen_companies(rng, fake)
    contacts = gen_contacts(rng, fake, companies)
    campaigns = gen_campaigns(rng, fake)

    # Seed p14 before campaign_performance so the launch campaign is included
    seed_p14_launch_ready(campaigns, fake)

    campaign_performance = gen_campaign_performance(rng, campaigns)
    budget = gen_budget()
    actual_spend = gen_actual_spend(rng, budget)
    engagement_events = gen_engagement_events(rng, companies, contacts)
    branded_search = gen_branded_search(rng)
    web_analytics = gen_web_analytics(rng)
    mentions = gen_mentions(rng, fake, competitors)
    analyst_mentions = gen_analyst_mentions(rng, fake)
    customer_reference_optins = gen_customer_reference_optins(rng, companies)
    product_launches = gen_product_launches()
    sdr_capacity = gen_sdr_capacity(rng)
    forecasts = gen_forecasts()
    renewals = gen_renewals(rng, companies)
    expansion_opportunities = gen_expansion_opportunities()

    # Deals start empty — all deals come from pattern seeders + background filler.
    deals: List[Dict] = []

    # Marketing pattern seeders
    seed_p01_marketing_velocity(rng, deals, companies)
    seed_p11_mm_wins_concentration(rng, deals, companies)
    seed_p03_enterprise_winrate(rng, deals, companies)
    seed_p04_channel_flip(rng, deals, campaigns, companies)
    seed_p06_event_velocity(rng, deals, campaigns, companies)
    seed_p05_digital_ads_reallocation(budget, actual_spend)
    seed_p07_branded_search_streak(rng, branded_search)
    seed_p08_share_of_voice(rng, fake, mentions)
    seed_p09_direct_vs_organic(rng, web_analytics)
    seed_p10_analyst_spike(rng, fake, analyst_mentions)
    seed_p13_target_account_intent(rng, companies, contacts, engagement_events)
    seed_p02_mm_sql_abm(rng, companies, contacts)
    # p12, p14, p15 already seeded above

    # Revenue Leader pattern seeders. Order matters:
    # - p_rl_03/05/06/13 add new deals → run before filler so the filler loop
    #   sees them and stops at 600.
    # - p_rl_10 mutates existing p03 deals → must run AFTER p03.
    # - p_rl_09 adds Q2 MM lost + Q1 MM closed deals; p_rl_02 sets
    #   time_in_proposal on MM closed deals → run p_rl_02 after p01/p11/p_rl_09
    #   so it sees the full MM closed pool.
    seed_p_rl_03_q3_ent_coverage(rng, deals, companies)
    seed_p_rl_04_q2_ms_share(rng, deals, companies)
    seed_p_rl_05_proc_review(rng, deals, companies)
    seed_p_rl_06_mm_30d(rng, deals, companies)
    seed_p_rl_09_mm_cycle(rng, deals, companies)
    seed_p_rl_10_h2h(rng, deals)
    seed_p_rl_11_expansion(rng, expansion_opportunities, companies)
    seed_p_rl_13_close_date_slips(rng, deals, companies)
    seed_p_rl_02_proposal_speed(rng, deals)

    # Background filler deals to reach ~600 total if below.
    # Invariants protected by filler:
    #   (1) closed enterprise deals are reserved for p03
    #   (2) closed deals use non-marketing sources only so they don't distort p01
    #       (marketing velocity) or p06 (event velocity) DTC math
    #   (3) paid_social / paid_search lead sources are reserved for p04
    #   (4) 'events' lead source is reserved for p06
    #   (5) MM closed-wins in last 60d are reserved for p11: filler MM wins in
    #       that window would dilute card 11's fintech concentration ratio
    while len(deals) < 600:
        co = rng.choice(companies)
        create = WINDOW_START + timedelta(days=rng.randint(0, (TODAY - WINDOW_START).days))
        dtc = rng.randint(20, 90)
        is_closed = rng.random() < 0.55
        if co["segment"] == "enterprise":
            is_closed = False
        is_won = is_closed and rng.random() < 0.30
        close = create + timedelta(days=dtc) if is_closed else None
        if close and close > TODAY:
            close = None
            is_closed = False
            is_won = False
        # p11 invariant: no filler MM closed-wins in last 60d
        if (is_closed and is_won and co["segment"] == "mid-market"
                and close and LAST_60_DAYS[0] <= close <= LAST_60_DAYS[1]):
            is_closed = False
            is_won = False
            close = None
        if is_closed:
            lead_source = rng.choice(NON_MARKETING_SOURCES)
        else:
            lead_source = rng.choice(GENERAL_MARKETING_SOURCES + NON_MARKETING_SOURCES)
        deals.append({
            "id": _new_deal_id(deals),
            "company_id": co["id"],
            "amount": rng.randint(6000, 120000),
            "stage": (DEAL_STAGE_WON if is_won else DEAL_STAGE_LOST) if is_closed else rng.choice(DEAL_STAGES_OPEN),
            "create_date": iso(create),
            "close_date": iso(close) if close else None,
            "is_closed": is_closed,
            "is_won": bool(is_won),
            "lead_source": lead_source,
            "campaign_source_id": None,
            "segment": co["segment"],
            "_pattern": "filler",
        })

    # Backfill Phase 2.3 deal fields with safe defaults across all deals
    apply_deal_field_defaults(deals)

    # Strip internal _pattern tags from final output
    for d in deals:
        d.pop("_pattern", None)

    return {
        "companies": companies,
        "contacts": contacts,
        "deals": deals,
        "campaigns": campaigns,
        "campaign_performance": campaign_performance,
        "budget": budget,
        "actual_spend": actual_spend,
        "engagement_events": engagement_events,
        "branded_search": branded_search,
        "web_analytics": web_analytics,
        "mentions": mentions,
        "competitors": competitors,
        "analyst_mentions": analyst_mentions,
        "customer_reference_optins": customer_reference_optins,
        "product_launches": product_launches,
        "sdr_capacity": sdr_capacity,
        "forecasts": forecasts,
        "renewals": renewals,
        "expansion_opportunities": expansion_opportunities,
    }


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------

@dataclass
class CheckResult:
    card_idx: int
    card_title: str
    pattern: str
    passed: bool
    detail: str


def _in_range(value: float, lo: float, hi: float) -> bool:
    return lo <= value <= hi


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def validate_revenue(ds: Dict[str, List[Dict]]) -> List[CheckResult]:
    """15 Revenue Leader pattern checks (P-RL-01..P-RL-15)."""
    results: List[CheckResult] = []
    deals = ds["deals"]
    forecasts = ds["forecasts"]
    renewals = ds["renewals"]
    expansion = ds["expansion_opportunities"]

    def fc(quarter: str) -> Dict:
        return next((f for f in forecasts if f["quarter"] == quarter), {})

    def cdate(d: Dict, key: str = "close_date"):
        return date.fromisoformat(d[key]) if d.get(key) else None

    # P-RL-01 — Q2 commit vs weighted pipeline (forecast reliability)
    q2 = fc("Q2_2026")
    commit = q2.get("commit", 0)
    weighted = q2.get("weighted_pipeline_80pct", 0)
    gap1 = weighted - commit
    passed = (
        _in_range(commit, 1_350_000, 1_450_000)
        and _in_range(weighted, 1_550_000, 1_650_000)
        and _in_range(gap1, 150_000, 250_000)
    )
    results.append(CheckResult(0, "Q2 commit vs weighted pipeline", "p_rl_01_q2_forecast", passed,
                               f"commit=${commit:,}; weighted80%=${weighted:,}; gap=${gap1:,}"))

    # P-RL-02 — MM time-in-proposal: Q2 ≈ 12d vs trailing 4Q ≈ 22d
    mm_q2 = [d["time_in_proposal"] for d in deals
             if d["segment"] == "mid-market" and d["is_closed"] and d.get("time_in_proposal") is not None
             and Q2_2026[0] <= cdate(d) <= Q2_2026[1]]
    mm_tr = [d["time_in_proposal"] for d in deals
             if d["segment"] == "mid-market" and d["is_closed"] and d.get("time_in_proposal") is not None
             and date(2025, 4, 1) <= cdate(d) <= date(2026, 3, 31)]
    q2_mean = _mean(mm_q2)
    tr_mean = _mean(mm_tr)
    passed = (
        len(mm_q2) >= 5 and len(mm_tr) >= 18
        and _in_range(q2_mean, 10, 14)
        and _in_range(tr_mean, 18, 26)
        and tr_mean - q2_mean >= 7
    )
    results.append(CheckResult(1, "MM proposal-stage speed Q2 vs trailing", "p_rl_02_proposal_speed", passed,
                               f"Q2 MM n={len(mm_q2)} mean={q2_mean:.1f}; trailing n={len(mm_tr)} mean={tr_mean:.1f}"))

    # P-RL-03 — Q3 enterprise pipeline coverage
    q3_open_ent = [d for d in deals if d["segment"] == "enterprise" and not d["is_closed"]
                   and d["close_date"] and Q3_2026[0] <= cdate(d) <= Q3_2026[1]]
    q3_pipeline = sum(d["amount"] for d in q3_open_ent)
    q3_plan = fc("Q3_2026").get("enterprise_plan", 0)
    coverage = q3_pipeline / q3_plan if q3_plan else 0
    passed = (
        len(q3_open_ent) >= 18
        and _in_range(q3_pipeline, 4_500_000, 5_300_000)
        and q3_plan == 1_200_000
        and _in_range(coverage, 3.7, 4.5)
    )
    results.append(CheckResult(2, "Q3 enterprise pipeline coverage", "p_rl_03_q3_ent_coverage", passed,
                               f"Q3 ent open n={len(q3_open_ent)} pipeline=${q3_pipeline:,}; plan=${q3_plan:,}; coverage={coverage:.2f}x"))

    # P-RL-04 — Q2 marketing-sourced share of net new pipeline
    q2_open = [d for d in deals if not d["is_closed"]
               and Q2_2026[0] <= date.fromisoformat(d["create_date"]) <= Q2_2026[1]]
    q2_total = sum(d["amount"] for d in q2_open)
    ms_set = set(MARKETING_SOURCES)
    q2_ms = sum(d["amount"] for d in q2_open if d["lead_source"] in ms_set)
    ms_share = q2_ms / q2_total if q2_total else 0
    passed = q2_total > 0 and ms_share >= 0.40
    results.append(CheckResult(3, "Q2 MS share of net new pipeline", "p_rl_04_q2_ms_share", passed,
                               f"Q2 open total=${q2_total:,}; MS=${q2_ms:,}; share={ms_share:.2%}"))

    # P-RL-05 — 3 enterprise deals cleared procurement this week
    cw_start, cw_end = CURRENT_WEEK
    proc_cleared = [d for d in deals if d["segment"] == "enterprise"
                    and d.get("procurement_signoff") and d.get("contract_revisions")
                    and not d["is_closed"]]
    passed = len(proc_cleared) == 3
    results.append(CheckResult(4, "Enterprise deals through procurement this week", "p_rl_05_proc_review", passed,
                               f"procurement-cleared open ent deals={len(proc_cleared)}"))

    # P-RL-06 — 18 MM opps in last 30d totaling ~$890K
    last30_start, last30_end = LAST_30_DAYS
    mm_30d = [d for d in deals if d["segment"] == "mid-market"
              and not d["is_closed"]
              and last30_start <= date.fromisoformat(d["create_date"]) <= last30_end]
    mm_30d_total = sum(d["amount"] for d in mm_30d)
    avg_acv = mm_30d_total / len(mm_30d) if mm_30d else 0
    passed = (
        len(mm_30d) >= 18
        and mm_30d_total >= 850_000
        and _in_range(avg_acv, 30_000, 80_000)
    )
    results.append(CheckResult(5, "MM new opps last 30 days", "p_rl_06_mm_30d", passed,
                               f"MM open opps last 30d n={len(mm_30d)} total=${mm_30d_total:,} avg=${avg_acv:,.0f}"))

    # P-RL-07 — Q2 enterprise WR > trailing enterprise WR (lift)
    ent_q2 = [d for d in deals if d["segment"] == "enterprise" and d["is_closed"]
              and Q2_2026[0] <= cdate(d) <= Q2_2026[1]]
    ent_q2_wins = [d for d in ent_q2 if d["is_won"]]
    q2_wr = len(ent_q2_wins) / len(ent_q2) if ent_q2 else 0
    ent_trailing = [d for d in deals if d["segment"] == "enterprise" and d["is_closed"]
                    and date(2025, 4, 1) <= cdate(d) <= date(2026, 3, 31)]
    ent_tr_wins = [d for d in ent_trailing if d["is_won"]]
    tr_wr = len(ent_tr_wins) / len(ent_trailing) if ent_trailing else 0
    passed = q2_wr > tr_wr and _in_range(q2_wr, 0.27, 0.36) and _in_range(tr_wr, 0.18, 0.26)
    results.append(CheckResult(6, "Enterprise Q2 WR lift vs trailing", "p_rl_07_q2_wr_lift", passed,
                               f"Q2 ent WR={q2_wr:.2%} (n={len(ent_q2)}); trailing WR={tr_wr:.2%} (n={len(ent_trailing)})"))

    # P-RL-08 — Q1_2026 enterprise wins avg ACV ≈ $145K
    q1_ent_wins = [d for d in deals if d["segment"] == "enterprise" and d["is_won"]
                   and Q1_2026[0] <= cdate(d) <= Q1_2026[1]]
    q1_avg = _mean(d["amount"] for d in q1_ent_wins)
    passed = len(q1_ent_wins) >= 3 and _in_range(q1_avg, 135_000, 160_000)
    results.append(CheckResult(7, "Q1 enterprise wins avg ACV anchor", "p_rl_08_q1_ent_avg_acv", passed,
                               f"Q1 ent wins n={len(q1_ent_wins)} avg=${q1_avg:,.0f}"))

    # P-RL-09 — MM cycle Q2 vs Q1
    def cycle(d: Dict) -> int:
        return (cdate(d) - date.fromisoformat(d["create_date"])).days
    mm_q2_closed = [d for d in deals if d["segment"] == "mid-market" and d["is_closed"]
                    and Q2_2026[0] <= cdate(d) <= Q2_2026[1]]
    mm_q1_closed = [d for d in deals if d["segment"] == "mid-market" and d["is_closed"]
                    and Q1_2026[0] <= cdate(d) <= Q1_2026[1]]
    q2_cycle = _mean(cycle(d) for d in mm_q2_closed)
    q1_cycle = _mean(cycle(d) for d in mm_q1_closed)
    passed = (
        len(mm_q2_closed) >= 20 and len(mm_q1_closed) >= 15
        and _in_range(q2_cycle, 55, 75)
        and _in_range(q1_cycle, 70, 95)
        and q1_cycle - q2_cycle >= 5
    )
    results.append(CheckResult(8, "MM cycle Q2 vs Q1", "p_rl_09_mm_cycle", passed,
                               f"Q2 MM closed n={len(mm_q2_closed)} cycle={q2_cycle:.1f}; Q1 MM closed n={len(mm_q1_closed)} cycle={q1_cycle:.1f}"))

    # P-RL-10 — Q2 h2h vs Beacon: 5W/1L; Q1 h2h vs Beacon: 3W/3L
    h2h = [d for d in deals if d.get("head_to_head") and d.get("competitor_id") == "Beacon Systems"]
    q2_h2h = [d for d in h2h if d["is_closed"] and Q2_2026[0] <= cdate(d) <= Q2_2026[1]]
    q1_h2h = [d for d in h2h if d["is_closed"] and Q1_2026[0] <= cdate(d) <= Q1_2026[1]]
    q2_w = sum(1 for d in q2_h2h if d["is_won"])
    q2_l = sum(1 for d in q2_h2h if not d["is_won"])
    q1_w = sum(1 for d in q1_h2h if d["is_won"])
    q1_l = sum(1 for d in q1_h2h if not d["is_won"])
    passed = q2_w == 5 and q2_l == 1 and q1_w == 3 and q1_l == 3
    results.append(CheckResult(9, "H2H vs Beacon Q2 vs Q1", "p_rl_10_h2h", passed,
                               f"Q2 {q2_w}W/{q2_l}L; Q1 {q1_w}W/{q1_l}L"))

    # P-RL-11 — 8 expansion opps from customer_health_review, last 30d, total ~$340K
    chr_30d = [e for e in expansion if e["source"] == "customer_health_review"
               and last30_start <= date.fromisoformat(e["create_date"]) <= last30_end]
    chr_total = sum(e["amount"] for e in chr_30d)
    chr_avg = chr_total / len(chr_30d) if chr_30d else 0
    passed = len(chr_30d) == 8 and _in_range(chr_total, 320_000, 360_000) and _in_range(chr_avg, 38_000, 48_000)
    results.append(CheckResult(10, "Health-review expansion opps last 30 days", "p_rl_11_expansion", passed,
                               f"n={len(chr_30d)} total=${chr_total:,} avg=${chr_avg:,.0f}"))

    # P-RL-12 — Q2 enterprise WR by lead-source class
    def wr_by_source_class(deals_in, sources):
        n = sum(1 for d in deals_in if d["lead_source"] in sources)
        w = sum(1 for d in deals_in if d["lead_source"] in sources and d["is_won"])
        return (w / n) if n else 0, n, w
    ms_set12 = set(MARKETING_SOURCES) | {"content", "email", "webinar", "nurture"}
    ob_set = {"outbound"}
    ms_wr, ms_n, ms_w = wr_by_source_class(ent_q2, ms_set12)
    ob_wr, ob_n, ob_w = wr_by_source_class(ent_q2, ob_set)
    passed = (
        ms_n >= 10 and ob_n >= 5
        and _in_range(ms_wr, 0.22, 0.40)
        and _in_range(ob_wr, 0.05, 0.22)
        and ms_wr > ob_wr
    )
    results.append(CheckResult(11, "Q2 ent WR by source class", "p_rl_12_q2_wr_by_source", passed,
                               f"MS n={ms_n} w={ms_w} WR={ms_wr:.2%}; OB n={ob_n} w={ob_w} WR={ob_wr:.2%}"))

    # P-RL-13 — 4 deals close-date moved Q2→Q3 this week
    slips = [d for d in deals if d.get("stage_change_history")
             and any(ev.get("from_quarter") == "Q2_2026" and ev.get("to_quarter") == "Q3_2026"
                     and cw_start <= date.fromisoformat(ev["change_date"]) <= cw_end
                     for ev in d["stage_change_history"])]
    slip_total = sum(d["amount"] for d in slips)
    passed = len(slips) == 4 and _in_range(slip_total, 160_000, 200_000)
    results.append(CheckResult(12, "Close-date slips Q2→Q3 this week", "p_rl_13_close_date_slips", passed,
                               f"n={len(slips)} total=${slip_total:,}"))

    # P-RL-14 — Q2 bookings pacing 105% of plan
    pacing_target = q2.get("plan_pacing_target_through_apr24", 0)
    pacing_actual = q2.get("bookings_actual_through_apr24", 0)
    pacing_pct = pacing_actual / pacing_target if pacing_target else 0
    passed = (
        pacing_target == 840_000
        and pacing_actual == 880_000
        and _in_range(pacing_pct, 1.03, 1.07)
    )
    results.append(CheckResult(13, "Q2 bookings pacing", "p_rl_14_q2_pacing", passed,
                               f"target=${pacing_target:,} actual=${pacing_actual:,} pct={pacing_pct:.1%}"))

    # P-RL-15 — Q2 MM renewals: total renewed ARR ≈ $620K, NRR 1.12
    q2_mm_ren = [r for r in renewals if r["quarter"] == "Q2_2026" and r["segment"] == "mid-market"]
    q2_mm_arr = sum(r["renewed_arr"] for r in q2_mm_ren)
    nrrs = {r["nrr"] for r in q2_mm_ren}
    passed = (
        len(q2_mm_ren) >= 4
        and _in_range(q2_mm_arr, 600_000, 640_000)
        and nrrs == {1.12}
    )
    results.append(CheckResult(14, "Q2 MM renewals + NRR", "p_rl_15_renewals", passed,
                               f"Q2 MM renewals n={len(q2_mm_ren)} ARR=${q2_mm_arr:,} NRR={nrrs}"))

    return results


def validate(ds: Dict[str, List[Dict]]) -> List[CheckResult]:
    results: List[CheckResult] = []
    deals = ds["deals"]
    companies = ds["companies"]
    by_co = {c["id"]: c for c in companies}

    def dtc(d: Dict) -> int:
        return (date.fromisoformat(d["close_date"]) - date.fromisoformat(d["create_date"])).days

    # P01 — marketing velocity current week
    cw_start, cw_end = CURRENT_WEEK
    cw_ms_wins = [d for d in deals if d["is_won"] and d["lead_source"] in MARKETING_SOURCES
                  and cw_start <= date.fromisoformat(d["close_date"]) <= cw_end]
    prior_start, prior_end = PRIOR_11_WEEKS
    prior_ms_wins = [d for d in deals if d["is_won"] and d["lead_source"] in MARKETING_SOURCES
                     and prior_start <= date.fromisoformat(d["close_date"]) <= prior_end]
    cw_mean = _mean(dtc(d) for d in cw_ms_wins)
    prior_mean = _mean(dtc(d) for d in prior_ms_wins)
    mm_cw = sum(1 for d in cw_ms_wins if d["segment"] == "mid-market")
    gap = prior_mean - cw_mean
    passed = (
        len(cw_ms_wins) >= 8 and mm_cw >= 6
        and _in_range(cw_mean, 34, 42)
        and _in_range(prior_mean, 48, 56)
        and _in_range(gap, 10, 18)
    )
    results.append(CheckResult(5, "Marketing deals closing faster this week", "p01_marketing_velocity", passed,
                               f"cw n={len(cw_ms_wins)} (mm={mm_cw}) mean={cw_mean:.1f}; prior n={len(prior_ms_wins)} mean={prior_mean:.1f}; gap={gap:.1f}"))

    # P02 — April MM SQLs + ABM acceptance
    mm_company_ids = {c["id"] for c in companies if c["segment"] == "mid-market"}
    contacts = ds["contacts"]
    mm_sqls = [ct for ct in contacts if ct.get("became_sql_date") and ct["company_id"] in mm_company_ids]
    by_month = defaultdict(list)
    for ct in mm_sqls:
        dt = date.fromisoformat(ct["became_sql_date"])
        by_month[(dt.year, dt.month)].append(ct)
    apr_mm = by_month.get((2026, 4), [])
    jfm_monthly_avg = _mean([len(by_month.get((2026, m), [])) for m in (1, 2, 3)])
    abm_apr = [c for c in apr_mm if c.get("is_abm")]
    non_abm_apr = [c for c in apr_mm if not c.get("is_abm")]
    abm_rate = (sum(1 for c in abm_apr if c.get("sql_accepted")) / len(abm_apr)) if abm_apr else 0
    non_abm_rate = (sum(1 for c in non_abm_apr if c.get("sql_accepted")) / len(non_abm_apr)) if non_abm_apr else 0
    passed = (
        _in_range(len(apr_mm), 137, 157)
        and _in_range(jfm_monthly_avg, 88, 108)
        and _in_range(abm_rate, 0.58, 0.66)
        and _in_range(non_abm_rate, 0.37, 0.45)
    )
    results.append(CheckResult(13, "April MM SQL surge + ABM acceptance", "p02_mm_sql_abm", passed,
                               f"apr MM SQL={len(apr_mm)}; J/F/M avg={jfm_monthly_avg:.0f}; ABM accept={abm_rate:.2f}; non-ABM={non_abm_rate:.2f}"))

    # P03 — enterprise win rate
    ent_q2 = [d for d in deals if d["segment"] == "enterprise" and d["is_closed"]
              and Q2_2026[0] <= date.fromisoformat(d["close_date"]) <= Q2_2026[1]]
    ent_q2_wins = [d for d in ent_q2 if d["is_won"]]
    q2_wr = len(ent_q2_wins) / len(ent_q2) if ent_q2 else 0
    q2_avg_won = _mean(d["amount"] for d in ent_q2_wins)
    trailing_start = date(2025, 4, 1)
    trailing_end = date(2026, 3, 31)
    ent_trailing = [d for d in deals if d["segment"] == "enterprise" and d["is_closed"]
                    and trailing_start <= date.fromisoformat(d["close_date"]) <= trailing_end]
    ent_tr_wins = [d for d in ent_trailing if d["is_won"]]
    tr_wr = len(ent_tr_wins) / len(ent_trailing) if ent_trailing else 0
    tr_avg_won = _mean(d["amount"] for d in ent_tr_wins)
    passed = (
        _in_range(q2_wr, 0.27, 0.36) and _in_range(tr_wr, 0.18, 0.26)
        and _in_range(q2_avg_won, 170_000, 205_000) and _in_range(tr_avg_won, 130_000, 155_000)
    )
    results.append(CheckResult(11, "Enterprise win rate Q2 lift", "p03_enterprise_winrate", passed,
                               f"Q2 WR={q2_wr:.2%} (n={len(ent_q2)}, won={len(ent_q2_wins)}, avg={q2_avg_won:.0f}); trailing WR={tr_wr:.2%} (n={len(ent_trailing)}, avg={tr_avg_won:.0f})"))

    # P04 — paid social vs search (pipeline = sum of deal.amount for deals created in quarter)
    def pipeline(source: str, quarter: Tuple[date, date]) -> int:
        return sum(d["amount"] for d in deals
                   if d["lead_source"] == source
                   and quarter[0] <= date.fromisoformat(d["create_date"]) <= quarter[1])
    q2_social = pipeline("paid_social", Q2_2026)
    q2_search = pipeline("paid_search", Q2_2026)
    q1_social = pipeline("paid_social", Q1_2026)
    q1_search = pipeline("paid_search", Q1_2026)
    passed = (
        _in_range(q2_social, 560_000, 680_000)
        and _in_range(q2_search, 340_000, 420_000)
        and _in_range(q1_search, 660_000, 780_000)
        and _in_range(q1_social, 370_000, 450_000)
        and q2_social > q2_search and q1_search > q1_social
    )
    results.append(CheckResult(7, "Paid social > paid search pipeline (Q-flip)", "p04_channel_flip", passed,
                               f"Q2 social=${q2_social:,} / search=${q2_search:,}; Q1 search=${q1_search:,} / social=${q1_social:,}"))

    # P05 — digital ads under plan; events reallocation present
    budget = ds["budget"]
    actual_spend = ds["actual_spend"]
    q2_ads_plan = next((b["planned_amount"] for b in budget if b["category"] == "digital_ads" and b["quarter"] == "Q2_2026"), 0)
    q2_ads_actual = sum(r["amount"] for r in actual_spend
                        if r["category"] == "digital_ads"
                        and Q2_2026[0] <= date.fromisoformat(r["date"]) <= date(2026, 4, 23))
    gap5 = q2_ads_plan - q2_ads_actual
    realloc = [b for b in budget if b["quarter"] == "Q2_2026" and b["category"] in ("events_saas_connect", "events_signal_summit")]
    realloc_total = sum(b["planned_amount"] for b in realloc)
    passed = (
        q2_ads_plan == 340_000
        and _in_range(q2_ads_actual, 245_000, 265_000)
        and _in_range(gap5, 75_000, 95_000)
        and len(realloc) == 2 and _in_range(realloc_total, 80_000, 90_000)
    )
    results.append(CheckResult(2, "Digital ads under plan; events reallocation", "p05_digital_ads_reallocation", passed,
                               f"plan=${q2_ads_plan:,}, actual thru Apr 23=${q2_ads_actual:,.0f}, gap=${gap5:,.0f}, realloc=${realloc_total:,}"))

    # P06 — event velocity lift
    q1_event = [d for d in deals if d["lead_source"] == "events" and d["is_won"]
                and Q1_2026[0] <= date.fromisoformat(d["create_date"]) <= Q1_2026[1]]
    q4_event = [d for d in deals if d["lead_source"] == "events" and d["is_won"]
                and Q4_2025[0] <= date.fromisoformat(d["create_date"]) <= Q4_2025[1]]
    q1_mean_dtc = _mean(dtc(d) for d in q1_event)
    q4_mean_dtc = _mean(dtc(d) for d in q4_event)
    campaigns = ds["campaigns"]
    saas_connect_ids = {c["id"] for c in campaigns if "SaaS Connect" in c["name"]}
    saas_connect_q1 = [d for d in q1_event if d.get("campaign_source_id") in saas_connect_ids]
    passed = (
        _in_range(q1_mean_dtc, 43, 51)
        and _in_range(q4_mean_dtc, 67, 75)
        and len(saas_connect_q1) >= 10
    )
    results.append(CheckResult(14, "Q1 event deals closing faster than Q4", "p06_event_velocity", passed,
                               f"Q1 n={len(q1_event)} mean DTC={q1_mean_dtc:.1f}; Q4 n={len(q4_event)} mean DTC={q4_mean_dtc:.1f}; SaaSConnect Q1 wins={len(saas_connect_q1)}"))

    # P07 — branded search 6-week streak
    bs = ds["branded_search"]
    anchor_ends = [date(2026, 3, 8), date(2026, 3, 15), date(2026, 3, 22),
                   date(2026, 3, 29), date(2026, 4, 5), date(2026, 4, 12), date(2026, 4, 19)]
    idx = {date.fromisoformat(r["date"]): r["search_volume"] for r in bs}
    vals = [idx.get(d, None) for d in anchor_ends]
    diffs = [vals[i + 1] > vals[i] for i in range(len(vals) - 1) if vals[i] and vals[i + 1]]
    cum_growth = (vals[-1] / vals[0] - 1) if vals[0] and vals[-1] else 0
    passed = all(diffs) and len(diffs) == 6 and _in_range(cum_growth, 0.80, 1.05)
    results.append(CheckResult(1, "Branded search 6-week streak", "p07_branded_search_streak", passed,
                               f"WoW increases={sum(diffs)}/6; cum growth={cum_growth:.2%}; series={vals}"))

    # P08 — share of voice
    mentions = ds["mentions"]
    apr_start = date(2026, 4, 1)
    atlas_apr = sum(1 for m in mentions if m["entity"] == "Atlas SaaS"
                    and apr_start <= date.fromisoformat(m["date"]) <= TODAY)
    competitor_totals = defaultdict(int)
    for m in mentions:
        if apr_start <= date.fromisoformat(m["date"]) <= TODAY and m["entity"] != "Atlas SaaS":
            competitor_totals[m["entity"]] += 1
    top_comp_count = max(competitor_totals.values()) if competitor_totals else 0
    passed = _in_range(atlas_apr, 1700, 2000) and _in_range(top_comp_count, 1100, 1300) and atlas_apr - top_comp_count >= 500
    results.append(CheckResult(9, "Share of voice beats top competitor", "p08_share_of_voice", passed,
                               f"Atlas April={atlas_apr}; top competitor={top_comp_count}; gap={atlas_apr - top_comp_count}"))

    # P09 — direct vs organic
    wa = ds["web_analytics"]
    apr_rows = [r for r in wa if apr_start <= date.fromisoformat(r["date"]) <= TODAY]
    total_new = sum(r["new_sessions"] for r in apr_rows)
    direct_new = sum(r["new_sessions"] for r in apr_rows if r["channel"] == "direct")
    organic_new = sum(r["new_sessions"] for r in apr_rows if r["channel"] == "organic_search")
    direct_share = direct_new / total_new if total_new else 0
    organic_share = organic_new / total_new if total_new else 0
    # Find the cross date: first day where direct >= organic after starting below
    by_day = defaultdict(lambda: {"direct": 0, "organic_search": 0})
    for r in apr_rows:
        if r["channel"] in ("direct", "organic_search"):
            by_day[r["date"]][r["channel"]] += r["new_sessions"]
    cross_date = None
    below_first = False
    for d_str in sorted(by_day.keys()):
        dct = by_day[d_str]
        if dct["organic_search"] > dct["direct"]:
            below_first = True
        elif below_first and dct["direct"] >= dct["organic_search"]:
            cross_date = date.fromisoformat(d_str)
            break
    passed = (
        _in_range(direct_share, 0.39, 0.45)
        and _in_range(organic_share, 0.35, 0.41)
        and cross_date is not None
        and date(2026, 4, 5) <= cross_date <= date(2026, 4, 11)
    )
    results.append(CheckResult(12, "Direct traffic crossed organic", "p09_direct_vs_organic", passed,
                               f"direct share={direct_share:.2%}; organic share={organic_share:.2%}; cross={cross_date}"))

    # P10 — analyst mentions
    am = ds["analyst_mentions"]
    last14_cutoff = TODAY - timedelta(days=13)  # past 14 days inclusive
    prior30_start = last14_cutoff - timedelta(days=30)
    last14 = [m for m in am if last14_cutoff <= date.fromisoformat(m["date"]) <= TODAY]
    prior30 = [m for m in am if prior30_start <= date.fromisoformat(m["date"]) < last14_cutoff]
    firm_counts_14 = Counter(m["analyst_firm"] for m in last14)
    top2 = {firm for firm, _ in firm_counts_14.most_common(2)}
    passed = (
        len(last14) >= 8 and len(prior30) <= 7
        and {"Forrester", "G2"}.issubset(top2 | {firm for firm, c in firm_counts_14.items() if c >= 3})
    )
    results.append(CheckResult(6, "Analyst mentions spike", "p10_analyst_spike", passed,
                               f"last14={len(last14)}, prior30={len(prior30)}, top firms={firm_counts_14.most_common(3)}"))

    # P11 — MM wins last 60 days: >=8 fintech industry, >=11 Snowflake+dbt tech pair
    mm_60d = [d for d in deals if d["segment"] == "mid-market" and d["is_won"]
              and LAST_60_DAYS[0] <= date.fromisoformat(d["close_date"]) <= LAST_60_DAYS[1]]
    fintech_n = sum(1 for d in mm_60d if by_co[d["company_id"]]["industry"] == "fintech")
    stack_n = sum(1 for d in mm_60d if {"Snowflake", "dbt"}.issubset(set(by_co[d["company_id"]]["tech_stack"])))
    passed = len(mm_60d) >= 12 and fintech_n >= 8 and stack_n >= 11
    results.append(CheckResult(3, "MM wins 60-day concentration (fintech / Snowflake+dbt)", "p11_mm_wins_concentration", passed,
                               f"MM wins last 60d n={len(mm_60d)}; fintech={fintech_n}; Snowflake+dbt={stack_n}"))

    # P12 — reference opt-ins
    optins = ds["customer_reference_optins"]
    by_line = defaultdict(list)
    for o in optins:
        by_line[o["product_line"]].append(o["reference_willingness"])
    rates = {pl: (sum(1 for v in vs if v) / len(vs)) if vs else 0 for pl, vs in by_line.items()}
    ai = rates.get("Atlas Insights", 0)
    aw = rates.get("Atlas Workflow", 0)
    ac = rates.get("Atlas Connect", 0)
    passed = _in_range(ai, 0.72, 0.80) and _in_range(aw, 0.67, 0.75) and _in_range(ac, 0.24, 0.32)
    results.append(CheckResult(10, "Reference opt-ins concentrated on two lines", "p12_reference_optins", passed,
                               f"Insights={ai:.2%}, Workflow={aw:.2%}, Connect={ac:.2%}"))

    # P13 — exactly 3 target accounts with 5+ high-intent events this week
    eng = ds["engagement_events"]
    cw_hi = [e for e in eng if e["event_type"] in HIGH_INTENT_TYPES
             and CURRENT_WEEK[0] <= date.fromisoformat(e["date"]) <= CURRENT_WEEK[1]]
    per_company = Counter(e["company_id"] for e in cw_hi)
    target_ids = {c["id"] for c in companies if c["is_target_account"]}
    hot_targets = [co_id for co_id, n in per_company.items() if n >= 5 and co_id in target_ids]
    # Check 2 named + 1 March ABM Add
    named_ids = {c["id"] for c in companies if c.get("target_list_name") == "Named Accounts"}
    march_ids = {c["id"] for c in companies if c.get("target_list_name") == "March ABM Add"}
    hot_named = [co_id for co_id in hot_targets if co_id in named_ids]
    hot_march = [co_id for co_id in hot_targets if co_id in march_ids]
    passed = len(hot_targets) == 3 and len(hot_named) == 2 and len(hot_march) == 1
    results.append(CheckResult(0, "Three target accounts hit 5+ high-intent events this week", "p13_target_account_intent", passed,
                               f"hot target accounts={len(hot_targets)} (named={len(hot_named)}, March ABM={len(hot_march)})"))

    # P14 — launch ready
    pl = ds["product_launches"]
    launch = next((p for p in pl if p["launch_date"] == iso(date(2026, 5, 8))), None)
    launch_cam = next((c for c in campaigns if c.get("is_launch_campaign") and c.get("launch_id") == (launch["id"] if launch else None)), None)
    passed = bool(launch) and bool(launch_cam) and launch_cam["status"] == "ready"
    results.append(CheckResult(4, "Launch two weeks out, campaign ready", "p14_launch_ready", passed,
                               f"launch={launch['name'] if launch else None}; campaign status={launch_cam['status'] if launch_cam else None}"))

    # P15 — SDR capacity
    sdr = ds["sdr_capacity"]
    cw_row = next((r for r in sdr if r["week_ending_date"] == iso(week_end(TODAY))), None)
    passed = bool(cw_row) and _in_range(cw_row["inbound_lead_volume"], 135, 150) and _in_range(cw_row["team_total_capacity"], 200, 220)
    results.append(CheckResult(8, "SDR capacity underused", "p15_sdr_capacity", passed,
                               f"cw row={cw_row}"))

    return results


# ----------------------------------------------------------------------------
# Output writers
# ----------------------------------------------------------------------------

def write_json(ds: Dict[str, List[Dict]], outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for name, rows in ds.items():
        (outdir / f"{name}.json").write_text(json.dumps(rows, indent=2, default=str))


def write_csv(ds: Dict[str, List[Dict]], outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for name, rows in ds.items():
        if not rows:
            continue
        # Flatten list-typed fields for CSV (tech_stack)
        rows_out = []
        for r in rows:
            flat = {}
            for k, v in r.items():
                if isinstance(v, list):
                    flat[k] = ";".join(str(x) for x in v)
                elif v is None:
                    flat[k] = ""
                else:
                    flat[k] = v
            rows_out.append(flat)
        keys = sorted({k for r in rows_out for k in r.keys()})
        with (outdir / f"{name}.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for r in rows_out:
                w.writerow(r)


def load_dataset(outdir: Path) -> Dict[str, List[Dict]]:
    ds = {}
    for path in sorted(outdir.glob("*.json")):
        ds[path.stem] = json.loads(path.read_text())
    return ds


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate Atlas SaaS synthetic dataset for Stage 1 Relevance Engine eval.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42).")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output format.")
    parser.add_argument("--output", type=str, default="./output", help="Output directory.")
    parser.add_argument("--validate", action="store_true", help="Skip generation; load from --output and re-run validation.")
    args = parser.parse_args()

    outdir = Path(args.output)

    if args.validate:
        ds = load_dataset(outdir)
        if not ds:
            print(f"No JSON files found in {outdir}", file=sys.stderr)
            sys.exit(2)
    else:
        ds = build_dataset(args.seed)
        if args.format == "json":
            write_json(ds, outdir)
        else:
            write_csv(ds, outdir)

    # Row-count summary
    print(f"Generated {len(ds)} entities into {outdir}:")
    for name, rows in ds.items():
        print(f"  {name:30s} {len(rows):6d} rows")

    # Run validation — Marketing (15) + Revenue (15) = 30 total
    mkt_results = validate(ds)
    print("\nMarketing validation (15 card patterns):")
    mkt_passed = 0
    for r in sorted(mkt_results, key=lambda x: x.card_idx):
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] card {r.card_idx:2d}  {r.pattern:35s}  {r.detail}")
        if r.passed:
            mkt_passed += 1
    print(f"  -> {mkt_passed}/{len(mkt_results)} marketing checks passed.")

    rev_results = validate_revenue(ds)
    print("\nRevenue Leader validation (15 card patterns):")
    rev_passed = 0
    for r in sorted(rev_results, key=lambda x: x.card_idx):
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] card {r.card_idx:2d}  {r.pattern:35s}  {r.detail}")
        if r.passed:
            rev_passed += 1
    print(f"  -> {rev_passed}/{len(rev_results)} revenue checks passed.")

    total_passed = mkt_passed + rev_passed
    total = len(mkt_results) + len(rev_results)
    print(f"\nTOTAL: {total_passed}/{total} pattern checks passed.")
    sys.exit(0 if total_passed == total else 1)


if __name__ == "__main__":
    main()
