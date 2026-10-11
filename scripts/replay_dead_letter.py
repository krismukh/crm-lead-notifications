"""Move dead-lettered delay-queue messages back onto the queue.

A message reaches the dead-letter queue when fn_lead_enricher raised on five consecutive
deliveries (for example Slack or the lookup host was down for a long time). After the
cause is fixed, this script re-submits each message body as a new message and completes
the dead-lettered copy. The enricher's duplicate guard (alert_sent_at_utc) means a replay
can never cause a second alert for a lead that was already announced.

Usage (Cloud Shell or any signed-in az session with the Service Bus data roles):

    python3 scripts/replay_dead_letter.py --dry-run     # list what would be replayed
    python3 scripts/replay_dead_letter.py               # replay everything
    python3 scripts/replay_dead_letter.py --max 1       # replay one message

Requires: pip install azure-servicebus azure-identity
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from azure.identity import AzureCliCredential, ChainedTokenCredential, DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage, ServiceBusSubQueue

NAMESPACE = "sb-crmleads-kcm.servicebus.windows.net"
QUEUE = "sbq-lead-delay"


def describe(body: dict) -> str:
    return (
        f"lead_id={body.get('lead_id')} attempt={body.get('attempt')} "
        f"received_at_utc={body.get('received_at_utc')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="list only; change nothing")
    parser.add_argument("--max", type=int, default=100, help="maximum messages to process")
    parser.add_argument("--namespace", default=NAMESPACE)
    parser.add_argument("--queue", default=QUEUE)
    args = parser.parse_args()

    # The az login first: Cloud Shell's managed identity cannot issue Service Bus tokens.
    credential = ChainedTokenCredential(AzureCliCredential(), DefaultAzureCredential())
    seen = replayed = 0
    with ServiceBusClient(args.namespace, credential) as client:
        receiver = client.get_queue_receiver(
            args.queue, sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=5
        )
        sender = client.get_queue_sender(args.queue)
        with receiver, sender:
            if args.dry_run:  # peek leaves the messages untouched
                for dl_message in receiver.peek_messages(max_message_count=args.max):
                    body = json.loads(b"".join(dl_message.body).decode("utf-8"))
                    print(f"{describe(body)}  reason={dl_message.dead_letter_reason!r}")
                    seen += 1
            while not args.dry_run and seen < args.max:
                batch = receiver.receive_messages(
                    max_message_count=min(10, args.max - seen), max_wait_time=5
                )
                if not batch:
                    break
                for dl_message in batch:
                    raw = b"".join(dl_message.body).decode("utf-8")
                    body = json.loads(raw)
                    print(f"{describe(body)}  reason={dl_message.dead_letter_reason!r}")
                    seen += 1
                    new_message = ServiceBusMessage(
                        raw,
                        content_type="application/json",
                        application_properties={
                            "replayed_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                            "original_message_id": dl_message.message_id,
                        },
                    )
                    sender.send_messages(new_message)
                    receiver.complete_message(dl_message)
                    replayed += 1

    if args.dry_run:
        print(f"dry run: {seen} dead-lettered message(s) listed, nothing changed")
    else:
        print(f"replayed {replayed} message(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
