#!/usr/bin/env bash
# =============================================================================
# create_monitoring.sh
# Creates the Phase 4 alerting for the pipeline (idempotent; safe to rerun):
#
#   ag-crmleads               action group: e-mail to the address given
#   alr-crmleads-failures     any failed function invocation in a 5-minute window
#   alr-crmleads-deadletter   any message in the dead-letter queue of sbq-lead-delay
#
#   bash infra/create_monitoring.sh you@example.com      # in Azure Cloud Shell
#
# Both alerts are metric alerts (no Log Analytics query cost): the first on the
# Application Insights metric requests/failed, which counts every function invocation
# that ended in an exception, HTTP-triggered or not; the second on the Service Bus
# namespace metric DeadletteredMessages for the delay queue.
# =============================================================================
set -euo pipefail

RG="rg-crmleads"
APPI="appi-crmleads-kcm"
SB_NAMESPACE="sb-crmleads-kcm"
SB_QUEUE="sbq-lead-delay"
ACTION_GROUP="ag-crmleads"
EMAIL="${1:-}"

log()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
skip() { printf '  exists: %s\n' "$*"; }

if [[ -z "$EMAIL" ]]; then
  echo "usage: bash infra/create_monitoring.sh <alert e-mail address>" >&2
  exit 2
fi

log "Action group $ACTION_GROUP -> $EMAIL"
if az monitor action-group show -n "$ACTION_GROUP" -g "$RG" --only-show-errors >/dev/null 2>&1; then
  skip "$ACTION_GROUP (e-mail receiver updated)"
  az monitor action-group update -n "$ACTION_GROUP" -g "$RG" \
    --add-action email owner "$EMAIL" --only-show-errors >/dev/null 2>&1 || true
else
  az monitor action-group create -n "$ACTION_GROUP" -g "$RG" --short-name crmleads \
    --action email owner "$EMAIL" --only-show-errors >/dev/null
fi
AG_ID=$(az monitor action-group show -n "$ACTION_GROUP" -g "$RG" --query id -o tsv)
APPI_ID=$(az monitor app-insights component show --app "$APPI" -g "$RG" --query id -o tsv)
SB_ID=$(az servicebus namespace show -n "$SB_NAMESPACE" -g "$RG" --query id -o tsv)

log "Alert alr-crmleads-failures (requests/failed > 0 in 5 minutes)"
if az monitor metrics alert show -n alr-crmleads-failures -g "$RG" --only-show-errors >/dev/null 2>&1; then
  skip "alr-crmleads-failures"
else
  az monitor metrics alert create -n alr-crmleads-failures -g "$RG" \
    --scopes "$APPI_ID" \
    --condition "count requests/failed > 0" \
    --window-size 5m --evaluation-frequency 5m --severity 2 \
    --description "A function invocation (receiver or enricher) ended in an exception." \
    --action "$AG_ID" --only-show-errors >/dev/null
fi

log "Alert alr-crmleads-deadletter (DeadletteredMessages > 0 on $SB_QUEUE)"
if az monitor metrics alert show -n alr-crmleads-deadletter -g "$RG" --only-show-errors >/dev/null 2>&1; then
  skip "alr-crmleads-deadletter"
else
  az monitor metrics alert create -n alr-crmleads-deadletter -g "$RG" \
    --scopes "$SB_ID" \
    --condition "avg DeadletteredMessages > 0 where EntityName includes $SB_QUEUE" \
    --window-size 5m --evaluation-frequency 5m --severity 1 \
    --description "A delay-queue message exceeded its delivery count. Run scripts/replay_dead_letter.py after fixing the cause." \
    --action "$AG_ID" --only-show-errors >/dev/null
fi

log "Monitoring in place"
az monitor metrics alert list -g "$RG" --query "[].{name:name, severity:severity, enabled:enabled}" -o table --only-show-errors
echo
echo "Azure sends a confirmation e-mail to $EMAIL the first time it is added to an action group."
