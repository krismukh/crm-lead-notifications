# Decision Log

Design decisions for the Real-Time CRM Lead Processing and Notification System, in the
order they were made. Items 1 through 9 correspond to Section 10 of the architecture
proposal (v1.0, October 7, 2026).

| # | Date | Decision | Rationale | Status |
|---|---|---|---|---|
| 0 | 2026-10-07 | Architecture proposal v1.0 and diagram submitted for SME review. | Required before implementation. | Approved 2026-10-07 |
| 1 | 2026-10-07 | Azure is used in place of AWS, with each service in the brief mapped to its Azure equivalent (Functions, ADLS Gen2, Service Bus, Key Vault, Application Insights). | Consistent with the previous projects; requirements, evaluation criteria, and success criteria unchanged. | Approved |
| 2 | 2026-10-07 | The 10-minute delay is a Service Bus scheduled message, measured from the time the receiver stores the event. | Closest equivalent to an SQS delay queue; dead-letter queue and delivery counting built in. | Approved |
| 3 | 2026-10-07 | The lead-owner lookup reads the public AWS bucket `dea-lead-owner` over HTTPS; no AWS credentials on the Azure side. | The bucket is supplied by the program. | Approved |
| 4 | 2026-10-07 | Slack is the notification channel, using a channel and incoming webhook in the author's own workspace. | SME: a channel in the author's workspace is acceptable for testing. | Approved |
| 5 | 2026-10-07 | If the lead-owner file is absent after the delay, retry every five minutes up to three further times; then write the record with `lead_owner = Unassigned` and `lookup_status = not_found` under `target/unmatched/`, still send the alert, and log the case. | SME: retry approach is fine; handle gracefully and document. | Approved |
| 6 | 2026-10-07 | Webhook signature verification uses the Close signature key obtained with the subscription; until the key is available, verification is configurable and a function key in the URL protects the endpoint. | Key is issued by Close at subscription creation, which the CRM team performs. | Approved |
| 7 | 2026-10-07 | Only events with `object_type = lead` and `action = created` are processed; other events return HTTP 200 and are ignored. | Scope of the brief. | Approved |
| 8 | 2026-10-07 | Enriched records go to a separate `target` container, with an `unmatched/` prefix for Unassigned leads. | Container-level separation; layout is a single configuration value. | Approved |
| 9 | 2026-10-07 | Validation uses test leads sent from Close by the CRM team once the endpoint URL is shared. | SME: test leads can be sent on request. | Approved |
| 10 | 2026-10-07 | Plan carries no calendar dates; phases are listed in execution order. | Final phase depends on the CRM team and lead activity. | Accepted |
| 11 | 2026-10-09 | Lead-owner files in `dea-lead-owner` are retained for one day only; S3 answers AccessDenied (403) for an expired or absent object. The enricher treats 403 and 404 alike as "not available" and applies the retry rule. Replayed dead-letter messages older than a day are processed as Unassigned. | CRM team confirmed the bucket is public, the HTTP URL pattern is unchanged, and files expire after one day. | Confirmed |
| 12 | 2026-10-09 | A second storage account `stcrmleadsfnkcm` holds the Functions runtime state; the data lake account keeps its hierarchical namespace. | The Functions host does not support hierarchical-namespace accounts for `AzureWebJobsStorage`. | Decided |
| 13 | 2026-10-09 | The Functions project root is `src/` (`function_app.py` beside `host.json`), with application code in `src/leadflow/`; the proposal's `src/functions/` folder is dropped. | The Functions host requires the entry point at the project root; one package avoids path manipulation. | Decided |
| 14 | 2026-10-09 | The receiver route keeps function-key authorization (`?code=`) even after signature verification is enabled. | Two independent controls on a public endpoint; the key is part of the subscription URL and costs nothing. | Decided |
| 15 | 2026-10-10 | Message completion follows the Functions host default (`autoCompleteMessages: true`): a normal return completes the message, an exception abandons it for redelivery. Idempotency rests on `alert_sent_at_utc` in the target record: a redelivery after a successful alert is skipped; one after a failed alert resends only the alert. | Keeps the function free of manual settlement code while still guaranteeing at most one alert per lead. | Decided |
| 16 | 2026-10-10 | A test-only HTTP function `fn_lead_owner_stub` serves synthetic owner records for `lead_test*` ids when `LEAD_OWNER_STUB_ENABLED=true`, so the found path can be exercised before real test leads exist. It is disabled in production settings. | Real bucket files exist only for CRM-created leads and for one day. | Decided |
| 17 | 2026-10-11 | Continuous deployment runs in GitHub Actions: every push runs ruff and pytest; a push to `main` that passes then zip-deploys `src/` with a remote build, authenticated by the Function App publish profile stored as a repository secret. `infra/deploy_function.sh` remains the manual fallback. | Same deployment mechanism as Cloud Shell, now triggered by the commit itself; the publish profile needs no Entra app registration; it requires basic publishing credentials on the app and is downloaded from the portal. | Decided |
| 18 | 2026-10-11 | Two metric alerts e-mail the author: any failed function invocation (`requests/failed` in Application Insights) and any message in the dead-letter queue (`DeadletteredMessages` on the namespace). Both evaluate every five minutes over a five-minute window. | Metric alerts cost nothing in query charges and cover both failure modes the design has: an exception in a function and a message that could not be processed after five deliveries. | Decided |
| 19 | 2026-10-11 | Dead-lettered messages are replayed by `scripts/replay_dead_letter.py`, run from a workstation signed in with `az login`, after the cause is fixed, never automatically. A replay re-submits the original body as a new message; the duplicate guard (decision 15) prevents a second alert if one was already sent. | Automatic replay would loop on a persistent fault; manual replay keeps a person in the loop and is a one-line command. | Decided |
| 20 | 2026-10-11 | Azure SDK loggers (`azure.*`, `uamqp`, `urllib3`) run at WARNING in the Function App; `leadflow` log lines stay at INFO. | The SDK request/response lines outnumbered the pipeline's own JSON lines in Phase 3 traces and carried no diagnostic value. | Decided |

## Open items

| Item | Owner | Needed by |
|---|---|---|
| Close webhook signature key | CRM team, with the subscription | Phase 5 |
| Webhook subscription against the Function URL | CRM team | Phase 5 |
| Test leads | CRM team | Phase 5 |

## Resolved items

| Item | Resolution |
|---|---|
| Public bucket access (AccessDenied on the sample file) | Bucket is public; files expire after one day. See item 11. |
