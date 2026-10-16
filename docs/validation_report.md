# Validation Report

Real-Time CRM Lead Processing and Notification System, Azure implementation.
Author: Krishna C. Mukherjee. Status: final, October 16, 2026.

## 1. Scope

This report records the evidence that the deployed pipeline meets the requirements of the
brief: a Close `lead.created` event is captured, held for ten minutes, enriched from the
lead-owner lookup, stored as an enriched record, and announced in Slack with the seven
required fields. Sections 2 and 5 are based on synthetic events posted with
`scripts/send_test_event.py` during Phases 2 to 4; section 4 is based on live leads
delivered by the Close webhook subscription after it was created by the CRM team.

## 2. Pipeline validation with synthetic events (Phases 2 to 4)

|Date (UTC)|Lead id|Path exercised|Lookup result|Attempts|Receipt to alert|Alert in Slack|
|-|-|-|-|-|-|-|
|2026-10-10|lead_testc654ae976e6ad030|retry, then Unassigned|not_found (403)|4|25 min|yes, Unassigned|
|2026-10-10|lead_test3481ccb0ca5a72d8|retry, then Unassigned|not_found (403)|4|25 min|yes, Unassigned|
|2026-10-10|lead_testbe044fbeda8a31eb|retry, then Unassigned|not_found (403)|4|25 min|yes, Unassigned|
|2026-10-10|lead_test03e04be2c2df3b83|found (stub lookup, decision 16)|found|1|10 min 7 s|yes, Stub Owner|
|2026-10-11|lead_test7b16834e955a377e|failure, dead-letter, replay, Unassigned|not_found|4|n/a (replayed)|yes, Unassigned|
|2026-10-11|lead_test05047b1bc438f38f|failure, dead-letter, replay, Unassigned|not_found|4|n/a (replayed)|yes, Unassigned|

Observations:

* The ten-minute delay is measured from receipt: scheduled time equals `received_at_utc`
plus ten minutes to the second (receiver response `scheduled_for_utc`).
* Retry attempts are five minutes apart to the second (18:25:37, 18:30:37, 18:35:37,
18:40:37 UTC on 2026-10-10).
* The found path (stub) produced an alert 10 minutes 7 seconds after receipt, with the
seven fields populated from the lookup record and the event.
* The Unassigned path writes the record under `target/unmatched/` with
`lookup_status = not_found`, `lookup_attempts = 4`, `lead_owner = Unassigned`, and the
funnel taken from the CRM custom field.
* Duplicate protection: a redelivered message for a lead whose alert was sent is skipped
(`duplicate_skipped`); covered by unit tests `test_redelivery_after_alert_is_skipped`
and `test_slack_failure_raises_and_redelivery_resends_only_the_alert`.

## 3. Signature verification (Phase 5, Part B)

|Check|Expected|Observed|Date|
|-|-|-|-|
|Key stored in Key Vault `close-webhook-signature-key`|secret present|stored 2026-10-16 01:11 UTC|2026-10-15|
|`/api/health` after switch|`verify_signature: true`|`verify_signature: true`|2026-10-15|
|Signed event (`--sign`)|HTTP 200 accepted|HTTP 200 accepted (lead_test5a1cb2a22a4dbd2e, 2.2 s)|2026-10-15|
|Unsigned event|HTTP 401, nothing stored|HTTP 401 rejected, "missing Close-Sig-Timestamp or Close-Sig-Hash header"|2026-10-15|
|Stale timestamp (unit test)|rejected|pass (`test_stale_timestamp_fails`)|2026-10-09|
|Function key matches the Close subscription URL|identical|aligned: Azure key set to the value held by Close; signed event accepted afterwards (lead_testbbea253574bf520c)|2026-10-15|

## 4. Validation with live CRM leads (Phase 5, Part C)

The CRM team created the webhook subscription (`whsub_2GXBbdBw3LguBVFI7XKRHS`) on
2026-10-13. Close began delivering events on 2026-10-16 at 01:31 UTC, after signature
verification had been switched on (01:11 UTC), so every event below was signature-checked.
No separate test leads were needed.

Totals as of 2026-10-16 16:30 UTC (`az storage blob list` on `source` and `target`,
excluding `lead_test*`):

| Measure | Value |
|---|---|
| Events received from Close | 319 |
| Enriched records written | 317 (2 in flight at the time of the count) |
| Records with a matched owner (`target/`) | 316 |
| Records announced as Unassigned (`target/unmatched/`) | 1 |
| Dead-lettered messages | 0 |
| Failed function invocations (alert `alr-crmleads-failures`) | 0 |
| Receipt-to-alert latency, 317 leads (Application Insights) | min 10.0 min, median 10.0 min, max 25.0 min |

