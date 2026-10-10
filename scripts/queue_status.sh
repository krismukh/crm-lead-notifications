#!/usr/bin/env bash
# Prints queue counts and the latest target records. Run in Cloud Shell.
RG="rg-crmleads"; SB="sb-crmleads-kcm"; Q="sbq-lead-delay"; ST="stcrmleadskcm"
echo "Queue $Q"
az servicebus queue show -g "$RG" --namespace-name "$SB" -n "$Q" \
  --query "countDetails.{scheduled:scheduledMessageCount, active:activeMessageCount, deadLetter:deadLetterMessageCount}" -o table
echo; echo "source"
az storage blob list --account-name "$ST" -c source --auth-mode login --query "[].{name:name, modified:properties.lastModified}" -o table
echo; echo "target"
az storage blob list --account-name "$ST" -c target --auth-mode login --query "[].{name:name, modified:properties.lastModified, lookup:metadata.lookup_status}" -o table
