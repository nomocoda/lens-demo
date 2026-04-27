#!/usr/bin/env python3
"""OrgForge adapter for Lens Relevance Engine eval (Phase 4 spike).

Reads from the pre-generated OrgForge dataset on HuggingFace
(aeriesec/orgforge — Apex Athletics, ~22.5k events over ~905 days)
and returns the same Dict[str, list] Atlas-shape contract that
load_dataset() returns from local JSON files.

Selected via --source orgforge in relevance_engine.py.

Contract differences vs synthetic Atlas / HubSpot adapters:

  Apex Athletics is a fictional sports/fitness wearables company. The
  OrgForge corpus is rich in CRM/conversational signals (sf_opp,
  crm_touchpoint, customer emails, vendor emails, sales_outbound_email)
  but does NOT contain marketing breadth (no campaigns, no ad-spend
  budget, no web analytics, no analyst mentions). Same gap class as
  Phase 3.5 found with HubSpot CRM-only.

  Implication: archetypes calibrated against marketing breadth
  (Marketing Leader, Marketing Strategist, Marketing Builder) will
  produce thin output here. The right archetypes for OrgForge data
  shape are revenue_operator, revenue_generator, revenue_developer,
  customer_advocate, customer_operator, customer_technician — anything
  that grounds on CRM + conversational signals.

  Default test archetype for the spike: revenue_operator.

Required deps: pandas, pyarrow.
Required path: ../../../orgforge-data/corpus/corpus-00000.parquet
  (clone with: git clone https://huggingface.co/datasets/aeriesec/orgforge
   from ~/Documents/Business/NomoCoda/Code/, then `git lfs pull`)
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


# OrgForge dataset path relative to this file: lens-demo/scripts/eval/
DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[3]
    / "orgforge-data"
    / "corpus"
    / "corpus-00000.parquet"
)


# ---------------------------------------------------------------------------
# Helpers


def _parse_json_field(value: Any) -> Any:
    """OrgForge stores JSON as a string in some fields; parse defensively."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _slug(name: str) -> str:
    return "".join(c.lower() for c in name if c.isalnum() or c == "-")[:32] or "x"


def _email_for(actor: str, account: str | None = None) -> str:
    domain = _slug(account) + ".com" if account else "apexathletics.com"
    return f"{_slug(actor)}@{domain}"


def _stage_to_atlas(orgforge_stage: str | None) -> str:
    """Map OrgForge / Salesforce-style stages to Atlas 'stage' values."""
    if not orgforge_stage:
        return "qualifiedtobuy"
    s = orgforge_stage.lower()
    if "value proposition" in s or "qualif" in s:
        return "qualifiedtobuy"
    if "needs analysis" in s or "discovery" in s:
        return "discovery"
    if "proposal" in s or "negotiation" in s:
        return "proposal"
    if "closed won" in s or "won" in s:
        return "closedwon"
    if "closed lost" in s or "lost" in s:
        return "closedlost"
    return "qualifiedtobuy"


# ---------------------------------------------------------------------------
# Main loader


