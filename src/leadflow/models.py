"""Typed views of the Close webhook event and the delay-queue message."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


class InvalidEvent(ValueError):
    """The request body is not a usable Close webhook event."""


@dataclass(frozen=True)
class LeadEvent:
    """The subset of a Close webhook event that the pipeline uses."""

    event_id: str
    lead_id: str
    object_type: str
    action: str
    display_name: str
    date_created: str
    status_label: str
    subscription_id: str
    raw: dict[str, Any]

    @property
    def is_lead_created(self) -> bool:
        return self.object_type == "lead" and self.action == "created"

    @property
    def source_blob_name(self) -> str:
        return f"crm_event_{self.lead_id}.json"

    @classmethod
    def from_body(cls, body: bytes | str) -> LeadEvent:
        try:
            raw = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise InvalidEvent(f"body is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("event"), dict):
            raise InvalidEvent("body has no 'event' object")
        event = raw["event"]
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        lead_id = event.get("lead_id") or event.get("object_id") or data.get("id") or ""
        if not isinstance(lead_id, str) or not lead_id.startswith("lead_"):
            raise InvalidEvent("event carries no lead_id")
        return cls(
            event_id=str(event.get("id", "")),
            lead_id=lead_id,
            object_type=str(event.get("object_type", "")),
            action=str(event.get("action", "")),
            display_name=str(data.get("display_name", "")),
            date_created=str(data.get("date_created", "")),
            status_label=str(data.get("status_label", "")),
            subscription_id=str(raw.get("subscription_id", "")),
            raw=raw,
        )


@dataclass(frozen=True)
class DelayMessage:
    """Body of the Service Bus message that drives the enrichment step."""

    lead_id: str
    event_id: str
    source_container: str
    source_blob: str
    received_at_utc: str
    attempt: int = 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str | bytes) -> DelayMessage:
        d = json.loads(text)
        return cls(
            lead_id=d["lead_id"],
            event_id=d.get("event_id", ""),
            source_container=d["source_container"],
            source_blob=d["source_blob"],
            received_at_utc=d.get("received_at_utc", ""),
            attempt=int(d.get("attempt", 1)),
        )

    def next_attempt(self) -> DelayMessage:
        return DelayMessage(
            lead_id=self.lead_id,
            event_id=self.event_id,
            source_container=self.source_container,
            source_blob=self.source_blob,
            received_at_utc=self.received_at_utc,
            attempt=self.attempt + 1,
        )
