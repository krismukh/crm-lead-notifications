# Real-Time CRM Lead Processing and Notification System

Data Engineering Project 5. Azure implementation of the automated lead assignment and
notification requirements: a Close CRM webhook is captured in real time, held for ten
minutes while the CRM assigns a lead owner, enriched from the lead-owner lookup, stored,
and announced to the sales team in Slack.

Author: Krishna C. Mukherjee

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Preparation: Slack channel and webhook, repository, decision log, sample data | Complete |
| 1 | Environment: `infra/create_environment.sh` | Complete |
| 2 | Webhook receiver function | In progress |
| 3 | Enrichment and notification function | Not started |
| 4 | CI/CD, observability, README | Not started |
| 5 | Webhook subscription and validation with test leads | Not started |

## Architecture

![Architecture](docs/CRM_Lead_Pipeline_Architecture.png)

Close CRM posts a `lead.created` event to an HTTP-triggered Azure Function, which verifies
the signature, writes the event to the `source` container as `crm_event_{lead_id}.json`,
and schedules a Service Bus message for ten minutes later. When the message becomes
visible, a second function reads the event, fetches `{lead_id}.json` from the public
lead-owner bucket, merges the two records on `lead_id`, writes
`crm_lead_enriched_{lead_id}.json` to the `target` container, and posts a New Lead Alert
to Slack. The full design is in `docs/CRM_Lead_Processing_Architecture_Proposal.docx`.

## Repository layout

```
.github/workflows/   GitHub Actions workflow (Phase 4)
docs/                Proposal, diagram, decision log, samples, validation report
docs/samples/        Sample webhook events and lead-owner record from the brief
infra/               Azure CLI environment script (Phase 1)
scripts/             Operational and test scripts
src/                 Azure Functions project root: function_app.py, host.json, requirements.txt
src/leadflow/        Application modules: config, models, verify, storage, delay_queue, receiver, logs
tests/               pytest unit tests
```

## Local setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env      # then fill in the values
```

Secrets are never committed. `.env` and `local.settings.json` are ignored by git; in Azure
the same values come from Key Vault references on the Function App.

## Deployment

`infra/deploy_function.sh` zip-deploys `src/` with a remote build and prints the webhook URL.
See `docs/phase2_receiver.md` for the smoke test.

## Azure environment

`infra/create_environment.sh` creates all resources from Azure Cloud Shell; `infra/verify_environment.sh`
prints their state. See `docs/phase1_environment.md`.

## Phase 0 check: Slack webhook

After creating the Slack channel and incoming webhook (see `docs/phase0_setup.md`):

```
python scripts/test_slack_webhook.py
```

This posts a sample New Lead Alert, built from the sample data in the brief, to the
channel. A `200 ok` response and a visible message confirm the webhook.
