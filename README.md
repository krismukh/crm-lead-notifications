# Real-Time CRM Lead Processing and Notification System

Data Engineering Project 5. Azure implementation of the automated lead assignment and
notification requirements: a Close CRM webhook is captured in real time, held for ten
minutes while the CRM assigns a lead owner, enriched from the lead-owner lookup, stored,
and announced to the sales team in Slack.

Author: Krishna C. Mukherjee

Status: complete. Validated in production with 319 live leads on October 16, 2026;
see `docs/validation_report.md`.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Preparation: Slack channel and webhook, repository, decision log, sample data | Complete |
| 1 | Environment: `infra/create_environment.sh` | Complete |
| 2 | Webhook receiver function | Complete |
| 3 | Enrichment and notification function | Complete |
| 4 | CI/CD, observability, operations | Complete |
| 5 | Webhook subscription and validation with live leads | Complete |

## Architecture

![Architecture](docs/CRM_Lead_Pipeline_Architecture.png)

Close CRM posts a `lead.created` event to an HTTP-triggered Azure Function, which verifies
the signature, writes the event to the `source` container as `crm_event_{lead_id}.json`,
and schedules a Service Bus message for ten minutes later. When the message becomes
visible, a second function reads the event, fetches `{lead_id}.json` from the public
lead-owner bucket, merges the two records on `lead_id`, writes
`crm_lead_enriched_{lead_id}.json` to the `target` container, and posts a New Lead Alert
to Slack. The full design is in `docs/CRM_Lead_Processing_Architecture_Proposal.docx`;
every design decision since is in `docs/decision_log.md`.

| Brief (AWS) | This implementation (Azure) |
|---|---|
| Lambda webhook receiver | `fn_webhook_receiver`, HTTP trigger, `POST /api/crm` |
| S3 source bucket | ADLS Gen2 `stcrmleadskcm`, container `source` |
| SQS queue with 10-minute delay | Service Bus queue `sbq-lead-delay`, scheduled messages |
| Lambda enrichment | `fn_lead_enricher`, Service Bus trigger |
| S3 target bucket | container `target` (`unmatched/` prefix for Unassigned leads) |
| Lead-owner lookup bucket | unchanged: public bucket `dea-lead-owner` over HTTPS |
| Slack or e-mail alert | Slack incoming webhook, channel `#new-lead-alerts` |
| Secrets Manager | Key Vault `kv-crmleads-kcm`, Key Vault references in app settings |
| CloudWatch | Application Insights `appi-crmleads-kcm`, two metric alerts |

## How a lead flows

1. **Receive** (`fn_webhook_receiver`). Verifies the Close signature when
   `VERIFY_SIGNATURE=true`, accepts only `object_type = lead` and `action = created`,
   writes the raw event to `source/`, schedules a delay message for
   `received_at + DELAY_MINUTES`, answers 200 within a second.
2. **Wait.** Service Bus holds the message for ten minutes while the CRM assigns an
   owner and the program publishes `{lead_id}.json` to the lookup bucket.
3. **Enrich** (`fn_lead_enricher`). Reads the source event, fetches the lookup record,
   merges on `lead_id`, writes the enriched record to `target/`, posts the alert.
   If the lookup file is not there yet (403 or 404), the message is rescheduled for
   `RETRY_INTERVAL_MINUTES` later, up to `MAX_LOOKUP_ATTEMPTS` in all; after that the
   lead is announced as `Unassigned` and the record goes to `target/unmatched/`.
4. **Alert.** A Slack Block Kit message with the seven fields: Name, Lead ID, Created
   Date, Label, Email, Lead Owner, Funnel.

Guarantees: at most one alert per lead (`alert_sent_at_utc` in the record is the
idempotency marker); an exception in the enricher abandons the message for redelivery,
five failed deliveries dead-letter it, and the dead-letter queue raises an alert.

## Repository layout

```
.github/workflows/ci.yml   lint and tests on every push; deploy to Azure on push to main
docs/                      proposal (.docx), diagram (.drawio, .png), decision log, phase runbooks,
                           validation report
docs/samples/              sample webhook events and lead-owner record from the brief
infra/                     create_environment.sh, verify_environment.sh, deploy_function.sh,
                           create_monitoring.sh
scripts/                   send_test_event.py, test_slack_webhook.py, queue_status.sh,
                           show_target.sh, replay_dead_letter.py
src/                       Azure Functions project root: function_app.py, host.json, requirements.txt
src/leadflow/              application modules (host-independent, unit tested)
tests/                     pytest unit tests (49), in-memory fakes only
```

`src/leadflow/` modules: `config` (settings), `models` (event and message types),
`verify` (Close HMAC signature), `storage` (blob read/write), `delay_queue` (Service Bus
scheduling), `receiver` (webhook logic), `lookup` (lead-owner HTTP lookup), `enrich`
(record schema), `notify` (Slack alert), `enricher` (enrichment logic), `logs`
(structured JSON log lines).

## Azure environment

Resource group `rg-crmleads` in West US 3, created by `infra/create_environment.sh`
(idempotent) and checked by `infra/verify_environment.sh`.

