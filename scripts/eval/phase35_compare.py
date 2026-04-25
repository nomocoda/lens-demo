#!/usr/bin/env python3
"""Phase 3.5 comparison: HubSpot-sourced card counts vs local-JSON baseline."""

import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).parent

# Local JSON baseline: canonical seed42 file per archetype
LOCAL_BASELINE = {
    "marketing":           "generated_cards_seed42.json",           # 16 expected
    "marketing_strategist": "generated_cards_marketing_strategist_seed42.json",
    "marketing_builder":   "generated_cards_marketing_builder_seed42.json",
    "revenue":             "generated_cards_revenue_seed42.json",
    "revenue_generator":   "generated_cards_rg_seed42.json",
    "revenue_developer":   "generated_cards_revenue_developer_seed42.json",
    "revenue_operator":    "generated_cards_ro_seed42.json",
    "customer":            "generated_cards_customer_seed42.json",
    "customer_advocate":   "generated_cards_ca_seed42.json",
    "customer_operator":   "generated_cards_customer_operator_seed42.json",
    "customer_technician": "generated_cards_customer_technician_seed42.json",
}

# HubSpot output files (written by relevance_engine.py --source hubspot-composio)
HUBSPOT_OUTPUT = {
    "marketing":           "generated_cards_marketing_hubspot_seed42.json",
    "marketing_strategist": "generated_cards_marketing_strategist_hubspot_seed42.json",
    "marketing_builder":   "generated_cards_marketing_builder_hubspot_seed42.json",
    "revenue":             "generated_cards_revenue_hubspot_seed42.json",
    "revenue_generator":   "generated_cards_revenue_generator_hubspot_seed42.json",
    "revenue_developer":   "generated_cards_revenue_developer_hubspot_seed42.json",
    "revenue_operator":    "generated_cards_revenue_operator_hubspot_seed42.json",
    "customer":            "generated_cards_customer_hubspot_seed42.json",
    "customer_advocate":   "generated_cards_customer_advocate_hubspot_seed42.json",
    "customer_operator":   "generated_cards_customer_operator_hubspot_seed42.json",
    "customer_technician": "generated_cards_customer_technician_hubspot_seed42.json",
}

def count_cards(path: Path) -> int:
    if not path.exists():
        return -1
    try:
        data = json.loads(path.read_text())
        return len(data)
    except Exception:
        return -1

print("=== Phase 3.5 Comparison: HubSpot vs Local JSON Baseline (seed 42) ===\n")
print(f"{'Archetype':<22} {'Local':>6} {'HubSpot':>8} {'Delta':>6} {'Coverage':>9}")
print("-" * 57)

total_local = 0
total_hubspot = 0
missing = []

for archetype in LOCAL_BASELINE:
    local_path = EVAL_DIR / LOCAL_BASELINE[archetype]
    hs_path = EVAL_DIR / HUBSPOT_OUTPUT[archetype]

    local_n = count_cards(local_path)
    hs_n = count_cards(hs_path)

    if hs_n == -1:
        print(f"{archetype:<22} {local_n:>6}  {'MISSING':>8}")
        missing.append(archetype)
        if local_n > 0:
            total_local += local_n
        continue

    delta = hs_n - local_n
    coverage = f"{hs_n * 100 // local_n}%" if local_n > 0 else "n/a"
    delta_str = f"{delta:+d}"
    total_local += local_n
    total_hubspot += hs_n

    print(f"{archetype:<22} {local_n:>6} {hs_n:>8} {delta_str:>6} {coverage:>9}")

print("-" * 57)
if total_local > 0:
    total_pct = f"{total_hubspot * 100 // total_local}%"
    print(f"{'TOTAL':<22} {total_local:>6} {total_hubspot:>8} {total_hubspot - total_local:>+6} {total_pct:>9}")

if missing:
    print(f"\nMissing HubSpot output for: {', '.join(missing)}")
    print("Run: python3 relevance_engine.py --source hubspot-composio --archetype <name> --seed 42")
    print("     --output generated_cards_<name>_hubspot_seed42.json")