Of the 316 matched leads, most were found on the first lookup (alert at 10 minutes);
some needed one or two further attempts (15 or 20 minutes) because the owner file was
published shortly after the ten-minute mark. The retry rule (decision 5) absorbed these
without an Unassigned alert.

Two records in full:

| Field | Found lead | Unassigned lead |
|---|---|---|
| `lead_id` | `lead_blc0ddzoTs4au1Wovd43XAgsAJi1cYVlDtC5FfQG8hv` | `lead_d7cBuZPL9sYJxalo13RxYUwPNFtqs5aYe6uuUtD3nEn` |
| `display_name` | Shrey Niraula | +1 614-673-4553 |
| `date_created` | 2026-10-16T02:31:43 | 2026-10-14T23:23:09 |
| `status_label` | Interested | Potential |
| `lead_email` | nshrey53@gmail.com | (none) |
| `lead_owner` | Kaisher von Wahl | Unassigned |
| `funnel` | None (literal value in the lookup record; CRM custom field empty) | (none) |
| `received_at_utc` | 2026-10-16T02:31:44 | 2026-10-16T01:34:57 |
| `alert_sent_at_utc` | 2026-10-16T02:46:51 | 2026-10-16T01:59:58 |
| `lookup_status` / `lookup_attempts` | found / 2 | not_found / 4 |
| Receipt to alert | 15 min 7 s | 25 min 1 s |

The Unassigned lead was created in Close on 2026-10-14 but its event was delivered on
2026-10-16, some 26 hours later; by then its owner file had passed the bucket's one-day
retention (decision 11). This was the only Unassigned lead among 317.

Field verification (seven fields in Slack against the stored records) was performed on
the found lead above and on two further alerts from 2026-10-16 16:10 and 16:13 UTC
(`lead_1OiABLWX...`, owner Ninad Magdum, funnel YT DE ACADEMY Direct VSL;
`lead_k2tuK6B7...`, owner Kaisher von Wahl): Name, Created Date, and Label matched the
CRM event; Email, Lead Owner, and Funnel matched the lookup record; Lead ID matched both.

## 5. Operations validation (Phase 4)

|Check|Observed|Date|
|-|-|-|
|Automated deploy on push to `main`|runs #2, #3, #4 green; health check passed|2026-10-11|
|Alert `alr-crmleads-failures`|fired 17:47 ET, resolved automatically|2026-10-11|
|Alert `alr-crmleads-deadletter`|fired 17:45 ET, resolved automatically|2026-10-11|
|Dead-letter replay|2 messages replayed; both processed to Unassigned; queue empty|2026-10-11|
|E-mail notifications|address verified with Azure Monitor; delivery active from 2026-10-11 18:51 ET|2026-10-11|

## 6. Requirements traceability

|Requirement (brief)|Evidence|
|-|-|
|Webhook received and stored in real time|Section 2: receiver 200 within about 1.4 s; source record written|
|Ten-minute delay before processing|Section 2: `scheduled_for_utc` = receipt + 10 min|
|Lead-owner lookup by `{lead_id}.json`|Section 2 (stub) and section 4 (real bucket, 316 matches)|
|Enriched record stored|`target/crm_lead_enriched_{lead_id}.json`; schema in `docs/phase3_enricher.md`|
|Alert with seven fields|Slack screenshots; `tests/test_lookup_notify.py::test_alert_has_seven_fields_in_order`|
|Secrets not in code|Key Vault references; `.env` ignored; unit tests use fakes|
|Error handling and retries|Sections 2 and 5; decisions 5, 11, 15, 19|
|Monitoring|Section 5; Application Insights traces with `stage` and `lead_id`|

## 7. Limitations

* The alert's Created Date is the CRM's `date_created`; for synthetic events it is the
sample's own date.
* Owner files are retained in the bucket for one day; a message replayed later is
processed as Unassigned (decision 11).
* Close may deliver an event well after the lead's `date_created` (26 hours in one observed
case). Such a lead is announced as Unassigned because its owner file has expired; the
alert's Created Date still shows the CRM value.
* Some lookup records carry the literal string `None` as the funnel; the alert shows it as
received. A future refinement could treat it as empty and fall back to the CRM field.
* Signature verification is enabled; the receiver's function key was aligned to the value
in the Close subscription URL (decision 22).

