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
        {"id": "PL-002", "name": "Custom Permissions and Audit Logs", "launch_date": iso(date(2026, 6, 15)), "status": "scheduled"},
        # Marketing Strategist launches (Phase 2.8)
        {"id": "PL-MS-001", "name": "Atlas CRM Sync", "launch_date": iso(date(2026, 4, 8)), "status": "shipped"},
        {"id": "PL-MS-002", "name": "Atlas Forecast Pro", "launch_date": iso(date(2026, 5, 15)), "status": "ready"},
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
    # Trailing MM NRR avg ~1.05 supports CL-06 (Q2 lift to 1.12 against trailing 1.05).
    nrr_map = {
        ("Q2_2026", "mid-market"): 1.12,
        ("Q1_2026", "mid-market"): 1.04,
        ("Q4_2025", "mid-market"): 1.06,
        ("Q3_2025", "mid-market"): 1.05,
        ("Q2_2025", "mid-market"): 1.05,
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
                "renewal_signed_date": iso(d),
                "original_renewal_date": iso(d),
                "renewed_arr": amt,
                "nrr": nrr_map[(q, seg)],
            })
            rid += 1
    return rows


def gen_expansion_opportunities() -> List[Dict]:
    """Default empty list. Pattern P-RL-11 seeds 8 in last 30 days."""
    return []


# ----------------------------------------------------------------------------
# Customer Leader entity generators
# ----------------------------------------------------------------------------

def gen_forecast_log() -> List[Dict]:
    """Quarterly renewal-forecast aggregate (Customer Leader leadership ledger).

    P-CL-01: Q2_2026 actual within 1.7% of plan on $1.8M renewing book; trailing
    4 quarters variance avg ~8%. P-CL-04 reads renewing_book_arr ($1.8M) and
    Q2 MM GRR (91%); the per-event renewals.json sums stay at the RL-15
    Q2 MM target ($620K) since CL-04 reads forecast aggregates, not events.
    """
    return [
        # Active quarter (Q2_2026)
        {
            "quarter": "Q2_2026",
            "segment": "all",
            "renewing_book_arr": 1_800_000,
            "forecast_arr": 1_800_000,
            "actual_arr": 1_770_000,  # variance 1.7%
            "variance_pct": 0.017,
            "grr": None,
            "nrr": None,
        },
        {"quarter": "Q2_2026", "segment": "mid-market", "renewing_book_arr": 1_116_000, "forecast_arr": None, "actual_arr": None, "variance_pct": None, "grr": 0.91, "nrr": 1.12},
        {"quarter": "Q2_2026", "segment": "enterprise", "renewing_book_arr": 432_000, "forecast_arr": None, "actual_arr": None, "variance_pct": None, "grr": 0.94, "nrr": 1.06},
        {"quarter": "Q2_2026", "segment": "small-business", "renewing_book_arr": 252_000, "forecast_arr": None, "actual_arr": None, "variance_pct": None, "grr": 0.86, "nrr": 1.02},
        # Trailing 4 quarters (variance avg ~8%)
        {"quarter": "Q1_2026", "segment": "all", "renewing_book_arr": 1_650_000, "forecast_arr": 1_650_000, "actual_arr": 1_525_000, "variance_pct": 0.076, "grr": None, "nrr": None},
        {"quarter": "Q4_2025", "segment": "all", "renewing_book_arr": 1_580_000, "forecast_arr": 1_580_000, "actual_arr": 1_440_000, "variance_pct": 0.089, "grr": None, "nrr": None},
        {"quarter": "Q3_2025", "segment": "all", "renewing_book_arr": 1_510_000, "forecast_arr": 1_510_000, "actual_arr": 1_390_000, "variance_pct": 0.079, "grr": None, "nrr": None},
        {"quarter": "Q2_2025", "segment": "all", "renewing_book_arr": 1_460_000, "forecast_arr": 1_460_000, "actual_arr": 1_340_000, "variance_pct": 0.082, "grr": None, "nrr": None},
    ]


def gen_renewal_at_risk_log(rng: random.Random, customers: List[Dict]) -> List[Dict]:
    """At-risk pool snapshots for current and prior month (P-CL-02, P-CL-14).

    Current month (April 2026): pool = $220K, 2 of top-20 ARR on early-warning.
    Prior month (March 2026): pool = $310K, 5 of top-20 ARR on early-warning.
    Net delta: 3 dropped off, 1 added.
    """
    rows: List[Dict] = []
    if not customers:
        return rows

    # Sort customers by current_arr desc; top 20.
    ranked = sorted(customers, key=lambda c: c.get("current_arr", 0), reverse=True)
    top20 = ranked[:20]

    # March 2026: 5 top-20 + several non-top-20 totaling $310K
    # April 2026: 2 top-20 (subset) + 1 new mid-tier; total $220K
    march_top20 = top20[:5]
    april_top20 = top20[:2]  # 2 of march's 5 carry over
    # Add 1 new entry in april that wasn't in march (next ranked customer beyond top 20)
    april_new_entry = ranked[20] if len(ranked) > 20 else top20[5]

    # Distribute amounts so totals match
    # March: $310K across 5 top-20 (avg $50K) + $60K spread on 2 non-top customers = $310K
    march_amounts_top = [80_000, 70_000, 50_000, 30_000, 20_000]  # sum 250K
    for c, amt in zip(march_top20, march_amounts_top):
        rows.append({
            "company_id": c["id"],
            "snapshot_month": "2026-03",
            "arr_at_risk": amt,
            "in_top_20_arr": True,
            "status": "early-warning",
        })
    # 2 mid-tier risk entries to bring March to $310K
    mid_pool_march = ranked[20:30] if len(ranked) > 30 else top20[5:7]
    for c, amt in zip(mid_pool_march[:2], [35_000, 25_000]):
        rows.append({
            "company_id": c["id"],
            "snapshot_month": "2026-03",
            "arr_at_risk": amt,
            "in_top_20_arr": False,
            "status": "early-warning",
        })

    # April: $220K total, 2 top-20 + 1 new ranked customer
    april_amounts_top = [85_000, 75_000]  # sum 160K
    for c, amt in zip(april_top20, april_amounts_top):
        rows.append({
            "company_id": c["id"],
            "snapshot_month": "2026-04",
            "arr_at_risk": amt,
            "in_top_20_arr": True,
            "status": "early-warning",
        })
    rows.append({
        "company_id": april_new_entry["id"],
        "snapshot_month": "2026-04",
        "arr_at_risk": 60_000,
        "in_top_20_arr": False,
        "status": "early-warning",
    })
    return rows


def gen_health_scores(rng: random.Random, customers: List[Dict]) -> List[Dict]:
    """Quarterly health score distribution (P-CL-11).

    Q2_2026 mid-market: 78% green, retention by color: green 96%, yellow 73%.
    Q1_2026 mid-market: 71% green.
    """
    rows: List[Dict] = []
    mm_customers = [c for c in customers if c.get("segment") == "mid-market"]
    if not mm_customers:
        return rows

    # Q2 distribution: 78% green, 17% yellow, 5% red
    n = len(mm_customers)
    n_green = int(round(n * 0.78))
    n_yellow = int(round(n * 0.17))
    n_red = n - n_green - n_yellow
    rng.shuffle(mm_customers)
    for i, c in enumerate(mm_customers):
        if i < n_green:
            color = "green"
        elif i < n_green + n_yellow:
            color = "yellow"
        else:
            color = "red"
        rows.append({
            "company_id": c["id"],
            "quarter": "Q2_2026",
            "segment": "mid-market",
            "color": color,
            "score": rng.randint(75, 95) if color == "green" else (rng.randint(55, 74) if color == "yellow" else rng.randint(20, 54)),
        })

    # Q1 distribution: 71% green, 21% yellow, 8% red
    n_green_q1 = int(round(n * 0.71))
    n_yellow_q1 = int(round(n * 0.21))
    n_red_q1 = n - n_green_q1 - n_yellow_q1
    rng.shuffle(mm_customers)
    for i, c in enumerate(mm_customers):
        if i < n_green_q1:
            color = "green"
        elif i < n_green_q1 + n_yellow_q1:
            color = "yellow"
        else:
            color = "red"
        rows.append({
            "company_id": c["id"],
            "quarter": "Q1_2026",
            "segment": "mid-market",
            "color": color,
            "score": rng.randint(75, 95) if color == "green" else (rng.randint(55, 74) if color == "yellow" else rng.randint(20, 54)),
        })

    return rows


def gen_cohorts() -> List[Dict]:
    """Cohort retention + TTFV (P-CL-08, P-CL-12).

    P-CL-08 MM TTFV: Q2 MM 23d, Q1 MM 38d; renew rate gap by TTFV bucket.
    P-CL-12 all-segments cohort: Q1 26d, Q4 38d; 90d retention Q1 88%, Q4 83%.

    Reconciled by scoping: CL-08 reads MM-only; CL-12 reads all-segments.
    Q1 all-segments 26d is reachable when Q1 SMB+ENT cohorts have fast TTFV
    pulling the avg below the MM 38d.
    """
    return [
        # MM-only TTFV (P-CL-08)
        {"cohort_quarter": "Q2_2026", "segment": "mid-market", "n_accounts": 24, "ttfv_days": 23, "retention_90d": None, "renewal_rate_under_30d_ttfv": 0.94, "renewal_rate_over_60d_ttfv": 0.76},
        {"cohort_quarter": "Q1_2026", "segment": "mid-market", "n_accounts": 22, "ttfv_days": 38, "retention_90d": None, "renewal_rate_under_30d_ttfv": 0.91, "renewal_rate_over_60d_ttfv": 0.74},
        {"cohort_quarter": "Q4_2025", "segment": "mid-market", "n_accounts": 20, "ttfv_days": 41, "retention_90d": None, "renewal_rate_under_30d_ttfv": 0.89, "renewal_rate_over_60d_ttfv": 0.72},
        # All-segments cohorts (P-CL-12)
        {"cohort_quarter": "Q1_2026", "segment": "all", "n_accounts": 60, "ttfv_days": 26, "retention_90d": 0.88, "renewal_rate_under_30d_ttfv": None, "renewal_rate_over_60d_ttfv": None},
        {"cohort_quarter": "Q4_2025", "segment": "all", "n_accounts": 55, "ttfv_days": 38, "retention_90d": 0.83, "renewal_rate_under_30d_ttfv": None, "renewal_rate_over_60d_ttfv": None},
        {"cohort_quarter": "Q3_2025", "segment": "all", "n_accounts": 50, "ttfv_days": 36, "retention_90d": 0.84, "renewal_rate_under_30d_ttfv": None, "renewal_rate_over_60d_ttfv": None},
        # SMB / ENT Q1 cohorts contributing to the 26d Q1 all avg
        {"cohort_quarter": "Q1_2026", "segment": "small-business", "n_accounts": 25, "ttfv_days": 14, "retention_90d": 0.85, "renewal_rate_under_30d_ttfv": None, "renewal_rate_over_60d_ttfv": None},
        {"cohort_quarter": "Q1_2026", "segment": "enterprise", "n_accounts": 13, "ttfv_days": 28, "retention_90d": 0.92, "renewal_rate_under_30d_ttfv": None, "renewal_rate_over_60d_ttfv": None},
    ]


