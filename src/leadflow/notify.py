"""Slack notification: the New Lead Alert with the seven fields required by the brief."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol

ALERT_FIELDS: tuple[tuple[str, str], ...] = (
    ("Name", "display_name"),
    ("Lead ID", "lead_id"),
    ("Created Date", "date_created"),
    ("Label", "status_label"),
    ("Email", "lead_email"),
    ("Lead Owner", "lead_owner"),
    ("Funnel", "funnel"),
)


class NotifyError(RuntimeError):
    """Slack did not accept the message."""


def build_alert(record: dict[str, Any]) -> dict[str, Any]:
    """Block Kit payload for one enriched record. `text` is the fallback for notifications."""
    fields = [(label, str(record.get(key) or "")) for label, key in ALERT_FIELDS]
    context = f"event {record.get('event_id', '')} · lookup {record.get('lookup_status', '')}"
    if record.get("lookup_status") != "found":
        context += f" after {record.get('lookup_attempts', '?')} attempts"
    return {
        "text": "New Lead Alert\n" + "\n".join(f"{label}: {value}" for label, value in fields),
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "New Lead Alert"}},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*{label}:*\n{value or '(none)'}"}
                    for label, value in fields
                ],
            },
            {"type": "context", "elements": [{"type": "mrkdwn", "text": context}]},
        ],
    }


class Notifier(Protocol):
    def send(self, record: dict[str, Any]) -> None: ...


class SlackNotifier:
    def __init__(self, webhook_url: str, timeout_seconds: float = 10.0) -> None:
        if not webhook_url.startswith("https://hooks.slack.com/"):
            raise ValueError("SLACK_WEBHOOK_URL is not a Slack incoming webhook URL")
        self._url = webhook_url
        self._timeout = timeout_seconds

    def send(self, record: dict[str, Any]) -> None:
        body = json.dumps(build_alert(record)).encode("utf-8")
        request = urllib.request.Request(
            self._url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                text = response.read().decode("utf-8", "replace")
                if response.status != 200 or text.strip() != "ok":
                    raise NotifyError(f"Slack responded {response.status} {text[:100]}")
        except urllib.error.HTTPError as exc:
            raise NotifyError(f"Slack returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise NotifyError(f"Slack unreachable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise NotifyError("Slack timed out") from exc


class MemoryNotifier:
    def __init__(self, fail_times: int = 0) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail_times = fail_times

    def send(self, record: dict[str, Any]) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise NotifyError("simulated Slack failure")
        self.sent.append(record)
