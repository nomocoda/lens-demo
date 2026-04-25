#!/usr/bin/env python3
"""HubSpot adapter for Lens Relevance Engine eval (Phase 3.4).

Reads from HubSpot via Composio's proxy endpoint and returns the same
Dict[str, list] shape that load_dataset() returns from local JSON files.
Selected via --source hubspot-composio in relevance_engine.py.

Required env vars (add to .env):
  COMPOSIO_API_KEY      from app.composio.dev/settings -> API Keys tab
  COMPOSIO_ENTITY_ID    email used to connect HubSpot (default: travis@nomocoda.com)

Active connection (Phase 3.3):
  Auth Config: hubspot-lens-dev (ID: ac_3ZQEpiEkiz4r)
  Entity:      travis@nomocoda.com
  Auth:        OAuth2, Managed by Composio
  Status:      Active

Architecture note:
  This adapter calls HubSpot CRM v3 endpoints directly via Composio's HTTP
  proxy (POST /api/v2/actions/proxy). No Composio action-name guessing
  required; we construct raw HubSpot query strings and Composio injects the
  stored OAuth token. Same result as the production Composio toolset path;
  appropriate for the eval harness.

Field map: Atlas to HubSpot Field Map (Notion, Phase 3 Prep 3 deliverable).
Adapter contract (field map section 9): returns Atlas-shape records keyed by
External ID, lifecycle_stage reverse-mapped from HubSpot internal values,
tech_stack split on ';' back to a Python list.

Entities not available in HubSpot (CRM only at v1):
  campaigns, campaign_performance, budget, actual_spend, branded_search,
  web_analytics, mentions, analyst_mentions, customer_reference_optins,
  product_launches, sdr_capacity, + all marketing / revenue-specific optional
  entities.
These are returned as empty lists. Cards grounded in those entities will not
surface via the HubSpot path; that delta is measured in Phase 3.5.
"""
from __future__ import annotations

import http.client
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Composio proxy constants
# ---------------------------------------------------------------------------

_COMPOSIO_BASE = "https://backend.composio.dev/api"
_PROXY_URL = f"{_COMPOSIO_BASE}/v2/actions/proxy"
_CONNECTED_ACCOUNTS_URL = f"{_COMPOSIO_BASE}/v1/connectedAccounts"
_DEFAULT_ENTITY_ID = "travis@nomocoda.com"

# HubSpot CRM v3 — max page size
_HS_PAGE_SIZE = 100

# ---------------------------------------------------------------------------
# HubSpot property lists (per field map)
# ---------------------------------------------------------------------------

_COMPANY_PROPS = [
    "name", "industry", "numberofemployees", "annualrevenue",
    "lifecyclestage", "createdate",
    # Custom properties (created by import wizard from Phase 3.2)
    "external_id", "atlas_segment", "abm_target", "tech_stack",
]

_CONTACT_PROPS = [
    "firstname", "lastname", "email", "jobtitle",
    "associatedcompanyid", "lifecyclestage", "createdate",
    # Custom properties
    "external_id", "atlas_role_category", "atlas_became_sql_date",
    "abm_contact", "atlas_sql_accepted",
]

_DEAL_PROPS = [
    "dealname", "amount", "dealstage", "pipeline",
    "closedate", "createdate", "lead_source",
    # Atlas custom properties
    "external_id", "atlas_time_in_proposal", "atlas_contract_revisions",
    "atlas_competitor",
]

_NOTE_PROPS = [
    "hs_note_body", "hs_timestamp", "hs_object_id",
]

# ---------------------------------------------------------------------------
# Enum reverse-maps (HubSpot internal values → Atlas values)
# ---------------------------------------------------------------------------

_HS_LIFECYCLE_TO_ATLAS: Dict[str, str] = {
    "lead": "lead",
    "marketingqualifiedlead": "mql",
    "salesqualifiedlead": "sql",
    "customer": "customer",
    "subscriber": "lead",
    "opportunity": "sql",
    "evangelist": "customer",
    "other": "other",
}