def gen_product_adoption(rng: random.Random, customers: List[Dict]) -> List[Dict]:
    """Per-customer product mix and license utilization (P-CL-07, P-CL-10).

    P-CL-07: multi-product Q2 NRR 124%, single 102%, gap 14→22 vs Q1; multi-product
    share up from 31% → 38% over the quarter (seeded to 38% by construction).
    P-CL-10: 22 MM customers crossed 80% license utilization in Q2 (14 in Q1).

    Construction: seed 24 MM customers as Atlas Insights multi-product (P-CL-06),
    then top up the multi-product pool from non-MM customers to land at 38%
    of all customers. This makes the multi-share locked across seeds and
    removes the need for downstream seeders to promote.
    """
    rows: List[Dict] = []
    if not customers:
        return rows

    mm = [c for c in customers if c["segment"] == "mid-market"]
    non_mm = [c for c in customers if c["segment"] != "mid-market"]
    rng.shuffle(mm)
    rng.shuffle(non_mm)

    n_total = len(customers)
    target_multi = int(round(n_total * 0.38))
    mm_multi_target = min(24, len(mm))
    extra_multi = max(0, target_multi - mm_multi_target)
    non_mm_multi = non_mm[:extra_multi]
    non_mm_single = non_mm[extra_multi:]

    def emit(c: Dict, multi: bool, mix: List[str]) -> Dict:
        return {
            "company_id": c["id"],
            "products": mix,
            "is_multi_product": multi,
            "license_util_q2_2026": 0.0,
            "license_util_q1_2026": 0.0,
        }

    # MM: first 24 multi (with atlas-insights), rest single
    for i, c in enumerate(mm):
        if i < mm_multi_target:
            mix = ["atlas-core", "atlas-insights"]
            if rng.random() < 0.4:
                mix.append("atlas-collaborate")
            rows.append(emit(c, True, mix))
        else:
            rows.append(emit(c, False, ["atlas-core"]))

    # Non-MM multi: split between insights/collaborate
    for c in non_mm_multi:
        mix = rng.choice([
            ["atlas-core", "atlas-insights"],
            ["atlas-core", "atlas-collaborate"],
        ])
        rows.append(emit(c, True, mix))

    for c in non_mm_single:
        rows.append(emit(c, False, ["atlas-core"]))

    # Force MM bucketing to hit the target counts (22 Q2, 14 Q1)
    by_co_seg = {c["id"]: c["segment"] for c in customers}
    mm_rows = [r for r in rows if by_co_seg.get(r["company_id"]) == "mid-market"]
    rng.shuffle(mm_rows)
    for i, r in enumerate(mm_rows):
        if i < 22:
            r["license_util_q2_2026"] = round(rng.uniform(0.81, 0.95), 3)
        else:
            r["license_util_q2_2026"] = round(rng.uniform(0.40, 0.79), 3)
        if i < 14:
            r["license_util_q1_2026"] = round(rng.uniform(0.81, 0.95), 3)
        else:
            r["license_util_q1_2026"] = round(rng.uniform(0.30, 0.79), 3)

    # Non-MM utilization (default fill)
    for r in rows:
        if r["license_util_q2_2026"] == 0.0:
            r["license_util_q2_2026"] = round(rng.uniform(0.30, 0.78), 3)
            r["license_util_q1_2026"] = round(rng.uniform(0.25, 0.75), 3)

    return rows


def gen_coverage_tier(rng: random.Random, customers: List[Dict]) -> List[Dict]:
    """High-touch vs tech-touch coverage tiering (P-CL-13).

    Q2_2026: high-touch GRR 96%, tech-touch GRR 82% (gap 8→14 vs Q1).
    High-touch covers top 18% by ARR.
    """
    rows: List[Dict] = []
    if not customers:
        return rows
    ranked = sorted(customers, key=lambda c: c.get("current_arr", 0), reverse=True)
    n = len(ranked)
    cutoff = int(round(n * 0.18))
    for i, c in enumerate(ranked):
        tier = "high-touch" if i < cutoff else "tech-touch"
        rows.append({
            "company_id": c["id"],
            "tier": tier,
            "grr_q2_2026": 0.96 if tier == "high-touch" else 0.82,
            "grr_q1_2026": 0.94 if tier == "high-touch" else 0.86,
        })
    return rows


def gen_executive_sponsor(rng: random.Random, customers: List[Dict]) -> List[Dict]:
    """Executive sponsor depth (P-CL-03, P-CL-14).

    P-CL-03 needs 3 enterprise renewals signed in April with sponsor depth_change=deepened
    in the prior quarter (Q1_2026). Plant a broader pool so seeders pick deterministically.
    P-CL-14: 2 of top-20 ARR on early-warning have sponsor review in current week.
    """
    rows: List[Dict] = []
    if not customers:
        return rows

    LEVELS = ["VP", "C-suite", "Director"]
    for c in customers:
        depth = rng.choice(LEVELS)
        depth_change = rng.choices(
            ["deepened", "stable", "shallowed", "none"],
            weights=[0.25, 0.55, 0.10, 0.10],
        )[0]
        last_review = None
        next_review = None
        rows.append({
            "company_id": c["id"],
            "sponsor_level": depth,
            "depth_change_q1_2026": depth_change,
            "last_review_date": last_review,
            "next_review_date": next_review,
        })
    return rows


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
    """RL-11 — 8 expansion opportunities from customer health reviews, last 30 days, total $340K, avg $42K.

    Pinned to April 1..TODAY (inclusive) so P-CL-09's "this month" framing
    aligns with RL-11's "last 30 days" — all 8 events fall in both windows.
    """
    customers = [c for c in companies if c["is_customer"]]
    apr_start = date(2026, 4, 1)
    span = (TODAY - apr_start).days
    target_total = 340_000
    n = 8
    amounts = _amounts_at_mean(rng, n, 42_500, 8_000)
    # Adjust to hit exact total (drift from rounding).
    diff = target_total - sum(amounts)
    amounts[0] += diff
    for i, amt in enumerate(amounts):
        co = rng.choice(customers)
        d = apr_start + timedelta(days=rng.randint(0, span))
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


# ----------------------------------------------------------------------------
# Customer Leader pattern seeders (P-CL-01..15)
# ----------------------------------------------------------------------------

def plant_customer_arr(rng: random.Random, companies: List[Dict]) -> None:
    """Plant `current_arr` on every customer. Top-20 ranking is the input to
    P-CL-02 / P-CL-14 risk-pool checks and P-CL-13 high-touch tiering.
    """
    for c in companies:
        if not c["is_customer"]:
            c["current_arr"] = 0
            continue
        if c["segment"] == "enterprise":
            c["current_arr"] = rng.randint(200_000, 500_000)
        elif c["segment"] == "mid-market":
            c["current_arr"] = rng.randint(40_000, 150_000)
        else:
            c["current_arr"] = rng.randint(5_000, 25_000)


def plant_beacon_logistics(companies: List[Dict]) -> None:
    """Force Beacon Logistics into the customer roster (P-CL-05 + P-CL-15).

    Replaces the first enterprise customer's identity with Beacon, locked at
    $280K ARR. Preserves all other fields so seeders that selected the row by
    segment continue to behave.
    """
    for c in companies:
        if c["is_customer"] and c["segment"] == "enterprise":
            c["name"] = "Beacon Logistics"
            c["industry"] = "logistics"
            c["current_arr"] = 280_000
            c["_beacon"] = True
            return


def seed_p_cl_01_forecast_accuracy() -> None:
    """CL-01 — Q2 forecast within 1.7% of plan on $1.8M renewing book.
    Static row in gen_forecast_log; no additional planting needed."""
    return


def seed_p_cl_02_risk_pool() -> None:
    """CL-02 — March $310K → April $220K at-risk pool. Static rows in
    gen_renewal_at_risk_log; no additional planting needed."""
    return


def seed_p_cl_03_april_ent_renewals(rng: random.Random, renewals: List[Dict], executive_sponsor: List[Dict]) -> None:
    """CL-03 — 3 enterprise renewals signed in April with sponsor depth_change=deepened in Q1."""
    apr_ent = [r for r in renewals
               if r["segment"] == "enterprise"
               and r["renewal_signed_date"]
               and r["renewal_signed_date"].startswith("2026-04")]
    rng.shuffle(apr_ent)
    chosen = apr_ent[:3]
    if len(chosen) < 3:
        # Augment by promoting Q2 ENT renewals to April-signed if needed.
        q2_ent = [r for r in renewals if r["segment"] == "enterprise" and r["quarter"] == "Q2_2026"]
        for r in q2_ent:
            if r in chosen:
                continue
            r["renewal_signed_date"] = iso(date(2026, 4, rng.randint(1, 24)))
            chosen.append(r)
            if len(chosen) >= 3:
                break
    sponsor_by_co = {s["company_id"]: s for s in executive_sponsor}
    for r in chosen:
        s = sponsor_by_co.get(r["company_id"])
        if s:
            s["depth_change_q1_2026"] = "deepened"
            s["sponsor_level"] = "C-suite"


def seed_p_cl_04_mm_grr() -> None:
    """CL-04 — Q2 MM GRR 91% on $1.8M renewing. Already in gen_forecast_log."""
    return


def seed_p_cl_05_beacon_renewal(rng: random.Random, renewals: List[Dict], companies: List[Dict]) -> None:
    """CL-05 — Beacon Logistics $280K renewal signed 2026-04-21, original 2026-07-15."""
    beacon = next((c for c in companies if c.get("_beacon")), None)
    if not beacon:
        return
    rid = max([int(r["id"].split("-")[1]) for r in renewals], default=0) + 1
    renewals.append({
        "id": f"RN-{rid:05d}",
        "company_id": beacon["id"],
        "quarter": "Q3_2026",
        "segment": "enterprise",
        "renewal_date": "2026-07-15",
        "renewal_signed_date": "2026-04-21",
        "original_renewal_date": "2026-07-15",
        "renewed_arr": 280_000,
        "nrr": 1.0,
    })


