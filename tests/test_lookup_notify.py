import io
import json
import urllib.error

import pytest

from leadflow.lookup import HttpLeadOwnerLookup, LookupError
from leadflow.notify import ALERT_FIELDS, SlackNotifier, build_alert


class _Response(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(b""))


@pytest.fixture
def fake_urlopen(monkeypatch):
    calls = {}

    def install(outcome):
        def _urlopen(request, timeout=None):
            calls["url"] = request.full_url
            calls["body"] = request.data
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr("urllib.request.urlopen", _urlopen)
        return calls

    return install


def test_lookup_url_pattern():
    lk = HttpLeadOwnerLookup("https://dea-lead-owner.s3.us-east-1.amazonaws.com/")
    assert (
        lk.url_for("lead_abc") == "https://dea-lead-owner.s3.us-east-1.amazonaws.com/lead_abc.json"
    )


def test_lookup_found(fake_urlopen, lookup_2):
    calls = fake_urlopen(_Response(json.dumps(lookup_2).encode()))
    result = HttpLeadOwnerLookup("https://example.test").get(lookup_2["lead_id"])
    assert result.found and result.record["lead_owner"] == "Lucija Bitunjac"
    assert calls["url"].endswith(f"/{lookup_2['lead_id']}.json")


@pytest.mark.parametrize("code", [403, 404])
def test_lookup_403_and_404_are_not_found(fake_urlopen, code):
    fake_urlopen(_http_error(code))
    result = HttpLeadOwnerLookup("https://example.test").get("lead_x")
    assert result.status == "not_found" and result.http_status == code


@pytest.mark.parametrize("code", [500, 502, 503])
def test_lookup_5xx_raises(fake_urlopen, code):
    fake_urlopen(_http_error(code))
    with pytest.raises(LookupError):
        HttpLeadOwnerLookup("https://example.test").get("lead_x")


def test_lookup_bad_json_raises(fake_urlopen):
    fake_urlopen(_Response(b"not json"))
    with pytest.raises(LookupError):
        HttpLeadOwnerLookup("https://example.test").get("lead_x")


def test_alert_has_seven_fields_in_order(lookup_2):
    record = dict(lookup_2, event_id="ev_1", lookup_status="found", lookup_attempts=1)
    payload = build_alert(record)
    assert payload["blocks"][0]["text"]["text"] == "New Lead Alert"
    labels = [f["text"].split(":*")[0].lstrip("*") for f in payload["blocks"][1]["fields"]]
    assert labels == [label for label, _ in ALERT_FIELDS]
    assert "Lead Owner: Lucija Bitunjac" in payload["text"]


def test_slack_notifier_posts_and_accepts_ok(fake_urlopen, lookup_2):
    calls = fake_urlopen(_Response(b"ok"))
    SlackNotifier("https://hooks.slack.com/services/T/B/x").send(dict(lookup_2, event_id="e"))
    assert calls["url"].startswith("https://hooks.slack.com/")
    assert b"New Lead Alert" in calls["body"]


def test_slack_notifier_rejects_non_slack_url():
    with pytest.raises(ValueError):
        SlackNotifier("https://example.com/hook")


def test_slack_notifier_raises_on_http_error(fake_urlopen, lookup_2):
    from leadflow.notify import NotifyError

    fake_urlopen(_http_error(500))
    with pytest.raises(NotifyError):
        SlackNotifier("https://hooks.slack.com/services/T/B/x").send(dict(lookup_2, event_id="e"))
