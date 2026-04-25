#!/usr/bin/env bash
# Phase 3.5: Run all 11 Delivery Archetypes via --source hubspot-composio
# Retries up to 3x on voice-violation exit (code 3).
# Writes per-archetype card counts to stdout for comparison table.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEED=42
MAX_ATTEMPTS=3

declare -A LOCAL_BASELINE=(
  ["marketing"]=16
  ["marketing_strategist"]=15
  ["marketing_builder"]=15
  ["revenue"]=15
  ["revenue_generator"]=18
  ["revenue_developer"]=15
  ["revenue_operator"]=15
  ["customer"]=19
  ["customer_advocate"]=21
  ["customer_operator"]=20
  ["customer_technician"]=18
)

ARCHETYPES=(
  marketing
  marketing_strategist
  marketing_builder
  revenue
  revenue_generator
  revenue_developer
  revenue_operator
  customer
  customer_advocate
  customer_operator
  customer_technician
)

echo "=== Phase 3.5 HubSpot Eval Run ==="
echo "Seed: $SEED"
echo ""

for archetype in "${ARCHETYPES[@]}"; do
  local_cards="${LOCAL_BASELINE[$archetype]}"
  hubspot_cards=0
  status="FAIL"
  attempts=0

  out_file="$SCRIPT_DIR/generated_cards_${archetype}_hubspot_seed${SEED}.json"

  for attempt in $(seq 1 $MAX_ATTEMPTS); do
    attempts=$attempt
    output=$(python3 "$SCRIPT_DIR/relevance_engine.py" \
      --source hubspot-composio \
      --archetype "$archetype" \
      --seed "$SEED" \
      --output "$out_file" 2>&1)
    exit_code=$?

    if [ $exit_code -eq 0 ]; then
      # Extract card count from "Wrote N cards to ..."
      hubspot_cards=$(echo "$output" | grep -oP 'Wrote \K[0-9]+' | tail -1 || echo 0)
      status="PASS"
      break
    elif [ $exit_code -eq 3 ]; then
      # Voice violation — retry
      :
    else
      # Other error — don't retry
      status="ERROR($exit_code)"
      break
    fi
  done

  if [ "$status" = "FAIL" ]; then
    echo "$archetype | local=$local_cards | hubspot=FAIL($attempts attempts)"
  elif [ "$status" = "PASS" ]; then
    delta=$((hubspot_cards - local_cards))
    pct=$(echo "scale=0; $hubspot_cards * 100 / $local_cards" | bc)
    echo "$archetype | local=$local_cards | hubspot=$hubspot_cards | delta=$delta | coverage=${pct}%"
  else
    echo "$archetype | local=$local_cards | hubspot=$status"
  fi
done
