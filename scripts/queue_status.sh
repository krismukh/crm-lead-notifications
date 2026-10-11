#!/usr/bin/env bash
# Prints queue counts and the source/target listings. Run in Cloud Shell.
RG="rg-crmleads"; SB="sb-crmleads-kcm"; Q="sbq-lead-delay"; ST="stcrmleadskcm"
echo "Queue $Q"
az servicebus queue show -g "$RG" --namespace-name "$SB" -n "$Q" \
  --query "countDetails.{scheduled:scheduledMessageCount, active:activeMessageCount, deadLetter:deadLetterMessageCount}" -o table
echo; echo "source (newest 10)"
az storage blob list --account-name "$ST" -c source --auth-mode login --only-show-errors \
  --query "reverse(sort_by([], &properties.lastModified))[:10].{name:name, modified:properties.lastModified}" -o table
echo; echo "target (newest 10)"
az storage blob list --account-name "$ST" -c target --auth-mode login --only-show-errors \
  --query "reverse(sort_by([], &properties.lastModified))[:10].{name:name, modified:properties.lastModified}" -o table
