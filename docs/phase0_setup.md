# Phase 0: Preparation

Checklist for the items that must exist before the environment is created in Phase 1.

## 1. Slack channel and incoming webhook

1. Sign in to your Slack workspace (or create one at https://slack.com/create if you do
   not have one).
2. Create a channel named `#new-lead-alerts`. A private channel is fine; the webhook can
   post to it as long as the app is added to the channel.
3. Open https://api.slack.com/apps and choose **Create New App > From scratch**. Name it
   `CRM Lead Alerts` and select your workspace.
4. In the app settings, open **Incoming Webhooks**, switch **Activate Incoming Webhooks**
   on, and click **Add New Webhook to Workspace**. Choose `#new-lead-alerts` and allow.
5. Copy the **Webhook URL** (`https://hooks.slack.com/services/T.../B.../...`). This URL
   is a credential: anyone who has it can post to the channel. Keep it out of the
   repository and out of chat messages.
6. Put the URL in `.env` as `SLACK_WEBHOOK_URL` and run
   `python scripts/test_slack_webhook.py`. A sample New Lead Alert should appear in the
   channel.

In Phase 1 the URL is stored in Key Vault as the secret `slack-webhook-url`.

## 2. Repository

```
cd "Data Engineering\Project 5"
mkdir crm-lead-notifications
cd crm-lead-notifications
# unzip the Phase 0 files here, then:
git init
git add .
git commit -m "Phase 0: repository skeleton, decision log, sample data, Slack webhook test"
gh repo create krismukh/crm-lead-notifications --public --source=. --push
```

If `gh` is not installed, create the repository on github.com and push with
`git remote add origin ... && git push -u origin main`.

## 3. Decision log

`docs/decision_log.md` records the SME approval received on October 7, 2026, and the nine
design decisions from Section 10 of the proposal. Add an entry whenever a decision is
made or changed during implementation.

## 4. Sample data

`docs/samples/` holds the two webhook event bodies and the one lead-owner record that
appear in the requirements document. They are the fixtures for the Phase 2 and Phase 3
unit tests and for `scripts/test_slack_webhook.py`.

| File | Lead | Use |
|---|---|---|
| `webhook_body_sample_1.json` | `lead_Q6uq...` (Adam Capozzoli) | Event body as delivered by Close; no lead-owner record is given in the brief |
| `webhook_body_sample_2.json` | `lead_niuY...` (Lowell Bast) | Event body as stored in the source folder |
| `lead_owner_sample_2.json` | `lead_niuY...` | Lead-owner lookup record for the same lead |

The `lead_niuY...` pair gives a complete end-to-end test case without any dependency on
the CRM team: the public bucket should still hold its lookup file at
`https://dea-lead-owner.s3.us-east-1.amazonaws.com/lead_niuYPXlw6vnFQIhwZCKDaaKv9XMQs9KA5NgxhNRBgaA.json`.
Confirm this with a browser before Phase 3; if the file has been removed, the local
sample is used instead.

## 5. Exit criteria

- [ ] Slack channel exists and `scripts/test_slack_webhook.py` posts successfully
- [ ] Repository created on GitHub with the Phase 0 commit
- [ ] Decision log entries 0 through 9 reviewed
- [ ] Public lookup file for `lead_niuY...` confirmed reachable (or noted as absent)
