"""Webhook receiver logic, independent of the Azure Functions host.

    verify signature -> parse event -> write source blob -> schedule delay message -> 200

The function_app entry point adapts the HTTP request to handle_webhook() and the
result back to an HTTP response. Everything here is unit tested with in-memory fakes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from leadflow import logs
from leadflow.config import Settings
from leadflow.delay_queue import Scheduler
from leadflow.models import DelayMessage, InvalidEvent, LeadEvent
from leadflow.storage import BlobStore
from leadflow.verify import SignatureError, verify_request

logger = logging.getLogger("leadflow.receiver")


@dataclass(frozen=True)
class ReceiveResult:
    status_code: int
    body: dict

    @property
    def accepted(self) -> bool:
        return self.body.get("status") == "accepted"


def handle_webhook(
    body: bytes,
    headers: dict[str, str],
    settings: Settings,
    store: BlobStore,
    scheduler: Scheduler,
    now: datetime | None = None,
) -> ReceiveResult:
    received_at = now or datetime.now(UTC)
    received_iso = received_at.isoformat(timespec="milliseconds")

    # 1. Signature
    if settings.verify_signature:
        try:
            verify_request(
                headers,
                body,
                settings.close_signature_key,
                settings.signature_max_age_seconds,
                now=received_at.timestamp(),
            )
        except SignatureError as exc:
            logs.warning(logger, "signature_rejected", reason=str(exc), bytes=len(body))
            return ReceiveResult(401, {"status": "rejected", "reason": str(exc)})

    # 2. Parse. A malformed body gets 400; Close will not retry a 4xx, which is correct
    #    because the payload will never become valid.
    try:
        event = LeadEvent.from_body(body)
    except InvalidEvent as exc:
        logs.warning(logger, "event_invalid", reason=str(exc), bytes=len(body))
        return ReceiveResult(400, {"status": "invalid", "reason": str(exc)})

    # 3. Scope: only lead.created is processed; everything else is acknowledged.
    if not event.is_lead_created:
        logs.info(
            logger,
            "event_ignored",
            lead_id=event.lead_id,
            event_id=event.event_id,
            object_type=event.object_type,
            action=event.action,
        )
        return ReceiveResult(
            200,
            {
                "status": "ignored",
                "lead_id": event.lead_id,
                "object_type": event.object_type,
                "action": event.action,
            },
        )

    # 4. Source write (idempotent: same lead_id overwrites the same blob)
    source_path = store.write_json(
        settings.source_container,
        event.source_blob_name,
        event.raw,
        metadata={
            "lead_id": event.lead_id,
            "event_id": event.event_id,
            "received_at_utc": received_iso,
        },
    )

    # 5. Schedule the enrichment step
    enqueue_at = received_at + timedelta(minutes=settings.delay_minutes)
    message = DelayMessage(
        lead_id=event.lead_id,
        event_id=event.event_id,
        source_container=settings.source_container,
        source_blob=event.source_blob_name,
        received_at_utc=received_iso,
        attempt=1,
    )
    sequence_number = scheduler.schedule(message, enqueue_at)

    elapsed_ms = int((datetime.now(UTC) - received_at).total_seconds() * 1000)
    logs.info(
        logger,
        "event_accepted",
        lead_id=event.lead_id,
        event_id=event.event_id,
        display_name=event.display_name,
        source_path=source_path,
        scheduled_for_utc=enqueue_at.isoformat(timespec="seconds"),
        sequence_number=sequence_number,
        elapsed_ms=elapsed_ms,
    )
    return ReceiveResult(
        200,
        {
            "status": "accepted",
            "lead_id": event.lead_id,
            "event_id": event.event_id,
            "source_path": source_path,
            "scheduled_for_utc": enqueue_at.isoformat(timespec="seconds"),
        },
    )
