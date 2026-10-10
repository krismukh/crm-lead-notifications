import json

import pytest

from leadflow.models import DelayMessage, InvalidEvent, LeadEvent


def test_sample_1_parses(sample_1):
    ev = LeadEvent.from_body(sample_1)
    assert ev.lead_id == "lead_Q6uqUbqVS4NYyHGJnfxpfNKpZ0roxEDCdD9oIAaMJ4z"
    assert ev.display_name == "Adam Capozzoli"
    assert ev.status_label == "Potential"
    assert ev.date_created == "2025-09-04T07:27:17.642000+00:00"
    assert ev.is_lead_created
    assert ev.source_blob_name == f"crm_event_{ev.lead_id}.json"


def test_sample_2_parses(sample_2):
    ev = LeadEvent.from_body(sample_2)
    assert ev.lead_id == "lead_niuYPXlw6vnFQIhwZCKDaaKv9XMQs9KA5NgxhNRBgaA"
    assert ev.display_name == "Lowell Bast"
    assert ev.event_id == "ev_1ntH1vAE4G7DNjNZYkMeck"
    assert ev.subscription_id == "whsub_1zwvQVQOBPFqrH6xXJEvFJ"


def test_raw_body_is_preserved(sample_2):
    ev = LeadEvent.from_body(sample_2)
    assert ev.raw == json.loads(sample_2)


def test_lead_updated_is_not_created(sample_2):
    body = json.loads(sample_2)
    body["event"]["action"] = "updated"
    ev = LeadEvent.from_body(json.dumps(body))
    assert not ev.is_lead_created


def test_contact_event_is_not_lead(sample_2):
    body = json.loads(sample_2)
    body["event"]["object_type"] = "contact"
    ev = LeadEvent.from_body(json.dumps(body))
    assert not ev.is_lead_created


def test_lead_id_falls_back_to_object_id(sample_2):
    body = json.loads(sample_2)
    del body["event"]["lead_id"]
    ev = LeadEvent.from_body(json.dumps(body))
    assert ev.lead_id.startswith("lead_")


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b'{"event": "x"}',
        b'{"event": {"id": "ev_1"}}',
        b'{"event": {"lead_id": "cont_123"}}',
    ],
)
def test_invalid_bodies_raise(body):
    with pytest.raises(InvalidEvent):
        LeadEvent.from_body(body)


def test_delay_message_round_trip():
    m = DelayMessage("lead_a", "ev_1", "source", "crm_event_lead_a.json", "2026-10-09T00:00:00Z")
    again = DelayMessage.from_json(m.to_json())
    assert again == m
    assert m.next_attempt().attempt == 2
    assert m.next_attempt().lead_id == "lead_a"
