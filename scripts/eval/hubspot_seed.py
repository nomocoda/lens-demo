#!/usr/bin/env python3
"""HubSpot programmatic import via Composio proxy (Phase 3.2).

Reads the Atlas SaaS synthetic dataset from scripts/eval/output/ (seed 42 by
default) and creates the following records in HubSpot via Composio's OAuth
connection:

  Companies      : 800 rows
  Contacts       : 3000 rows  (marked non-marketing)
  Deals          : 600  rows
  Notes          : all engagement_events rows (associated to contacts)

All Atlas entity IDs are stored as HubSpot external_id custom properties for
idempotent re-runs. First run creates missing custom properties, then creates
entities in batches of 100.

Usage:
  python3 scripts/eval/hubspot_seed.py                   # full run (seed 42)
  python3 scripts/eval/hubspot_seed.py --dry-run         # show counts, no writes
  python3 scripts/eval/hubspot_seed.py --status          # show HubSpot record counts
  python3 scripts/eval/hubspot_seed.py --limit N         # import only first N per entity
  python3 scripts/eval/hubspot_seed.py --skip-notes      # skip note creation
  python3 scripts/eval/hubspot_seed.py --seed 99         # use a different seed

Required env vars (in .env or environment):
  COMPOSIO_API_KEY    — from app.composio.dev/settings -> API Keys tab
  COMPOSIO_ENTITY_ID  — email used to connect HubSpot (default: travis@nomocoda.com)

Active connection (Phase 3.3):
  Auth Config : hubspot-lens-dev (ID ac_3ZQEpiEkiz4r)
  Entity      : travis@nomocoda.com
  Auth        : OAuth2, Managed by Composio
  Status      : Active
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
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = ROOT / "scripts" / "eval"

_COMPOSIO_BASE = "https://backend.composio.dev/api"
_PROXY_URL = f"{_COMPOSIO_BASE}/v2/actions/proxy"
_CONNECTED_ACCOUNTS_URL = f"{_COMPOSIO_BASE}/v1/connectedAccounts"

_DEFAULT_ENTITY_ID = "travis@nomocoda.com"
_BATCH_SIZE = 100
# Conservative rate limit: ~4 batches/sec stays well under HubSpot 10 req/s burst
_BATCH_DELAY = 0.25


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


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# ---------------------------------------------------------------------------
# Composio proxy
# ---------------------------------------------------------------------------

class _Proxy:
    def __init__(self, api_key: str, entity_id: str) -> None:
        self._api_key = api_key
        self._entity_id = entity_id
        self._conn_id: Optional[str] = None

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "curl/7.88.1",
        }

    def _get_connection_id(self) -> str:
        if self._conn_id:
            return self._conn_id
        url = (
            f"{_CONNECTED_ACCOUNTS_URL}"
            f"?entityId={urllib.parse.quote(self._entity_id)}"
            f"&appName=hubspot&status=ACTIVE&limit=5"
        )
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Composio returned HTTP {exc.code} fetching connected accounts. "
                "Verify COMPOSIO_API_KEY is correct and HubSpot OAuth is active."
            ) from exc
        items = data.get("items", [])
        if not items:
            raise RuntimeError(
                f"No active HubSpot connection for entity '{self._entity_id}'. "
                "Ensure Phase 3.3 (Composio HubSpot OAuth) is complete."
            )
        self._conn_id = items[0]["id"]
        return self._conn_id

    def call(
        self,
        method: str,
        endpoint: str,
        body: Optional[dict] = None,
    ) -> dict:
        conn_id = self._get_connection_id()
        payload = json.dumps({
            "connectedAccountId": conn_id,
            "method": method.upper(),
            "endpoint": endpoint,
            "body": body,
            "parameters": [],
        }).encode()
        req = urllib.request.Request(
            _PROXY_URL, data=payload, headers=self._headers()
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            body_txt = exc.read().decode("utf-8", errors="replace")[:600]
            raise RuntimeError(
                f"Composio proxy HTTP {exc.code} for {method} {endpoint}: {body_txt}"
            ) from exc

    def get_record_count(self, object_type: str) -> int:
        """Return total HubSpot records of the given type."""
        result = self.call("POST", f"/crm/v3/objects/{object_type}/search", {
            "filterGroups": [],
            "properties": ["hs_object_id"],
            "limit": 1,
        })
        data = result.get("data", result)
        return data.get("total", 0)


# ---------------------------------------------------------------------------
# Custom property management
# ---------------------------------------------------------------------------

_CUSTOM_PROPS: Dict[str, List[Dict]] = {
    "companies": [
        {"name": "external_id", "label": "Atlas External ID", "type": "string",
         "fieldType": "text", "groupName": "companyinformation"},
        {"name": "atlas_segment", "label": "Atlas Segment", "type": "string",
         "fieldType": "text", "groupName": "companyinformation"},
        # abm_target stored as string "true"/"false" — HubSpot rejects bool fieldType via proxy
        {"name": "abm_target", "label": "ABM Target", "type": "string",
         "fieldType": "text", "groupName": "companyinformation"},
        {"name": "tech_stack", "label": "Tech Stack", "type": "string",
         "fieldType": "textarea", "groupName": "companyinformation"},
    ],
    "contacts": [
        {"name": "external_id", "label": "Atlas External ID", "type": "string",
         "fieldType": "text", "groupName": "contactinformation"},
        {"name": "atlas_role_category", "label": "Atlas Role Category", "type": "string",
         "fieldType": "text", "groupName": "contactinformation"},
        {"name": "atlas_became_sql_date", "label": "Atlas Became SQL Date",
         "type": "string", "fieldType": "text", "groupName": "contactinformation"},
        # abm_contact and atlas_sql_accepted as strings for same reason
        {"name": "abm_contact", "label": "ABM Contact", "type": "string",
         "fieldType": "text", "groupName": "contactinformation"},
        {"name": "atlas_sql_accepted", "label": "Atlas SQL Accepted", "type": "string",
         "fieldType": "text", "groupName": "contactinformation"},
    ],
    "deals": [
        {"name": "external_id", "label": "Atlas External ID", "type": "string",
         "fieldType": "text", "groupName": "dealinformation"},
        {"name": "atlas_time_in_proposal", "label": "Atlas Time in Proposal (days)",
         "type": "number", "fieldType": "number", "groupName": "dealinformation"},
        {"name": "atlas_contract_revisions", "label": "Atlas Contract Revisions",
         "type": "number", "fieldType": "number", "groupName": "dealinformation"},
        {"name": "atlas_competitor", "label": "Atlas Competitor ID", "type": "string",
         "fieldType": "text", "groupName": "dealinformation"},
    ],
}


def ensure_custom_properties(proxy: _Proxy, dry_run: bool) -> None:
    print("Creating custom properties...", flush=True)
    for obj_type, props in _CUSTOM_PROPS.items():
        for prop in props:
            if dry_run:
                print(f"  [DRY] would create {obj_type}/{prop['name']}")
                continue
            try:
                proxy.call("POST", f"/crm/v3/properties/{obj_type}", prop)
                print(f"  created {obj_type}/{prop['name']}")
            except RuntimeError as exc:
                msg = str(exc)
                if "409" in msg or "already exists" in msg.lower() or "PROPERTY_EXISTS" in msg:
                    print(f"  exists  {obj_type}/{prop['name']}")
                else:
                    print(f"  WARN    {obj_type}/{prop['name']}: {msg[:120]}")
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# Idempotency: fetch existing external_ids
# ---------------------------------------------------------------------------

def _fetch_existing_external_ids(
    proxy: _Proxy,
    object_type: str,
) -> Dict[str, str]:
    """Return {external_id: hs_object_id} for all records that have external_id set."""
    existing: Dict[str, str] = {}
    after: Optional[str] = None

    while True:
        body: dict = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "external_id",
                    "operator": "HAS_PROPERTY",
                }]
            }],
            "properties": ["external_id"],
            "limit": 100,
        }
        if after:
            body["after"] = after

        result = proxy.call(
            "POST", f"/crm/v3/objects/{object_type}/search", body
        )
        data = result.get("data", result)
        for rec in data.get("results", []):
            ext_id = (rec.get("properties") or {}).get("external_id") or ""
            if ext_id:
                existing[ext_id] = rec["id"]

        paging = data.get("paging") or {}
        after = (paging.get("next") or {}).get("after")
        if not after:
            break
        time.sleep(0.1)

    return existing


# ---------------------------------------------------------------------------
# Entity creation
# ---------------------------------------------------------------------------

def _batch_create(
    proxy: _Proxy,
    object_type: str,
    inputs: List[dict],
    dry_run: bool,
    label: str,
) -> Dict[str, str]:
    """Batch-create records. Returns {external_id: hs_object_id} for created records."""
    created: Dict[str, str] = {}
    total = len(inputs)
    done = 0

    for chunk in _chunks(inputs, _BATCH_SIZE):
        if dry_run:
            done += len(chunk)
            print(f"  [DRY] {label}: {done}/{total}", end="\r", flush=True)
            # Simulate hs_ids for dry-run mapping
            for item in chunk:
                ext_id = (item.get("properties") or {}).get("external_id", "")
                if ext_id:
                    created[ext_id] = f"dry-{ext_id}"
            continue

        result = proxy.call(
            "POST", f"/crm/v3/objects/{object_type}/batch/create",
            {"inputs": chunk}
        )
        data = result.get("data", result)
        if data.get("status") == "error":
            msg = data.get("message", "unknown error")
            print(f"\n  ERROR batch create {object_type}: {msg[:200]}", flush=True)
            # Continue with next chunk rather than aborting the whole run
            done += len(chunk)
            print(f"  {label}: {done}/{total} (batch error — see above)", end="\r", flush=True)
            time.sleep(_BATCH_DELAY)
            continue
        for rec in data.get("results", []):
            ext_id = (rec.get("properties") or {}).get("external_id", "")
            if ext_id:
                created[ext_id] = rec["id"]
        done += len(chunk)
        print(f"  {label}: {done}/{total}", end="\r", flush=True)
        time.sleep(_BATCH_DELAY)

    print(f"  {label}: {done}/{total} done     ")
    return created


def _batch_associate(
    proxy: _Proxy,
    from_type: str,
    to_type: str,
    assoc_type_id: int,
    pairs: List[Tuple[str, str]],
    dry_run: bool,
    label: str,
) -> None:
    """Batch-create associations. pairs is list of (from_hs_id, to_hs_id)."""
    total = len(pairs)
    done = 0
    for chunk in _chunks(pairs, _BATCH_SIZE):
        if dry_run:
            done += len(chunk)
            print(f"  [DRY] {label}: {done}/{total}", end="\r", flush=True)
            continue
        inputs = [
            {
                "from": {"id": frm},
                "to": {"id": to},
                "types": [{"associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": assoc_type_id}],
            }
            for frm, to in chunk
        ]
        proxy.call(
            "POST",
            f"/crm/v4/associations/{from_type}/{to_type}/batch/create",
            {"inputs": inputs},
        )
        done += len(chunk)
        print(f"  {label}: {done}/{total}", end="\r", flush=True)
        time.sleep(_BATCH_DELAY)
    print(f"  {label}: {done}/{total} done     ")


# ---------------------------------------------------------------------------
# Per-entity import functions
# ---------------------------------------------------------------------------

def import_companies(
    proxy: _Proxy,
    companies: list,
    dry_run: bool,
    limit: Optional[int],
) -> Dict[str, str]:
    """Returns {atlas_company_id: hs_company_id}."""
    print(f"\n--- Companies ({len(companies)}) ---")
    if not dry_run:
        existing = _fetch_existing_external_ids(proxy, "companies")
        print(f"  {len(existing)} already in HubSpot")
    else:
        existing = {}

    rows = companies[:limit] if limit else companies
    to_create = [co for co in rows if co["id"] not in existing]
    print(f"  creating {len(to_create)}")

    inputs = []
    for co in to_create:
        tech = ";".join(co.get("tech_stack") or []) if isinstance(co.get("tech_stack"), list) else (co.get("tech_stack") or "")
        props: Dict[str, str] = {
            "name": co.get("name") or "",
            # industry excluded: Atlas values (healthtech, fintech, etc.) are not in
            # HubSpot's allowed enum and cause entire batch to fail
            "numberofemployees": str(co.get("employees") or 0),
            "annualrevenue": str(co.get("current_arr") or 0),
            "lifecyclestage": _atlas_lc_to_hs(co.get("lifecycle_stage") or ""),
            "external_id": co["id"],
            "atlas_segment": co.get("segment") or "",
            "abm_target": "true" if co.get("is_target_account") else "false",
            "tech_stack": tech,
        }
        inputs.append({"properties": props})

    atlas_to_hs = dict(existing)
    created = _batch_create(proxy, "companies", inputs, dry_run, "companies")
    atlas_to_hs.update(created)
    return atlas_to_hs


def import_contacts(
    proxy: _Proxy,
    contacts: list,
    atlas_to_hs_company: Dict[str, str],
    dry_run: bool,
    limit: Optional[int],
) -> Dict[str, str]:
    """Returns {atlas_contact_id: hs_contact_id}."""
    print(f"\n--- Contacts ({len(contacts)}) ---")
    if not dry_run:
        existing = _fetch_existing_external_ids(proxy, "contacts")
        print(f"  {len(existing)} already in HubSpot")
    else:
        existing = {}

    rows = contacts[:limit] if limit else contacts
    to_create = [ct for ct in rows if ct["id"] not in existing]
    print(f"  creating {len(to_create)}")

    inputs = []
    assoc_pairs: List[Tuple[str, str]] = []  # (atlas_contact_id, hs_company_id)

    for ct in to_create:
        sql_date = ct.get("became_sql_date") or ""
        # Sanitize email: strip commas/spaces from domain part
        # (synthetic generator can produce "user@company,.com" via company name)
        raw_email = ct.get("email") or ""
        if "@" in raw_email:
            local, domain = raw_email.split("@", 1)
            domain = domain.replace(",", "").replace(" ", "")
            raw_email = f"{local}@{domain}"
        props: Dict[str, str] = {
            "firstname": ct.get("first_name") or "",
            "lastname": ct.get("last_name") or "",
            "email": raw_email,
            "jobtitle": ct.get("title") or "",
            "lifecyclestage": _atlas_lc_to_hs(ct.get("lifecycle_stage") or ""),
            "hs_marketable_status": "false",  # non-marketing contact
            "external_id": ct["id"],
            "atlas_role_category": ct.get("role_category") or "",
            "atlas_became_sql_date": sql_date,
            "abm_contact": "true" if ct.get("is_abm") else "false",
            "atlas_sql_accepted": "true" if ct.get("sql_accepted") else "false",
        }
        co_hs_id = atlas_to_hs_company.get(ct.get("company_id") or "")
        if co_hs_id and not co_hs_id.startswith("dry-"):
            assoc_pairs.append((ct["id"], co_hs_id))
        inputs.append({"properties": props})

    atlas_to_hs = dict(existing)
    created = _batch_create(proxy, "contacts", inputs, dry_run, "contacts")
    atlas_to_hs.update(created)

    # Now create contact → company associations
    resolved_pairs = [
        (atlas_to_hs[ct_id], co_id)
        for ct_id, co_id in assoc_pairs
        if ct_id in atlas_to_hs
    ]
    if resolved_pairs:
        print(f"  associating {len(resolved_pairs)} contacts to companies...")
        _batch_associate(
            proxy, "contacts", "companies", 1,
            resolved_pairs, dry_run, "contact-company associations"
        )

    return atlas_to_hs


def import_deals(
    proxy: _Proxy,
    deals: list,
    atlas_to_hs_company: Dict[str, str],
    dry_run: bool,
    limit: Optional[int],
) -> Dict[str, str]:
    """Returns {atlas_deal_id: hs_deal_id}."""
    print(f"\n--- Deals ({len(deals)}) ---")
    if not dry_run:
        existing = _fetch_existing_external_ids(proxy, "deals")
        print(f"  {len(existing)} already in HubSpot")
    else:
        existing = {}

    rows = deals[:limit] if limit else deals
    to_create = [d for d in rows if d["id"] not in existing]
    print(f"  creating {len(to_create)}")

    inputs = []
    assoc_pairs: List[Tuple[str, str]] = []  # (atlas_deal_id, hs_company_id)

    for d in to_create:
        props: Dict[str, str] = {
            "dealname": f"Atlas Deal {d['id']}",
            "amount": str(d.get("amount") or 0),
            "dealstage": d.get("stage") or "appointmentscheduled",
            "pipeline": "default",
            "closedate": d.get("close_date") or "",
            # lead_source and createdate excluded: not writable HubSpot deal properties
            "external_id": d["id"],
            "atlas_time_in_proposal": str(d.get("time_in_proposal") or 0),
            "atlas_contract_revisions": str(1 if d.get("contract_revisions") else 0),
            "atlas_competitor": d.get("competitor_id") or "",
        }
        co_hs_id = atlas_to_hs_company.get(d.get("company_id") or "")
        if co_hs_id and not co_hs_id.startswith("dry-"):
            assoc_pairs.append((d["id"], co_hs_id))
        inputs.append({"properties": props})

    atlas_to_hs = dict(existing)
    created = _batch_create(proxy, "deals", inputs, dry_run, "deals")
    atlas_to_hs.update(created)

    resolved_pairs = [
        (atlas_to_hs[d_id], co_id)
        for d_id, co_id in assoc_pairs
        if d_id in atlas_to_hs
    ]
    if resolved_pairs:
        print(f"  associating {len(resolved_pairs)} deals to companies...")
        _batch_associate(
            proxy, "deals", "companies", 5,
            resolved_pairs, dry_run, "deal-company associations"
        )

    return atlas_to_hs


def import_notes(
    proxy: _Proxy,
    events: list,
    atlas_to_hs_contact: Dict[str, str],
    dry_run: bool,
    limit: Optional[int],
) -> None:
    """Create HubSpot Notes from Atlas engagement events."""
    print(f"\n--- Notes from engagement events ({len(events)}) ---")
    rows = events[:limit] if limit else events
    print(f"  creating {len(rows)} notes (no idempotency check — notes are recreated)")

    inputs = []
    assoc_pairs: List[Tuple[str, str]] = []  # (note_input_idx, hs_contact_id)

    for ev in rows:
        ct_id = ev.get("contact_id") or ""
        co_hs = atlas_to_hs_contact.get(ct_id)
        event_type = ev.get("event_type") or "event"
        date = ev.get("date") or ""
        body = f"{event_type}: company {ev.get('company_id', '')} on {date}"
        ts = f"{date}T00:00:00Z" if date else "2026-04-24T00:00:00Z"

        props: Dict[str, str] = {
            "hs_note_body": body,
            "hs_timestamp": ts,
        }
        note_input: dict = {"properties": props}
        if co_hs and not co_hs.startswith("dry-"):
            note_input["associations"] = [{
                "to": {"id": co_hs},
                "types": [{"associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": 202}],
            }]
        inputs.append(note_input)

    _batch_create(proxy, "notes", inputs, dry_run, "notes")


# ---------------------------------------------------------------------------
# Lifecycle stage mapping
# ---------------------------------------------------------------------------

_ATLAS_TO_HS_LC: Dict[str, str] = {
    "lead": "lead",
    "mql": "marketingqualifiedlead",
    "sql": "salesqualifiedlead",
    "customer": "customer",
    "other": "other",
    "": "lead",
}


def _atlas_lc_to_hs(v: str) -> str:
    return _ATLAS_TO_HS_LC.get(v.lower(), "lead")


# ---------------------------------------------------------------------------
# Status mode
# ---------------------------------------------------------------------------

def show_status(proxy: _Proxy) -> None:
    print("Current HubSpot record counts:")
    for obj_type in ("companies", "contacts", "deals", "notes"):
        try:
            count = proxy.get_record_count(obj_type)
            print(f"  {obj_type:<12} {count:>6}")
        except Exception as exc:
            print(f"  {obj_type:<12}  ERROR: {exc}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="HubSpot seed via Composio proxy")
    ap.add_argument("--seed", type=int, default=42, help="Dataset seed (default 42)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be created without making API calls")
    ap.add_argument("--status", action="store_true",
                    help="Show current HubSpot record counts and exit")
    ap.add_argument("--limit", type=int, default=None,
                    help="Limit import to first N records per entity (for testing)")
    ap.add_argument("--skip-notes", action="store_true",
                    help="Skip note creation (saves time if notes are not needed)")
    args = ap.parse_args(argv)

    api_key = os.environ.get("COMPOSIO_API_KEY") or _load_env_key("COMPOSIO_API_KEY")
    if not api_key and not args.dry_run:
        print("ERROR: COMPOSIO_API_KEY not found in env or .env", file=sys.stderr)
        return 1

    entity_id = (
        os.environ.get("COMPOSIO_ENTITY_ID")
        or _load_env_key("COMPOSIO_ENTITY_ID")
        or _DEFAULT_ENTITY_ID
    )

    proxy = _Proxy(api_key or "dry-run-placeholder", entity_id)

    if args.status:
        if not api_key:
            print("ERROR: COMPOSIO_API_KEY required for --status", file=sys.stderr)
            return 1
        show_status(proxy)
        return 0

    print(f"Loading Atlas dataset (seed {args.seed})...")
    ds = _load_dataset(args.seed)
    companies = ds["companies"]
    contacts = ds["contacts"]
    deals = ds["deals"]
    events = ds["engagement_events"]

    print(f"  companies: {len(companies)}")
    print(f"  contacts:  {len(contacts)}")
    print(f"  deals:     {len(deals)}")
    print(f"  events:    {len(events)}")

    if args.dry_run:
        print("\n[DRY-RUN MODE] No writes will occur.\n")

    # Step 1: Custom properties
    ensure_custom_properties(proxy, args.dry_run)

    # Step 2: Companies
    atlas_to_hs_company = import_companies(
        proxy, companies, args.dry_run, args.limit
    )

    # Step 3: Contacts
    atlas_to_hs_contact = import_contacts(
        proxy, contacts, atlas_to_hs_company, args.dry_run, args.limit
    )

    # Step 4: Deals
    import_deals(
        proxy, deals, atlas_to_hs_company, args.dry_run, args.limit
    )

    # Step 5: Notes
    if not args.skip_notes:
        import_notes(
            proxy, events, atlas_to_hs_contact, args.dry_run, args.limit
        )

    print("\nDone.")

    if not args.dry_run:
        print("\nFinal HubSpot record counts:")
        show_status(proxy)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