def seed_p_cl_06_mm_nrr_lift(product_adoption: List[Dict], companies: List[Dict]) -> None:
    """CL-06 — Q2 MM NRR 1.12 (already in nrr_map), 18 of 24 Atlas Insights MM expanded.

    Tags MM customers running Atlas Insights with `expanded_q2_2026` so the
    validator can read 18/24 directly.
    """
    by_co = {c["id"]: c for c in companies}
    insights_mm = [r for r in product_adoption
                   if "atlas-insights" in r["products"]
                   and by_co.get(r["company_id"], {}).get("segment") == "mid-market"]
    # Force exactly 24 MM Atlas Insights customers.
    if len(insights_mm) < 24:
        # Promote single-product MM customers to also include atlas-insights.
        candidates = [r for r in product_adoption
                      if by_co.get(r["company_id"], {}).get("segment") == "mid-market"
                      and "atlas-insights" not in r["products"]]
        for r in candidates:
            r["products"] = list(set(r["products"]) | {"atlas-insights"})
            r["is_multi_product"] = len(r["products"]) > 1
            insights_mm.append(r)
            if len(insights_mm) >= 24:
                break
    # Trim to exactly 24
    insights_mm = insights_mm[:24]
    for i, r in enumerate(insights_mm):
        r["expanded_q2_2026"] = i < 18


def seed_p_cl_07_multiproduct_nrr(product_adoption: List[Dict]) -> None:
    """CL-07 — multi-product Q2 NRR 124%, single 102%, gap 14→22; multi share 31→38."""
    for r in product_adoption:
        if r["is_multi_product"]:
            r["nrr_q2_2026"] = 1.24
            r["nrr_q1_2026"] = 1.16
        else:
            r["nrr_q2_2026"] = 1.02
            r["nrr_q1_2026"] = 1.02


def seed_p_cl_08_mm_ttfv() -> None:
    """CL-08 — Q2 MM TTFV 23d, Q1 MM 38d. Already in gen_cohorts."""
    return


def seed_p_cl_09_cs_sourced_expansion(rng: random.Random, expansion_opportunities: List[Dict], companies: List[Dict]) -> None:
    """CL-09 — 8 CS-sourced this month $340K (already from RL-11), 6 prior-month CS-sourced
    sales-accepted 5 (83%), 17 outbound prior-month sales-accepted 7 (41%).
    """
    customers = [c for c in companies if c["is_customer"]]
    if not customers:
        return
    # Tag the 8 CS-sourced this month (from RL-11) with sales_accepted=None (decision pending).
    for o in expansion_opportunities:
        o.setdefault("month", o["create_date"][:7])
        o.setdefault("sales_accepted", None)
    # Add 6 prior-month CS-sourced expansions (March 1-24, before last-30d window),
    # 5 accepted. Stays out of RL-11's last-30d count.
    base_id = max([int(o["id"].split("-")[1]) for o in expansion_opportunities], default=0) + 1
    for i in range(6):
        co = rng.choice(customers)
        d = date(2026, 3, rng.randint(1, 24))
        expansion_opportunities.append({
            "id": f"EX-{base_id + i:04d}",
            "company_id": co["id"],
            "create_date": iso(d),
            "amount": rng.randint(20_000, 80_000),
            "source": "customer_health_review",
            "stage": "closedwon",
            "month": "2026-03",
            "sales_accepted": i < 5,
        })
    base_id += 6
    # Add 17 prior-month outbound expansions (March 1-24), 7 accepted (~41%).
    for i in range(17):
        co = rng.choice(customers)
        d = date(2026, 3, rng.randint(1, 24))
        expansion_opportunities.append({
            "id": f"EX-{base_id + i:04d}",
            "company_id": co["id"],
            "create_date": iso(d),
            "amount": rng.randint(15_000, 60_000),
            "source": "outbound",
            "stage": "presentationscheduled",
            "month": "2026-03",
            "sales_accepted": i < 7,
        })


def seed_p_cl_10_license_util() -> None:
    """CL-10 — 22 MM crossed 80% util Q2 (14 in Q1). Already in gen_product_adoption."""
    return


def seed_p_cl_11_health_score_renewal_link(rng: random.Random, health_scores: List[Dict]) -> None:
    """CL-11 — Q1 health green renewed 96%, yellow 73%, red ~30%. Sets `renewed` per row."""
    q1 = [h for h in health_scores if h["quarter"] == "Q1_2026"]
    by_color = defaultdict(list)
    for h in q1:
        by_color[h["color"]].append(h)
    for color, rows in by_color.items():
        if color == "green":
            rate = 0.96
        elif color == "yellow":
            rate = 0.73
        else:
            rate = 0.30
        n_renewed = int(round(len(rows) * rate))
        rng.shuffle(rows)
        for i, h in enumerate(rows):
            h["renewed"] = i < n_renewed


def seed_p_cl_12_cohort_retention() -> None:
    """CL-12 — Q1 88% 90d retention, Q4 83%, Q1 TTFV 12d faster. Already in gen_cohorts."""
    return


def seed_p_cl_13_coverage_tier() -> None:
    """CL-13 — High-touch Q2 GRR 96%, tech-touch 82%, gap 8→14. Already in gen_coverage_tier."""
    return


def seed_p_cl_14_top20_at_risk(rng: random.Random, renewal_at_risk_log: List[Dict], executive_sponsor: List[Dict]) -> None:
    """CL-14 — 2 top-20 at-risk in April both have sponsor review in current week."""
    apr_top20 = [r for r in renewal_at_risk_log
                 if r["snapshot_month"] == "2026-04" and r["in_top_20_arr"]]
    sponsor_by_co = {s["company_id"]: s for s in executive_sponsor}
    cw_start, cw_end = CURRENT_WEEK
    for r in apr_top20[:2]:
        s = sponsor_by_co.get(r["company_id"])
        if s:
            review_d = cw_start + timedelta(days=rng.randint(0, (cw_end - cw_start).days))
            s["next_review_date"] = iso(review_d)


def seed_p_cl_15_launch_renewal_link() -> None:
    """CL-15 — PL-002 ships 6/15 (already in gen_product_launches), Beacon
    renewal signed 4/21 (already in seed_p_cl_05_beacon_renewal). No-op."""
    return


# ----------------------------------------------------------------------------
# Marketing Strategist entity generators (Phase 2.8)
# ----------------------------------------------------------------------------

def gen_competitive_intel() -> List[Dict]:
    """Per-competitor intelligence records for Marketing Strategist eval.

    P-MS-01: Beacon Systems Q2 h2h win rate 14/22 = 63.6%; prior 4Q avg 28%.
    P-MS-05: Beacon Systems Q2 battlecard utilization 38/62 opps (61%); prior 22%.
    P-MS-06: Northstar Platform win rate 42% pre Apr-8 → 51% post; Gong -22%.
    P-MS-07: Verge IO appears in 18/75 Q2 competitive opps (24%); Q1 was 11%.
              Series B $40M raised 2026-03-14.
    """
    return [
        {
            "competitor_id": "Beacon Systems",
            "period": "Q2_2026",
            "total_competitive_opps": 62,
            "h2h_deals": 22,
            "wins": 14,
            "losses": 8,
            "win_rate": round(14 / 22, 4),
            "prior_4q_win_rate": 0.28,
            "battlecard_opens": 38,
            "battlecard_util": round(38 / 62, 4),
            "prior_q_battlecard_util": 0.22,
            "win_rate_pre_event": None,
            "win_rate_post_event": None,
            "gong_mentions_change_pct": None,
            "event_date": None,
            "appearance_pct": None,
            "prior_q_appearance_pct": None,
            "series_b_date": None,
            "series_b_amount_m": None,
            "segment_concentration": None,
        },
        {
            "competitor_id": "Northstar Platform",
            "period": "Q2_2026",
            "total_competitive_opps": None,
            "h2h_deals": None,
            "wins": None,
            "losses": None,
            "win_rate": None,
            "prior_4q_win_rate": 0.42,
            "battlecard_opens": None,
            "battlecard_util": None,
            "prior_q_battlecard_util": None,
            "win_rate_pre_event": 0.42,
            "win_rate_post_event": 0.51,
            "gong_mentions_change_pct": -0.22,
            "event_date": "2026-04-08",
            "appearance_pct": None,
            "prior_q_appearance_pct": None,
            "series_b_date": None,
            "series_b_amount_m": None,
            "segment_concentration": None,
        },
        {
            "competitor_id": "Verge IO",
            "period": "Q2_2026",
            "total_competitive_opps": 75,
            "h2h_deals": 18,
            "wins": None,
            "losses": None,
            "win_rate": None,
            "prior_4q_win_rate": None,
            "battlecard_opens": None,
            "battlecard_util": None,
            "prior_q_battlecard_util": None,
            "win_rate_pre_event": None,
            "win_rate_post_event": None,
            "gong_mentions_change_pct": None,
            "event_date": None,
            "appearance_pct": round(18 / 75, 4),
            "prior_q_appearance_pct": 0.11,
            "series_b_date": "2026-03-14",
            "series_b_amount_m": 40,
            "segment_concentration": "mid-market",
        },
    ]


def gen_discovery_calls() -> List[Dict]:
    """Gong-sampled discovery call message-frame resonance data.

    P-MS-02: April 2026, 27 calls sampled, speed-to-value 62%, platform-
             consolidation 19%. Speed-to-value was dominant before the rebrand.
    """
    return [
        {
            "period": "2026-04",
            "calls_sampled": 27,
            "frame_results": [
                {"frame": "speed_to_value", "resonance_rate": 0.62, "count": 17},
                {"frame": "platform_consolidation", "resonance_rate": 0.19, "count": 5},
            ],
            "prior_dominant_frame": "speed_to_value",
            "prior_period_note": "Speed-to-value was dominant in Q1 of last year before the rebrand",
        },
    ]


def gen_icp_analysis() -> List[Dict]:
    """ICP match rate on new logos per quarter.

    P-MS-04: Q2 28/36 = 78%; Q1 23/36 = 64%. ICP-aligned wins close 12 days
             faster on average.
    """
    return [
        {
            "period": "Q2_2026",
            "closed_won_total": 36,
            "icp_matched": 28,
            "icp_match_rate": round(28 / 36, 4),
            "icp_cycle_advantage_days": 12,
        },
        {
            "period": "Q1_2026",
            "closed_won_total": 36,
            "icp_matched": 23,
            "icp_match_rate": round(23 / 36, 4),
            "icp_cycle_advantage_days": None,
        },
    ]


def gen_messaging_performance() -> List[Dict]:
    """Message frame effectiveness by segment and period.

    P-MS-03: Refreshed positioning (speed-to-value hierarchy). Mid-market 31%;
             enterprise 13% on the same message frame.
    P-MS-12: Enterprise inbound with new positioning hook: $290K Q2 pipeline;
             inbound-to-meeting conversion up 8 points.
    """
    return [
        {
            "period": "Q2_2026",
            "frame": "refreshed_positioning",
            "segment": "mid-market",
            "close_rate": 0.31,
            "pipeline_usd": None,
            "inbound_conversion_lift_pct": None,
        },
        {
            "period": "Q2_2026",
            "frame": "refreshed_positioning",
            "segment": "enterprise",
            "close_rate": 0.13,
            "pipeline_usd": None,
            "inbound_conversion_lift_pct": None,
        },
        {
            "period": "Q2_2026",
            "frame": "new_positioning_hook",
            "segment": "enterprise",
            "close_rate": None,
            "pipeline_usd": 290000,
            "inbound_conversion_lift_pct": 8,
        },
    ]


