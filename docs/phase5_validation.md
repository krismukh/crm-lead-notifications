# Phase 5: Webhook Subscription and Validation

Phase 5 connects the finished pipeline to the real CRM and proves it with real leads. The
pipeline itself is not changed. Three things come from the CRM team (decision log, open
items): the webhook subscription against the Function URL, the Close signature key issued
with that subscription, and a few test leads. Everything else is on our side.

The phase runs in three parts, in whatever order the CRM team's replies allow:

|Part|Trigger|Our work|
|-|-|-|
|A|now|Send the request to the CRM team|
|B|signature key received|Store the key in Key Vault, switch verification on, prove it|
|C|test leads sent|Observe each lead end to end, record the evidence, write the report|

## Part A: request to the CRM team

Send the request to the CRM team (subscription, signature key, test leads). The URL is printed by `bash infra/deploy\_function.sh` (Cloud Shell) or assembled from `.env`:
`FUNCTION\_URL` + `?code=` + `FUNCTION\_KEY`.

What the CRM team does with it (for reference; Close documents this under *Webhooks*):
they create a webhook subscription in Close whose `url` is ours and whose `events` are
`object\_type = lead`, `action = created`. The subscription's `signature\_key` is shown
once, in the API response that creates the subscription. That is the key we need.

While waiting, nothing is required. The receiver answers every request within a second,
unsigned requests are accepted (`VERIFY\_SIGNATURE=false`), and the function key in the URL
is the access control (decision 6).

## Part B: switch signature verification on

The key is a hex string of 64 characters. Do not paste it into chat, a commit, or a
screenshot; put it straight into Key Vault.

1. Store the key (Cloud Shell; the `read -s` prompt hides what you paste):

```
   read -s -p "Close signature key: " KEY; echo
   az keyvault secret set --vault-name kv-crmleads-kcm -n close-webhook-signature-key --value "$KEY" -o none
   unset KEY
   ```

2. Restart the app so the Key Vault reference is re-read, then switch verification on:

```
   az functionapp restart -n func-crmleads-kcm -g rg-crmleads
   az functionapp config appsettings set -g rg-crmleads -n func-crmleads-kcm --settings VERIFY\_SIGNATURE=true -o none
   sleep 30; curl -s https://func-crmleads-kcm.azurewebsites.net/api/health
   ```

   Expected: `"verify\_signature": true`.

3. Prove it from the workstation. Put the key in `.env` as `CLOSE\_WEBHOOK\_SIGNATURE\_KEY=<key>`
(the file is ignored by git), then:

```
   python scripts\\send\_test\_event.py --fresh --sample 2 --sign      # expect HTTP 200 accepted
   python scripts\\send\_test\_event.py --fresh --sample 2             # expect HTTP 401 invalid signature
   ```

   The signed event goes through the pipeline normally (Unassigned after 25 minutes, since
it is a synthetic lead). The unsigned one is rejected before anything is stored.

4. Record the outcome in the validation report (section 3) and close the decision-log open
item "Close webhook signature key".

If the CRM team cannot supply the key, verification stays off and the function key remains
the only control; say so in the report under limitations. The code path is unit tested
either way (`tests/test\_verify.py`).

## Part C: validate with test leads

Ask the CRM team to create the test leads in Close in the normal way, and to assign an
owner to at least one of them within ten minutes of creation, so that both outcomes are
exercised: a lead whose owner file appears (found) and a lead whose file never appears
(Unassigned). A lead whose owner is assigned after ten minutes but within twenty-five
exercises the retry path with a late match.

For each test lead, collect:

|Evidence|Where|Command or query|
|-|-|-|
|Receipt time and HTTP 200|Application Insights|`requests` where `name == "fn\_webhook\_receiver"`|
|Source record|`source/` container|`bash scripts/queue\_status.sh` (listing)|
|Lookup result and attempts|Application Insights|trace query below, stages `lookup\_\*`|
|Enriched record|`target/` container|`bash scripts/show\_target.sh <lead\_id> \[unmatched]`|
|Alert|Slack `#new-lead-alerts`|screenshot; seven fields present|
|Receipt-to-alert latency|Application Insights|latency query in `docs/phase4\_operations.md`|

Trace query for one lead:

```kusto
traces
| where message contains "<lead\_id>"
| extend e = parse\_json(message)
| project timestamp, stage = tostring(e.stage), attempt = toint(e.attempt), action = tostring(e.action)
| order by timestamp asc
```

Expected timings: `event\_accepted` at T; `message\_received` at T + 10 min; for a found lead
`alert\_sent` within seconds of that; for an Unassigned lead `lookup\_rescheduled` at T + 10,
15, 20 and `lead\_unassigned` plus `alert\_sent` at T + 25.

Check the content as well as the timing. For a found lead, every one of the seven fields
in Slack must match the lookup record and the CRM event: Name and Created Date and Label
from the event, Email and Lead Owner and Funnel from the lookup record, Lead ID in both.

## Validation report

`docs/validation\_report.md` is pre-filled with the evidence gathered in Phases 2 to 4
(synthetic leads). Add one row per CRM test lead in section 4 and complete sections 3, 5
and 6. Export the report to PDF only if the program asks for one; the Markdown file in
the repository is the deliverable.

## Hand-off

The hand-off is the repository itself. The README is the entry point; the runbooks cover
every operation; the decision log records why things are as they are. Two items should be
stated plainly in the final message to the SME:

* The alert's Created Date is the CRM's `date\_created`, not the time of processing.
* Owner files are retained for one day; a message replayed later than that is processed as
Unassigned (decision 11).

## Exit criteria

* \[ ] Request sent to the CRM team (Part A)
* \[ ] Signature key in Key Vault; `VERIFY\_SIGNATURE=true`; signed event accepted, unsigned rejected (Part B)
* \[ ] At least one CRM test lead announced with a real owner (found path)
* \[ ] At least one CRM test lead announced as Unassigned, or the retry path shown with a late match
* \[ ] Seven fields verified against source data for every test lead
* \[ ] `docs/validation\_report.md` completed; decision-log open items closed
* \[ ] README status: Phase 5 Complete; committed and pushed; hand-off message sent

