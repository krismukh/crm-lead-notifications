"""Lead-owner lookup against the public bucket.

    GET {LEAD_OWNER_BASE_URL}/{lead_id}.json

Outcomes
    found      200 with a JSON object
    not_found  403 or 404. S3 answers 403 for an object that does not exist (or has
               expired after its one-day retention) when the caller lacks list
               permission, so both codes mean "no file for this lead right now"
               (decision 11).
    error      anything else (5xx, timeout, malformed JSON); raised as LookupError so the
               caller can retry and, if that fails, let Service Bus redeliver.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class LookupError(RuntimeError):  # noqa: A001 - domain-specific, intentionally shadows nothing used here
    """Transient failure talking to the lookup source."""


@dataclass(frozen=True)
class LookupResult:
    status: str  # found | not_found
    record: dict[str, Any] | None
    http_status: int

    @property
    def found(self) -> bool:
        return self.status == "found"


class LeadOwnerLookup(Protocol):
    def get(self, lead_id: str) -> LookupResult: ...


class HttpLeadOwnerLookup:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def url_for(self, lead_id: str) -> str:
        return f"{self._base}/{lead_id}.json"

    def get(self, lead_id: str) -> LookupResult:
        request = urllib.request.Request(
            self.url_for(lead_id),
            headers={"Accept": "application/json", "User-Agent": "crm-lead-notifications/0.3"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return LookupResult("not_found", None, exc.code)
            raise LookupError(f"lookup returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise LookupError(f"lookup unreachable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LookupError("lookup timed out") from exc
        try:
            record = json.loads(raw)
        except ValueError as exc:
            raise LookupError("lookup body is not valid JSON") from exc
        if not isinstance(record, dict):
            raise LookupError("lookup body is not a JSON object")
        return LookupResult("found", record, status)


class MemoryLeadOwnerLookup:
    """Test double: serves records from a dict; optionally fails N times first."""

    def __init__(self, records: dict[str, dict] | None = None, fail_times: int = 0) -> None:
        self.records = records or {}
        self.fail_times = fail_times
        self.calls: list[str] = []

    def get(self, lead_id: str) -> LookupResult:
        self.calls.append(lead_id)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LookupError("simulated transient failure")
        record = self.records.get(lead_id)
        if record is None:
            return LookupResult("not_found", None, 403)
        return LookupResult("found", record, 200)