def gen_launch_attribution() -> List[Dict]:
    """Pipeline attributed to product launches.

    P-MS-09: April 8 launch (PL-MS-001), $420K from 14 opps in first 3 weeks.
             Prior October launch (PL-000): $310K in same window.
    P-MS-13: Q2 aggregate launch-attributable $620K of $3.4M net new (18.2%).
    """
    return [
        {
            "launch_id": "PL-MS-001",
            "launch_date": "2026-04-08",
            "attribution_window": "3_weeks",
            "opportunities_created": 14,
            "pipeline_usd": 420000,
            "period": None,
            "total_period_pipeline_usd": None,
            "launch_share_pct": None,
        },
        {
            "launch_id": "PL-000",
            "launch_date": "2025-10-01",
            "attribution_window": "3_weeks",
            "opportunities_created": None,
            "pipeline_usd": 310000,
            "period": None,
            "total_period_pipeline_usd": None,
            "launch_share_pct": None,
        },
        {
            "launch_id": None,
            "launch_date": None,
            "attribution_window": "quarter",
            "opportunities_created": None,
            "pipeline_usd": 620000,
            "period": "Q2_2026",
            "total_period_pipeline_usd": 3400000,
            "launch_share_pct": round(620000 / 3400000, 4),
        },
    ]


def gen_launch_enablement() -> List[Dict]:
    """Launch readiness and enablement asset adoption per launch.

    P-MS-10: May 15 launch (PL-MS-002), 3/3 readiness items cleared 10 days
             before. Prior launch: positioning brief signed off 2 days before.
    P-MS-11: April 8 launch (PL-MS-001), 27/38 reps opened assets in first
             14 days (71%); prior launch adoption was 42%. Pipeline from
             asset-opening reps ran 2.4x that from non-openers.
    """
    return [
        {
            "launch_id": "PL-MS-001",
            "launch_date": "2026-04-08",
            "status": "shipped",
            "readiness_items_count": 3,
            "readiness_items_cleared": 3,
            "days_cleared_before_launch": None,
            "readiness_signoff_date": None,
            "reps_total": 38,
            "reps_opened_assets_14d": 27,
            "asset_adoption_rate_14d": round(27 / 38, 4),
            "prior_launch_asset_adoption_rate": 0.42,
            "pipeline_by_asset_openers_vs_nonopeners_multiple": 2.4,
        },
        {
            "launch_id": "PL-MS-002",
            "launch_date": "2026-05-15",
            "status": "ready",
            "readiness_items_count": 3,
            "readiness_items_cleared": 3,
            "days_cleared_before_launch": 10,
            "readiness_signoff_date": "2026-05-05",
            "prior_launch_days_cleared_before": 2,
            "reps_total": None,
            "reps_opened_assets_14d": None,
            "asset_adoption_rate_14d": None,
            "prior_launch_asset_adoption_rate": 0.42,
            "pipeline_by_asset_openers_vs_nonopeners_multiple": None,
        },
    ]


def gen_earned_media() -> List[Dict]:
    """PR and earned-media pickup rates per launch.

    P-MS-15: April 8 launch: 22/53 publications picked up (41%); prior was 28%.
             Launch-attributable pipeline doubled in the same 7-day window.
    """
    return [
        {
            "launch_id": "PL-MS-001",
            "launch_date": "2026-04-08",
            "publications_outreached": 53,
            "publications_picked_up": 22,
            "pickup_rate": round(22 / 53, 4),
            "prior_launch_pickup_rate": 0.28,
            "pipeline_7d_vs_prior_multiple": 2.0,
        },
    ]


def gen_crm_hygiene() -> List[Dict]:
    """CRM data completeness metrics.

    P-MS-08: Outcome reason capture 47/51 closed Q2 deals (92%); Q1 was 71%.
    """
    return [
        {
            "period": "Q2_2026",
            "closed_deals_total": 51,
            "outcome_reason_captured": 47,
            "capture_rate": round(47 / 51, 4),
        },
        {
            "period": "Q1_2026",
            "closed_deals_total": None,
            "outcome_reason_captured": None,
            "capture_rate": 0.71,
        },
    ]


def gen_cs_exit_interviews() -> List[Dict]:
    """CS exit interview themes surfaced to marketing for positioning work.

    P-MS-14: April 2026, 14 interviews, 6 themes surfaced, 2 feeding the
             positioning refresh. Both positioning themes appear in Beacon
             Systems competitive deals 31% of the time.
    """
    return [
        {
            "period": "2026-04",
            "interviews_conducted": 14,
            "themes_identified": 6,
            "themes_feeding_positioning": 2,
            "positioning_themes": [
                "implementation timeline expectations",
                "integration breadth",
            ],
            "competitor_a_id": "Beacon Systems",
            "competitor_a_overlap_pct": 0.31,
        },
    ]


# ----------------------------------------------------------------------------
# Marketing Builder entity generators (Phase 2.11)
# All deterministic — no random seed dependency.
# ----------------------------------------------------------------------------

def gen_mb_paid_performance() -> List[Dict]:
    """Paid channel performance by period.

    P-MB-01: April paid pipeline $1.18M of $1.5M target by April 21 (week 3).
             LinkedIn CPL $142 flat across weeks 1-3; March CPL climbed 12% MoM.
    P-MB-03: Full-April LinkedIn CPL $138; March $156; Q1 avg $174.
             April 1 audience refresh on 4 campaigns covering 62% of paid budget.
    """
    return [
        {
            "period": "2026-04",
            "pipeline_target_usd": 1500000,
            "pipeline_at_week3_usd": 1180000,
            "week3_date": "2026-04-21",
            "week3_cpl_linkedin": 142,
            "full_month_cpl_linkedin": 138,
            "prior_month_cpl": 156,
            "q1_avg_cpl": 174,
            "march_cpl_mom_climb_pct": 0.12,
            "audience_refresh_date": "2026-04-01",
            "campaigns_in_refresh": 4,
            "budget_share_refreshed": 0.62,
        },
    ]


def gen_mb_mql_sources() -> List[Dict]:
    """MQL source breakdown by period.

    P-MB-02: April 2026 — 312 of 740 MQLs from April 9 webinar (42.2%)
             in 11 days. Highest concentration in mid-market.
             Webinar SQL rate 19% vs paid social 11%.
    """
    return [
        {
            "period": "2026-04",
            "total_mqls": 740,
            "sources": [
                {
                    "source": "webinar_apr9",
                    "campaign_date": "2026-04-09",
                    "mqls": 312,
                    "share": round(312 / 740, 4),
                    "window_days": 11,
                    "segment_concentration": "mid-market",
                    "sql_conversion_rate": 0.19,
                },
                {
                    "source": "paid_social",
                    "campaign_date": None,
                    "mqls": None,
                    "share": None,
                    "window_days": None,
                    "segment_concentration": None,
                    "sql_conversion_rate": 0.11,
                },
            ],
        },
    ]


def gen_mb_inbound_demos() -> List[Dict]:
    """Inbound demo request volume by period.

    P-MB-04: April 84 (47 mid-market + 37 enterprise) vs March 61.
             Homepage CTA test live April 4; +22% form conversion lift.
    """
    return [
        {
            "period": "2026-04",
            "demo_requests": 84,
            "mid_market": 47,
            "enterprise": 37,
            "cta_test_live_date": "2026-04-04",
            "cta_conversion_lift_pct": 0.22,
        },
        {
            "period": "2026-03",
            "demo_requests": 61,
            "mid_market": None,
            "enterprise": None,
            "cta_test_live_date": None,
            "cta_conversion_lift_pct": None,
        },
    ]


def gen_mb_seo_keywords() -> List[Dict]:
    """Keyword ranking movements.

    P-MB-05: "saas pricing models" position 7 → 2 in 9 days (week ending ~Apr 21).
             4,400 monthly search volume. Refreshed April 12.
    P-MB-08: "saas attribution", "b2b lead routing", "marketing ops checklist"
             all moved into top 3 in week ending April 7, from page-2 positions.
             All refreshed with structured FAQ sections in March.
    """
    return [
        {
            "keyword": "saas pricing models",
            "position_before": 7,
            "position_after": 2,
            "days_to_move": 9,
            "monthly_search_volume": 4400,
            "page_refresh_date": "2026-04-12",
            "week_ending": "2026-04-21",
        },
        {
            "keyword": "saas attribution",
            "position_before": "page 2",
            "position_after": 2,
            "days_to_move": None,
            "monthly_search_volume": None,
            "page_refresh_date": "2026-03",
            "week_ending": "2026-04-07",
        },
        {
            "keyword": "b2b lead routing",
            "position_before": "page 2",
            "position_after": 3,
            "days_to_move": None,
            "monthly_search_volume": None,
            "page_refresh_date": "2026-03",
            "week_ending": "2026-04-07",
        },
        {
            "keyword": "marketing ops checklist",
            "position_before": "page 2",
            "position_after": 1,
            "days_to_move": None,
            "monthly_search_volume": None,
            "page_refresh_date": "2026-03",
            "week_ending": "2026-04-07",
        },
    ]


def gen_mb_organic_traffic() -> List[Dict]:
    """Organic traffic by page and period.

    P-MB-07: Comparison hub April 12,400 sessions vs March 9,700 (+27.8%).
             Competitor A page 4,200 sessions. AI Overview on "Competitor A vs"
             queries fell from 71% to 38%.
    """
    return [
        {
            "page": "comparison_hub",
            "period": "2026-04",
            "sessions": 12400,
            "prior_sessions": 9700,
            "change_pct": round((12400 - 9700) / 9700, 4),
            "top_subpage": "competitor_a",
            "top_subpage_sessions": 4200,
            "ai_overview_coverage_before": 0.71,
            "ai_overview_coverage_after": 0.38,
            "ai_overview_query_type": "Competitor A vs",
        },
    ]


def gen_mb_content_attribution() -> List[Dict]:
    """Content-attributable pipeline.

    P-MB-06: 6 of 18 published Q2 pieces carry a touched-deal flag = $310K total.
             Buyer's guide: $140K, 41% WoW view growth since gated download live.
    """
    return [
        {
            "period": "Q2_2026",
            "pieces_with_pipeline": 6,
            "pieces_total_published": 18,
            "pipeline_total_usd": 310000,
            "top_piece": "buyers_guide",
            "top_piece_pipeline_usd": 140000,
            "top_piece_wow_view_growth_pct": 0.41,
        },
    ]


