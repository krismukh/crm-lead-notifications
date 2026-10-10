"""Enrichment and notification logic, independent of the Azure Functions host.

    read source event -> (skip if already alerted) -> lookup lead owner
      found      -> write target record -> Slack alert -> mark alert sent
      not found  -> attempt < max ? reschedule +RETRY_INTERVAL_MINUTES
                                  : write unmatched record (Unassigned) -> alert -> mark
      transient  -> raise, so the host abandons the message and Service Bus redelivers

Idempotency: the target record carries alert_sent_at_utc. A redelivered message whose
record already has it is completed without a second alert; one whose record exists but
has no alert timestamp (Slack failed last time) resends the alert only.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from leadflow import logs
from leadflow.config import Settings
from leadflow.delay_queue import Scheduler
from leadflow.enrich import build_enriched_record, target_blob_name
from leadflow.lookup import LeadOwnerLookup, LookupError, LookupResult
from leadflow.models import DelayMessage, InvalidEvent, LeadEvent
from leadflow.notify import Notifier, NotifyError
from leadflow.storage import BlobStore

logger = logging.getLogger("leadflow.enricher")
T = TypeVar("T")


@dataclass(frozen=True)
class EnrichResult:
    action: str  # enriched | unassigned | rescheduled | duplicate | source_missing
    lead_id: str
    attempt: int
    target_path: str | None = None
    next_attempt_utc: str | None = None
    lookup_status: str | None = None


def _with_retry(fn: Callable[[], T], *, attempts: int, base_delay: float, what: str) -> T:
    """Exponential back-off inside one invocation for transient lookup and Slack errors."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except (LookupError, NotifyError) as exc:
            last = exc
            logs.warning(logger, f"{what}_retry", try_number=i + 1, error=str(exc))
            if i < attempts - 1:
                time.sleep(base_delay * (2**i))
    assert last is not None
    raise last


def handle_delay_message(
    message: DelayMessage,
    settings: Settings,
    store: BlobStore,
    lookup: LeadOwnerLookup,
    notifier: Notifier,
    scheduler: Scheduler,
    now: datetime | None = None,
    retry_attempts: int = 3,
    retry_base_delay: float = 1.0,
) -> EnrichResult:
    started = now or datetime.now(UTC)
    now_iso = started.isoformat(timespec="milliseconds")
    lead_id = message.lead_id

    # 1. Source event
    raw = store.read_json(message.source_container, message.source_blob)
    if raw is None:
        logs.error(logger, "source_missing", lead_id=lead_id, source_blob=message.source_blob)
        return EnrichResult("source_missing", lead_id, message.attempt)
    try:
        event = LeadEvent.from_body(json.dumps(raw))
    except InvalidEvent as exc:
        logs.error(logger, "source_invalid", lead_id=lead_id, reason=str(exc))
        return EnrichResult("source_missing", lead_id, message.attempt)
    source_path = f"{message.source_container}/{message.source_blob}"

    # 2. Idempotency: has this lead already been announced?
    for matched in (True, False):
        name = target_blob_name(lead_id, matched)
        existing = store.read_json(settings.target_container, name)
        if existing is None:
            continue
        if existing.get("alert_sent_at_utc"):
            logs.info(logger, "duplicate_skipped", lead_id=lead_id, target=name)
            return EnrichResult(
                "duplicate", lead_id, message.attempt, f"{settings.target_container}/{name}"
            )
        # Record exists but the alert never went out: send it now and finish.
        _send_and_mark(existing, name, settings, store, notifier, retry_attempts, retry_base_delay)
        return EnrichResult(
            "enriched" if matched else "unassigned",
            lead_id,
            message.attempt,
            f"{settings.target_container}/{name}",
            lookup_status=existing.get("lookup_status"),
        )

    # 3. Lookup (transient errors retried here, then raised for Service Bus redelivery)
    result: LookupResult = _with_retry(
        lambda: lookup.get(lead_id),
        attempts=retry_attempts,
        base_delay=retry_base_delay,
        what="lookup",
    )

    if result.found and result.record is not None:
        if str(result.record.get("lead_id", lead_id)) != lead_id:
            logs.error(
                logger,
                "lookup_mismatch",
                lead_id=lead_id,
                lookup_lead_id=result.record.get("lead_id"),
            )
            lookup_status, record_for_merge, matched = "mismatch", None, False
        else:
            lookup_status, record_for_merge, matched = "found", result.record, True
    elif message.attempt < settings.max_lookup_attempts:
        # 4a. Not yet available: try again later
        next_message = message.next_attempt()
        enqueue_at = started + timedelta(minutes=settings.retry_interval_minutes)
        scheduler.schedule(next_message, enqueue_at)
        logs.info(
            logger,
            "lookup_rescheduled",
            lead_id=lead_id,
            attempt=message.attempt,
            next_attempt=next_message.attempt,
            next_attempt_utc=enqueue_at.isoformat(timespec="seconds"),
            http_status=result.http_status,
        )
        return EnrichResult(
            "rescheduled",
            lead_id,
            message.attempt,
            next_attempt_utc=enqueue_at.isoformat(timespec="seconds"),
            lookup_status="not_found",
        )
    else:
        # 4b. Retries exhausted: announce the lead as Unassigned (decision 5)
        lookup_status, record_for_merge, matched = "not_found", None, False

    # 5. Write the target record, then alert, then mark the alert as sent
    record = build_enriched_record(
        event,
        record_for_merge,
        lookup_status=lookup_status,
        lookup_attempts=message.attempt,
        received_at_utc=message.received_at_utc,
        enriched_at_utc=now_iso,
        source_path=source_path,
    )
    name = target_blob_name(lead_id, matched)
    store.write_json(
        settings.target_container,
        name,
        record,
        metadata={"lead_id": lead_id, "lookup_status": lookup_status},
    )
    _send_and_mark(record, name, settings, store, notifier, retry_attempts, retry_base_delay)

    elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    logs.info(
        logger,
        "lead_enriched" if matched else "lead_unassigned",
        lead_id=lead_id,
        event_id=event.event_id,
        lookup_status=lookup_status,
        lookup_attempts=message.attempt,
        lead_owner=record["lead_owner"],
        target_path=f"{settings.target_container}/{name}",
        received_at_utc=message.received_at_utc,
        elapsed_ms=elapsed_ms,
    )
    return EnrichResult(
        "enriched" if matched else "unassigned",
        lead_id,
        message.attempt,
        f"{settings.target_container}/{name}",
        lookup_status=lookup_status,
    )


def _send_and_mark(
    record: dict[str, Any],
    name: str,
    settings: Settings,
    store: BlobStore,
    notifier: Notifier,
    retry_attempts: int,
    retry_base_delay: float,
) -> None:
    _with_retry(
        lambda: notifier.send(record),
        attempts=retry_attempts,
        base_delay=retry_base_delay,
        what="notify",
    )
    record["alert_sent_at_utc"] = datetime.now(UTC).isoformat(timespec="milliseconds")
    store.write_json(
        settings.target_container,
        name,
        record,
        metadata={"lead_id": record["lead_id"], "lookup_status": str(record["lookup_status"])},
    )
    logs.info(
        logger,
        "alert_sent",
        lead_id=record["lead_id"],
        lead_owner=record["lead_owner"],
        alert_sent_at_utc=record["alert_sent_at_utc"],
    )
