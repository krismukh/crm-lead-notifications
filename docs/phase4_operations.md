# Phase 4: CI/CD, Observability, Operations

Phase 4 turns the working pipeline into an operated one: a commit to `main` deploys
itself, failures and dead-lettered messages raise an e-mail, the traces are readable, and
the two recovery actions (replay a dead-lettered message, inspect a record) are scripts.

## What is added

```
.github/workflows/ci.yml        lint + tests on every push; deploy to Azure on push to main
infra/create_monitoring.sh      action group and the two alert rules
scripts/replay_dead_letter.py   move dead-lettered messages back onto the queue
scripts/show_target.sh          fixed (downloads to a temp file; /dev/stdout did not work)
scripts/queue_status.sh         newest ten blobs first
src/function_app.py             Azure SDK loggers at WARNING (decision 20)
src/.funcignore                 files excluded from the deployment package
src/requirements.txt            azure-functions pinned to 1.23.0 (Python 3.11)
README.md                       full project README
docs/decision_log.md            decisions 17 to 20
```

Unit tests are unchanged (49). The workflow runs `ruff check`, `ruff format --check`
and `pytest`, so a formatting difference now fails the build; run `ruff format .`
locally before committing.

## Step 1: install the files and check locally (workstation, PowerShell)

```
cd "C:\Users\krism\Data Engineering\Project 5\crm-lead-notifications"
.venv\Scripts\activate
ruff check .
ruff format --check .
pytest -q
```

Expected: `All checks passed!`, `N files already formatted`, `49 passed`.

## Step 2: give GitHub the publish profile (one time)

The deploy job authenticates with the Function App's publish profile, an XML file that
holds the deployment credentials for this one app (decision 17). Two things must be true
for it to work: basic publishing credentials must be enabled on the app (new apps have
them off), and the XML must reach GitHub byte for byte.

1. Enable basic publishing credentials. In Cloud Shell or PowerShell:
   ```
   az resource update --resource-group rg-crmleads --name scm --namespace Microsoft.Web --resource-type basicPublishingCredentialsPolicies --parent sites/func-crmleads-kcm --set properties.allow=true --query properties.allow
   ```
   Expected output: `true`.
2. Download the profile from the portal: open the Function App **func-crmleads-kcm**,
   and on its **Overview** page click **Get publish profile** in the toolbar. The browser
   saves `func-crmleads-kcm.PublishSettings` to Downloads.
   Do not produce the file with `az ... --xml > file` from PowerShell: PowerShell
   re-encodes the output and the resulting file is unreadable, which the deploy reports
   as HTTP 401.
3. Open the downloaded file in Notepad; it must start with `<publishData>`. Select all,
   copy.
4. On GitHub: repository **crm-lead-notifications** > **Settings** > **Secrets and
   variables** > **Actions** > **New repository secret**.
   Name: `AZURE_FUNCTIONAPP_PUBLISH_PROFILE`. Secret: paste. **Add secret**.
   (GitHub may ask for your password first.)
5. Delete the downloaded file. It is a credential; the copy in the GitHub secret is the
   only one needed.

## Step 3: push and watch the first automated deploy

```
git add -A
git commit -m "Phase 4: CI/CD workflow, monitoring, operations scripts, README"
git push
```

On GitHub, open the **Actions** tab. The run "CI and deploy" shows two jobs: **Lint and
test** (about one minute) and **Deploy to Azure Functions** (three to five minutes,
including the remote build). The deploy job ends with a health check against
`/api/health`; its log prints the JSON the endpoint returned.

If the deploy job fails with HTTP 401 at the "Deploy" step, either basic publishing
credentials are still disabled (Step 2.1) or the secret does not hold readable XML
(Step 2.2). Fix the cause, then on the run page choose **Re-run jobs** > **Re-run failed
jobs**.

## Step 4: create the alerts (Cloud Shell)

```
cd ~/crm-lead-notifications && git pull     # or git clone ... in a fresh Cloud Shell
az extension add -n application-insights   # first time only
bash infra/create_monitoring.sh <your e-mail address>
```

Without the extension installed first, the script stalls on a hidden "install it?"
prompt; if that happens, press Ctrl+C, add the extension, and rerun.

The script creates the action group `ag-crmleads` (e-mail) and two metric alerts
(decision 18):

| Alert | Fires when | Severity |
|---|---|---|
| `alr-crmleads-failures` | any function invocation ended in an exception in the last 5 minutes | 2 (Warning) |
| `alr-crmleads-deadletter` | the dead-letter queue of `sbq-lead-delay` holds a message | 1 (Error) |

Azure sends two e-mails: "You've been added to an action group" (no action needed) and
"Verify your email for Azure Monitor action group". **The second one requires action**:
until the address is verified, Azure fires the alerts but withholds the e-mails. Open it
within 30 minutes, click the link, and enter the code. If the code has expired, request a
new one by removing and re-adding the receiver:

```
az monitor action-group update -n ag-crmleads -g rg-crmleads --remove-action owner -o none
az monitor action-group update -n ag-crmleads -g rg-crmleads --add-action email owner <your e-mail address> -o none
```