def gen_mb_routing_ops() -> List[Dict]:
    """Demo routing SLA compliance and speed-to-lead by period.

    P-MB-09: April 412/433 = 95.2% inside 5-min SLA vs March 357/435 = 82.1%.
             April 6 routing update added round-robin fallback for after-hours.
    P-MB-14: Median speed-to-lead April 4.2 min vs March 11.6 min.
             SQL conversion: 2.1x for under-5-min vs over-15-min touches.
    """
    return [
        {
            "period": "2026-04",
            "demos_routed": 412,
            "demos_total": 433,
            "sla_pct": round(412 / 433, 4),
            "sla_threshold_minutes": 5,
            "median_speed_to_lead_minutes": 4.2,
            "routing_update_date": "2026-04-06",
            "routing_update_description": "round-robin fallback for after-hours requests",
            "sql_conversion_under5min_multiple": 2.1,
        },
        {
            "period": "2026-03",
            "demos_routed": 357,
            "demos_total": 435,
            "sla_pct": round(357 / 435, 4),
            "sla_threshold_minutes": 5,
            "median_speed_to_lead_minutes": 11.6,
            "routing_update_date": None,
            "routing_update_description": None,
            "sql_conversion_under5min_multiple": None,
        },
    ]


def gen_mb_attribution_accuracy() -> List[Dict]:
    """Marketo-to-Salesforce attribution accuracy and pipeline coverage.

    P-MB-10: Q2 47/2,240 sourced opps mismatch = 2.1% variance vs Q1 4.8%.
             April 14 UTM cleanup on 12 campaigns.
    P-MB-15: $2.4M of $2.7M April pipeline has clean attribution = 88.9%.
             Q1 avg coverage 71%. Attribution mapping locked April 7, 14 campaign types.
    """
    return [
        {
            "period": "Q2_2026",
            "sourced_opps_total": 2240,
            "mismatch_opps": 47,
            "variance_pct": round(47 / 2240, 4),
            "utm_cleanup_date": "2026-04-14",
            "campaigns_cleaned": 12,
            "pipeline_with_clean_attribution_usd": 2400000,
            "pipeline_total_usd": 2700000,
            "attribution_coverage_pct": round(2400000 / 2700000, 4),
            "attribution_mapping_date": "2026-04-07",
            "campaign_types_covered": 14,
        },
        {
            "period": "Q1_2026",
            "sourced_opps_total": None,
            "mismatch_opps": None,
            "variance_pct": 0.048,
            "utm_cleanup_date": None,
            "campaigns_cleaned": None,
            "pipeline_with_clean_attribution_usd": None,
            "pipeline_total_usd": None,
            "attribution_coverage_pct": 0.71,
            "attribution_mapping_date": None,
            "campaign_types_covered": None,
        },
    ]


def gen_mb_mql_hygiene() -> List[Dict]:
    """MQL field completeness at handoff.

    P-MB-11: April 678/745 = 91.0% complete vs March 73%.
             April 8 form-fill scoring threshold applied to 6 forms.
    """
    return [
        {
            "period": "2026-04",
            "mqls_complete": 678,
            "mqls_total": 745,
            "completeness_pct": round(678 / 745, 4),
            "form_scoring_date": "2026-04-08",
            "forms_updated": 6,
        },
        {
            "period": "2026-03",
            "mqls_complete": None,
            "mqls_total": None,
            "completeness_pct": 0.73,
            "form_scoring_date": None,
            "forms_updated": None,
        },
    ]


def gen_mb_sales_enablement_assets() -> List[Dict]:
    """Sales enablement asset adoption (battlecard + ROI calculator).

    P-MB-12: Battlecard library — April 480 opens from 38 of 47 active reps.
             Competitor A card leads at 162 opens. Refresh shipped April 2.
    P-MB-13: ROI calculator — 22 of 36 active mid-market deals by April 22 (14 days).
             7 deals progressing to proposal. Deal size: $48K with vs $39K without.
    """
    return [
        {
            "asset_type": "battlecard",
            "period": "2026-04",
            "total_opens": 480,
            "unique_reps": 38,
            "total_reps": 47,
            "top_card": "competitor_a",
            "top_card_opens": 162,
            "refresh_date": "2026-04-02",
            "deals_with_asset": None,
            "deals_total_active": None,
            "deals_to_proposal": None,
            "deal_size_with_asset_usd": None,
            "deal_size_without_asset_usd": None,
            "asset_live_date": None,
            "days_since_launch": None,
            "segment": None,
        },
        {
            "asset_type": "roi_calculator",
            "period": "2026-04",
            "total_opens": None,
            "unique_reps": None,
            "total_reps": None,
            "top_card": None,
            "top_card_opens": None,
            "refresh_date": None,
            "deals_with_asset": 22,
            "deals_total_active": 36,
            "deals_to_proposal": 7,
            "deal_size_with_asset_usd": 48000,
            "deal_size_without_asset_usd": 39000,
            "asset_live_date": "2026-04-08",
            "days_since_launch": 14,
            "segment": "mid-market",
        },
    ]


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
    # Phase 2.4 — plant per-customer ARR and Beacon Logistics before any
    # downstream entity generator reads `current_arr` for top-20 ranking.
    plant_customer_arr(rng, companies)
    plant_beacon_logistics(companies)

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

    # Phase 2.4 — Customer Leader entities
    customers_only = [c for c in companies if c["is_customer"]]
    forecast_log = gen_forecast_log()
    renewal_at_risk_log = gen_renewal_at_risk_log(rng, customers_only)
    health_scores = gen_health_scores(rng, customers_only)
    cohorts = gen_cohorts()
    product_adoption = gen_product_adoption(rng, customers_only)
    coverage_tier = gen_coverage_tier(rng, customers_only)
    executive_sponsor = gen_executive_sponsor(rng, customers_only)

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

    # Customer Leader pattern seeders (P-CL-01..15)
    seed_p_cl_01_forecast_accuracy()
    seed_p_cl_02_risk_pool()
    seed_p_cl_05_beacon_renewal(rng, renewals, companies)
    seed_p_cl_03_april_ent_renewals(rng, renewals, executive_sponsor)
    seed_p_cl_04_mm_grr()
    seed_p_cl_06_mm_nrr_lift(product_adoption, companies)
    seed_p_cl_07_multiproduct_nrr(product_adoption)
    seed_p_cl_08_mm_ttfv()
    seed_p_cl_09_cs_sourced_expansion(rng, expansion_opportunities, companies)
    seed_p_cl_10_license_util()
    seed_p_cl_11_health_score_renewal_link(rng, health_scores)
    seed_p_cl_12_cohort_retention()
    seed_p_cl_13_coverage_tier()
    seed_p_cl_14_top20_at_risk(rng, renewal_at_risk_log, executive_sponsor)
    seed_p_cl_15_launch_renewal_link()

    # Marketing Strategist entity generators (Phase 2.8) — all deterministic
    competitive_intel = gen_competitive_intel()
    discovery_calls = gen_discovery_calls()
    icp_analysis = gen_icp_analysis()
    messaging_performance = gen_messaging_performance()
    launch_attribution = gen_launch_attribution()
    launch_enablement = gen_launch_enablement()
    earned_media = gen_earned_media()
    crm_hygiene = gen_crm_hygiene()
    cs_exit_interviews = gen_cs_exit_interviews()

    # Marketing Builder entity generators (Phase 2.11) — all deterministic
    mb_paid_performance = gen_mb_paid_performance()
    mb_mql_sources = gen_mb_mql_sources()
    mb_inbound_demos = gen_mb_inbound_demos()
    mb_seo_keywords = gen_mb_seo_keywords()
    mb_organic_traffic = gen_mb_organic_traffic()
    mb_content_attribution = gen_mb_content_attribution()
    mb_routing_ops = gen_mb_routing_ops()
    mb_attribution_accuracy = gen_mb_attribution_accuracy()
    mb_mql_hygiene = gen_mb_mql_hygiene()
    mb_sales_enablement_assets = gen_mb_sales_enablement_assets()

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

    # Strip internal _beacon tag from companies
    for c in companies:
        c.pop("_beacon", None)

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
        "forecast_log": forecast_log,
        "renewal_at_risk_log": renewal_at_risk_log,
        "health_scores": health_scores,
        "cohorts": cohorts,
        "product_adoption": product_adoption,
        "coverage_tier": coverage_tier,
        "executive_sponsor": executive_sponsor,
        # Marketing Strategist entities (Phase 2.8)
        "competitive_intel": competitive_intel,
        "discovery_calls": discovery_calls,
        "icp_analysis": icp_analysis,
        "messaging_performance": messaging_performance,
        "launch_attribution": launch_attribution,
        "launch_enablement": launch_enablement,
        "earned_media": earned_media,
        "crm_hygiene": crm_hygiene,
        "cs_exit_interviews": cs_exit_interviews,
        # Marketing Builder entities (Phase 2.11)
        "mb_paid_performance": mb_paid_performance,
        "mb_mql_sources": mb_mql_sources,
        "mb_inbound_demos": mb_inbound_demos,
        "mb_seo_keywords": mb_seo_keywords,
        "mb_organic_traffic": mb_organic_traffic,
        "mb_content_attribution": mb_content_attribution,
        "mb_routing_ops": mb_routing_ops,
        "mb_attribution_accuracy": mb_attribution_accuracy,
        "mb_mql_hygiene": mb_mql_hygiene,
        "mb_sales_enablement_assets": mb_sales_enablement_assets,
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


