# Validation Report

Real-Time CRM Lead Processing and Notification System, Azure implementation.
Author: Krishna C. Mukherjee. Status: draft, to be completed in Phase 5.

## 1. Scope

This report records the evidence that the deployed pipeline meets the requirements of the
brief: a Close `lead.created` event is captured, held for ten minutes, enriched from the
lead-owner lookup, stored as an enriched record, and announced in Slack with the seven
required fields. Sections 2 and 5 are based on synthetic events posted with
`scripts/send_test_event.py` during Phases 2 to 4; section 4 is based on test leads
created in Close by the CRM team.

## 2. Pipeline validation with synthetic events (Phases 2 to 4)

| Date (UTC) | Lead id | Path exercised | Lookup result | Attempts | Receipt to alert | Alert in Slack |
|---|---|---|---|---|---|---|
| 2026-10-10 | lead_testc654ae976e6ad030 | retry, then Unassigned | not_found (403) | 4 | 25 min | yes, Unassigned |
| 2026-10-10 | lead_test3481ccb0ca5a72d8 | retry, then Unassigned | not_found (403) | 4 | 25 min | yes, Unassigned |
| 2026-10-10 | lead_testbe044fbeda8a31eb | retry, then Unassigned | not_found (403) | 4 | 25 min | yes, Unassigned |
| 2026-10-10 | lead_test03e04be2c2df3b83 | found (stub lookup, decision 16) | found | 1 | 10 min 7 s | yes, Stub Owner |
| 2026-10-11 | lead_test7b16834e955a377e | failure, dead-letter, replay, Unassigned | not_found | 4 | n/a (replayed) | yes, Unassigned |
| 2026-10-11 | lead_test05047b1bc438f38f | failure, dead-letter, replay, Unassigned | not_found | 4 | n/a (replayed) | yes, Unassigned |

Observations:

- The ten-minute delay is measured from receipt: scheduled time equals `received_at_utc`
  plus ten minutes to the second (receiver response `scheduled_for_utc`).
- Retry attempts are five minutes apart to the second (18:25:37, 18:30:37, 18:35:37,
  18:40:37 UTC on 2026-10-10).
- The found path (stub) produced an alert 10 minutes 7 seconds after receipt, with the
  seven fields populated from the lookup record and the event.
- The Unassigned path writes the record under `target/unmatched/` with
  `lookup_status = not_found`, `lookup_attempts = 4`, `lead_owner = Unassigned`, and the
  funnel taken from the CRM custom field.
- Duplicate protection: a redelivered message for a lead whose alert was sent is skipped
  (`duplicate_skipped`); covered by unit tests `test_redelivery_after_alert_is_skipped`
  and `test_slack_failure_raises_and_redelivery_resends_only_the_alert`.

## 3. Signature verification (Phase 5, Part B)

| Check | Expected | Observed | Date |
|---|---|---|---|
| Key stored in Key Vault `close-webhook-signature-key` | secret present | | |
| `/api/health` after switch | `verify_signature: true` | | |
| Signed event (`--sign`) | HTTP 200 accepted | | |
| Unsigned event | HTTP 401, nothing stored | | |
| Stale timestamp (unit test) | rejected | pass (`test_stale_timestamp_fails`) | 2026-10-09 |

## 4. Validation with CRM test leads (Phase 5, Part C)

One row per test lead created in Close.

| Created (UTC) | Lead id | Owner assigned at | Lookup result | Attempts | Receipt to alert | Fields verified (7/7) | Notes |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

Field verification for each found lead: Name, Created Date, Label from the CRM event;
Email, Lead Owner, Funnel from the lookup record; Lead ID in both.

## 5. Operations validation (Phase 4)

| Check | Observed | Date |
|---|---|---|
| Automated deploy on push to `main` | runs #2, #3, #4 green; health check passed | 2026-10-11 |
| Alert `alr-crmleads-failures` | fired 17:47 ET, resolved automatically | 2026-10-11 |
| Alert `alr-crmleads-deadletter` | fired 17:45 ET, resolved automatically | 2026-10-11 |
| Dead-letter replay | 2 messages replayed; both processed to Unassigned; queue empty | 2026-10-11 |
| E-mail notifications | address verified with Azure Monitor; delivery active from 2026-10-11 18:51 ET | 2026-10-11 |

## 6. Requirements traceability

| Requirement (brief) | Evidence |
|---|---|
| Webhook received and stored in real time | Section 2: receiver 200 within about 1.4 s; source record written |
| Ten-minute delay before processing | Section 2: `scheduled_for_utc` = receipt + 10 min |
| Lead-owner lookup by `{lead_id}.json` | Section 2 (stub) and section 4 (real bucket) |
| Enriched record stored | `target/crm_lead_enriched_{lead_id}.json`; schema in `docs/phase3_enricher.md` |
| Alert with seven fields | Slack screenshots; `tests/test_lookup_notify.py::test_alert_has_seven_fields_in_order` |
| Secrets not in code | Key Vault references; `.env` ignored; unit tests use fakes |
| Error handling and retries | Sections 2 and 5; decisions 5, 11, 15, 19 |
| Monitoring | Section 5; Application Insights traces with `stage` and `lead_id` |

## 7. Limitations

- The alert's Created Date is the CRM's `date_created`; for synthetic events it is the
  sample's own date.
- Owner files are retained in the bucket for one day; a message replayed later is
  processed as Unassigned (decision 11).
- (Complete after Phase 5: signature verification status, any CRM-side constraints.)
