"""Post a sample New Lead Alert to the Slack incoming webhook.

Phase 0 check that the channel and webhook work before any Azure resource exists.
The message is built from the sample lead in the requirements document, using the
same seven fields and layout that fn_lead_enricher will send in Phase 3.

Usage:
    python scripts/test_slack_webhook.py            # posts, using SLACK_WEBHOOK_URL
    python scripts/test_slack_webhook.py --dry-run  # prints the payload without posting

SLACK_WEBHOOK_URL is read from the environment or from .env in the repository root.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EVENT = REPO_ROOT / "docs" / "samples" / "webhook_body_sample_2.json"
SAMPLE_LOOKUP = REPO_ROOT / "docs" / "samples" / "lead_owner_sample_2.json"


def load_dotenv(path: Path) -> None:
    """Minimal .env loader so the script has no third-party dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_alert(event: dict, lookup: dict) -> dict:
    """Return the Slack Block Kit payload for a New Lead Alert.

    Field sources follow the brief: name, lead ID, created date, and label come from the
    CRM event; email, lead owner, and funnel come from the lookup record.
    """
    data = event["event"]["data"]
    fields = [
        ("Name", data.get("display_name", "")),
        ("Lead ID", event["event"]["lead_id"]),
        ("Created Date", data.get("date_created", "")),
        ("Label", data.get("status_label", "")),
        ("Email", lookup.get("lead_email", "")),
        ("Lead Owner", lookup.get("lead_owner", "Unassigned")),
        ("Funnel", lookup.get("funnel", "")),
    ]
    text_lines = [f"{label}: {value}" for label, value in fields]
    return {
        "text": "New Lead Alert\n" + "\n".join(text_lines),
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "New Lead Alert"}},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*{label}:*\n{value}"} for label, value in fields
                ],
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "Phase 0 webhook test (sample data from the brief)"}
                ],
            },
        ],
    }


def post(url: str, payload: dict) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read().decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the payload and exit")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    event = json.loads(SAMPLE_EVENT.read_text(encoding="utf-8"))
    lookup = json.loads(SAMPLE_LOOKUP.read_text(encoding="utf-8"))
    payload = build_alert(event, lookup)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url.startswith("https://hooks.slack.com/"):
        print("SLACK_WEBHOOK_URL is not set or is not a Slack webhook URL.", file=sys.stderr)
        return 2

    try:
        status, text = post(url, payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        print(f"Slack returned HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Could not reach Slack: {exc.reason}", file=sys.stderr)
        return 1

    print(f"Slack responded {status} {text}")
    return 0 if status == 200 and text == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
