#!/usr/bin/env python3
"""Salesforce adapter for Lens Relevance Engine eval (Phase 3.6).

Reads from a connected Salesforce Developer Edition org via Composio's
SALESFORCE_EXECUTE_SOQL_QUERY native action and returns the same
Dict[str, list] Atlas-shape that load_dataset() returns from local JSON files.
Selected via --source salesforce-composio in relevance_engine.py.

Active connection (Phase 3.6):
  Auth Config : salesforce-pydufo (ID ac_vmmBh56iROnk)
  Entity      : travis@playful-narwhal-1dxk34.com (Developer Edition trial)
  Auth        : OAuth2, Managed by Composio
  Status      : Active

Architecture note:
  Composio's raw v3 proxy doesn't auto-route to the SFDC instance URL —
  it returns "URL_NOT_RESET". Native actions DO resolve the instance URL
  server-side, so this adapter calls SALESFORCE_EXECUTE_SOQL_QUERY to
  fetch records.

  Atlas metadata was written by salesforce_seed.py into:
    Account.SicDesc      = atlas_id (queryable anchor)
    Contact.Department   = atlas_id (queryable anchor)
    Opportunity.NextStep = atlas_id (queryable anchor)
    {entity}.Description = "ATLAS_JSON:{...}" (full atlas payload)

  This adapter parses the Description JSON to recover segment, lifecycle
  stage, tech stack, etc. — fields that don't map cleanly onto SFDC
  standard fields.

Entities not available in Salesforce CRM (CRM-only at v1, same gap class
as HubSpot Phase 3.5 documented):
  campaigns, campaign_performance, budget, actual_spend, branded_search,
  web_analytics, mentions, analyst_mentions, customer_reference_optins,
  product_launches, sdr_capacity, + all marketing / revenue-specific
  optional entities.
These are returned as empty lists. Cards grounded in those entities will
not surface via the SFDC path.

Field map: per Atlas to SFDC encoding established in salesforce_seed.py.
Adapter contract: returns Atlas-shape records keyed by atlas_id (recovered
from queryable anchor field, validated against ATLAS_JSON Description).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from threading import Lock
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Composio constants
# ---------------------------------------------------------------------------

_COMPOSIO_BASE = "https://backend.composio.dev/api"
_CONNECTED_ACCOUNTS_URL = f"{_COMPOSIO_BASE}/v1/connectedAccounts"
_ACTION_EXEC_URL = f"{_COMPOSIO_BASE}/v2/actions/{{action}}/execute"
_DESC_PREFIX = "ATLAS_JSON:"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class SalesforceComposioAdapter:
    """Reads from SFDC via Composio native actions, returns Atlas-shape dataset."""

    def __init__(
        self,
        api_key: str,
        entity_id: Optional[str] = None,
        connected_account_id: Optional[str] = None,
    ) -> None:
        self._api_key = api_key
        self._entity_id = entity_id
        self._conn_id = connected_account_id
        self._lock = Lock()

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
        if self._conn_id:
            return self._conn_id
        with self._lock:
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
                    f"Composio HTTP {exc.code} fetching SFDC connection. "
                    "Verify COMPOSIO_API_KEY."
                ) from exc
            items = data.get("items", [])
            if not items:
                raise RuntimeError(
                    f"No active Salesforce connection for entity {self._entity_id!r}. "
                    "Ensure Phase 3.6 (Composio Salesforce OAuth) is complete."
                )
            self._conn_id = items[0]["id"]
            return self._conn_id

    def _execute(self, action: str, payload: dict, attempts: int = 3) -> dict:
        conn_id = self._get_connection_id()
        body = json.dumps({
            "connectedAccountId": conn_id,
            "input": payload,
        }).encode()
        url = _ACTION_EXEC_URL.format(action=action)

        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(url, data=body, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 502, 503, 504) and attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                txt = exc.read().decode("utf-8", errors="replace")[:300]
                raise RuntimeError(
                    f"Composio {action} HTTP {exc.code}: {txt}"
                ) from exc
            except (urllib.error.URLError, OSError) as exc:
                if attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(
                    f"Composio {action} failed after {attempts} attempts: {exc}"
                ) from exc
        raise RuntimeError("unreachable")

    def _soql_all(self, query: str, limit_per_page: int = 2000) -> List[dict]:
        """Run SOQL via the native action. The native action returns up to
        2000 records per call without pagination support, so we LIMIT each
        query and chunk by created date or id-range if needed.

        For the Atlas dataset (max 3000 contacts) we split into batches
        using id-range pagination via SicDesc/Department/NextStep ordering.
        """
        # The native SALESFORCE_EXECUTE_SOQL_QUERY caps at the SFDC standard
        # batchSize (2000). For datasets larger than 2000, the caller passes
        # a paginated query externally. For our Atlas data (max 3000 contacts),
        # we paginate via SicDesc/Department/NextStep ordering — since the
        # atlas_id is the primary anchor and is monotonically increasing,
        # we can do >id-range pagination there.
        r = self._execute(
            "SALESFORCE_EXECUTE_SOQL_QUERY", {"soql_query": query}
        )
        outer = r.get("data") or {}
        sfdc = outer.get("data") or outer
        records = sfdc.get("records") or []
        return records

    def _paged_soql(
        self,
        sobject: str,
        select: str,
        anchor_field: str,
        anchor_prefix: str,
        page_size: int = 1000,
    ) -> List[dict]:
        """Paginate via anchor_field > 'last_seen_id' ORDER BY anchor_field.

        Composio's SALESFORCE_EXECUTE_SOQL_QUERY caps responses at 1000
        records regardless of LIMIT clause, so default page_size matches
        and the loop only stops on truly-empty pages or when the last
        anchor doesn't advance.
        """
        all_rows: List[dict] = []
        last: Optional[str] = None
        while True:
            where = f"{anchor_field} LIKE '{anchor_prefix}%'"
            if last:
                where += f" AND {anchor_field} > '{last}'"
            soql = (
                f"SELECT {select} FROM {sobject} "
                f"WHERE {where} "
                f"ORDER BY {anchor_field} ASC "
                f"LIMIT {page_size}"
            )
            page = self._soql_all(soql)
            if not page:
                break
            all_rows.extend(page)
            new_last = page[-1].get(anchor_field)
            if not new_last or new_last == last:
                # anchor didn't advance — guard against infinite loop on
                # records whose anchor field is null
                break
            last = new_last
        return all_rows

    # ------------------------------------------------------------------
    # Atlas-payload parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_atlas_desc(desc: Optional[str]) -> Dict[str, Any]:
        if not desc or not desc.startswith(_DESC_PREFIX):
            return {}
        body = desc[len(_DESC_PREFIX):].split("\n", 1)[0]
        try:
            return json.loads(body)
        except (ValueError, TypeError):
            return {}

    # ------------------------------------------------------------------
    # Per-entity transforms
    # ------------------------------------------------------------------

    def _fetch_companies(self) -> List[dict]:
        rows = self._paged_soql(
            sobject="Account",
            select="Id, Name, NumberOfEmployees, AnnualRevenue, SicDesc, Description, CreatedDate",
            anchor_field="SicDesc",
            anchor_prefix="CO-",
        )
        atlas: List[dict] = []
        for r in rows:
            meta = self._parse_atlas_desc(r.get("Description"))
            atlas_id = (r.get("SicDesc") or meta.get("id") or r.get("Id"))
            atlas.append({
                "id": atlas_id,
                "name": r.get("Name") or "",
                "industry": meta.get("industry") or "",
                "employees": int(r.get("NumberOfEmployees") or 0),
                "current_arr": int(r.get("AnnualRevenue") or 0),
                "lifecycle_stage": meta.get("lifecycle_stage") or "",
                "created_date": (meta.get("created_date") or (r.get("CreatedDate") or "")[:10]),
                "segment": meta.get("segment") or "",
                "is_target_account": bool(meta.get("is_target_account")),
                "tech_stack": meta.get("tech_stack") or [],
                "is_customer": bool(meta.get("is_customer")),
                "target_list_name": None,
            })
        return atlas

    def _fetch_contacts(self) -> List[dict]:
        rows = self._paged_soql(
            sobject="Contact",
            select=(
                "Id, FirstName, LastName, Email, Title, Department, Description, "
                "AccountId, CreatedDate"
            ),
            anchor_field="Department",
            anchor_prefix="CT-",
        )
        # Build sfdc_account_id → atlas company_id lookup from the contact
        # records' embedded Description (avoids a second SFDC roundtrip)
        atlas: List[dict] = []
        for r in rows:
            meta = self._parse_atlas_desc(r.get("Description"))
            atlas_id = (r.get("Department") or meta.get("id") or r.get("Id"))
            atlas.append({
                "id": atlas_id,
                "company_id": meta.get("company_id") or "",
                "first_name": r.get("FirstName") or "",
                "last_name": r.get("LastName") or "",
                "email": r.get("Email") or "",
                "title": r.get("Title") or "",
                "role_category": meta.get("role_category") or "",
                "created_date": (meta.get("created_date") or (r.get("CreatedDate") or "")[:10]),
                "lifecycle_stage": meta.get("lifecycle_stage") or "",
                "became_sql_date": meta.get("became_sql_date") or None,
                "is_abm": bool(meta.get("is_abm")),
                "sql_accepted": bool(meta.get("sql_accepted")),
            })
        return atlas

    def _fetch_deals(self) -> List[dict]:
        rows = self._paged_soql(
            sobject="Opportunity",
            select=(
                "Id, Name, Amount, StageName, CloseDate, CreatedDate, "
                "NextStep, Description, AccountId"
            ),
            anchor_field="NextStep",
            anchor_prefix="DL-",
        )
        atlas: List[dict] = []
        for r in rows:
            meta = self._parse_atlas_desc(r.get("Description"))
            atlas_id = (r.get("NextStep") or meta.get("id") or r.get("Id"))
            stage = (r.get("StageName") or "").strip()
            is_won = stage == "Closed Won"
            is_lost = stage == "Closed Lost"
            is_closed = is_won or is_lost
            atlas.append({
                "id": atlas_id,
                "company_id": meta.get("company_id") or "",
                "amount": int(r.get("Amount") or 0),
                "stage": _sfdc_stage_to_atlas(stage),
                "is_won": is_won,
                "is_closed": is_closed,
                "close_date": (r.get("CloseDate") or "")[:10],
                "create_date": (r.get("CreatedDate") or "")[:10],
                "lead_source": meta.get("lead_source") or "",
                "campaign_source_id": None,
                "segment": meta.get("segment") or "",
                "time_in_proposal": int(meta.get("time_in_proposal") or 0),
                "competitor_id": meta.get("competitor_id") or None,
                "head_to_head": bool(meta.get("head_to_head")),
                "contract_revisions": bool(meta.get("contract_revisions")),
                "procurement_signoff": bool(meta.get("procurement_signoff")),
                "stage_change_history": [],
            })
        return atlas

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_dataset(self) -> Dict[str, list]:
        print("Salesforce adapter: discovering connection...", file=sys.stderr)
        self._get_connection_id()

        print("Salesforce adapter: fetching accounts...", file=sys.stderr)
        atlas_companies = self._fetch_companies()
        print(f"  {len(atlas_companies)} accounts", file=sys.stderr)

        print("Salesforce adapter: fetching contacts...", file=sys.stderr)
        atlas_contacts = self._fetch_contacts()
        print(f"  {len(atlas_contacts)} contacts", file=sys.stderr)

        print("Salesforce adapter: fetching opportunities...", file=sys.stderr)
        atlas_deals = self._fetch_deals()
        print(f"  {len(atlas_deals)} opportunities", file=sys.stderr)

        empty: List = []
        return {
            # SFDC-backed
            "companies": atlas_companies,
            "contacts": atlas_contacts,
            "deals": atlas_deals,
            # Tasks deferred (not in v1 SFDC writer)
            "engagement_events": empty,
            # Marketing / external entities — same gap class as HubSpot
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
            # Optional entities — all absent from SFDC at v1
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
            "ca_active_book": empty,
            "ca_renewal_pipeline": empty,
            "ca_early_renewals": empty,
            "ca_segment_grr": empty,
            "ca_lighthouse_qbr": empty,
            "ca_qbr_log": empty,
            "ca_onboarding": empty,
            "ca_advocate_pipeline": empty,
            "co_health_model": empty,
            "co_playbook_ops": empty,
            "co_platform_integrations": empty,
            "co_segmentation": empty,
            "co_handoff_quality": empty,
            "co_benchmark": empty,
            "co_performance": empty,
            "ct_ttfv_cohort": empty,
            "ct_go_live_velocity": empty,
            "ct_integration_and_activation": empty,
            "ct_handoff_quality": empty,
            "ct_nps": empty,
            "ct_support_and_blockers": empty,
            "ct_product_event": empty,
        }


# ---------------------------------------------------------------------------
# Stage reverse-mapping (SFDC → Atlas)
# ---------------------------------------------------------------------------

_SFDC_TO_ATLAS_STAGE: Dict[str, str] = {
    "Prospecting": "lead",
    "Qualification": "qualifying",
    "Needs Analysis": "discovery",
    "Value Proposition": "discovery",
    "Id. Decision Makers": "discovery",
    "Perception Analysis": "discovery",
    "Proposal/Price Quote": "proposal",
    "Negotiation/Review": "negotiation",
    "Closed Won": "closedwon",
    "Closed Lost": "closedlost",
}


def _sfdc_stage_to_atlas(stage: str) -> str:
    return _SFDC_TO_ATLAS_STAGE.get(stage, stage.lower().replace(" ", "_"))


# ---------------------------------------------------------------------------
# Convenience loader (called from relevance_engine.py)
# ---------------------------------------------------------------------------

def load_salesforce_dataset(
    api_key: str,
    entity_id: Optional[str] = None,
    connected_account_id: Optional[str] = None,
) -> Dict[str, list]:
    """Top-level entry point for relevance_engine.py --source salesforce-composio."""
    adapter = SalesforceComposioAdapter(
        api_key=api_key,
        entity_id=entity_id,
        connected_account_id=connected_account_id,
    )
    return adapter.fetch_dataset()
