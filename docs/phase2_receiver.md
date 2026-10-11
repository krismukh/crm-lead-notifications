# Phase 2: Webhook Receiver

`fn_webhook_receiver` is the HTTP-triggered Azure Function that Close calls for each new
lead. It verifies the request, stores the event, schedules the enrichment step, and
returns within a second.

## Behavior

| Step | Action | Outcome |
|---|---|---|
| 1 | Verify `Close-Sig-Timestamp` and `Close-Sig-Hash` (when `VERIFY_SIGNATURE=true`) | 401 on failure; nothing stored |
| 2 | Parse the body as a Close event | 400 on malformed body (Close does not retry 4xx) |
| 3 | Check `object_type = lead` and `action = created` | 200 `ignored` for anything else |
| 4 | Write the raw event to `source/crm_event_{lead_id}.json` with metadata `lead_id`, `event_id`, `received_at_utc` | Overwrite on repeat delivery (idempotent) |
| 5 | Schedule a Service Bus message for `received_at + DELAY_MINUTES` | Message body: `lead_id`, `event_id`, `source_container`, `source_blob`, `received_at_utc`, `attempt` |
| 6 | Respond 200 `accepted` with `source_path` and `scheduled_for_utc` | Any unexpected exception returns 500 so that Close retries |

The route is `POST /api/crm` with function-key authorization (`?code=`), per decision 6.
`GET /api/health` is anonymous and returns configuration presence only.

## Code layout

```
src/
  function_app.py            Azure Functions entry point (v2 model); adapts HTTP to leadflow
  host.json                  Functions host settings; Service Bus autoComplete on (decision 15)
  requirements.txt           Runtime dependencies (pinned)
  local.settings.json.example  Template for local runs with Functions Core Tools
  leadflow/
    config.py                Settings.from_env()
    models.py                LeadEvent, DelayMessage, InvalidEvent
    verify.py                Close HMAC-SHA256 signature verification
    storage.py               AzureBlobStore (managed identity) and MemoryBlobStore (tests)
    delay_queue.py           ServiceBusScheduler and MemoryScheduler (tests)
    receiver.py              handle_webhook(): the logic above, host-independent
    logs.py                  JSON log lines carrying lead_id, event_id, stage, elapsed_ms
tests/
  test_models.py, test_verify.py, test_receiver.py   29 tests, in-memory fakes only
scripts/
  send_test_event.py         Posts a sample event (optionally fresh lead_id, optionally signed)
infra/
  deploy_function.sh         Zip deploy with remote build; prints the webhook URL
```

The Function App project root is `src/` (the host requires `function_app.py` beside
`host.json`), which is why the proposal's `src/functions/` folder was folded into `src/`.

## Local checks (workstation)

```
cd crm-lead-notifications
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
ruff check .
pytest
```

Expected: `All checks passed!` and `29 passed`.

## Deploy (Cloud Shell)

```
cd ~/crm-lead-notifications && git pull
bash infra/deploy_function.sh
```

The script zips `src/`, deploys with a remote build (pip install runs in Azure), waits for
`fn_webhook_receiver` to appear, and prints the health and webhook URLs. The `code=` value
in the webhook URL is the function key; keep it out of commits and screenshots.

## Smoke test (workstation)

1. Health: open `https://func-crmleads-kcm.azurewebsites.net/api/health` in a browser.
   Expected: `{"status": "ok", "storage_configured": true, "servicebus_configured": true, ...}`.
2. Post a fresh sample event (the `--fresh` flag gives it a new lead_id so repeated runs
   do not overwrite one another):
   ```
   python scripts\send_test_event.py --fresh --sample 2 --url "https://func-crmleads-kcm.azurewebsites.net/api/crm?code=<key>"
   ```
   Expected: `HTTP 200` with `"status": "accepted"` and a `scheduled_for_utc` ten minutes
   ahead. Note the elapsed time: the success criterion is seconds, and a cold start of the
   Consumption plan can add 2 to 5 seconds on the first call only.
3. Confirm the source file: in the portal, Storage account `stcrmleadskcm` > Containers >
   `source`, or in Cloud Shell:
   ```
   az storage blob list --account-name stcrmleadskcm -c source --auth-mode login -o table
   ```
4. Confirm the scheduled message: Service Bus `sb-crmleads-kcm` > Queues > `sbq-lead-delay`
   shows Scheduled message count 1 (it moves to Active after ten minutes, where it waits
   until Phase 3 adds the consumer; the 14-day TTL keeps it safe).
5. Post the same event again without `--fresh`: the source file is overwritten and a
   second message is scheduled. Post with `--action updated`: response `"status": "ignored"`.
6. Application Insights > Logs, run:
   ```
   traces | where message contains "event_accepted" | order by timestamp desc
   ```
   Each line is a JSON object with `lead_id`, `source_path`, `scheduled_for_utc`, and
   `elapsed_ms`.

## Exit criteria

- [ ] `ruff check .` and `pytest` pass locally
- [ ] `deploy_function.sh` lists `fn_webhook_receiver` and `fn_health`
- [ ] Health endpoint returns `status ok` with both `_configured` flags true
- [ ] A fresh test event is accepted in under 2 seconds (after warm-up), its file is in `source`, and one scheduled message is on the queue
- [ ] An `updated` event is ignored; a malformed body returns 400
- [ ] `event_accepted` traces visible in Application Insights
- [ ] Phase 2 committed and pushed; README status updated
