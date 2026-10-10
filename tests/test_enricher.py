import json
from datetime import UTC, datetime, timedelta

import pytest

from leadflow.config import Settings
from leadflow.enricher import handle_delay_message
from leadflow.lookup import LookupError, MemoryLeadOwnerLookup
from leadflow.models import DelayMessage
from leadflow.notify import MemoryNotifier, NotifyError

NOW = datetime(2026, 10, 14, 13, 10, 0, tzinfo=UTC)
LEAD_2 = "lead_niuYPXlw6vnFQIhwZCKDaaKv9XMQs9KA5NgxhNRBgaA"
FAST = {"retry_attempts": 3, "retry_base_delay": 0.0}


@pytest.fixture
def esettings() -> Settings:
    return Settings.from_env(
        {"RETRY_INTERVAL_MINUTES": "5", "MAX_LOOKUP_ATTEMPTS": "4", "TARGET_CONTAINER": "target"}
    )


@pytest.fixture
def seeded_store(store, sample_2):
    store.write_json("source", f"crm_event_{LEAD_2}.json", json.loads(sample_2), {})
    return store


def message(attempt: int = 1) -> DelayMessage:
    return DelayMessage(
        lead_id=LEAD_2,
        event_id="ev_1ntH1vAE4G7DNjNZYkMeck",
        source_container="source",
        source_blob=f"crm_event_{LEAD_2}.json",
        received_at_utc="2026-10-14T13:00:00.000+00:00",
        attempt=attempt,
    )


def test_found_path_writes_target_and_alerts(esettings, seeded_store, scheduler, lookup_2):
    lookup = MemoryLeadOwnerLookup({LEAD_2: lookup_2})
    notifier = MemoryNotifier()

    result = handle_delay_message(
        message(), esettings, seeded_store, lookup, notifier, scheduler, now=NOW, **FAST
    )

    assert result.action == "enriched"
    assert result.target_path == f"target/crm_lead_enriched_{LEAD_2}.json"
    record = seeded_store.read_json("target", f"crm_lead_enriched_{LEAD_2}.json")
    # fields from the CRM event
    assert record["display_name"] == "Lowell Bast"
    assert record["date_created"] == "2025-05-20T12:14:56.409000+00:00"
    assert record["status_label"] == "Potential"
    # fields from the lookup
    assert record["lead_email"] == "gatequdit@gmail.com"
    assert record["lead_owner"] == "Lucija Bitunjac"
    assert record["funnel"] == "DE ACADEMY Direct VSL"
    assert record["funnel_from_crm"] == "DE ACADEMY Direct VSL"
    assert record["lookup_status"] == "found" and record["lookup_attempts"] == 1
    assert record["received_at_utc"] == "2026-10-14T13:00:00.000+00:00"
    assert record["alert_sent_at_utc"] is not None
    # one alert with the seven fields
    assert len(notifier.sent) == 1
    assert notifier.sent[0]["lead_owner"] == "Lucija Bitunjac"
    assert not scheduler.scheduled


def test_not_found_reschedules_with_incremented_attempt(esettings, seeded_store, scheduler):
    lookup = MemoryLeadOwnerLookup({})  # 403 for everything
    notifier = MemoryNotifier()

    result = handle_delay_message(
        message(attempt=1), esettings, seeded_store, lookup, notifier, scheduler, now=NOW, **FAST
    )

    assert result.action == "rescheduled"
    assert len(scheduler.scheduled) == 1
    next_message, enqueue_at = scheduler.scheduled[0]
    assert next_message.attempt == 2 and next_message.lead_id == LEAD_2
    assert enqueue_at == NOW + timedelta(minutes=5)
    assert not notifier.sent
    assert not seeded_store.exists("target", f"crm_lead_enriched_{LEAD_2}.json")


def test_last_attempt_writes_unassigned_and_alerts(esettings, seeded_store, scheduler):
    lookup = MemoryLeadOwnerLookup({})
    notifier = MemoryNotifier()

    result = handle_delay_message(
        message(attempt=4), esettings, seeded_store, lookup, notifier, scheduler, now=NOW, **FAST
    )

    assert result.action == "unassigned"
    assert result.target_path == f"target/unmatched/crm_lead_enriched_{LEAD_2}.json"
    record = seeded_store.read_json("target", f"unmatched/crm_lead_enriched_{LEAD_2}.json")
    assert record["lead_owner"] == "Unassigned"
    assert record["lead_email"] == ""
    assert record["funnel"] == "DE ACADEMY Direct VSL"  # falls back to the CRM custom field
    assert record["lookup_status"] == "not_found" and record["lookup_attempts"] == 4
    assert len(notifier.sent) == 1 and notifier.sent[0]["lead_owner"] == "Unassigned"
    assert not scheduler.scheduled


