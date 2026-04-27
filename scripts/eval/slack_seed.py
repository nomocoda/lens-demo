#!/usr/bin/env python3
"""Slack programmatic seeder via Composio native actions (Phase 3.7).

Posts synthetic threads in three #atlas-* channels of the nomocoda Slack
workspace so the engine has Atlas-related Slack content to consume:

  #atlas-sales-pipeline        sales motion: deal stage changes, blockers
  #atlas-customer-success      CS motion: renewals, health, support escalation
  #atlas-marketing-launches    marketing motion: campaign performance, content

Each message references Atlas accounts (CO-* / company names) and deals
(DL-*) by name pulled from the local synthetic dataset, so the engine can
do cross-system entity matching: "the Slack thread mentions 'Figueroa and
Sons' which the Salesforce account record knows is CO-00001."

Active connection (Phase 3.7):
  Auth Config : slack-* (lens-web onboarding flow)
  Entity      : <Clerk user ID> (lens-web's onboarding stores by Clerk id)
  Workspace   : nomocoda
  Status      : Active

Architecture note:
  Composio's native Slack actions handle workspace routing — same approach
  as the Salesforce path. SLACK_CREATE_CHANNEL is idempotent (returns the
  existing channel on name collision rather than failing). Messages are
  posted via SLACK_CHAT_POST_MESSAGE.

  For thread creation: post the parent message, then post replies with
  thread_ts set to the parent's ts. The seeder makes ~3 messages per
  thread to keep the data shape realistic.

Idempotency:
  Channel creation: SLACK_CREATE_CHANNEL on an existing name returns the
  channel — no need to check first.
  Messages: NOT idempotent. Re-running the seeder posts duplicates. Use
  --skip-if-not-empty to avoid noise on re-runs.

Usage:
  python3 scripts/eval/slack_seed.py                         # seed all 3 channels
  python3 scripts/eval/slack_seed.py --dry-run               # show plan, no posts
  python3 scripts/eval/slack_seed.py --channel sales-pipeline  # one channel only
  python3 scripts/eval/slack_seed.py --skip-if-not-empty     # skip if channel has messages
  python3 scripts/eval/slack_seed.py --threads N             # how many threads per channel (default 8)

Required env vars:
  COMPOSIO_API_KEY   from app.composio.dev/settings -> API Keys tab
  SLACK_ENTITY_ID    optional; else picks first ACTIVE Slack connection
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = ROOT / "scripts" / "eval"

_COMPOSIO_BASE = "https://backend.composio.dev/api"
_CONNECTED_ACCOUNTS_URL = f"{_COMPOSIO_BASE}/v1/connectedAccounts"
_ACTION_EXEC_URL = f"{_COMPOSIO_BASE}/v2/actions/{{action}}/execute"

_CHANNELS = {
    "atlas-sales-pipeline": "Sales-pipeline conversations about Atlas SaaS deals",
    "atlas-customer-success": "Customer-success motion for Atlas SaaS accounts",
    "atlas-marketing-launches": "Marketing launches and campaign chatter for Atlas SaaS",
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


def _load_atlas_companies() -> List[dict]:
    p = EVAL_DIR / "output" / "companies.json"
    if not p.exists():
        return []
    return json.loads(p.read_text())


def _load_atlas_deals() -> List[dict]:
    p = EVAL_DIR / "output" / "deals.json"
    if not p.exists():
        return []
    return json.loads(p.read_text())


# ---------------------------------------------------------------------------
# Composio client (native actions only, mirror of salesforce_seed)
# ---------------------------------------------------------------------------

class _Client:
    def __init__(self, api_key: str, entity_id: Optional[str] = None) -> None:
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

    def get_connection_id(self) -> str:
        if self._conn_id:
            return self._conn_id
        qs = "appName=slack&status=ACTIVE&limit=10"
        if self._entity_id:
            qs = f"entityId={urllib.parse.quote(self._entity_id)}&" + qs
        url = f"{_CONNECTED_ACCOUNTS_URL}?{qs}"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Composio HTTP {exc.code} fetching Slack connection") from exc

        # Composio's appName filter is loose — pick the actual slack connection
        items = [it for it in data.get("items", []) if it.get("appName") == "slack"]
        if not items:
            raise RuntimeError(
                "No active Slack connection in Composio. Connect Slack via "
                "lens-web onboarding or app.composio.dev → Auth Configs → Slack."
            )
        self._conn_id = items[0]["id"]
        ent = items[0].get("clientUniqueUserId") or "unknown"
        print(f"  Slack connection: {self._conn_id} (entity {ent})", flush=True)
        return self._conn_id

    def execute(self, action: str, input_payload: dict, attempts: int = 3) -> dict:
        conn_id = self.get_connection_id()
        body = json.dumps({
            "connectedAccountId": conn_id,
            "input": input_payload,
        }).encode()
        url = _ACTION_EXEC_URL.format(action=action)
        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(url, data=body, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 502, 503, 504) and attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                txt = exc.read().decode("utf-8", errors="replace")[:300]
                raise RuntimeError(f"Composio {action} HTTP {exc.code}: {txt}") from exc
            except (urllib.error.URLError, OSError) as exc:
                if attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"Composio {action} failed after {attempts} attempts: {exc}") from exc
        raise RuntimeError("unreachable")


def _unwrap(r: dict) -> dict:
    outer = r.get("data") or {}
    return outer.get("data") or outer.get("response_data") or outer


# ---------------------------------------------------------------------------
# Channel management
# ---------------------------------------------------------------------------

def list_channels(client: _Client) -> Dict[str, str]:
    """Return {channel_name: channel_id} for all visible channels."""
    out: Dict[str, str] = {}
    cursor: Optional[str] = None
    while True:
        payload = {"limit": 200}
        if cursor:
            payload["cursor"] = cursor
        r = client.execute("SLACK_LIST_CONVERSATIONS", payload)
        sfdc = _unwrap(r)
        chans = sfdc.get("channels") or []
        for c in chans:
            name = c.get("name")
            cid = c.get("id")
            if name and cid:
                out[name] = cid
        meta = sfdc.get("response_metadata") or {}
        cursor = meta.get("next_cursor")
        if not cursor:
            break
    return out


def ensure_channel(client: _Client, name: str, description: str, dry_run: bool) -> Optional[str]:
    """Create channel if absent. Returns channel_id (or None on dry-run/failure)."""
    if dry_run:
        print(f"  [DRY] would ensure #{name}")
        return f"dry-{name}"
    existing = list_channels(client)
    if name in existing:
        print(f"  exists  #{name} (id={existing[name]})")
        return existing[name]
    try:
        r = client.execute(
            "SLACK_CREATE_CHANNEL",
            {"name": name, "is_private": False, "description": description},
        )
        if not r.get("successful"):
            err = (r.get("error") or "")[:200]
            print(f"  WARN    #{name}: {err}")
            return None
        sfdc = _unwrap(r)
        ch = sfdc.get("channel") or sfdc
        cid = ch.get("id")
        if cid:
            print(f"  created #{name} (id={cid})")
            return cid
        print(f"  WARN    #{name}: no id in response")
    except RuntimeError as exc:
        print(f"  WARN    #{name}: {str(exc)[:200]}")
    return None


def channel_message_count(client: _Client, channel_id: str) -> int:
    """Best-effort count of recent messages via conversations.history."""
    r = client.execute(
        "SLACK_FETCH_CONVERSATION_HISTORY",
        {"channel": channel_id, "limit": 200},
    )
    sfdc = _unwrap(r)
    msgs = sfdc.get("messages") or []
    return len(msgs)


# ---------------------------------------------------------------------------
# Message generation
# ---------------------------------------------------------------------------

def _company_label(co: dict) -> str:
    return co.get("name") or co.get("id") or "an account"


def _deal_label(d: dict, co_lookup: Dict[str, dict]) -> str:
    co = co_lookup.get(d.get("company_id") or "", {})
    co_name = co.get("name") or "Unknown"
    amount = d.get("amount") or 0
    return f"{co_name} (${amount:,})"


_SALES_TEMPLATES = [
    "Status update on {deal}: stage moved to {stage} this morning. Next step is {next_step}.",
    "Heads up — {deal} just hit {stage}. Champion confirmed budget but procurement still pending.",
    "Decision committee scheduled for {deal} next week. {co} brought in their CFO; we should have the security questionnaire ready.",
    "{co} pushed back on pricing in last call. Counter-proposal going out today on {deal}.",
    "Closed won: {deal} 🎉. Implementation kickoff with {co} next Monday.",
    "Lost {deal} to incumbent. Notes: {co} cited integration complexity as primary blocker. Logging for win/loss review.",
    "{co} expansion conversation surfacing — current MRR strong, exec sponsor asking about platform tier.",
    "Demo with {co} tomorrow at 2pm. Use case: revenue ops automation. Tagging the SE for technical depth.",
]

_SALES_REPLIES = [
    "Got it. Updating the forecast.",
    "Will loop in legal.",
    "Calendar dropped, see you there.",
    "Adding to next 1:1 with the AE.",
    "Already on it — drafting the response now.",
    "Synced with the SE, we're ready.",
]


_CS_TEMPLATES = [
    "{co} renewal in 60 days. Health score yellow. Booking a QBR for next week to dig into adoption gaps.",
    "{co} support ticket #SF-{tk} flagged: SSO config breaking after their IdP migration. Engineering looped in.",
    "{co} expansion signal — they asked about adding a second seat tier. Worth a discovery call.",
    "{co} at risk: usage dropped 40% MoM after their internal reorg. Reaching out to confirm sponsor still in role.",
    "Onboarding for {co} crossed time-to-first-value milestone today. NPS survey going out next week.",
    "{co} renewed early — {amount} ARR locked for another year. Reference call confirmed for the marketing team.",
    "Escalation from {co}: report-builder UI bug blocking their weekly cadence. Severity 2, ETA on fix?",
    "QBR notes from {co}: they want to consolidate from 3 tools to 1, we're in the running. Following up with proposal.",
]

_CS_REPLIES = [
    "Adding to the renewal pipeline tracker.",
    "Eng acknowledged, ticket assigned.",
    "Will sync with the AE on expansion path.",
    "Health score updated, watching.",
    "Great — I'll get the case study going.",
    "Logged in the CS notes.",
]


_MARKETING_TEMPLATES = [
    "Campaign update: {camp} hit {target} pipeline contribution this week. Top accounts engaged: {co_a}, {co_b}.",
    "New whitepaper went live this morning — '{topic}'. First-day downloads: 47, with {co_a} and {co_b} on the list.",
    "Webinar with {co_a} as guest speaker confirmed for Tuesday. Registration page open.",
    "Paid media test on the {topic} angle: CTR up 18%, CPC stable. Reallocating budget from the {old_topic} variant.",
    "Field event in {city} next month — pulling target list. {co_a}, {co_b} both responded yes.",
    "ABM tier-1 list refresh done. Adding {co_a} (just hit ICP threshold) and removing {co_b} (closed lost).",
    "Content gap surfaced from sales: prospects asking about {topic} integration patterns. Drafting a pillar piece.",
    "Influencer placement landed — {influencer} mentioned us in their newsletter. Watching attribution.",
]

_MARKETING_REPLIES = [
    "Updating the dashboard.",
    "Will share with the AE team.",
    "Coordinating with design on the asset.",
    "Loving the angle, let's amplify.",
    "On it — posting in the launch channel too.",
    "Tagging product marketing for review.",
]


def _build_sales_threads(deals: List[dict], companies: List[dict], n: int, rng: random.Random) -> List[Tuple[str, List[str]]]:
    co_lookup = {c["id"]: c for c in companies}
    out: List[Tuple[str, List[str]]] = []
    sample = rng.sample([d for d in deals if d.get("amount", 0) > 10000], min(n, len(deals)))
    for d in sample:
        co = co_lookup.get(d.get("company_id") or "", {})
        ctx = {
            "deal": _deal_label(d, co_lookup),
            "co": _company_label(co),
            "stage": (d.get("stage") or "qualifying").replace("closedwon", "closed-won"),
            "next_step": rng.choice([
                "scope alignment",
                "security review",
                "exec readout",
                "MSA review",
                "POC sign-off",
            ]),
        }
        parent = rng.choice(_SALES_TEMPLATES).format(**ctx)
        replies = rng.sample(_SALES_REPLIES, k=rng.randint(1, 3))
        out.append((parent, replies))
    return out


def _build_cs_threads(companies: List[dict], n: int, rng: random.Random) -> List[Tuple[str, List[str]]]:
    customers = [c for c in companies if c.get("is_customer")]
    out: List[Tuple[str, List[str]]] = []
    sample = rng.sample(customers, min(n, len(customers)))
    for c in sample:
        ctx = {
            "co": _company_label(c),
            "tk": rng.randint(1000, 9999),
            "amount": f"${(c.get('current_arr') or 0):,}",
        }
        parent = rng.choice(_CS_TEMPLATES).format(**ctx)
        replies = rng.sample(_CS_REPLIES, k=rng.randint(1, 3))
        out.append((parent, replies))
    return out


def _build_marketing_threads(companies: List[dict], n: int, rng: random.Random) -> List[Tuple[str, List[str]]]:
    targets = [c for c in companies if c.get("is_target_account")]
    if len(targets) < 2:
        targets = companies[:20]
    topics = ["RevOps automation", "pipeline forecasting", "lifecycle scoring", "ABM attribution", "GTM tooling"]
    cities = ["NYC", "Austin", "London", "São Paulo", "Singapore"]
    influencers = ["Pete Kazanjy", "Kyle Lacy", "Jen Allen-Knuth", "Nate Nasralla"]
    out: List[Tuple[str, List[str]]] = []
    for _ in range(n):
        co_a, co_b = rng.sample(targets, 2)
        topic = rng.choice(topics)
        old_topic = rng.choice([t for t in topics if t != topic])
        ctx = {
            "camp": f"Q2 {topic} push",
            "target": rng.choice(["68%", "112%", "94%", "85%"]),
            "co_a": _company_label(co_a),
            "co_b": _company_label(co_b),
            "topic": topic,
            "old_topic": old_topic,
            "city": rng.choice(cities),
            "influencer": rng.choice(influencers),
        }
        parent = rng.choice(_MARKETING_TEMPLATES).format(**ctx)
        replies = rng.sample(_MARKETING_REPLIES, k=rng.randint(1, 3))
        out.append((parent, replies))
    return out


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------

def post_thread(
    client: _Client,
    channel_id: str,
    parent_text: str,
    reply_texts: List[str],
    dry_run: bool,
) -> Optional[str]:
    """Post parent + replies as a thread. Returns parent ts."""
    if dry_run:
        print(f"  [DRY] post '{parent_text[:80]}...' + {len(reply_texts)} replies")
        return "dry-ts"
    try:
        r = client.execute(
            "SLACK_CHAT_POST_MESSAGE",
            {"channel": channel_id, "text": parent_text},
        )
        sfdc = _unwrap(r)
        parent_ts = sfdc.get("ts") or sfdc.get("message", {}).get("ts")
        if not parent_ts:
            print(f"  WARN: no ts for parent message: {str(sfdc)[:160]}")
            return None
    except RuntimeError as exc:
        print(f"  WARN: parent post failed: {str(exc)[:200]}")
        return None

    for reply in reply_texts:
        try:
            client.execute(
                "SLACK_CHAT_POST_MESSAGE",
                {"channel": channel_id, "text": reply, "thread_ts": parent_ts},
            )
        except RuntimeError as exc:
            print(f"  WARN: reply post failed: {str(exc)[:160]}")
        time.sleep(0.3)
    return parent_ts


# ---------------------------------------------------------------------------
# Per-channel orchestration
# ---------------------------------------------------------------------------

def seed_channel(
    client: _Client,
    channel_short: str,
    description: str,
    threads: List[Tuple[str, List[str]]],
    skip_if_not_empty: bool,
    dry_run: bool,
) -> int:
    print(f"\n--- #{channel_short} ({len(threads)} threads) ---")
    cid = ensure_channel(client, channel_short, description, dry_run)
    if not cid:
        return 0

    if skip_if_not_empty and not dry_run:
        n_existing = channel_message_count(client, cid)
        if n_existing > 0:
            print(f"  skipping — channel already has {n_existing} messages")
            return 0

    posted = 0
    for parent, replies in threads:
        ts = post_thread(client, cid, parent, replies, dry_run)
        if ts:
            posted += 1
        time.sleep(0.5)
    print(f"  posted {posted}/{len(threads)} threads")
    return posted


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Slack seeder via Composio native actions")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be posted without making API calls")
    ap.add_argument("--threads", type=int, default=8,
                    help="Threads per channel (default 8)")
    ap.add_argument("--skip-if-not-empty", action="store_true",
                    help="Skip a channel if it already has any messages")
    ap.add_argument("--channel", choices=list(_CHANNELS.keys()) + [k.replace("atlas-", "") for k in _CHANNELS],
                    default=None,
                    help="Limit to a single channel")
    ap.add_argument("--seed", type=int, default=42,
                    help="RNG seed for reproducible message text (default 42)")
    args = ap.parse_args(argv)

    api_key = os.environ.get("COMPOSIO_API_KEY") or _load_env_key("COMPOSIO_API_KEY")
    if not api_key and not args.dry_run:
        print("ERROR: COMPOSIO_API_KEY not found", file=sys.stderr)
        return 1
    entity_id = (
        os.environ.get("SLACK_ENTITY_ID")
        or _load_env_key("SLACK_ENTITY_ID")
    )

    client = _Client(api_key or "dry-run-placeholder", entity_id)
    rng = random.Random(args.seed)

    companies = _load_atlas_companies()
    deals = _load_atlas_deals()
    if not companies or not deals:
        print("ERROR: Atlas dataset missing. Generate via generate_dataset.py first.", file=sys.stderr)
        return 1
    print(f"Atlas dataset: {len(companies)} companies, {len(deals)} deals")

    channel_filter = args.channel
    if channel_filter and not channel_filter.startswith("atlas-"):
        channel_filter = f"atlas-{channel_filter}"

    plan: List[Tuple[str, str, List[Tuple[str, List[str]]]]] = []
    for name, desc in _CHANNELS.items():
        if channel_filter and name != channel_filter:
            continue
        if name == "atlas-sales-pipeline":
            threads = _build_sales_threads(deals, companies, args.threads, rng)
        elif name == "atlas-customer-success":
            threads = _build_cs_threads(companies, args.threads, rng)
        elif name == "atlas-marketing-launches":
            threads = _build_marketing_threads(companies, args.threads, rng)
        else:
            threads = []
        plan.append((name, desc, threads))

    if args.dry_run:
        print("\n[DRY-RUN MODE] No posts will be made.")

    total = 0
    for name, desc, threads in plan:
        total += seed_channel(client, name, desc, threads, args.skip_if_not_empty, args.dry_run)

    print(f"\nDone. {total} threads posted across {len(plan)} channel(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
