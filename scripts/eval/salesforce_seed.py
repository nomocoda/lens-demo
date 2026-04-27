#!/usr/bin/env python3
"""Salesforce programmatic import via Composio native actions (Phase 3.6).

Mirror of hubspot_seed.py for the Salesforce side of the v1 plumbing test.
Reads the Atlas SaaS synthetic dataset from scripts/eval/output/ (seed 42 by
default) and creates these records in a Salesforce Developer Edition org via
Composio's OAuth connection:

  Accounts        : 800 rows  (Atlas companies)
  Contacts        : 3000 rows
  Opportunities   : 600 rows  (Atlas deals)

Tasks (engagement events) are deferred — they're 10k records, single-record
write API, and the engine derives the same intent signal from Opportunity +
Contact lifecycle anyway. Add later if a Revenue/Marketing archetype needs
them.

Architecture decision (2026-04-27):
  Composio's v3 raw proxy returns "URL_NOT_RESET" for Salesforce connections —
  the proxy doesn't auto-route to the org's instance URL. Native actions DO
  resolve the instance URL server-side. So this script uses Composio's native
  actions (POST /v2/actions/<NAME>/execute) and parallelizes with a thread
  pool to absorb the per-record overhead.

  Custom fields via the Tooling API are not reachable through Composio either,
  so Atlas-specific metadata is encoded in standard fields:

    Account.AccountNumber = <atlas_id>           (8 chars in 40-char field)
    Account.Description   = json({atlas metadata})

    Contact.Description   = json({atlas_id, role, lifecycle, sql_date, ...})
    (Contact.AccountId set from Atlas company_id → SFDC Account.Id map)

    Opportunity.Description = json({atlas_id, lead_source, lifecycle, ...})
    Opportunity.StageName mapped from Atlas stage to SFDC standard picklist
    (Opportunity.AccountId set from same map)

  Idempotency: query Atlas-tagged records once at start (AccountNumber LIKE
  for Account, Description LIKE for Contact/Opportunity). Skip records whose
  atlas_id already exists.

Required env vars (in .env or environment):
  COMPOSIO_API_KEY        from app.composio.dev/settings -> API Keys tab
  SALESFORCE_ENTITY_ID    optional override; else picks first ACTIVE SFDC connection

Active connection (Phase 3.6, 2026-04-27):
  Auth Config : salesforce-pydufo (ID ac_vmmBh56iROnk)
  Entity      : travis@playful-narwhal-1dxk34.com (Developer Edition trial)
  Auth        : OAuth2, Managed by Composio
  Status      : Active

Usage:
  python3 scripts/eval/salesforce_seed.py                  # full run (seed 42)
  python3 scripts/eval/salesforce_seed.py --dry-run        # show counts, no writes
  python3 scripts/eval/salesforce_seed.py --status         # show SFDC record counts
  python3 scripts/eval/salesforce_seed.py --limit N        # import only first N per entity
  python3 scripts/eval/salesforce_seed.py --workers N      # parallelism (default 8)
  python3 scripts/eval/salesforce_seed.py --wipe-atlas     # delete existing Atlas-tagged records first
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = ROOT / "scripts" / "eval"

_COMPOSIO_BASE = "https://backend.composio.dev/api"
_CONNECTED_ACCOUNTS_URL = f"{_COMPOSIO_BASE}/v1/connectedAccounts"
_ACTION_EXEC_URL = f"{_COMPOSIO_BASE}/v2/actions/{{action}}/execute"

_DESC_PREFIX = "ATLAS_JSON:"  # marker for the JSON-encoded atlas metadata in Description

# Account.Description is a textarea (NOT filterable in SOQL), so the atlas_id
# anchor lives in a queryable text field per SObject. Adapter + idempotency
# lookup use these fields:
_ATLAS_ID_FIELD: Dict[str, str] = {
    "Account": "SicDesc",         # standard 40-char text, exposed as 'sic_desc' input
    "Contact": "Department",      # standard 80-char text, 'department' input
    "Opportunity": "NextStep",    # standard 255-char text, 'next_step' input
}
_ATLAS_ID_INPUT: Dict[str, str] = {
    "Account": "sic_desc",
    "Contact": "department",
    "Opportunity": "next_step",
}
# Atlas ID prefix per SObject — used in LIKE queries for idempotency
_ATLAS_ID_PREFIX: Dict[str, str] = {
    "Account": "CO-",
    "Contact": "CT-",
    "Opportunity": "DL-",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env_key(name: str) -> Optional[str]:
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _load_dataset(seed: int) -> Dict[str, list]:
    output_dir = EVAL_DIR / "output"
    dataset_path = output_dir / "companies.json"
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Dataset not found at {output_dir}. "
            f"Run: python3 scripts/eval/generate_dataset.py --seed {seed} --output scripts/eval/output"
        )
    entities = ["companies", "contacts", "deals", "engagement_events"]
    return {e: json.loads((output_dir / f"{e}.json").read_text()) for e in entities}


def _atlas_desc(atlas_id: str, payload: dict) -> str:
    """Encode atlas_id + metadata into a Description string the adapter can parse.

    Format: 'ATLAS_JSON:{json}\\n\\n<optional human description>'
    Adapter splits on the first newline, parses everything after the prefix on
    line 1 as JSON.
    """
    obj = {"id": atlas_id, **payload}
    return f"{_DESC_PREFIX}{json.dumps(obj, separators=(',', ':'))}"


# ---------------------------------------------------------------------------
# Composio client (native actions only)
# ---------------------------------------------------------------------------

class _Client:
    def __init__(self, api_key: str, entity_id: Optional[str] = None) -> None:
        self._api_key = api_key
        self._entity_id = entity_id
        self._conn_id: Optional[str] = None
        self._conn_lock = Lock()

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "curl/7.88.1",
        }

    def get_connection_id(self) -> str:
        if self._conn_id:
            return self._conn_id
        with self._conn_lock:
            if self._conn_id:
                return self._conn_id
            qs = "appName=salesforce&status=ACTIVE&limit=10"
            if self._entity_id:
                qs = f"entityId={urllib.parse.quote(self._entity_id)}&" + qs
            url = f"{_CONNECTED_ACCOUNTS_URL}?{qs}"
            req = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = json.loads(r.read())
            except urllib.error.HTTPError as exc:
                raise RuntimeError(
                    f"Composio HTTP {exc.code} fetching SFDC connections. "
                    "Verify COMPOSIO_API_KEY and that Salesforce OAuth is active."
                ) from exc
            items = data.get("items", [])
            if not items:
                raise RuntimeError(
                    "No active Salesforce connection. Connect a Developer Edition "
                    "org via app.composio.dev → Auth Configs → Salesforce."
                )
            self._conn_id = items[0]["id"]
            ent = items[0].get("clientUniqueUserId") or "unknown"
            print(f"  Salesforce connection: {self._conn_id} (entity {ent})", flush=True)
            return self._conn_id

    def execute(self, action: str, input_payload: dict, attempts: int = 3) -> dict:
        """Execute a Composio native action. Returns the parsed JSON response."""
        conn_id = self.get_connection_id()
        body = json.dumps({
            "connectedAccountId": conn_id,
            "input": input_payload,
        }).encode()
        url = _ACTION_EXEC_URL.format(action=action)

        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(url, data=body, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=45) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as exc:
                txt = exc.read().decode("utf-8", errors="replace")[:400]
                if exc.code in (429, 502, 503, 504) and attempt < attempts:
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue
                raise RuntimeError(
                    f"Composio action {action} HTTP {exc.code}: {txt}"
                ) from exc
            except (urllib.error.URLError, OSError) as exc:
                last_exc = exc
                if attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(
                    f"Composio action {action} failed after {attempts} attempts: {exc}"
                ) from exc
        raise RuntimeError(f"Composio action {action} exhausted retries ({last_exc})")


# ---------------------------------------------------------------------------
# SOQL helpers
# ---------------------------------------------------------------------------

def _unwrap_sfdc(r: dict) -> dict:
    """Composio wraps SFDC responses inconsistently across actions:
       - SALESFORCE_EXECUTE_SOQL_QUERY → r['data']['data'] = sfdc response
       - SALESFORCE_CREATE_*           → r['data']['response_data'] = sfdc response
    """
    outer = r.get("data") or {}
    return outer.get("data") or outer.get("response_data") or outer


def _soql(client: _Client, query: str) -> List[dict]:
    r = client.execute("SALESFORCE_EXECUTE_SOQL_QUERY", {"soql_query": query})
    sfdc = _unwrap_sfdc(r)
    return sfdc.get("records") or []


def _soql_count(client: _Client, sobject: str, where: str = "") -> int:
    q = f"SELECT COUNT() FROM {sobject}"
    if where:
        q += f" WHERE {where}"
    r = client.execute("SALESFORCE_EXECUTE_SOQL_QUERY", {"soql_query": q})
    sfdc = _unwrap_sfdc(r)
    return sfdc.get("totalSize", 0)


def _fetch_existing_atlas_ids(
    client: _Client,
    sobject: str,
) -> Dict[str, str]:
    """Return {atlas_id: sfdc_id} for records whose atlas-id field starts with the
    expected prefix for the SObject."""
    field = _ATLAS_ID_FIELD[sobject]
    prefix = _ATLAS_ID_PREFIX[sobject]
    soql = (
        f"SELECT Id, {field} FROM {sobject} "
        f"WHERE {field} LIKE '{prefix}%' LIMIT 5000"
    )
    out: Dict[str, str] = {}
    rows = _soql(client, soql)
    for rec in rows:
        sfdc_id = rec.get("Id")
        atlas_id = (rec.get(field) or "").strip()
        if atlas_id and sfdc_id and atlas_id.startswith(prefix):
            out[atlas_id] = sfdc_id
    return out


# ---------------------------------------------------------------------------
# Per-entity import (parallelized via ThreadPoolExecutor)
# ---------------------------------------------------------------------------

def _create_account(client: _Client, co: dict) -> Tuple[str, Optional[str], Optional[str]]:
    """Returns (atlas_id, sfdc_id_or_None, error_or_None)."""
    atlas_id = co["id"]
    desc = _atlas_desc(atlas_id, {
        "segment": co.get("segment") or "",
        "lifecycle_stage": co.get("lifecycle_stage") or "",
        "is_target_account": bool(co.get("is_target_account")),
        "tech_stack": co.get("tech_stack") or [],
        "industry": co.get("industry") or "",
        "is_customer": bool(co.get("is_customer")),
        "created_date": co.get("created_date") or "",
    })
    payload = {
        "name": (co.get("name") or atlas_id)[:255],
        "annual_revenue": int(co.get("current_arr") or 0),
        "number_of_employees": int(co.get("employees") or 0),
        "description": desc[:32768],
        "sic_desc": atlas_id[:40],  # queryable atlas anchor (Account.SicDesc)
    }
    try:
        r = client.execute("SALESFORCE_CREATE_ACCOUNT", payload)
        if not r.get("successful"):
            return atlas_id, None, (r.get("error") or "")[:160]
        sfdc = _unwrap_sfdc(r)
        sfdc_id = sfdc.get("id") or sfdc.get("Id")
        if not sfdc_id:
            return atlas_id, None, f"no id in response: {str(sfdc)[:140]}"
        return atlas_id, sfdc_id, None
    except RuntimeError as exc:
        return atlas_id, None, str(exc)[:160]


def _create_contact(
    client: _Client,
    ct: dict,
    atlas_to_sfdc_account: Dict[str, str],
) -> Tuple[str, Optional[str], Optional[str]]:
    atlas_id = ct["id"]
    raw_email = ct.get("email") or ""
    if "@" in raw_email:
        local, domain = raw_email.split("@", 1)
        domain = domain.replace(",", "").replace(" ", "")
        raw_email = f"{local}@{domain}"

    desc = _atlas_desc(atlas_id, {
        "company_id": ct.get("company_id") or "",
        "lifecycle_stage": ct.get("lifecycle_stage") or "",
        "role_category": ct.get("role_category") or "",
        "became_sql_date": ct.get("became_sql_date") or "",
        "is_abm": bool(ct.get("is_abm")),
        "sql_accepted": bool(ct.get("sql_accepted")),
        "created_date": ct.get("created_date") or "",
    })
    payload = {
        "first_name": (ct.get("first_name") or "")[:40],
        "last_name": (ct.get("last_name") or "(Unknown)")[:80] or "(Unknown)",
        "email": raw_email[:80] if raw_email else None,
        "title": (ct.get("title") or "")[:128],
        "description": desc[:32768],
        "department": atlas_id[:40],  # queryable atlas anchor (Contact.Department)
    }
    sfdc_account_id = atlas_to_sfdc_account.get(ct.get("company_id") or "")
    if sfdc_account_id and not sfdc_account_id.startswith("dry-"):
        payload["account_id"] = sfdc_account_id
    try:
        r = client.execute("SALESFORCE_CREATE_CONTACT", payload)
        if not r.get("successful"):
            return atlas_id, None, (r.get("error") or "")[:160]
        sfdc = _unwrap_sfdc(r)
        sfdc_id = sfdc.get("id") or sfdc.get("Id")
        if not sfdc_id:
            return atlas_id, None, f"no id: {str(sfdc)[:140]}"
        return atlas_id, sfdc_id, None
    except RuntimeError as exc:
        return atlas_id, None, str(exc)[:160]


def _create_opportunity(
    client: _Client,
    d: dict,
    atlas_to_sfdc_account: Dict[str, str],
) -> Tuple[str, Optional[str], Optional[str]]:
    atlas_id = d["id"]
    desc = _atlas_desc(atlas_id, {
        "company_id": d.get("company_id") or "",
        "lead_source": d.get("lead_source") or "",
        "segment": d.get("segment") or "",
        "time_in_proposal": int(d.get("time_in_proposal") or 0),
        "contract_revisions": bool(d.get("contract_revisions")),
        "competitor_id": d.get("competitor_id") or "",
        "head_to_head": bool(d.get("head_to_head")),
        "procurement_signoff": bool(d.get("procurement_signoff")),
    })
    payload = {
        "name": f"Atlas Deal {atlas_id}"[:120],
        "stage_name": _atlas_stage_to_sfdc(d.get("stage") or ""),
        "close_date": d.get("close_date") or "2026-12-31",
        "amount": int(d.get("amount") or 0),
        "description": desc[:32768],
        "next_step": atlas_id[:40],  # queryable atlas anchor (Opportunity.NextStep)
    }
    sfdc_account_id = atlas_to_sfdc_account.get(d.get("company_id") or "")
    if sfdc_account_id and not sfdc_account_id.startswith("dry-"):
        payload["account_id"] = sfdc_account_id
    try:
        r = client.execute("SALESFORCE_CREATE_OPPORTUNITY", payload)
        if not r.get("successful"):
            return atlas_id, None, (r.get("error") or "")[:160]
        sfdc = _unwrap_sfdc(r)
        sfdc_id = sfdc.get("id") or sfdc.get("Id")
        if not sfdc_id:
            return atlas_id, None, f"no id: {str(sfdc)[:140]}"
        return atlas_id, sfdc_id, None
    except RuntimeError as exc:
        return atlas_id, None, str(exc)[:160]


def _parallel_create(
    items: list,
    create_fn,
    label: str,
    workers: int,
    dry_run: bool,
) -> Tuple[Dict[str, str], int]:
    """Run create_fn in parallel. Returns ({atlas_id: sfdc_id}, n_failed)."""
    out: Dict[str, str] = {}
    n_failed = 0
    total = len(items)
    if total == 0:
        print(f"  {label}: nothing to create")
        return out, 0

    if dry_run:
        for it in items:
            atlas_id = it["id"]
            out[atlas_id] = f"dry-{atlas_id}"
        print(f"  [DRY] {label}: {total}/{total}")
        return out, 0

    done = 0
    err_examples = 0
    print_lock = Lock()

    def _print_progress():
        # Carriage-return overwrite for live progress
        with print_lock:
            print(f"  {label}: {done}/{total}", end="\r", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(create_fn, it): it for it in items}
        for fut in as_completed(futures):
            try:
                atlas_id, sfdc_id, err = fut.result()
            except Exception as exc:
                atlas_id = futures[fut].get("id", "?")
                sfdc_id = None
                err = f"unhandled: {exc}"
            done += 1
            if sfdc_id:
                out[atlas_id] = sfdc_id
            else:
                n_failed += 1
                if err and err_examples < 3:
                    err_examples += 1
                    with print_lock:
                        print(f"\n  FAIL {label}/{atlas_id}: {err}", flush=True)
            if done % 25 == 0 or done == total:
                _print_progress()

    print(f"  {label}: {done}/{total} done ({len(out)} succeeded, {n_failed} failed)")
    return out, n_failed


def import_accounts(
    client: _Client,
    companies: list,
    dry_run: bool,
    limit: Optional[int],
    workers: int,
) -> Dict[str, str]:
    print(f"\n--- Accounts ({len(companies)}) ---")
    if not dry_run:
        existing = _fetch_existing_atlas_ids(client, "Account")
        print(f"  {len(existing)} already in SFDC")
    else:
        existing = {}

    rows = companies[:limit] if limit else companies
    to_create = [co for co in rows if co["id"] not in existing]
    print(f"  creating {len(to_create)}")

    out = dict(existing)
    created, _ = _parallel_create(
        to_create,
        lambda co: _create_account(client, co),
        "accounts",
        workers,
        dry_run,
    )
    out.update(created)
    return out


def import_contacts(
    client: _Client,
    contacts: list,
    atlas_to_sfdc_account: Dict[str, str],
    dry_run: bool,
    limit: Optional[int],
    workers: int,
) -> Dict[str, str]:
    print(f"\n--- Contacts ({len(contacts)}) ---")
    if not dry_run:
        existing = _fetch_existing_atlas_ids(client, "Contact")
        print(f"  {len(existing)} already in SFDC")
    else:
        existing = {}

    rows = contacts[:limit] if limit else contacts
    to_create = [ct for ct in rows if ct["id"] not in existing]
    print(f"  creating {len(to_create)}")

    out = dict(existing)
    created, _ = _parallel_create(
        to_create,
        lambda ct: _create_contact(client, ct, atlas_to_sfdc_account),
        "contacts",
        workers,
        dry_run,
    )
    out.update(created)
    return out


def import_opportunities(
    client: _Client,
    deals: list,
    atlas_to_sfdc_account: Dict[str, str],
    dry_run: bool,
    limit: Optional[int],
    workers: int,
) -> Dict[str, str]:
    print(f"\n--- Opportunities ({len(deals)}) ---")
    if not dry_run:
        existing = _fetch_existing_atlas_ids(client, "Opportunity")
        print(f"  {len(existing)} already in SFDC")
    else:
        existing = {}

    rows = deals[:limit] if limit else deals
    to_create = [d for d in rows if d["id"] not in existing]
    print(f"  creating {len(to_create)}")

    out = dict(existing)
    created, _ = _parallel_create(
        to_create,
        lambda d: _create_opportunity(client, d, atlas_to_sfdc_account),
        "opportunities",
        workers,
        dry_run,
    )
    out.update(created)
    return out


# ---------------------------------------------------------------------------
# Stage mapping
# ---------------------------------------------------------------------------

# Atlas deal stages → SFDC StageName (standard Salesforce values)
_ATLAS_TO_SFDC_STAGE: Dict[str, str] = {
    "lead": "Prospecting",
    "qualifying": "Qualification",
    "discovery": "Needs Analysis",
    "proposal": "Proposal/Price Quote",
    "negotiation": "Negotiation/Review",
    "closedwon": "Closed Won",
    "closedlost": "Closed Lost",
    "appointmentscheduled": "Qualification",
    "presentationscheduled": "Needs Analysis",
    "decisionmakerboughtin": "Negotiation/Review",
    "contractsent": "Negotiation/Review",
    "": "Prospecting",
}


def _atlas_stage_to_sfdc(v: str) -> str:
    return _ATLAS_TO_SFDC_STAGE.get(v.lower(), "Prospecting")


# ---------------------------------------------------------------------------
# Status / wipe modes
# ---------------------------------------------------------------------------

def _atlas_where(sobject: str) -> str:
    field = _ATLAS_ID_FIELD[sobject]
    prefix = _ATLAS_ID_PREFIX[sobject]
    return f"{field} LIKE '{prefix}%'"


def show_status(client: _Client) -> None:
    print("Current Salesforce Atlas record counts:")
    for sobject, label in [
        ("Account", "accounts (atlas)"),
        ("Contact", "contacts (atlas)"),
        ("Opportunity", "opportunities (atlas)"),
    ]:
        try:
            n = _soql_count(client, sobject, _atlas_where(sobject))
            print(f"  {label:<28} {n:>6}")
        except Exception as exc:
            print(f"  {label:<28}  ERROR: {str(exc)[:160]}")
    for sobject, label in [
        ("Account", "accounts (total)"),
        ("Contact", "contacts (total)"),
        ("Opportunity", "opportunities (total)"),
    ]:
        try:
            n = _soql_count(client, sobject)
            print(f"  {label:<28} {n:>6}")
        except Exception as exc:
            print(f"  {label:<28}  ERROR: {str(exc)[:160]}")


def wipe_atlas(client: _Client, workers: int) -> None:
    """Delete all Atlas-tagged records (Opportunity → Contact → Account order)."""
    for sobject, where in [
        ("Opportunity", _atlas_where("Opportunity")),
        ("Contact", _atlas_where("Contact")),
        ("Account", _atlas_where("Account")),
    ]:
        print(f"  wiping Atlas {sobject}s...")
        ids = _soql(client, f"SELECT Id FROM {sobject} WHERE {where} LIMIT 5000")
        sfdc_ids = [rec.get("Id") for rec in ids if rec.get("Id")]
        if not sfdc_ids:
            print(f"    none to delete")
            continue
        print(f"    deleting {len(sfdc_ids)}")
        # Delete via native single-record action
        delete_action = {
            "Account": "SALESFORCE_DELETE_ACCOUNT",
            "Contact": "SALESFORCE_DELETE_CONTACT",
            "Opportunity": "SALESFORCE_DELETE_OPPORTUNITY",
        }[sobject]
        # The delete actions take an "id" parameter
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(client.execute, delete_action, {"id": sid})
                for sid in sfdc_ids
            ]
            for _ in as_completed(futures):
                done += 1
                if done % 25 == 0:
                    print(f"    {done}/{len(sfdc_ids)}", end="\r", flush=True)
        print(f"    {done}/{len(sfdc_ids)} done     ")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Salesforce seed via Composio native actions")
    ap.add_argument("--seed", type=int, default=42, help="Dataset seed (default 42)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be created without making API calls")
    ap.add_argument("--status", action="store_true",
                    help="Show current SFDC Atlas record counts and exit")
    ap.add_argument("--wipe-atlas", action="store_true",
                    help="Delete all existing Atlas-tagged records first")
    ap.add_argument("--limit", type=int, default=None,
                    help="Limit import to first N records per entity (for testing)")
    ap.add_argument("--workers", type=int, default=8,
                    help="Parallel workers for record creation (default 8)")
    args = ap.parse_args(argv)

    api_key = os.environ.get("COMPOSIO_API_KEY") or _load_env_key("COMPOSIO_API_KEY")
    if not api_key and not args.dry_run:
        print("ERROR: COMPOSIO_API_KEY not found in env or .env", file=sys.stderr)
        return 1

    entity_id = (
        os.environ.get("SALESFORCE_ENTITY_ID")
        or _load_env_key("SALESFORCE_ENTITY_ID")
    )

    client = _Client(api_key or "dry-run-placeholder", entity_id)

    if args.status:
        if not api_key:
            print("ERROR: COMPOSIO_API_KEY required for --status", file=sys.stderr)
            return 1
        show_status(client)
        return 0

    if args.wipe_atlas:
        if not api_key:
            print("ERROR: COMPOSIO_API_KEY required for --wipe-atlas", file=sys.stderr)
            return 1
        print("Wiping Atlas-tagged records (Opportunity → Contact → Account order)...")
        wipe_atlas(client, args.workers)
        print("Wipe complete.")
        return 0

    print(f"Loading Atlas dataset (seed {args.seed})...")
    ds = _load_dataset(args.seed)
    companies = ds["companies"]
    contacts = ds["contacts"]
    deals = ds["deals"]

    print(f"  companies: {len(companies)}")
    print(f"  contacts:  {len(contacts)}")
    print(f"  deals:     {len(deals)}")
    print(f"  events:    {len(ds['engagement_events'])} (deferred — Tasks not in v1)")

    if args.dry_run:
        print("\n[DRY-RUN MODE] No writes will occur.\n")

    t0 = time.time()

    atlas_to_sfdc_account = import_accounts(
        client, companies, args.dry_run, args.limit, args.workers
    )
    atlas_to_sfdc_contact = import_contacts(
        client, contacts, atlas_to_sfdc_account, args.dry_run, args.limit, args.workers
    )
    import_opportunities(
        client, deals, atlas_to_sfdc_account, args.dry_run, args.limit, args.workers
    )

    elapsed = time.time() - t0
    print(f"\nDone. ({elapsed:.1f}s)")

    if not args.dry_run:
        print("\nFinal Salesforce Atlas record counts:")
        show_status(client)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