def load_orgforge_dataset(
    corpus_path: Path | None = None,
    cutoff_date: str | None = None,
) -> Dict[str, list]:
    """Load OrgForge corpus parquet and reshape to Atlas Dict[str, list].

    Args:
        corpus_path: path to OrgForge corpus parquet. Defaults to the cloned
            HuggingFace dataset location.
        cutoff_date: ISO date string. If provided, only include events up to
            this date. Useful for "current snapshot" queries (default: latest).

    Returns:
        Dict[str, list] matching the load_dataset() contract from
        relevance_engine.py. Required entities are populated from OrgForge
        events; entities OrgForge can't supply (campaigns, web_analytics,
        etc.) are returned as empty lists.
    """
    path = corpus_path or DEFAULT_CORPUS_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"OrgForge corpus not found at {path}. "
            "Clone it: git clone https://huggingface.co/datasets/aeriesec/orgforge "
            "into ~/Documents/Business/NomoCoda/Code/orgforge-data/, then `git lfs pull`."
        )

    df = pd.read_parquet(path)

    # Parse JSON fields lazily (the corpus stores them stringified)
    df["facts_obj"] = df["facts"].apply(_parse_json_field)
    df["actors_list"] = df["actors"].apply(_parse_json_field)

    if cutoff_date:
        df = df[df["date"] <= cutoff_date]

    # ---- Build Atlas entities ----

    # 1. companies: unique accounts from crm_touchpoint + customer emails + sf_opp
    accounts: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        facts = row["facts_obj"] or {}
        account_name = facts.get("account_name") or facts.get("customer_account")
        if not account_name:
            continue
        if account_name not in accounts:
            accounts[account_name] = {
                "id": f"CO-{len(accounts) + 1:05d}",
                "name": account_name,
                "segment": "enterprise",
                "industry": "sports_and_fitness",
                "employees": 500,
                "tech_stack": ["Salesforce", "Slack"],
                "is_customer": True,
                "is_target_account": False,
                "target_list_name": None,
                "created_date": str(row["date"])[:10] if row["date"] else "2025-01-01",
                "lifecycle_stage": "customer",
                "current_arr": 250000,
            }
    companies: List[Dict[str, Any]] = list(accounts.values())

    # 2. contacts: unique actors that interacted with accounts
    contacts: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        facts = row["facts_obj"] or {}
        actor = facts.get("sender") or facts.get("contact_name")
        account_name = facts.get("account_name")
        if not actor or not account_name or account_name not in accounts:
            continue
        contact_key = f"{actor}|{account_name}"
        if contact_key not in contacts:
            first, *rest = actor.split(" ", 1)
            contacts[contact_key] = {
                "id": f"CT-{len(contacts) + 1:06d}",
                "company_id": accounts[account_name]["id"],
                "first_name": first,
                "last_name": rest[0] if rest else "",
                "email": _email_for(actor, account_name),
                "title": "Account Contact",
                "role_category": "buyer",
                "created_date": str(row["date"])[:10] if row["date"] else "2025-01-01",
                "lifecycle_stage": "customer",
                "became_sql_date": None,
                "is_abm": False,
                "sql_accepted": True,
            }
    contacts_list: List[Dict[str, Any]] = list(contacts.values())

    # 3. deals: derive from sf_opp + crm_touchpoint events
    deal_rows = df[df["doc_type"].isin(["sf_opp", "crm_touchpoint"])]
    deals_by_id: Dict[str, Dict[str, Any]] = {}
    for _, row in deal_rows.iterrows():
        facts = row["facts_obj"] or {}
        opp_id = facts.get("opportunity_id") or facts.get("opp_id")
        account_name = facts.get("account_name")
        if not opp_id or not account_name or account_name not in accounts:
            continue
        # Track latest stage observed per opp
        existing = deals_by_id.get(opp_id)
        date_str = str(row["date"])[:10] if row["date"] else "2026-01-01"
        if not existing:
            deals_by_id[opp_id] = {
                "id": f"DL-{len(deals_by_id) + 1:05d}",
                "company_id": accounts[account_name]["id"],
                "amount": 75000,
                "stage": _stage_to_atlas(facts.get("stage")),
                "create_date": date_str,
                "close_date": date_str,
                "is_closed": _stage_to_atlas(facts.get("stage")).startswith("closed"),
                "is_won": _stage_to_atlas(facts.get("stage")) == "closedwon",
                "lead_source": "outbound",
                "campaign_source_id": None,
                "segment": "enterprise",
                "time_in_proposal": 14,
                "competitor_id": None,
                "head_to_head": False,
                "contract_revisions": False,
                "procurement_signoff": False,
                "stage_change_history": [],
            }
        else:
            new_stage = _stage_to_atlas(facts.get("stage"))
            if new_stage != existing["stage"]:
                existing["stage_change_history"].append(
                    {"from": existing["stage"], "to": new_stage, "date": date_str}
                )
                existing["stage"] = new_stage
                existing["is_closed"] = new_stage.startswith("closed")
                existing["is_won"] = new_stage == "closedwon"
                existing["close_date"] = date_str
    deals: List[Dict[str, Any]] = list(deals_by_id.values())

    # 4. engagement_events: customer/vendor emails, outbound sales touches
    event_doc_types = {
        "customer_email_routed": "email_open",
        "customer_reply_sent": "email_reply",
        "inbound_external_email": "email_inbound",
        "vendor_email_routed": "email_open",
        "vendor_ack_sent": "email_reply",
        "sales_outbound_email": "email_outbound",
        "proactive_outreach_initiated": "email_outbound",
        "crm_touchpoint": "page_view",
    }
    engagement: List[Dict[str, Any]] = []
    event_rows = df[df["doc_type"].isin(event_doc_types.keys())]
    for _, row in event_rows.iterrows():
        facts = row["facts_obj"] or {}
        account_name = facts.get("account_name") or facts.get("customer_account")
        if not account_name or account_name not in accounts:
            continue
        sender = facts.get("sender") or facts.get("contact_name") or "unknown"
        contact_key = f"{sender}|{account_name}"
        contact_id = contacts.get(contact_key, {}).get("id")
        engagement.append(
            {
                "company_id": accounts[account_name]["id"],
                "contact_id": contact_id,
                "date": str(row["date"])[:10] if row["date"] else "2026-01-01",
                "event_type": event_doc_types[row["doc_type"]],
                "intent_level": "medium",
            }
        )

    # ---- Assemble final dataset ----

    data: Dict[str, list] = {
        "companies": companies,
        "contacts": contacts_list,
        "deals": deals,
        "campaigns": [],
        "campaign_performance": [],
        "budget": [],
        "actual_spend": [],
        "engagement_events": engagement,
        "branded_search": [],
        "web_analytics": [],
        "mentions": [],
        "competitors": [],
        "analyst_mentions": [],
        "customer_reference_optins": [],
        "product_launches": [],
        "sdr_capacity": [],
        # all optional entities default to []
    }
    return data


def main():
    """CLI: print summary of what the adapter produces."""
    ds = load_orgforge_dataset()
    print(f"OrgForge → Atlas adapter output:")
    for entity, rows in ds.items():
        marker = "  ✓" if rows else "  ·"
        print(f"{marker} {entity:32s} {len(rows):>5} rows")


if __name__ == "__main__":
    main()