def validate_customer(ds: Dict[str, List[Dict]]) -> List[CheckResult]:
    """15 Customer Leader pattern checks (P-CL-01..P-CL-15)."""
    results: List[CheckResult] = []
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

    # P-CL-01 — Q2_2026 forecast within 1.7% of plan on $1.8M renewing book
    q2_all = next((r for r in forecast_log if r["quarter"] == "Q2_2026" and r["segment"] == "all"), None)
    passed = bool(q2_all) and q2_all["renewing_book_arr"] == 1_800_000 and _in_range(q2_all["variance_pct"], 0.013, 0.022)
    results.append(CheckResult(0, "Q2 forecast on $1.8M renewing book", "p_cl_01_forecast_accuracy", passed,
                               f"Q2 all={q2_all}"))

    # P-CL-02 — Apr risk pool $220K, Mar $310K, top-20 movement
    mar = [r for r in risk_log if r["snapshot_month"] == "2026-03"]
    apr = [r for r in risk_log if r["snapshot_month"] == "2026-04"]
    mar_total = sum(r["arr_at_risk"] for r in mar)
    apr_total = sum(r["arr_at_risk"] for r in apr)
    mar_top20 = {r["company_id"] for r in mar if r["in_top_20_arr"]}
    apr_top20 = {r["company_id"] for r in apr if r["in_top_20_arr"]}
    passed = (
        _in_range(mar_total, 290_000, 330_000)
        and _in_range(apr_total, 200_000, 240_000)
        and len(mar_top20) >= 5
        and len(apr_top20) >= 2
    )
    results.append(CheckResult(1, "At-risk pool drop with top-20 movement", "p_cl_02_risk_pool", passed,
                               f"Mar=${mar_total:,} top20={len(mar_top20)}; Apr=${apr_total:,} top20={len(apr_top20)}"))

    # P-CL-03 — 3 enterprise renewals signed in April with sponsor depth_change=deepened
    apr_ent = [r for r in renewals if r["segment"] == "enterprise"
               and r.get("renewal_signed_date", "").startswith("2026-04")]
    deepened = [r for r in apr_ent
                if sponsor_by_co.get(r["company_id"], {}).get("depth_change_q1_2026") == "deepened"]
    passed = len(deepened) >= 3
    results.append(CheckResult(2, "April ENT renewals with deepened sponsor", "p_cl_03_april_ent_renewals", passed,
                               f"Apr ENT signed={len(apr_ent)}; deepened={len(deepened)}"))

    # P-CL-04 — Q2 MM GRR 91%
    q2_mm = next((r for r in forecast_log if r["quarter"] == "Q2_2026" and r["segment"] == "mid-market"), None)
    passed = bool(q2_mm) and _in_range(q2_mm["grr"], 0.89, 0.93)
    results.append(CheckResult(3, "Q2 MM GRR 91%", "p_cl_04_mm_grr", passed,
                               f"Q2 MM={q2_mm}"))

    # P-CL-05 — Beacon Logistics renewal: signed 4/21, originally 7/15, $280K
    beacon = next((c for c in companies if c.get("name") == "Beacon Logistics"), None)
    beacon_renewal = next((r for r in renewals
                           if beacon and r["company_id"] == beacon["id"]
                           and r.get("original_renewal_date") == "2026-07-15"), None)
    passed = (
        bool(beacon)
        and bool(beacon_renewal)
        and beacon_renewal["renewal_signed_date"] == "2026-04-21"
        and beacon_renewal["renewed_arr"] == 280_000
    )
    results.append(CheckResult(4, "Beacon Logistics renewal signed early", "p_cl_05_beacon_renewal", passed,
                               f"beacon={beacon['id'] if beacon else None}; renewal={beacon_renewal}"))

    # P-CL-06 — Q2 MM NRR 1.12, trailing ~1.05, 18 of 24 Atlas Insights MM expanded
    q2_mm_ren = [r for r in renewals if r["quarter"] == "Q2_2026" and r["segment"] == "mid-market"]
    q2_mm_nrr = q2_mm_ren[0]["nrr"] if q2_mm_ren else 0
    trailing_qs = ["Q1_2026", "Q4_2025", "Q3_2025"]
    trailing_nrrs = [r["nrr"] for r in renewals if r["quarter"] in trailing_qs and r["segment"] == "mid-market"]
    trailing_avg = _mean(trailing_nrrs) if trailing_nrrs else 0
    insights_mm = [r for r in adoption
                   if "atlas-insights" in r["products"]
                   and by_co.get(r["company_id"], {}).get("segment") == "mid-market"]
    expanded = sum(1 for r in insights_mm if r.get("expanded_q2_2026"))
    passed = (
        q2_mm_nrr == 1.12
        and _in_range(trailing_avg, 1.03, 1.07)
        and len(insights_mm) >= 24
        and expanded >= 18
    )
    results.append(CheckResult(5, "Q2 MM NRR lift + Insights expansion", "p_cl_06_mm_nrr_lift", passed,
                               f"Q2 NRR={q2_mm_nrr} trailing={trailing_avg:.3f}; Insights MM={len(insights_mm)} expanded={expanded}"))

    # P-CL-07 — multi-product Q2 NRR 124% vs single 102%
    multi = [r for r in adoption if r["is_multi_product"]]
    single = [r for r in adoption if not r["is_multi_product"]]
    multi_q2 = _mean(r["nrr_q2_2026"] for r in multi) if multi else 0
    single_q2 = _mean(r["nrr_q2_2026"] for r in single) if single else 0
    multi_share = (len(multi) / len(adoption)) if adoption else 0
    passed = (
        _in_range(multi_q2, 1.22, 1.26)
        and _in_range(single_q2, 1.00, 1.04)
        and _in_range(multi_share, 0.34, 0.42)
    )
    results.append(CheckResult(6, "Multi-product NRR gap", "p_cl_07_multiproduct_nrr", passed,
                               f"multi NRR={multi_q2:.3f} single={single_q2:.3f} share={multi_share:.2%}"))

    # P-CL-08 — Q2 MM TTFV 23d vs Q1 MM 38d
    mm_q2 = next((c for c in cohorts if c["cohort_quarter"] == "Q2_2026" and c["segment"] == "mid-market"), None)
    mm_q1 = next((c for c in cohorts if c["cohort_quarter"] == "Q1_2026" and c["segment"] == "mid-market"), None)
    passed = (
        bool(mm_q2) and bool(mm_q1)
        and _in_range(mm_q2["ttfv_days"], 21, 25)
        and _in_range(mm_q1["ttfv_days"], 36, 40)
        and (mm_q1["renewal_rate_under_30d_ttfv"] - mm_q1["renewal_rate_over_60d_ttfv"]) >= 0.15
    )
    results.append(CheckResult(7, "MM TTFV Q2 vs Q1", "p_cl_08_mm_ttfv", passed,
                               f"Q2 MM TTFV={mm_q2['ttfv_days'] if mm_q2 else None}; Q1 MM TTFV={mm_q1['ttfv_days'] if mm_q1 else None}"))

    # P-CL-09 — 8 CS-sourced this month $340K, prior month CS 5/6 (83%) vs outbound ~41%
    apr_cs = [e for e in expansion
              if e["source"] == "customer_health_review" and e.get("month") == "2026-04"]
    apr_cs_total = sum(e["amount"] for e in apr_cs)
    mar_cs = [e for e in expansion
              if e["source"] == "customer_health_review" and e.get("month") == "2026-03"]
    mar_cs_acc = sum(1 for e in mar_cs if e.get("sales_accepted"))
    mar_cs_rate = (mar_cs_acc / len(mar_cs)) if mar_cs else 0
    mar_ob = [e for e in expansion if e["source"] == "outbound" and e.get("month") == "2026-03"]
    mar_ob_acc = sum(1 for e in mar_ob if e.get("sales_accepted"))
    mar_ob_rate = (mar_ob_acc / len(mar_ob)) if mar_ob else 0
    passed = (
        len(apr_cs) >= 8
        and _in_range(apr_cs_total, 320_000, 360_000)
        and _in_range(mar_cs_rate, 0.78, 0.88)
        and _in_range(mar_ob_rate, 0.36, 0.46)
    )
    results.append(CheckResult(8, "CS-sourced expansion acceptance edge", "p_cl_09_cs_sourced_expansion", passed,
                               f"AprCS n={len(apr_cs)} ${apr_cs_total:,}; MarCS {mar_cs_acc}/{len(mar_cs)}={mar_cs_rate:.2%}; MarOB={mar_ob_rate:.2%}"))

    # P-CL-10 — 22 MM crossed 80% util Q2, 14 in Q1
    mm_adopt = [r for r in adoption if by_co.get(r["company_id"], {}).get("segment") == "mid-market"]
    q2_high = sum(1 for r in mm_adopt if r["license_util_q2_2026"] >= 0.80)
    q1_high = sum(1 for r in mm_adopt if r["license_util_q1_2026"] >= 0.80)
    passed = q2_high == 22 and q1_high == 14
    results.append(CheckResult(9, "MM license util crossings Q2 vs Q1", "p_cl_10_license_util", passed,
                               f"Q2 high={q2_high}; Q1 high={q1_high}"))

    # P-CL-11 — Q2 78% green, Q1 71% green, Q1 green renewed 96%, yellow 73%
    q1_h = [h for h in health if h["quarter"] == "Q1_2026"]
    q2_h = [h for h in health if h["quarter"] == "Q2_2026"]
    q1_green_share = sum(1 for h in q1_h if h["color"] == "green") / len(q1_h) if q1_h else 0
    q2_green_share = sum(1 for h in q2_h if h["color"] == "green") / len(q2_h) if q2_h else 0
    q1_green = [h for h in q1_h if h["color"] == "green"]
    q1_yellow = [h for h in q1_h if h["color"] == "yellow"]
    green_renewed = (sum(1 for h in q1_green if h.get("renewed")) / len(q1_green)) if q1_green else 0
    yellow_renewed = (sum(1 for h in q1_yellow if h.get("renewed")) / len(q1_yellow)) if q1_yellow else 0
    passed = (
        _in_range(q2_green_share, 0.74, 0.82)
        and _in_range(q1_green_share, 0.67, 0.75)
        and _in_range(green_renewed, 0.92, 0.98)
        and _in_range(yellow_renewed, 0.68, 0.78)
    )
    results.append(CheckResult(10, "Health distribution + retention by color", "p_cl_11_health_renewal_link", passed,
                               f"Q2 green={q2_green_share:.2%} Q1 green={q1_green_share:.2%}; green ren={green_renewed:.2%} yellow ren={yellow_renewed:.2%}"))

    # P-CL-12 — Q1 cohort 88% retention, Q4 83%, Q1 TTFV 12d faster than Q4
    q1_all = next((c for c in cohorts if c["cohort_quarter"] == "Q1_2026" and c["segment"] == "all"), None)
    q4_all = next((c for c in cohorts if c["cohort_quarter"] == "Q4_2025" and c["segment"] == "all"), None)
    passed = (
        bool(q1_all) and bool(q4_all)
        and _in_range(q1_all["retention_90d"], 0.86, 0.90)
        and _in_range(q4_all["retention_90d"], 0.81, 0.85)
        and (q4_all["ttfv_days"] - q1_all["ttfv_days"]) >= 10
    )
    results.append(CheckResult(11, "Cohort 90d retention Q1 vs Q4", "p_cl_12_cohort_retention", passed,
                               f"Q1 all={q1_all}; Q4 all={q4_all}"))

    # P-CL-13 — high-touch GRR 96%, tech-touch 82%, gap 14, top 18% by ARR
    high = [r for r in coverage if r["tier"] == "high-touch"]
    tech = [r for r in coverage if r["tier"] == "tech-touch"]
    high_grr = high[0]["grr_q2_2026"] if high else 0
    tech_grr = tech[0]["grr_q2_2026"] if tech else 0
    high_share = (len(high) / len(coverage)) if coverage else 0
    passed = (
        _in_range(high_grr, 0.94, 0.98)
        and _in_range(tech_grr, 0.80, 0.84)
        and (high_grr - tech_grr) >= 0.12
        and _in_range(high_share, 0.16, 0.20)
    )
    results.append(CheckResult(12, "High-touch vs tech-touch GRR", "p_cl_13_coverage_tier", passed,
                               f"high GRR={high_grr:.2%} tech GRR={tech_grr:.2%} high share={high_share:.2%}"))

    # P-CL-14 — 2 top-20 ARR on Apr early-warning + sponsor review in current week
    apr_top20_rows = [r for r in risk_log if r["snapshot_month"] == "2026-04" and r["in_top_20_arr"]]
    cw_start, cw_end = CURRENT_WEEK
    in_cw = 0
    for r in apr_top20_rows:
        s = sponsor_by_co.get(r["company_id"])
        if s and s.get("next_review_date"):
            d = date.fromisoformat(s["next_review_date"])
            if cw_start <= d <= cw_end:
                in_cw += 1
    mar_top20 = sum(1 for r in risk_log if r["snapshot_month"] == "2026-03" and r["in_top_20_arr"])
    passed = len(apr_top20_rows) >= 2 and in_cw >= 2 and mar_top20 >= 5
    results.append(CheckResult(13, "Top-20 at-risk + sponsor review in CW", "p_cl_14_top20_at_risk", passed,
                               f"Apr top20={len(apr_top20_rows)} in CW={in_cw}; Mar top20={mar_top20}"))

    # P-CL-15 — Custom Permissions launch 6/15 + Beacon renewal signed 4/21
    pl = next((p for p in launches if p["id"] == "PL-002"), None)
    beacon_signed = beacon_renewal["renewal_signed_date"] if beacon_renewal else None
    passed = (
        bool(pl)
        and pl["launch_date"] == "2026-06-15"
        and beacon_signed == "2026-04-21"
    )
    results.append(CheckResult(14, "Launch ahead of Beacon renewal", "p_cl_15_launch_renewal_link", passed,
                               f"launch={pl['name'] if pl else None}; beacon signed={beacon_signed}"))

    return results