| Resource | Name | Notes |
|---|---|---|
| Storage (data lake) | `stcrmleadskcm` | hierarchical namespace; containers `source`, `target`, `logs` |
| Storage (runtime) | `stcrmleadsfnkcm` | Functions host state (decision 12) |
| Service Bus | `sb-crmleads-kcm` / `sbq-lead-delay` | Basic; max delivery 5; lock 5 min; dead-letter on expiry |
| Key Vault | `kv-crmleads-kcm` | RBAC; `slack-webhook-url`, `close-webhook-signature-key` |
| Function App | `func-crmleads-kcm` | Linux Consumption, Python 3.11, Functions v4; system-assigned identity |
| Monitoring | `log-crmleads-kcm`, `appi-crmleads-kcm` | workspace-based Application Insights |
| Alerts | `ag-crmleads`, `alr-crmleads-failures`, `alr-crmleads-deadletter` | `infra/create_monitoring.sh` |

The Function App's identity holds Storage Blob Data Contributor, Service Bus Data Sender
and Receiver, and Key Vault Secrets User. No connection strings or keys are stored in
app settings; secrets are Key Vault references.

Application settings: `STORAGE_ACCOUNT_URL`, `SOURCE_CONTAINER`, `TARGET_CONTAINER`,
`SERVICEBUS_FQDN`, `SERVICEBUS_QUEUE`, `LEAD_OWNER_BASE_URL`, `DELAY_MINUTES` (10),
`RETRY_INTERVAL_MINUTES` (5), `MAX_LOOKUP_ATTEMPTS` (4), `VERIFY_SIGNATURE`,
`LEAD_OWNER_STUB_ENABLED` (test only), `SLACK_WEBHOOK_URL` and
`CLOSE_WEBHOOK_SIGNATURE_KEY` (Key Vault references).

## Endpoints

| Route | Auth | Purpose |
|---|---|---|
| `POST /api/crm?code=<function key>` | function key (+ Close signature when enabled) | webhook receiver; this is the URL given to the CRM team |
| `GET /api/health` | anonymous | liveness and configuration presence, no secrets |
| `GET /api/lead-owner/{lead_id}.json` | anonymous | test-only lookup stub; 404 unless `LEAD_OWNER_STUB_ENABLED=true` |

## Local setup (workstation)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env      # then fill in the values
ruff check . && ruff format --check . && pytest -q
```

`.env` holds `SLACK_WEBHOOK_URL`, `FUNCTION_URL`, `FUNCTION_KEY`, `LEAD_OWNER_BASE_URL`
and, from Phase 5, `CLOSE_WEBHOOK_SIGNATURE_KEY`. `.env` and `local.settings.json` are
ignored by git.

## Deployment

**Automatic.** A push to `main` runs `.github/workflows/ci.yml`: ruff, pytest, then a
zip deploy of `src/` with a remote build, authenticated by the publish profile stored as
the repository secret `AZURE_FUNCTIONAPP_PUBLISH_PROFILE`. The job ends with a call to
`/api/health`.

**Manual.** From Azure Cloud Shell, `bash infra/deploy_function.sh` does the same
deploy and prints the webhook URL with its key.

## Operations

| Task | Command (Cloud Shell unless noted) |
|---|---|
| Post a test event | workstation: `python scripts\send_test_event.py --fresh --sample 2` |
| Queue counts and latest blobs | `bash scripts/queue_status.sh` |
| Show one enriched record | `bash scripts/show_target.sh <lead_id> [unmatched]` |
| List dead-lettered messages | workstation: `python scripts\replay_dead_letter.py --dry-run` |
| Replay dead-lettered messages | workstation: `python scripts\replay_dead_letter.py` |
| Check configuration | `curl -s https://func-crmleads-kcm.azurewebsites.net/api/health` |
| Switch signature verification on | `az functionapp config appsettings set ... --settings VERIFY_SIGNATURE=true` |

Every pipeline log line is a JSON object with `stage` and `lead_id`, queryable in
Application Insights > Logs; the queries used day to day are in
`docs/phase4_operations.md`.

## Runbooks

| Phase | Document |
|---|---|
| 0 | `docs/phase0_setup.md`: Slack channel and webhook, repository |
| 1 | `docs/phase1_environment.md`: environment creation and verification |
| 2 | `docs/phase2_receiver.md`: receiver behavior and smoke test |
| 3 | `docs/phase3_enricher.md`: enricher behavior, retry and found paths, stub |
| 4 | `docs/phase4_operations.md`: CI/CD setup, alerts, dead-letter replay, queries |
| 5 | `docs/phase5_validation.md`: subscription, signature key, validation report |

## Known limitations

- Lead-owner files are retained in the bucket for one day; a message replayed later than
  that is processed as Unassigned (decision 11).
- `Created Date` in the alert is the CRM's `date_created`; for sample-based test events
  it is the sample's own date, not the time of the test.
- The stub lookup must be switched off (`LEAD_OWNER_STUB_ENABLED=false`) outside
  tests; `/api/health` shows its state.
