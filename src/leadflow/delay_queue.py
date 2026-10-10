"""Service Bus scheduling: the 10-minute delay and the lookup retries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage

from leadflow.models import DelayMessage


class Scheduler(Protocol):
    def schedule(self, message: DelayMessage, enqueue_at_utc: datetime) -> int: ...


class ServiceBusScheduler:
    """Schedules a DelayMessage on the queue; returns the Service Bus sequence number."""

    def __init__(self, fqdn: str, queue: str, credential: Any | None = None) -> None:
        self._fqdn = fqdn
        self._queue = queue
        self._credential = credential or DefaultAzureCredential()

    def schedule(self, message: DelayMessage, enqueue_at_utc: datetime) -> int:
        with ServiceBusClient(self._fqdn, credential=self._credential) as client:
            with client.get_queue_sender(self._queue) as sender:
                sb_message = ServiceBusMessage(
                    message.to_json(),
                    content_type="application/json",
                    message_id=f"{message.lead_id}:{message.attempt}",
                    application_properties={
                        "lead_id": message.lead_id,
                        "attempt": message.attempt,
                    },
                )
                sequence_numbers = sender.schedule_messages(sb_message, enqueue_at_utc)
        return int(sequence_numbers[0])


class MemoryScheduler:
    """Records scheduled messages for unit tests."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[DelayMessage, datetime]] = []

    def schedule(self, message: DelayMessage, enqueue_at_utc: datetime) -> int:
        self.scheduled.append((message, enqueue_at_utc))
        return len(self.scheduled)