def validate_marketing_strategist(ds: Dict[str, List[Dict]]) -> List[CheckResult]:
    """15 Marketing Strategist pattern checks (P-MS-01..P-MS-15)."""
    results: List[CheckResult] = []
    ci = ds.get("competitive_intel", [])
    dc = ds.get("discovery_calls", [])
    icp = ds.get("icp_analysis", [])
    mp = ds.get("messaging_performance", [])
    la = ds.get("launch_attribution", [])
    le = ds.get("launch_enablement", [])
    em = ds.get("earned_media", [])
    crm = ds.get("crm_hygiene", [])
    csei = ds.get("cs_exit_interviews", [])

    beacon = next((r for r in ci if r["competitor_id"] == "Beacon Systems" and r["period"] == "Q2_2026"), None)
    northstar = next((r for r in ci if r["competitor_id"] == "Northstar Platform" and r["period"] == "Q2_2026"), None)
    verge = next((r for r in ci if r["competitor_id"] == "Verge IO" and r["period"] == "Q2_2026"), None)

    # P-MS-01: Beacon Systems Q2 h2h: 14 wins, 22 deals, prior 4Q avg 28%
    passed = (
        bool(beacon)
        and beacon["wins"] == 14
        and beacon["h2h_deals"] == 22
        and _in_range(beacon["prior_4q_win_rate"], 0.26, 0.30)
    )
    results.append(CheckResult(0, "Beacon Systems Q2 h2h win rate", "p_ms_01_beacon_winrate", passed,
                               f"wins={beacon['wins'] if beacon else None} deals={beacon['h2h_deals'] if beacon else None}"))

    # P-MS-02: 27 calls sampled, speed_to_value 62%
    dc_apr = next((r for r in dc if r["period"] == "2026-04"), None)
    stv = next((f for f in (dc_apr["frame_results"] if dc_apr else []) if f["frame"] == "speed_to_value"), None)
    passed = (
        bool(dc_apr)
        and dc_apr["calls_sampled"] == 27
        and bool(stv)
        and _in_range(stv["resonance_rate"], 0.60, 0.64)
    )
    results.append(CheckResult(1, "Discovery call speed-to-value resonance", "p_ms_02_discovery_frame", passed,
                               f"sampled={dc_apr['calls_sampled'] if dc_apr else None} stv={stv['resonance_rate'] if stv else None}"))

    # P-MS-03: MM 31%, enterprise 13% on refreshed positioning
    mm_rp = next((r for r in mp if r["frame"] == "refreshed_positioning" and r["segment"] == "mid-market"), None)
    ent_rp = next((r for r in mp if r["frame"] == "refreshed_positioning" and r["segment"] == "enterprise"), None)
    passed = (
        bool(mm_rp) and bool(ent_rp)
        and _in_range(mm_rp["close_rate"], 0.29, 0.33)
        and _in_range(ent_rp["close_rate"], 0.11, 0.15)
    )
    results.append(CheckResult(2, "Refreshed positioning close rate by segment", "p_ms_03_positioning_wr", passed,
                               f"MM={mm_rp['close_rate'] if mm_rp else None} ENT={ent_rp['close_rate'] if ent_rp else None}"))

    # P-MS-04: Q2 28/36 = 78%; Q1 23/36 = 64%; 12d cycle advantage
    q2_icp = next((r for r in icp if r["period"] == "Q2_2026"), None)
    q1_icp = next((r for r in icp if r["period"] == "Q1_2026"), None)
    passed = (
        bool(q2_icp) and bool(q1_icp)
        and q2_icp["icp_matched"] == 28
        and q2_icp["closed_won_total"] == 36
        and q1_icp["icp_matched"] == 23
        and q2_icp["icp_cycle_advantage_days"] == 12
    )
    results.append(CheckResult(3, "ICP match rate Q2 vs Q1", "p_ms_04_icp_match", passed,
                               f"Q2 {q2_icp['icp_matched'] if q2_icp else None}/{q2_icp['closed_won_total'] if q2_icp else None}; Q1 {q1_icp['icp_matched'] if q1_icp else None}"))

    # P-MS-05: Beacon battlecard utilization 38/62 (61%), prior 22%
    passed = (
        bool(beacon)
        and beacon["battlecard_opens"] == 38
        and beacon["total_competitive_opps"] == 62
        and _in_range(beacon["battlecard_util"], 0.60, 0.63)
        and _in_range(beacon["prior_q_battlecard_util"], 0.20, 0.24)
    )
    results.append(CheckResult(4, "Beacon battlecard utilization Q2 vs Q1", "p_ms_05_battlecard_util", passed,
                               f"opens={beacon['battlecard_opens'] if beacon else None} opps={beacon['total_competitive_opps'] if beacon else None}"))

    # P-MS-06: Northstar win rate 42%→51% post Apr-8; Gong mentions -22%
    passed = (
        bool(northstar)
        and northstar["event_date"] == "2026-04-08"
        and _in_range(northstar["win_rate_pre_event"], 0.40, 0.44)
        and _in_range(northstar["win_rate_post_event"], 0.49, 0.53)
        and northstar["gong_mentions_change_pct"] is not None
        and northstar["gong_mentions_change_pct"] < 0
    )
    results.append(CheckResult(5, "Northstar objection section win rate lift", "p_ms_06_northstar_objection", passed,
                               f"pre={northstar['win_rate_pre_event'] if northstar else None} post={northstar['win_rate_post_event'] if northstar else None}"))

    # P-MS-07: Verge IO 18/75 opps (24%), prior 11%, Series B $40M Mar 14
    passed = (
        bool(verge)
        and verge["h2h_deals"] == 18
        and verge["total_competitive_opps"] == 75
        and _in_range(verge["appearance_pct"], 0.23, 0.25)
        and _in_range(verge["prior_q_appearance_pct"], 0.09, 0.13)
        and verge["series_b_date"] == "2026-03-14"
        and verge["series_b_amount_m"] == 40
    )
    results.append(CheckResult(6, "Verge IO emergence + Series B", "p_ms_07_verge_emergence", passed,
                               f"appearances={verge['h2h_deals'] if verge else None}/{verge['total_competitive_opps'] if verge else None} series_b={verge['series_b_date'] if verge else None}"))

    # P-MS-08: Outcome reason capture 47/51 = 92%, Q1 71%
    q2_crm = next((r for r in crm if r["period"] == "Q2_2026"), None)
    q1_crm = next((r for r in crm if r["period"] == "Q1_2026"), None)
    passed = (
        bool(q2_crm) and bool(q1_crm)
        and q2_crm["outcome_reason_captured"] == 47
        and q2_crm["closed_deals_total"] == 51
        and _in_range(q2_crm["capture_rate"], 0.90, 0.94)
        and _in_range(q1_crm["capture_rate"], 0.69, 0.73)
    )
    results.append(CheckResult(7, "Outcome reason capture rate Q2 vs Q1", "p_ms_08_outcome_capture", passed,
                               f"Q2 {q2_crm['outcome_reason_captured'] if q2_crm else None}/{q2_crm['closed_deals_total'] if q2_crm else None}; Q1 rate={q1_crm['capture_rate'] if q1_crm else None}"))

    # P-MS-09: Apr-8 launch $420K / 14 opps; prior $310K
    la_apr8 = next((r for r in la if r["launch_id"] == "PL-MS-001" and r["attribution_window"] == "3_weeks"), None)
    la_prior = next((r for r in la if r["launch_id"] == "PL-000" and r["attribution_window"] == "3_weeks"), None)
    passed = (
        bool(la_apr8)
        and la_apr8["opportunities_created"] == 14
        and la_apr8["pipeline_usd"] == 420_000
        and bool(la_prior)
        and la_prior["pipeline_usd"] == 310_000
    )
    results.append(CheckResult(8, "April 8 launch pipeline vs prior", "p_ms_09_launch_pipeline", passed,
                               f"apr8 opps={la_apr8['opportunities_created'] if la_apr8 else None} ${la_apr8['pipeline_usd'] if la_apr8 else None:,}"))

    # P-MS-10: May-15 launch 3/3 items cleared 10 days before
    le_may15 = next((r for r in le if r["launch_id"] == "PL-MS-002"), None)
    passed = (
        bool(le_may15)
        and le_may15["readiness_items_cleared"] == 3
        and le_may15["readiness_items_count"] == 3
        and le_may15["days_cleared_before_launch"] == 10
    )
    results.append(CheckResult(9, "May-15 launch readiness 3/3 cleared 10 days prior", "p_ms_10_launch_readiness", passed,
                               f"cleared={le_may15['readiness_items_cleared'] if le_may15 else None}/{le_may15['readiness_items_count'] if le_may15 else None} days={le_may15['days_cleared_before_launch'] if le_may15 else None}"))

    # P-MS-11: Apr-8 launch asset adoption 27/38 (71%), prior 42%, 2.4x multiple
    le_apr8 = next((r for r in le if r["launch_id"] == "PL-MS-001"), None)
    passed = (
        bool(le_apr8)
        and le_apr8["reps_opened_assets_14d"] == 27
        and le_apr8["reps_total"] == 38
        and _in_range(le_apr8["asset_adoption_rate_14d"], 0.69, 0.73)
        and _in_range(le_apr8["prior_launch_asset_adoption_rate"], 0.40, 0.44)
        and le_apr8["pipeline_by_asset_openers_vs_nonopeners_multiple"] == 2.4
    )
    results.append(CheckResult(10, "Apr-8 launch enablement asset adoption", "p_ms_11_asset_adoption", passed,
                               f"reps={le_apr8['reps_opened_assets_14d'] if le_apr8 else None}/{le_apr8['reps_total'] if le_apr8 else None}"))

    # P-MS-12: Enterprise inbound new-positioning-hook pipeline $290K
    ent_hook = next((r for r in mp if r["frame"] == "new_positioning_hook" and r["segment"] == "enterprise"), None)
    passed = (
        bool(ent_hook)
        and ent_hook["pipeline_usd"] == 290_000
        and ent_hook["inbound_conversion_lift_pct"] == 8
    )
    results.append(CheckResult(11, "Enterprise inbound new-positioning pipeline", "p_ms_12_positioning_pipeline", passed,
                               f"pipeline=${ent_hook['pipeline_usd'] if ent_hook else None:,} lift={ent_hook['inbound_conversion_lift_pct'] if ent_hook else None}%"))

    # P-MS-13: Q2 launch-attributable $620K of $3.4M net new (18%)
    la_q2 = next((r for r in la if r.get("period") == "Q2_2026" and r["attribution_window"] == "quarter"), None)
    passed = (
        bool(la_q2)
        and la_q2["pipeline_usd"] == 620_000
        and la_q2["total_period_pipeline_usd"] == 3_400_000
        and _in_range(la_q2["launch_share_pct"], 0.17, 0.19)
    )
    results.append(CheckResult(12, "Q2 launch-attributable pipeline share", "p_ms_13_launch_share", passed,
                               f"launch=${la_q2['pipeline_usd'] if la_q2 else None:,} total=${la_q2['total_period_pipeline_usd'] if la_q2 else None:,}"))

    # P-MS-14: April CS exit interviews: 14, 6 themes, 2 feeding positioning, Beacon 31%
    cs_apr = next((r for r in csei if r["period"] == "2026-04"), None)
    passed = (
        bool(cs_apr)
        and cs_apr["interviews_conducted"] == 14
        and cs_apr["themes_identified"] == 6
        and cs_apr["themes_feeding_positioning"] == 2
        and _in_range(cs_apr["competitor_a_overlap_pct"], 0.29, 0.33)
    )
    results.append(CheckResult(13, "CS exit interview themes feeding positioning", "p_ms_14_exit_interviews", passed,
                               f"interviews={cs_apr['interviews_conducted'] if cs_apr else None} themes={cs_apr['themes_identified'] if cs_apr else None} positioning={cs_apr['themes_feeding_positioning'] if cs_apr else None}"))

    # P-MS-15: Apr-8 launch 22/53 earned media (41%), prior 28%
    em_apr8 = next((r for r in em if r["launch_id"] == "PL-MS-001"), None)
    passed = (
        bool(em_apr8)
        and em_apr8["publications_picked_up"] == 22
        and em_apr8["publications_outreached"] == 53
        and _in_range(em_apr8["pickup_rate"], 0.40, 0.43)
        and _in_range(em_apr8["prior_launch_pickup_rate"], 0.26, 0.30)
    )
    results.append(CheckResult(14, "Earned media pickup rate April launch", "p_ms_15_earned_media", passed,
                               f"pickup={em_apr8['publications_picked_up'] if em_apr8 else None}/{em_apr8['publications_outreached'] if em_apr8 else None}"))

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