def test_redelivery_after_alert_is_skipped(esettings, seeded_store, scheduler, lookup_2):
    lookup = MemoryLeadOwnerLookup({LEAD_2: lookup_2})
    notifier = MemoryNotifier()
    handle_delay_message(
        message(), esettings, seeded_store, lookup, notifier, scheduler, now=NOW, **FAST
    )

    result = handle_delay_message(
        message(), esettings, seeded_store, lookup, notifier, scheduler, now=NOW, **FAST
    )

    assert result.action == "duplicate"
    assert len(notifier.sent) == 1
    assert lookup.calls == [LEAD_2]  # second delivery never hit the lookup


def test_slack_failure_raises_and_redelivery_resends_only_the_alert(
    esettings, seeded_store, scheduler, lookup_2
):
    lookup = MemoryLeadOwnerLookup({LEAD_2: lookup_2})
    notifier = MemoryNotifier(fail_times=3)  # exhausts the in-invocation retries

    with pytest.raises(NotifyError):
        handle_delay_message(
            message(), esettings, seeded_store, lookup, notifier, scheduler, now=NOW, **FAST
        )
    record = seeded_store.read_json("target", f"crm_lead_enriched_{LEAD_2}.json")
    assert record is not None and record["alert_sent_at_utc"] is None

    result = handle_delay_message(  # Service Bus redelivers; Slack now works
        message(), esettings, seeded_store, lookup, notifier, scheduler, now=NOW, **FAST
    )
    assert result.action == "enriched"
    assert len(notifier.sent) == 1
    assert seeded_store.read_json("target", f"crm_lead_enriched_{LEAD_2}.json")["alert_sent_at_utc"]
    assert lookup.calls == [LEAD_2]


def test_transient_lookup_error_is_retried_then_raised(
    esettings, store, sample_2, scheduler, lookup_2
):
    def fresh_store():
        from leadflow.storage import MemoryBlobStore

        s = MemoryBlobStore()
        s.write_json("source", f"crm_event_{LEAD_2}.json", json.loads(sample_2), {})
        return s

    lookup = MemoryLeadOwnerLookup({LEAD_2: lookup_2}, fail_times=2)  # succeeds on third try
    result = handle_delay_message(
        message(), esettings, fresh_store(), lookup, MemoryNotifier(), scheduler, now=NOW, **FAST
    )
    assert result.action == "enriched" and len(lookup.calls) == 3

    lookup = MemoryLeadOwnerLookup({LEAD_2: lookup_2}, fail_times=5)  # never recovers
    with pytest.raises(LookupError):
        handle_delay_message(
            message(),
            esettings,
            fresh_store(),
            lookup,
            MemoryNotifier(),
            scheduler,
            now=NOW,
            **FAST,
        )
    assert len(lookup.calls) == 3  # retry_attempts exhausted, then raised for redelivery


def test_lookup_lead_id_mismatch_is_unassigned(esettings, seeded_store, scheduler, lookup_2):
    wrong = dict(lookup_2, lead_id="lead_someoneelse")
    lookup = MemoryLeadOwnerLookup({LEAD_2: wrong})
    notifier = MemoryNotifier()
    result = handle_delay_message(
        message(), esettings, seeded_store, lookup, notifier, scheduler, now=NOW, **FAST
    )
    assert result.action == "unassigned" and result.lookup_status == "mismatch"
    assert notifier.sent[0]["lead_owner"] == "Unassigned"


def test_missing_source_is_logged_and_completed(esettings, store, scheduler):
    result = handle_delay_message(
        message(),
        esettings,
        store,
        MemoryLeadOwnerLookup({}),
        MemoryNotifier(),
        scheduler,
        now=NOW,
        **FAST,
    )
    assert result.action == "source_missing"
    assert not scheduler.scheduled
