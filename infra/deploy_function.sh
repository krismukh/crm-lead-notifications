#!/usr/bin/env bash
# =============================================================================
# deploy_function.sh
# Zip-deploys the Function App project in src/ to func-crmleads-kcm with a remote
# build (pip install runs on the Azure side), so no Functions Core Tools are needed.
#
#   bash infra/deploy_function.sh            # from the repository root, in Cloud Shell
#
# Afterwards prints the function key and the full webhook URL.
# =============================================================================
set -euo pipefail

RG="rg-crmleads"
FUNC_APP="func-crmleads-kcm"
SRC_DIR="$(cd "$(dirname "$0")/../src" && pwd)"
ZIP="/tmp/${FUNC_APP}.zip"

log() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

log "Packaging $SRC_DIR"
rm -f "$ZIP"
(cd "$SRC_DIR" && zip -qr "$ZIP" . -x '*.pyc' -x '__pycache__/*' -x '.venv/*' \
   -x 'local.settings.json' -x 'local.settings.json.example' -x '.pytest_cache/*')
ls -l "$ZIP"

log "Enabling remote build"
az functionapp config appsettings set -n "$FUNC_APP" -g "$RG" --only-show-errors --settings \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true ENABLE_ORYX_BUILD=true >/dev/null

log "Deploying (remote build; allow 2 to 5 minutes)"
az functionapp deployment source config-zip -n "$FUNC_APP" -g "$RG" --src "$ZIP" \
  --build-remote true --timeout 600 --only-show-errors >/dev/null

log "Functions registered on the app"
for attempt in 1 2 3 4 5 6; do
  if az functionapp function list -n "$FUNC_APP" -g "$RG" --query "[].name" -o tsv --only-show-errors 2>/dev/null | grep -q fn_webhook_receiver; then
    az functionapp function list -n "$FUNC_APP" -g "$RG" --query "[].{name:name, trigger:config.bindings[0].type}" -o table --only-show-errors
    break
  fi
  [[ $attempt -eq 6 ]] && { echo "fn_webhook_receiver not listed yet; check the deployment log in the portal (Deployment Center)." >&2; exit 1; }
  sleep 15
done

HOST=$(az functionapp show -n "$FUNC_APP" -g "$RG" --query defaultHostName -o tsv)
KEY=$(az functionapp function keys list -n "$FUNC_APP" -g "$RG" --function-name fn_webhook_receiver --query default -o tsv --only-show-errors)

log "Endpoints"
cat <<EOF

  Health   https://${HOST}/api/health
  Webhook  https://${HOST}/api/crm?code=${KEY}

  The code= value is the function key: treat it as a secret. It is what the Close
  subscription URL will carry until signature verification is switched on.

EOF
