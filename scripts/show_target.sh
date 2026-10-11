#!/usr/bin/env bash
# Prints one enriched record. Usage: bash scripts/show_target.sh <lead_id> [unmatched]
set -euo pipefail
ST="stcrmleadskcm"; LEAD="${1:?usage: show_target.sh <lead_id> [unmatched]}"
PREFIX=""; [[ "${2:-}" == "unmatched" ]] && PREFIX="unmatched/"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
az storage blob download --account-name "$ST" -c target -n "${PREFIX}crm_lead_enriched_${LEAD}.json" \
  --auth-mode login -f "$TMP" --no-progress --only-show-errors >/dev/null
python3 -m json.tool "$TMP"