# HubSpot lifecycle stage value map (Atlas → HubSpot internal name)
_HS_LIFECYCLE = {
    "subscriber": "subscriber",
    "lead": "lead",
    "mql": "marketingqualifiedlead",
    "sql": "salesqualifiedlead",
    "opportunity": "opportunity",
    "customer": "customer",
}


def write_hubspot_csv(ds: Dict[str, List[Dict]], outdir: Path) -> None:
    """Write HubSpot-import-compatible CSVs for Companies, Contacts, Deals, and Notes.

    Column names match HubSpot's standard import template headers. Lifecycle stage
    values are mapped to HubSpot internal names. Company name lookups replace
    Atlas internal IDs for association columns.

    Gaps not patchable here (documented):
      - companies: Domain Name, Website URL, City, State, Country, Phone — no source data
      - contacts: Phone number — no source data
      - deals: Associated contact email — deals link to companies, not contacts, in Atlas
    """
    outdir.mkdir(parents=True, exist_ok=True)

    # Build lookup dicts
    company_by_id: Dict[str, Dict] = {c["id"]: c for c in ds.get("companies", [])}
    contact_by_id: Dict[str, Dict] = {c["id"]: c for c in ds.get("contacts", [])}

    # ── Companies ────────────────────────────────────────────────────────────
    company_rows = []
    for c in ds.get("companies", []):
        company_rows.append({
            "Company name": c["name"],
            "Lifecycle Stage": _HS_LIFECYCLE.get(c.get("lifecycle_stage", ""), c.get("lifecycle_stage", "")),
            "Industry": c.get("industry", ""),
            "Number of Employees": c.get("employees", ""),
            "Annual Revenue": c.get("current_arr", ""),
            "Create Date": c.get("created_date", ""),
            "External ID": c["id"],
            "Atlas Segment": c.get("segment", ""),
            "ABM Target": c.get("is_target_account", ""),
            "ABM List Name": c.get("target_list_name", ""),
            "Tech Stack": ";".join(c["tech_stack"]) if isinstance(c.get("tech_stack"), list) else c.get("tech_stack", ""),
        })
    _write_csv_rows(outdir / "hubspot_companies.csv", company_rows)

    # ── Contacts ─────────────────────────────────────────────────────────────
    contact_rows = []
    for c in ds.get("contacts", []):
        co = company_by_id.get(c.get("company_id", ""), {})
        contact_rows.append({
            "First name": c.get("first_name", ""),
            "Last name": c.get("last_name", ""),
            "Email": c.get("email", ""),
            "Job title": c.get("title", ""),
            "Lifecycle stage": _HS_LIFECYCLE.get(c.get("lifecycle_stage", ""), c.get("lifecycle_stage", "")),
            "Associated Company": co.get("name", ""),
            "Create Date": c.get("created_date", ""),
            "External ID": c["id"],
            "Atlas Role Category": c.get("role_category", ""),
            "ABM Target": c.get("is_abm", ""),
            "SQL Date": c.get("became_sql_date", ""),
            "SQL Accepted": c.get("sql_accepted", ""),
        })
    _write_csv_rows(outdir / "hubspot_contacts.csv", contact_rows)

    # ── Deals ────────────────────────────────────────────────────────────────
    deal_rows = []
    for d in ds.get("deals", []):
        co = company_by_id.get(d.get("company_id", ""), {})
        co_name = co.get("name", "")
        deal_rows.append({
            "Deal name": f"{co_name} – {d['id']}",
            "Deal stage": d.get("stage", ""),
            "Pipeline": "default",
            "Amount": d.get("amount", ""),
            "Close date": d.get("close_date", ""),
            "Associated company": co_name,
            "Create Date": d.get("create_date", ""),
            "External ID": d["id"],
            "Lead source": d.get("lead_source", ""),
            "Atlas Segment": d.get("segment", ""),
            "Competitive Deal": d.get("head_to_head", ""),
            "Competitor": d.get("competitor_id", ""),
            "Time in Proposal (days)": d.get("time_in_proposal", ""),
            "Contract Revisions": d.get("contract_revisions", ""),
            "Procurement Cleared Date": d.get("procurement_cleared_date", ""),
            "Procurement Signoff": d.get("procurement_signoff", ""),
            "Campaign Source": d.get("campaign_source_id", ""),
        })
    _write_csv_rows(outdir / "hubspot_deals.csv", deal_rows)

    # ── Notes (from engagement_events) ───────────────────────────────────────
    # HubSpot CSV import for activities supports Notes: "Note body", "Activity date",
    # "Associated contact email". Engagement events are mapped to Notes as the closest
    # CSV-importable equivalent. High-intent events (demo_request, form_fill,
    # pricing_page_view) are included; low-signal events (page_view, ad_click) are skipped.
    high_intent_event_types = {"demo_request", "form_fill", "pricing_page_view", "content_download"}
    note_rows = []
    for ev in ds.get("engagement_events", []):
        if ev.get("event_type") not in high_intent_event_types:
            continue
        ct = contact_by_id.get(ev.get("contact_id", ""), {})
        co = company_by_id.get(ev.get("company_id", ""), {})
        note_rows.append({
            "Note body": f"Event: {ev['event_type']} | Intent: {ev.get('intent_level', '')} | Company: {co.get('name', '')}",
            "Activity date": ev.get("date", ""),
            "Associated contact email": ct.get("email", ""),
            "Associated company": co.get("name", ""),
        })
    _write_csv_rows(outdir / "hubspot_notes.csv", note_rows)

    print(f"HubSpot CSV export: {len(company_rows)} companies, {len(contact_rows)} contacts, "
          f"{len(deal_rows)} deals, {len(note_rows)} notes (filtered from {len(ds.get('engagement_events', []))} events)")


def _write_csv_rows(path: Path, rows: List[Dict]) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate Atlas SaaS synthetic dataset for Stage 1 Relevance Engine eval.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42).")
    parser.add_argument("--format", choices=["json", "csv", "hubspot"], default="json",
                        help="Output format. 'hubspot' writes HubSpot-import-compatible CSVs.")
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
        elif args.format == "hubspot":
            write_hubspot_csv(ds, outdir)
        else:
            write_csv(ds, outdir)

    # Row-count summary
    print(f"Generated {len(ds)} entities into {outdir}:")
    for name, rows in ds.items():
        print(f"  {name:30s} {len(rows):6d} rows")

    # Run validation — Marketing (15) + Revenue (15) + Customer (15) = 45 total
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

    cust_results = validate_customer(ds)
    print("\nCustomer Leader validation (15 card patterns):")
    cust_passed = 0
    for r in sorted(cust_results, key=lambda x: x.card_idx):
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] card {r.card_idx:2d}  {r.pattern:38s}  {r.detail}")
        if r.passed:
            cust_passed += 1
    print(f"  -> {cust_passed}/{len(cust_results)} customer checks passed.")

    ms_results = validate_marketing_strategist(ds)
    print("\nMarketing Strategist validation (15 card patterns):")
    ms_passed = 0
    for r in sorted(ms_results, key=lambda x: x.card_idx):
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] card {r.card_idx:2d}  {r.pattern:40s}  {r.detail}")
        if r.passed:
            ms_passed += 1
    print(f"  -> {ms_passed}/{len(ms_results)} marketing strategist checks passed.")

    total_passed = mkt_passed + rev_passed + cust_passed + ms_passed
    total = len(mkt_results) + len(rev_results) + len(cust_results) + len(ms_results)
    print(f"\nTOTAL: {total_passed}/{total} pattern checks passed.")
    sys.exit(0 if total_passed == total else 1)


if __name__ == "__main__":
    main()
