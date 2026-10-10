#!/usr/bin/env bash
# =============================================================================
# create_environment.sh
# Real-Time CRM Lead Processing and Notification System (Project 5)
#
# Creates every Azure resource in Section 8 of the architecture proposal.
# Idempotent: each step checks for the resource first, so the script can be
# rerun after a partial failure. Run from Azure Cloud Shell (bash):
#
#   export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...'
#   bash infra/create_environment.sh
#
# If SLACK_WEBHOOK_URL is not exported, the script prompts for it (input hidden).
# =============================================================================
set -euo pipefail

# ----------------------------------------------------------------------------
# Names (Section 8 of the proposal)
# ----------------------------------------------------------------------------
LOCATION="westus3"
RG="rg-crmleads"
STORAGE="stcrmleadskcm"          # ADLS Gen2: source, target, logs
FUNC_STORAGE="stcrmleadsfnkcm"   # Function host storage (no hierarchical namespace)
SB_NAMESPACE="sb-crmleads-kcm"
SB_QUEUE="sbq-lead-delay"
KEYVAULT="kv-crmleads-kcm"
LOG_WORKSPACE="log-crmleads-kcm"
APP_INSIGHTS="appi-crmleads-kcm"
FUNC_APP="func-crmleads-kcm"
LEAD_OWNER_BASE_URL="https://dea-lead-owner.s3.us-east-1.amazonaws.com"
TAGS="project=crm-lead-notifications owner=kcm"

log()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
skip() { printf '    exists: %s\n' "$*"; }

az config set extension.use_dynamic_install=yes_without_prompt --only-show-errors >/dev/null

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
MY_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)
log "Subscription $SUBSCRIPTION_ID, location $LOCATION"

# ----------------------------------------------------------------------------
# 0. Resource providers (a subscription that has never hosted a web app lacks Microsoft.Web)
# ----------------------------------------------------------------------------
log "0. Resource providers"
for ns in Microsoft.Storage Microsoft.ServiceBus Microsoft.KeyVault Microsoft.OperationalInsights Microsoft.Insights Microsoft.Web; do
  state=$(az provider show -n "$ns" --query registrationState -o tsv 2>/dev/null || echo Unknown)
  if [[ "$state" == "Registered" ]]; then skip "$ns"; else
    printf '    registering %s\n' "$ns"
    az provider register --namespace "$ns" --wait --only-show-errors >/dev/null
  fi
done

# ----------------------------------------------------------------------------
# Slack webhook URL (stored in Key Vault, never written to disk)
# ----------------------------------------------------------------------------
if [[ -z "${SLACK_WEBHOOK_URL:-}" ]]; then
  read -r -s -p "Slack incoming webhook URL: " SLACK_WEBHOOK_URL; echo
