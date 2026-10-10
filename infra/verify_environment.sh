#!/usr/bin/env bash
# Prints the state of every Phase 1 resource and the Function App identity's roles.
# Run from Azure Cloud Shell:  bash infra/verify_environment.sh
set -uo pipefail
RG="rg-crmleads"; STORAGE="stcrmleadskcm"; SB="sb-crmleads-kcm"; Q="sbq-lead-delay"
KV="kv-crmleads-kcm"; AI="appi-crmleads-kcm"; FUNC="func-crmleads-kcm"

echo "Resources in $RG"
az resource list -g "$RG" --query "[].{name:name, type:type, location:location}" -o table

echo; echo "Containers in $STORAGE"
az storage container list --account-name "$STORAGE" --auth-mode login --query "[].name" -o tsv

echo; echo "Queue $Q"
az servicebus queue show -n "$Q" --namespace-name "$SB" -g "$RG" \
  --query "{maxDeliveryCount:maxDeliveryCount, lockDuration:lockDuration, ttl:defaultMessageTimeToLive, deadLetterOnExpiry:deadLetteringOnMessageExpiration, status:status}" -o table

echo; echo "Key Vault secrets"
az keyvault secret list --vault-name "$KV" --query "[].name" -o tsv

echo; echo "Function App"
az functionapp show -n "$FUNC" -g "$RG" --query "{state:state, host:defaultHostName, runtime:siteConfig.linuxFxVersion, identity:identity.principalId}" -o table

PID=$(az functionapp show -n "$FUNC" -g "$RG" --query identity.principalId -o tsv)
echo; echo "Roles held by the Function App identity"
az role assignment list --assignee "$PID" --all --query "[].{role:roleDefinitionName, scope:scope}" -o table

echo; echo "Key Vault references resolved by the Function App (should show status Resolved)"
az functionapp config appsettings list -n "$FUNC" -g "$RG" \
  --query "[?starts_with(value, '@Microsoft.KeyVault')].{name:name}" -o table
az rest --method get \
  --url "https://management.azure.com/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG/providers/Microsoft.Web/sites/$FUNC/config/configreferences/appsettings?api-version=2022-03-01" \
  --query "value[].{setting:name, status:properties.status}" -o table 2>/dev/null || echo "(reference status not available yet)"
