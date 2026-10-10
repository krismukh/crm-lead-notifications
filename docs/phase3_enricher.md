# Phase 3: Enrichment and Notification

`fn_lead_enricher` is the Service Bus-triggered Azure Function that runs when a delay
message becomes visible, ten minutes after the lead was received. It looks up the lead
owner, writes the enriched record, and posts the New Lead Alert to Slack.

## Behavior

| Step | Action | Outcome |
|---|---|---|
| 1 | Read `source/crm_event_{lead_id}.json` | Missing or unreadable: logged as `source_missing`, message completed (nothing to do) |
| 2 | Check `target/` for an existing record | Record with `alert_sent_at_utc`: `duplicate`, message completed, no second alert. Record without it (Slack failed last time): resend the alert only |
| 3 | `GET {LEAD_OWNER_BASE_URL}/{lead_id}.json` | 200: found. 403 or 404: not available (decision 11). 5xx or timeout: retried three times in-invocation with back-off, then raised |
| 4a | Not available and `attempt < MAX_LOOKUP_ATTEMPTS` | Reschedule `attempt + 1` for `now + RETRY_INTERVAL_MINUTES`; message completed |
| 4b | Not available on the last attempt | Record written to `target/unmatched/` with `lead_owner = Unassigned`, `lookup_status = not_found` |
| 5 | Found | `lead_id` in the record must equal the message's; otherwise treated as `mismatch` and handled as 4b. Record written to `target/crm_lead_enriched_{lead_id}.json` |
| 6 | Slack alert with the seven fields | Retried three times in-invocation; on success `alert_sent_at_utc` is stamped into the record |
| 7 | Return | Normal return completes the message. Any raised error abandons it; Service Bus redelivers up to 5 times, then dead-letters it |

With `DELAY_MINUTES=10`, `RETRY_INTERVAL_MINUTES=5`, and `MAX_LOOKUP_ATTEMPTS=4`, a lead
whose owner file never appears is announced as Unassigned 25 minutes after creation.

## Enriched record

```json
{
  "lead_id": "lead_niuY...",            "display_name": "Lowell Bast",
  "date_created": "2025-05-20T12:14:56.409000+00:00",
  "status_label": "Potential",
  "lead_email": "gatequdit@gmail.com",  "lead_owner": "Lucija Bitunjac",
  "funnel": "DE ACADEMY Direct VSL",    "funnel_from_crm": "DE ACADEMY Direct VSL",
  "event_id": "ev_1ntH...",
  "received_at_utc": "...", "enriched_at_utc": "...", "alert_sent_at_utc": "...",
  "lookup_status": "found", "lookup_attempts": 1,
  "source_path": "source/crm_event_lead_niuY....json"
}
```

`funnel` falls back to the CRM custom field when the lookup record has none, so an
Unassigned alert still shows the funnel.

## Code added

```
src/leadflow/lookup.py       HttpLeadOwnerLookup (403/404 -> not_found; else LookupError)
src/leadflow/enrich.py       build_enriched_record(), target_blob_name()
src/leadflow/notify.py       build_alert() (Block Kit, seven fields), SlackNotifier
src/leadflow/enricher.py     handle_delay_message(): the table above, host-independent
src/function_app.py          fn_lead_enricher (Service Bus trigger), fn_lead_owner_stub
tests/test_enricher.py       found, reschedule, unassigned, duplicate, Slack failure and resend,
                             transient lookup error, mismatch, missing source
tests/test_lookup_notify.py  HTTP status handling, alert layout, Slack client
scripts/queue_status.sh      queue counts and container listings (Cloud Shell)
scripts/show_target.sh       print one enriched record (Cloud Shell)
```

`host.json` sets `autoCompleteMessages: true`: the host completes the message on a normal
return and abandons it on an exception, which is the semantics the table relies on. Lock
auto-renewal is set to five minutes to cover the in-invocation retries.

## The lookup stub (test only)

The real bucket holds a file only for leads the CRM creates, and only for one day, so the
found path cannot be exercised with the sample lead. `fn_lead_owner_stub` at
`GET /api/lead-owner/{lead_id}.json` returns a synthetic owner record for any lead id
beginning with `lead_test`, and only when the app setting `LEAD_OWNER_STUB_ENABLED` is
`true`. Pointing `LEAD_OWNER_BASE_URL` at it for the duration of the smoke test exercises
the complete found path end to end (decision 16). Both settings are returned to their
production values at the end of the test.

## Deploy (Cloud Shell)

```
cd ~/crm-lead-notifications && git pull
bash infra/deploy_function.sh
```

The deploy lists four functions. The three messages left on the queue by the Phase 2
smoke test are consumed within a minute of the deploy: their lead ids have no file in the
real bucket, so each is rescheduled three times at five-minute intervals and then announced
as Unassigned about fifteen minutes later. That is the retry path, observed live.

## Smoke test

**A. Retry path (nothing to configure).** Immediately after the deploy:

```
bash scripts/queue_status.sh
```
Expected within a minute: `active 0`, `scheduled 3` (each message rescheduled as attempt 2).
After about fifteen minutes: three Unassigned alerts in `#new-lead-alerts`, three records
under `target/unmatched/`, queue empty. Inspect one with
`bash scripts/show_target.sh <lead_id> unmatched`; expect `lookup_attempts: 4`.

**B. Found path (stub).** In Cloud Shell, switch the lookup to the stub:

```
az functionapp config appsettings set -g rg-crmleads -n func-crmleads-kcm --settings \
  LEAD_OWNER_STUB_ENABLED=true \
  LEAD_OWNER_BASE_URL=https://func-crmleads-kcm.azurewebsites.net/api/lead-owner
```

Then from the workstation post a fresh event:

```
python scripts\send_test_event.py --fresh --sample 2
```

Ten minutes later: one alert in Slack with Lead Owner `Stub Owner`, Email
`<id>@example.com`, Funnel `STUB Direct VSL`; a record in `target/` (not `unmatched/`)
with `lookup_status: found`, `lookup_attempts: 1`; and an `alert_sent_at_utc` stamp.
Receipt-to-alert latency should be ten minutes plus a few seconds.

**C. Duplicate protection.** Re-post the *same* event (no `--fresh`; edit the lead id in
the sample or reuse the Phase 2 approach). Expected: a second source write and a second
message, but after ten minutes no second alert; the trace shows `duplicate_skipped`.

**D. Restore production settings:**

```
az functionapp config appsettings set -g rg-crmleads -n func-crmleads-kcm --settings \
  LEAD_OWNER_STUB_ENABLED=false \
  LEAD_OWNER_BASE_URL=https://dea-lead-owner.s3.us-east-1.amazonaws.com
```

Confirm with the health endpoint: `lead_owner_stub_enabled: false` and the bucket URL.

**E. Traces.** Application Insights > Logs:

```
traces
| where message has_any ("message_received", "lookup_rescheduled", "lead_enriched", "lead_unassigned", "alert_sent", "duplicate_skipped")
| project timestamp, message
| order by timestamp desc
```

## Exit criteria

- [ ] `ruff check .` and `pytest` pass (49 tests)
- [ ] Deploy lists `fn_lead_enricher` with trigger `serviceBusTrigger`
- [ ] A: three Unassigned alerts, three `unmatched/` records, empty queue
- [ ] B: one found alert with the stub owner; record in `target/` with `lookup_status: found`
- [ ] C: no duplicate alert on re-delivery
- [ ] D: production settings restored and confirmed via `/api/health`
- [ ] Phase 3 committed and pushed; README status updated