fi
if [[ "$SLACK_WEBHOOK_URL" != https://hooks.slack.com/* ]]; then
  echo "SLACK_WEBHOOK_URL does not look like a Slack incoming webhook URL." >&2; exit 1
fi

# ----------------------------------------------------------------------------
# 1. Resource group
# ----------------------------------------------------------------------------
log "1. Resource group $RG"
if az group show -n "$RG" --only-show-errors >/dev/null 2>&1; then skip "$RG"; else
  az group create -n "$RG" -l "$LOCATION" --tags $TAGS --only-show-errors >/dev/null
fi

# ----------------------------------------------------------------------------
# 2. Storage accounts and containers
# ----------------------------------------------------------------------------
log "2. Data lake storage $STORAGE (hierarchical namespace)"
if az storage account show -n "$STORAGE" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$STORAGE"; else
  az storage account create -n "$STORAGE" -g "$RG" -l "$LOCATION" \
    --sku Standard_LRS --kind StorageV2 --enable-hierarchical-namespace true \
    --min-tls-version TLS1_2 --allow-blob-public-access false --tags $TAGS \
    --only-show-errors >/dev/null
fi

# The signed-in user needs a data-plane role to create containers with --auth-mode login.
STORAGE_ID=$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)
az role assignment create --assignee-object-id "$MY_OBJECT_ID" --assignee-principal-type User \
  --role "Storage Blob Data Contributor" --scope "$STORAGE_ID" --only-show-errors >/dev/null 2>&1 || true

for c in source target logs; do
  if az storage container show -n "$c" --account-name "$STORAGE" --auth-mode login --only-show-errors >/dev/null 2>&1; then
    skip "container $c"
  else
    # Role propagation can take a minute; retry a few times.
    for attempt in 1 2 3 4 5 6; do
      if az storage container create -n "$c" --account-name "$STORAGE" --auth-mode login --only-show-errors >/dev/null 2>&1; then
        break
      fi
      [[ $attempt -eq 6 ]] && { echo "Could not create container $c" >&2; exit 1; }
      sleep 20
    done
  fi
done

log "2b. Function host storage $FUNC_STORAGE"
if az storage account show -n "$FUNC_STORAGE" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$FUNC_STORAGE"; else
  az storage account create -n "$FUNC_STORAGE" -g "$RG" -l "$LOCATION" \
    --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 \
    --allow-blob-public-access false --tags $TAGS --only-show-errors >/dev/null
fi

# ----------------------------------------------------------------------------
# 3. Service Bus namespace and delay queue
# ----------------------------------------------------------------------------
log "3. Service Bus $SB_NAMESPACE (Basic) and queue $SB_QUEUE"
if az servicebus namespace show -n "$SB_NAMESPACE" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$SB_NAMESPACE"; else
  az servicebus namespace create -n "$SB_NAMESPACE" -g "$RG" -l "$LOCATION" --sku Basic --tags $TAGS --only-show-errors >/dev/null
fi
if az servicebus queue show -n "$SB_QUEUE" --namespace-name "$SB_NAMESPACE" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$SB_QUEUE"; else
  az servicebus queue create -n "$SB_QUEUE" --namespace-name "$SB_NAMESPACE" -g "$RG" \
    --max-delivery-count 5 --lock-duration PT5M --default-message-time-to-live P14D \
    --enable-dead-lettering-on-message-expiration true --only-show-errors >/dev/null
fi
SB_ID=$(az servicebus namespace show -n "$SB_NAMESPACE" -g "$RG" --query id -o tsv)

# ----------------------------------------------------------------------------
# 4. Key Vault and secrets
# ----------------------------------------------------------------------------
log "4. Key Vault $KEYVAULT (RBAC)"
if az keyvault show -n "$KEYVAULT" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$KEYVAULT"; else
  if az keyvault list-deleted --query "[?name=='$KEYVAULT']" -o tsv --only-show-errors | grep -q "$KEYVAULT"; then
    log "   recovering soft-deleted vault $KEYVAULT"
    az keyvault recover -n "$KEYVAULT" --only-show-errors >/dev/null
  else
    az keyvault create -n "$KEYVAULT" -g "$RG" -l "$LOCATION" --enable-rbac-authorization true \
      --tags $TAGS --only-show-errors >/dev/null
  fi
fi
KV_ID=$(az keyvault show -n "$KEYVAULT" -g "$RG" --query id -o tsv)
az role assignment create --assignee-object-id "$MY_OBJECT_ID" --assignee-principal-type User \
  --role "Key Vault Secrets Officer" --scope "$KV_ID" --only-show-errors >/dev/null 2>&1 || true

set_secret() {  # name value
  for attempt in 1 2 3 4 5 6; do
    if az keyvault secret set --vault-name "$KEYVAULT" -n "$1" --value "$2" --only-show-errors >/dev/null 2>&1; then return 0; fi
    [[ $attempt -eq 6 ]] && { echo "Could not set secret $1" >&2; exit 1; }
    sleep 20
  done
}
set_secret slack-webhook-url "$SLACK_WEBHOOK_URL"
if ! az keyvault secret show --vault-name "$KEYVAULT" -n close-webhook-signature-key --only-show-errors >/dev/null 2>&1; then
  set_secret close-webhook-signature-key "PLACEHOLDER-REPLACE-IN-PHASE-5"
fi

# ----------------------------------------------------------------------------
# 5. Log Analytics and Application Insights
# ----------------------------------------------------------------------------
log "5. Log Analytics $LOG_WORKSPACE and Application Insights $APP_INSIGHTS"
if az monitor log-analytics workspace show -n "$LOG_WORKSPACE" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$LOG_WORKSPACE"; else
  az monitor log-analytics workspace create -n "$LOG_WORKSPACE" -g "$RG" -l "$LOCATION" --tags $TAGS --only-show-errors >/dev/null
fi
LOG_ID=$(az monitor log-analytics workspace show -n "$LOG_WORKSPACE" -g "$RG" --query id -o tsv)
if az monitor app-insights component show --app "$APP_INSIGHTS" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$APP_INSIGHTS"; else
  az monitor app-insights component create --app "$APP_INSIGHTS" -g "$RG" -l "$LOCATION" \
    --kind web --application-type web --workspace "$LOG_ID" --tags $TAGS --only-show-errors >/dev/null
fi
AI_CONN=$(az monitor app-insights component show --app "$APP_INSIGHTS" -g "$RG" --query connectionString -o tsv)

# ----------------------------------------------------------------------------
# 6. Function App (Linux Consumption, Python 3.11) with managed identity
# ----------------------------------------------------------------------------
log "6. Function App $FUNC_APP"
if az functionapp show -n "$FUNC_APP" -g "$RG" --only-show-errors >/dev/null 2>&1; then skip "$FUNC_APP"; else
  az functionapp create -n "$FUNC_APP" -g "$RG" --consumption-plan-location "$LOCATION" \
    --storage-account "$FUNC_STORAGE" --runtime python --runtime-version 3.11 \
    --functions-version 4 --os-type Linux --app-insights "$APP_INSIGHTS" \
    --tags $TAGS --only-show-errors >/dev/null
fi
PRINCIPAL_ID=$(az functionapp identity assign -n "$FUNC_APP" -g "$RG" --query principalId -o tsv)
log "   managed identity $PRINCIPAL_ID"

# ----------------------------------------------------------------------------
# 7. Role assignments for the Function App identity
# ----------------------------------------------------------------------------
log "7. Role assignments"
assign() {  # role scope
  az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
    --role "$1" --scope "$2" --only-show-errors >/dev/null 2>&1 && printf '    %s\n' "$1" || printf '    exists: %s\n' "$1"
}
assign "Storage Blob Data Contributor" "$STORAGE_ID"
assign "Azure Service Bus Data Sender" "$SB_ID"
assign "Azure Service Bus Data Receiver" "$SB_ID"
assign "Key Vault Secrets User" "$KV_ID"

# ----------------------------------------------------------------------------
# 8. Application settings (Key Vault references for secrets)
# ----------------------------------------------------------------------------
log "8. Application settings"
KV_URI="https://${KEYVAULT}.vault.azure.net/secrets"
az functionapp config appsettings set -n "$FUNC_APP" -g "$RG" --only-show-errors --settings \
  "APPLICATIONINSIGHTS_CONNECTION_STRING=$AI_CONN" \
  "STORAGE_ACCOUNT_URL=https://${STORAGE}.blob.core.windows.net" \
  "SOURCE_CONTAINER=source" \
  "TARGET_CONTAINER=target" \
  "SERVICEBUS_FQDN=${SB_NAMESPACE}.servicebus.windows.net" \
  "ServiceBusConnection__fullyQualifiedNamespace=${SB_NAMESPACE}.servicebus.windows.net" \
  "SERVICEBUS_QUEUE=$SB_QUEUE" \
  "LEAD_OWNER_BASE_URL=$LEAD_OWNER_BASE_URL" \
  "DELAY_MINUTES=10" \
  "RETRY_INTERVAL_MINUTES=5" \
  "MAX_LOOKUP_ATTEMPTS=4" \
  "VERIFY_SIGNATURE=false" \
  "SLACK_WEBHOOK_URL=@Microsoft.KeyVault(SecretUri=${KV_URI}/slack-webhook-url/)" \
  "CLOSE_WEBHOOK_SIGNATURE_KEY=@Microsoft.KeyVault(SecretUri=${KV_URI}/close-webhook-signature-key/)" \
  >/dev/null

# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------
HOST=$(az functionapp show -n "$FUNC_APP" -g "$RG" --query defaultHostName -o tsv)
log "Environment ready"
cat <<EOF

  Resource group      $RG ($LOCATION)
  Data lake           $STORAGE  (containers: source, target, logs)
  Function storage    $FUNC_STORAGE
  Service Bus         $SB_NAMESPACE / $SB_QUEUE
  Key Vault           $KEYVAULT  (slack-webhook-url, close-webhook-signature-key)
  App Insights        $APP_INSIGHTS  (workspace $LOG_WORKSPACE)
  Function App        $FUNC_APP
  Webhook endpoint    https://${HOST}/api/crm   (live after the Phase 2 deployment)

EOF
