#!/usr/bin/env bash
# Prints one enriched record. Usage: bash scripts/show_target.sh <lead_id> [unmatched]
ST="stcrmleadskcm"; LEAD="$1"; PREFIX=""; [[ "${2:-}" == "unmatched" ]] && PREFIX="unmatched/"
az storage blob download --account-name "$ST" -c target -n "${PREFIX}crm_lead_enriched_${LEAD}.json" --auth-mode login -f /dev/stdout --no-progress 2>/dev/null | python3 -m json.tool
