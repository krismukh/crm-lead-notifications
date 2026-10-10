# Phase 1: Environment

`infra/create_environment.sh` creates every resource in Section 8 of the proposal. It is
idempotent: rerunning it after a partial failure skips what already exists.

## Resources created

| Resource | Name | Notes |
|---|---|---|
| Resource group | `rg-crmleads` | West US 3 |
| Data lake storage | `stcrmleadskcm` | ADLS Gen2 (hierarchical namespace); containers `source`, `target`, `logs`; public blob access off |
| Function host storage | `stcrmleadsfnkcm` | Required by the Functions runtime, which does not support hierarchical-namespace accounts for its own state |
| Service Bus | `sb-crmleads-kcm` (Basic), queue `sbq-lead-delay` | Max delivery count 5, lock 5 min, TTL 14 days, dead-letter on expiry |
| Key Vault | `kv-crmleads-kcm` | RBAC mode; secrets `slack-webhook-url` and `close-webhook-signature-key` (placeholder until Phase 5) |
| Log Analytics | `log-crmleads-kcm` | Backing workspace for Application Insights |
| Application Insights | `appi-crmleads-kcm` | Workspace-based |
| Function App | `func-crmleads-kcm` | Linux Consumption, Python 3.11, Functions v4, system-assigned identity |

Role assignments on the Function App identity: Storage Blob Data Contributor
(`stcrmleadskcm`), Azure Service Bus Data Sender and Data Receiver (`sb-crmleads-kcm`),
Key Vault Secrets User (`kv-crmleads-kcm`). The signed-in user receives Storage Blob Data
Contributor and Key Vault Secrets Officer so that the script can create containers and
secrets.

Application settings written to the Function App (consumed by the code in Phases 2 and 3):

| Setting | Value |
|---|---|
| `STORAGE_ACCOUNT_URL` | `https://stcrmleadskcm.blob.core.windows.net` |
| `SOURCE_CONTAINER`, `TARGET_CONTAINER` | `source`, `target` |
| `SERVICEBUS_FQDN`, `SERVICEBUS_QUEUE` | `sb-crmleads-kcm.servicebus.windows.net`, `sbq-lead-delay` |
| `ServiceBusConnection__fullyQualifiedNamespace` | Identity-based connection for the Service Bus trigger |
| `LEAD_OWNER_BASE_URL` | `https://dea-lead-owner.s3.us-east-1.amazonaws.com` |
| `DELAY_MINUTES`, `RETRY_INTERVAL_MINUTES`, `MAX_LOOKUP_ATTEMPTS` | `10`, `5`, `4` (one initial attempt plus three retries) |
| `VERIFY_SIGNATURE` | `false` until the Close signature key is available (Phase 5) |
| `SLACK_WEBHOOK_URL`, `CLOSE_WEBHOOK_SIGNATURE_KEY` | Key Vault references |

No connection strings or keys are stored in application settings; all access is through
the managed identity.

## Running the script

1. Open Azure Cloud Shell (bash) at https://shell.azure.com in the Pay-As-You-Go
   subscription. Confirm with `az account show --query name`.
2. Upload `infra/create_environment.sh` with the Cloud Shell upload button, or clone the
   repository: `git clone https://github.com/krismukh/crm-lead-notifications.git && cd crm-lead-notifications`.
3. Export the Slack webhook URL from `.env` on your workstation (copy the value, do not
   upload the file), then run:
   ```
   export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...'
   bash infra/create_environment.sh
   ```
   If the variable is not exported, the script prompts for it with hidden input.
4. Expected runtime: 6 to 10 minutes, most of it the Function App and Application
   Insights creation. Role propagation pauses of up to two minutes are built in.
5. Run `bash infra/verify_environment.sh` and keep the output for the README.

## Verification checklist

- [ ] `az resource list -g rg-crmleads` shows 8 resources (2 storage accounts, Service
      Bus namespace, Key Vault, Log Analytics workspace, Application Insights, App Service
      plan, Function App)
- [ ] Containers `source`, `target`, `logs` exist in `stcrmleadskcm`
- [ ] Queue `sbq-lead-delay` shows max delivery count 5 and status Active
- [ ] Key Vault lists both secrets
- [ ] Function App state is Running and the identity holds the four roles
- [ ] Key Vault references show status Resolved (may take a few minutes after the roles
      are assigned; rerun `verify_environment.sh` if they show an error at first)

## Known issues

- **Key Vault name conflict.** Vault names are global and soft-deleted vaults keep their
  name for 90 days. The script recovers a soft-deleted `kv-crmleads-kcm` automatically.
  If the name is held by someone else, change `KEYVAULT` in the script and the
  `.env.example` note.
- **Consumption plan availability.** If `az functionapp create` reports that the
  Consumption plan is not available in West US 3, add `--flexconsumption-location`
  in place of `--consumption-plan-location` to use the Flex Consumption plan; nothing
  else in the design changes.
- **Role propagation.** Azure RBAC assignments can take one to two minutes to take
  effect. The script retries container creation and secret creation; if a later step
  fails with an authorization error, rerun the script.

## Exit criteria

- [ ] All verification checks pass
- [ ] `infra/` scripts committed and pushed
- [ ] README status table updated (Phase 1 complete)
- [ ] Cost check: Azure portal cost analysis for `rg-crmleads` after 24 hours shows only
      Service Bus, storage, and Log Analytics charges (expected under $0.20 per day)