# Note body prefix → Atlas event_type (from field map section 4)
_NOTE_PREFIX_TO_EVENT_TYPE: List[Tuple[str, str]] = [
    ("demo requested", "demo_request"),
    ("form submission", "form_fill"),
    ("viewed pricing page", "pricing_page_view"),
    ("downloaded", "content_download"),
]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class HubSpotComposioAdapter:
    """Reads from HubSpot via Composio proxy, returns Atlas-shape dataset dict."""

    def __init__(
        self,
        api_key: str,
        entity_id: str = _DEFAULT_ENTITY_ID,
        connected_account_id: Optional[str] = None,
    ) -> None:
        self._api_key = api_key
        self._entity_id = entity_id
        self._conn_id = connected_account_id  # skip discovery if provided

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "curl/7.88.1",
        }

    def _get_connection_id(self) -> str:
        """Discover the active HubSpot connected account ID for this entity."""
        if self._conn_id:
            return self._conn_id
        url = (
            f"{_CONNECTED_ACCOUNTS_URL}"
            f"?entityId={urllib.parse.quote(self._entity_id)}"
            f"&appName=hubspot&status=ACTIVE&limit=5"
        )
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Composio returned HTTP {exc.code} fetching connected accounts. "
                f"Verify COMPOSIO_API_KEY is correct."
            ) from exc
        items = data.get("items", [])
        if not items:
            raise RuntimeError(
                f"No active HubSpot connection found for entity '{self._entity_id}'. "
                f"Ensure Phase 3.3 (Composio HubSpot OAuth) is complete."
            )
        self._conn_id = items[0]["id"]
        return self._conn_id

    def _proxy_get(self, hs_endpoint: str, _attempt: int = 1) -> dict:
        """Call any HubSpot endpoint via Composio proxy using stored OAuth token."""
        conn_id = self._get_connection_id()
        payload = json.dumps({
            "connectedAccountId": conn_id,
            "method": "GET",
            "endpoint": hs_endpoint,
            "body": None,
            "parameters": [],
        }).encode()
        req = urllib.request.Request(
            _PROXY_URL, data=payload, headers=self._headers()
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(
                f"Composio proxy returned HTTP {exc.code} for {hs_endpoint}: {body}"
            ) from exc
        except (http.client.RemoteDisconnected, urllib.error.URLError, OSError) as exc:
            if _attempt < 3:
                wait = 2 ** _attempt
                print(
                    f"  transient error on attempt {_attempt} ({exc}), retrying in {wait}s...",
                    file=sys.stderr,
                )
                time.sleep(wait)
                return self._proxy_get(hs_endpoint, _attempt + 1)
            raise RuntimeError(
                f"Composio proxy failed after 3 attempts for {hs_endpoint}: {exc}"
            ) from exc

    def _get_all_objects(
        self,
        object_type: str,
        properties: List[str],
        include_associations: Optional[str] = None,
    ) -> List[dict]:
        """Paginate through all HubSpot objects of the given type."""
        records: List[dict] = []
        props_param = urllib.parse.quote(",".join(properties))
        after: Optional[str] = None
        page = 0

        while True:
            qs = f"?properties={props_param}&limit={_HS_PAGE_SIZE}"
            if after:
                qs += f"&after={urllib.parse.quote(after)}"
            if include_associations:
                qs += f"&associations={include_associations}"
            endpoint = f"/crm/v3/objects/{object_type}{qs}"

            result = self._proxy_get(endpoint)
            # Composio may wrap the HubSpot response in a "data" key
            data = result.get("data", result)
            # Composio occasionally returns a string body on transient errors
            if not isinstance(data, dict):
                print(
                    f"  unexpected response type ({type(data).__name__}) on page {page} of {object_type} — stopping pagination",
                    file=sys.stderr,
                )
                break

            page_records = data.get("results", [])
            records.extend(page_records)
            page += 1

            paging = data.get("paging") or {}
            next_info = paging.get("next") or {}
            after = next_info.get("after")
            if not after:
                break

            # Light throttle to stay well under HubSpot's burst rate cap
            if page % 10 == 0:
                time.sleep(0.1)

        return records

    # ------------------------------------------------------------------
    # Transform functions (HubSpot → Atlas shape, per field map section 9)
    # ------------------------------------------------------------------

    def _transform_companies(
        self, raw: List[dict]
    ) -> Tuple[List[dict], Dict[str, str]]:
        """Return (atlas_companies, {hs_object_id: atlas_external_id})."""
        atlas: List[dict] = []
        hs_id_to_atlas: Dict[str, str] = {}

        for rec in raw:
            props = rec.get("properties") or {}
            hs_id = rec.get("id", "")
            external_id = props.get("external_id") or hs_id

            if hs_id:
                hs_id_to_atlas[hs_id] = external_id

            raw_tech = props.get("tech_stack") or ""
            tech_stack = [t.strip() for t in raw_tech.split(";") if t.strip()]

            lc = (props.get("lifecyclestage") or "").lower()
            atlas.append({
                "id": external_id,
                "name": props.get("name") or "",
                "industry": props.get("industry") or "",
                "employees": _to_int(props.get("numberofemployees")),
                "current_arr": _to_int(props.get("annualrevenue")),
                "lifecycle_stage": _HS_LIFECYCLE_TO_ATLAS.get(lc, "other"),
                "created_date": _date_str(props.get("createdate")),
                "segment": props.get("atlas_segment") or "",
                "is_target_account": _to_bool(props.get("abm_target")),
                "tech_stack": tech_stack,
            })

        return atlas, hs_id_to_atlas

    def _transform_contacts(
        self,
        raw: List[dict],
        hs_id_to_atlas: Dict[str, str],
    ) -> List[dict]:
        atlas: List[dict] = []
        for rec in raw:
            props = rec.get("properties") or {}
            external_id = props.get("external_id") or rec.get("id", "")

            # Resolve company FK: prefer associatedcompanyid property,
            # fall back to associations object (if include_associations was used)
            hs_co_id = props.get("associatedcompanyid") or ""
            if not hs_co_id:
                assocs = (rec.get("associations") or {}).get("companies", {})
                results = (assocs.get("results") or [])
                hs_co_id = results[0]["id"] if results else ""
            company_id = hs_id_to_atlas.get(str(hs_co_id), str(hs_co_id))

            lc = (props.get("lifecyclestage") or "").lower()
            sql_date = _date_str(props.get("atlas_became_sql_date"))

            atlas.append({
                "id": external_id,
                "first_name": props.get("firstname") or "",
                "last_name": props.get("lastname") or "",
                "email": props.get("email") or "",
                "title": props.get("jobtitle") or "",
                "company_id": company_id,
                "lifecycle_stage": _HS_LIFECYCLE_TO_ATLAS.get(lc, "other"),
                "created_date": _date_str(props.get("createdate")),
                "role_category": props.get("atlas_role_category") or "",
                "became_sql_date": sql_date if sql_date else None,
                "sql_accepted": _to_bool(props.get("atlas_sql_accepted")),
                "is_abm": _to_bool(props.get("abm_contact")),
            })
        return atlas

    def _transform_deals(
        self,
        raw: List[dict],
        hs_id_to_atlas: Dict[str, str],
    ) -> List[dict]:
        atlas: List[dict] = []
        for rec in raw:
            props = rec.get("properties") or {}
            external_id = props.get("external_id") or rec.get("id", "")

            hs_co_id = props.get("associatedcompanyid") or ""
            if not hs_co_id:
                assocs = (rec.get("associations") or {}).get("companies", {})
                results = (assocs.get("results") or [])
                hs_co_id = results[0]["id"] if results else ""
            company_id = hs_id_to_atlas.get(str(hs_co_id), str(hs_co_id))

            stage = (props.get("dealstage") or "").lower()
            is_won = stage == "closedwon"
            is_lost = stage == "closedlost"
            is_closed = is_won or is_lost

            atlas.append({
                "id": external_id,
                "company_id": company_id,
                "amount": _to_int(props.get("amount")),
                "stage": stage,
                "is_won": is_won,
                "is_closed": is_closed,
                "close_date": _date_str(props.get("closedate")),
                "create_date": _date_str(props.get("createdate")),
                "lead_source": _normalize_lead_source(
                    props.get("lead_source") or props.get("deal_source") or ""
                ),
                "segment": "",  # not stored on deal; can join via company if needed
                "time_in_proposal": _to_int(props.get("atlas_time_in_proposal")),
                "contract_revisions": _to_int(props.get("atlas_contract_revisions")),
                "competitor_id": props.get("atlas_competitor") or None,
            })
        return atlas

    def _transform_notes(self, raw: List[dict]) -> List[dict]:
        """Convert HubSpot Notes back to Atlas engagement_events shape."""
        atlas: List[dict] = []
        for rec in raw:
            props = rec.get("properties") or {}
            body = (props.get("hs_note_body") or "").strip()
            event_type = _parse_note_event_type(body)
            if not event_type:
                continue  # skip low-intent or unrecognized notes
            ts = props.get("hs_timestamp") or props.get("createdate") or ""
            atlas.append({
                "id": rec.get("id", ""),
                "event_type": event_type,
                "timestamp": ts[:10] if ts else "",
                "body": body,
            })
        return atlas

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_dataset(self) -> Dict[str, list]:
        """Fetch HubSpot CRM data and return in Atlas shape.

        Entities not present in HubSpot (campaigns, web_analytics, etc.) are
        returned as empty lists. Cards grounded in those entities will not
        surface on the HubSpot path; the delta is measured in Phase 3.5.
        """
        print("HubSpot adapter: discovering connection...", file=sys.stderr)
        self._get_connection_id()  # validates credentials early

        print("HubSpot adapter: fetching companies...", file=sys.stderr)
        raw_companies = self._get_all_objects("companies", _COMPANY_PROPS)
        atlas_companies, hs_id_to_atlas = self._transform_companies(raw_companies)
        print(f"  {len(atlas_companies)} companies", file=sys.stderr)

        print("HubSpot adapter: fetching contacts...", file=sys.stderr)
        raw_contacts = self._get_all_objects(
            "contacts", _CONTACT_PROPS, include_associations="companies"
        )
        atlas_contacts = self._transform_contacts(raw_contacts, hs_id_to_atlas)
        print(f"  {len(atlas_contacts)} contacts", file=sys.stderr)

        print("HubSpot adapter: fetching deals...", file=sys.stderr)
        raw_deals = self._get_all_objects(
            "deals", _DEAL_PROPS, include_associations="companies"
        )
        atlas_deals = self._transform_deals(raw_deals, hs_id_to_atlas)
        print(f"  {len(atlas_deals)} deals", file=sys.stderr)

        print("HubSpot adapter: fetching notes...", file=sys.stderr)
        raw_notes = self._get_all_objects("notes", _NOTE_PROPS)
        atlas_events = self._transform_notes(raw_notes)
        print(
            f"  {len(raw_notes)} notes → {len(atlas_events)} high-intent events",
            file=sys.stderr,
        )

        # Build the full entity dict; empty lists for HubSpot-absent entities
        empty: List = []
        return {
            # HubSpot-backed
            "companies": atlas_companies,
            "contacts": atlas_contacts,
            "deals": atlas_deals,
            "engagement_events": atlas_events,
            # HubSpot CRM does not carry these; empty is fine for eval
            "campaigns": empty,
            "campaign_performance": empty,
            "budget": empty,
            "actual_spend": empty,
            "branded_search": empty,
            "web_analytics": empty,
            "mentions": empty,
            "competitors": empty,
            "analyst_mentions": empty,
            "customer_reference_optins": empty,
            "product_launches": empty,
            "sdr_capacity": empty,
            # Optional entities — all absent from HubSpot at v1
            "forecasts": empty,
            "renewals": empty,
            "expansion_opportunities": empty,
            "forecast_log": empty,
            "renewal_at_risk_log": empty,
            "health_scores": empty,
            "cohorts": empty,
            "product_adoption": empty,
            "coverage_tier": empty,
            "executive_sponsor": empty,
            "competitive_intel": empty,
            "discovery_calls": empty,
            "icp_analysis": empty,
            "messaging_performance": empty,
            "launch_attribution": empty,
            "launch_enablement": empty,
            "earned_media": empty,
            "crm_hygiene": empty,
            "cs_exit_interviews": empty,
            "mb_paid_performance": empty,
            "mb_mql_sources": empty,
            "mb_inbound_demos": empty,
            "mb_seo_keywords": empty,
            "mb_organic_traffic": empty,
            "mb_content_attribution": empty,
            "mb_routing_ops": empty,
            "mb_attribution_accuracy": empty,
            "mb_mql_hygiene": empty,
            "mb_sales_enablement_assets": empty,
            "rg_deal_threads": empty,
            "rg_champion_status": empty,
            "rg_buying_committee": empty,
            "rg_pipeline_coverage": empty,
            "rg_win_rates": empty,
            "rg_deal_hygiene": empty,
            "rg_outbound_sequences": empty,
            "rg_competitive_coverage": empty,
            "rg_battlecard_usage": empty,
            "rg_expansion_flags": empty,
            # Revenue Developer — no HubSpot equivalent at v1
            "rd_inbound_speed": empty,
            "rd_sequence_perf": empty,
            "rd_subject_test": empty,
            "rd_segment_penetration": empty,
            "rd_intent_outreach": empty,
            "rd_ae_handoff": empty,
            "rd_linkedin_inbound": empty,
            "rd_call_timing": empty,
            "rd_dormant_reengagement": empty,
            "rd_enterprise_committee": empty,
            # Revenue Operator — no HubSpot equivalent at v1
            "ro_forecast_metrics": empty,
            "ro_pipeline_governance": empty,
            "ro_data_quality": empty,
            "ro_tool_sync": empty,
            "ro_stage_gate": empty,
            "ro_lead_routing": empty,
            "ro_attribution": empty,
            "ro_qbr_changes": empty,
            "ro_account_dedup": empty,
            "ro_deal_review_presence": empty,
            # Customer Advocate — no HubSpot equivalent at v1
            "ca_active_book": empty,
            "ca_renewal_pipeline": empty,
            "ca_early_renewals": empty,
            "ca_segment_grr": empty,
            "ca_lighthouse_qbr": empty,
            "ca_qbr_log": empty,
            "ca_onboarding": empty,
            "ca_advocate_pipeline": empty,
            # Customer Operator — no HubSpot equivalent at v1
            "co_health_model": empty,
            "co_playbook_ops": empty,
            "co_platform_integrations": empty,
            "co_segmentation": empty,
            "co_handoff_quality": empty,
            "co_benchmark": empty,
            "co_performance": empty,
            # Customer Technician — no HubSpot equivalent at v1
            "ct_ttfv_cohort": empty,
            "ct_go_live_velocity": empty,
            "ct_integration_and_activation": empty,
            "ct_handoff_quality": empty,
            "ct_nps": empty,
            "ct_support_and_blockers": empty,
            "ct_product_event": empty,
        }


# ---------------------------------------------------------------------------
# Convenience loader (called from relevance_engine.py)
# ---------------------------------------------------------------------------

def load_hubspot_dataset(
    api_key: str,
    entity_id: str = _DEFAULT_ENTITY_ID,
    connected_account_id: Optional[str] = None,
) -> Dict[str, list]:
    """Top-level entry point for relevance_engine.py --source hubspot-composio."""
    adapter = HubSpotComposioAdapter(
        api_key=api_key,
        entity_id=entity_id,
        connected_account_id=connected_account_id,
    )
    return adapter.fetch_dataset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_int(v) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "yes", "1")
    return bool(v)


def _date_str(v) -> str:
    """Return YYYY-MM-DD from ISO 8601 datetime or date string, or ''."""
    if not v:
        return ""
    return str(v)[:10]


def _normalize_lead_source(v: str) -> str:
    """Map HubSpot lead source values to Atlas values."""
    mapping = {
        "organic_search": "Inbound",
        "paid_search": "paid_search",
        "direct_traffic": "Inbound",
        "referrals": "Inbound",
        "social_media": "paid_social",
        "email_marketing": "email",
        "other_campaigns": "content",
        "": "",
    }
    return mapping.get(v.lower(), v)


def _parse_note_event_type(body: str) -> Optional[str]:
    """Recover Atlas event_type from Note body prefix (field map section 4)."""
    low = body.lower()
    for prefix, event_type in _NOTE_PREFIX_TO_EVENT_TYPE:
        if low.startswith(prefix):
            return event_type
    return None