Fired and resolved alerts are listed under **Monitor > Alerts** in the portal (remove the
"Alert condition : Fired" filter to see resolved ones); rules are under **Alert rules**.

## Step 5: smoke test the alerts and the replay path

This forces a dead-lettered message without touching real data. From the workstation,
post a fresh test lead while the lookup is pointed at an address that does not exist, so
the enricher raises on every delivery (the smoke test on 2026-10-11 posted two):

```
# Cloud Shell: break the lookup on purpose
az functionapp config appsettings set -g rg-crmleads -n func-crmleads-kcm --settings \
  LEAD_OWNER_BASE_URL=https://no-such-host.invalid

# workstation
python scripts\send_test_event.py --fresh --sample 2
```

What happens: ten minutes after receipt the enricher runs, the lookup raises
`LookupError` after three in-invocation retries, the message is abandoned, and Service
Bus redelivers it; after the fifth failed delivery (about two to three minutes in all)
the message is dead-lettered (observed: both leads dead-lettered within two minutes of
becoming visible). Within the next five to ten minutes two e-mails arrive:
*failures* (fired on the first exception) and *deadletter*.

Then recover. The lookup is restored from Cloud Shell; the replay runs on the
**workstation**, because Cloud Shell's managed identity cannot obtain Service Bus tokens
(the script reports `AudienceNotSupported` there), whereas PowerShell is signed in as you.

```
# Cloud Shell: restore the lookup and confirm
az functionapp config appsettings set -g rg-crmleads -n func-crmleads-kcm --settings \
  LEAD_OWNER_BASE_URL=https://dea-lead-owner.s3.us-east-1.amazonaws.com -o none
sleep 30; curl -s https://func-crmleads-kcm.azurewebsites.net/api/health
bash scripts/queue_status.sh                          # expect DeadLetter 2

# Cloud Shell, one time: Service Bus data roles for your own account
SB_ID=$(az servicebus namespace show -n sb-crmleads-kcm -g rg-crmleads --query id -o tsv)
ME=$(az ad signed-in-user show --query id -o tsv)
az role assignment create --assignee-object-id "$ME" --assignee-principal-type User \
  --role "Azure Service Bus Data Owner" --scope "$SB_ID" -o none

# workstation (PowerShell, .venv active; az login if asked)
python scripts\replay_dead_letter.py --dry-run       # lists the messages
python scripts\replay_dead_letter.py                 # replays them

# Cloud Shell
bash scripts/queue_status.sh                          # expect DeadLetter 0, Scheduled 2
```

After the replay the enricher processes the message once more with the real lookup. The
test lead has no file in the bucket, so it follows the retry path and is announced as
Unassigned about fifteen minutes later (the attempt counter restarts at the value carried
in the replayed message). Both alerts return to "Resolved" automatically on the next
evaluation that sees no failures and an empty dead-letter queue.

## Reading the traces

Application Insights > Logs (KQL mode). With the SDK noise removed (decision 20), the
pipeline's own lines are what remains.

One lead, start to finish:

```kusto
traces
| where message contains "<lead_id>"
| extend e = parse_json(message)
| project timestamp, stage = tostring(e.stage), attempt = toint(e.attempt), action = tostring(e.action), msg = message
| order by timestamp asc
```

Alerts sent in the last day, with receipt-to-alert latency:

```kusto
traces
| extend e = parse_json(message)
| where e.stage in ("event_accepted", "alert_sent")
| summarize received = minif(timestamp, e.stage == "event_accepted"),
            alerted  = minif(timestamp, e.stage == "alert_sent") by lead_id = tostring(e.lead_id)
| where isnotnull(alerted)
| extend latency_min = datetime_diff("second", alerted, received) / 60.0
| order by alerted desc
```

Failures:

```kusto
requests
| where success == false
| project timestamp, name, resultCode, duration
| join kind=leftouter (exceptions | project operation_Id, problemId, outerMessage) on operation_Id
| order by timestamp desc
```

## Deploying by hand

`infra/deploy_function.sh` from Cloud Shell still works and does exactly what the
workflow does. Use it when GitHub Actions is unavailable or to deploy a branch.

## Exit criteria

- [ ] `ruff check .`, `ruff format --check .` and `pytest` pass locally (49 tests)
- [ ] Secret `AZURE_FUNCTIONAPP_PUBLISH_PROFILE` stored; `publish.xml` deleted
- [ ] First "CI and deploy" run green; deploy job's health check printed the JSON
- [ ] `/api/health` still reports `lead_owner_stub_enabled: false` and the bucket URL
- [ ] `ag-crmleads`, `alr-crmleads-failures`, `alr-crmleads-deadletter` listed by the script; e-mail address verified
- [ ] Smoke test: both alert e-mails received; dead-lettered messages replayed; queue clean
- [ ] Traces for the smoke-test lead show no `Request URL` lines from the Azure SDK
- [ ] README status: Phase 4 Complete; committed and pushed (the push deploys)
