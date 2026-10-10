import json
from datetime import UTC, datetime, timedelta

from leadflow.receiver import handle_webhook
from leadflow.verify import compute_signature
from tests.conftest import TEST_SIGNATURE_KEY

NOW = datetime(2026, 10, 14, 13, 0, 0, tzinfo=UTC)


def test_lead_created_is_stored_and_scheduled(sample_2, settings, store, scheduler):
    result = handle_webhook(sample_2, {}, settings, store, scheduler, now=NOW)

    assert result.status_code == 200 and result.accepted
    lead_id = "lead_niuYPXlw6vnFQIhwZCKDaaKv9XMQs9KA5NgxhNRBgaA"
    key = ("source", f"crm_event_{lead_id}.json")
    assert store.blobs[key] == json.loads(sample_2)
    assert store.metadata[key]["lead_id"] == lead_id
    assert store.metadata[key]["received_at_utc"].startswith("2026-10-14T13:00:00")

    assert len(scheduler.scheduled) == 1
    message, enqueue_at = scheduler.scheduled[0]
    assert message.lead_id == lead_id
    assert message.attempt == 1
    assert message.source_blob == f"crm_event_{lead_id}.json"
    assert enqueue_at == NOW + timedelta(minutes=10)
    assert result.body["source_path"] == f"source/crm_event_{lead_id}.json"


def test_both_samples_produce_distinct_blobs(sample_1, sample_2, settings, store, scheduler):
    handle_webhook(sample_1, {}, settings, store, scheduler, now=NOW)
    handle_webhook(sample_2, {}, settings, store, scheduler, now=NOW)
    assert len(store.blobs) == 2
    assert len(scheduler.scheduled) == 2


def test_duplicate_delivery_is_idempotent(sample_2, settings, store, scheduler):
    handle_webhook(sample_2, {}, settings, store, scheduler, now=NOW)
    handle_webhook(sample_2, {}, settings, store, scheduler, now=NOW)
    assert len(store.blobs) == 1  # same blob overwritten, not duplicated


def test_non_created_event_is_acknowledged_not_processed(sample_2, settings, store, scheduler):
    body = json.loads(sample_2)
    body["event"]["action"] = "updated"
    result = handle_webhook(json.dumps(body).encode(), {}, settings, store, scheduler, now=NOW)
    assert result.status_code == 200
    assert result.body["status"] == "ignored"
    assert not store.blobs and not scheduler.scheduled


def test_malformed_body_returns_400(settings, store, scheduler):
    result = handle_webhook(b"{not json", {}, settings, store, scheduler, now=NOW)
    assert result.status_code == 400
    assert result.body["status"] == "invalid"
    assert not store.blobs and not scheduler.scheduled


def test_signature_required_when_enabled(sample_2, signed_settings, store, scheduler):
    result = handle_webhook(sample_2, {}, signed_settings, store, scheduler, now=NOW)
    assert result.status_code == 401
    assert not store.blobs and not scheduler.scheduled


def test_valid_signature_is_accepted(sample_2, signed_settings, store, scheduler):
    ts = str(int(NOW.timestamp()))
    headers = {
        "Close-Sig-Timestamp": ts,
        "Close-Sig-Hash": compute_signature(TEST_SIGNATURE_KEY, ts, sample_2),
    }
    result = handle_webhook(sample_2, headers, signed_settings, store, scheduler, now=NOW)
    assert result.status_code == 200 and result.accepted


def test_delay_setting_is_honored(sample_2, store, scheduler):
    from leadflow.config import Settings

    s = Settings.from_env({"DELAY_MINUTES": "1"})
    handle_webhook(sample_2, {}, s, store, scheduler, now=NOW)
    assert scheduler.scheduled[0][1] == NOW + timedelta(minutes=1)
