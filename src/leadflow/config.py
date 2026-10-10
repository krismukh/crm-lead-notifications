"""Runtime settings, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    storage_account_url: str
    source_container: str
    target_container: str
    servicebus_fqdn: str
    servicebus_queue: str
    lead_owner_base_url: str
    slack_webhook_url: str
    close_signature_key: str
    verify_signature: bool
    delay_minutes: int
    retry_interval_minutes: int
    max_lookup_attempts: int
    signature_max_age_seconds: int
    lead_owner_stub_enabled: bool

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        return cls(
            storage_account_url=e.get("STORAGE_ACCOUNT_URL", ""),
            source_container=e.get("SOURCE_CONTAINER", "source"),
            target_container=e.get("TARGET_CONTAINER", "target"),
            servicebus_fqdn=e.get("SERVICEBUS_FQDN", ""),
            servicebus_queue=e.get("SERVICEBUS_QUEUE", "sbq-lead-delay"),
            lead_owner_base_url=e.get(
                "LEAD_OWNER_BASE_URL", "https://dea-lead-owner.s3.us-east-1.amazonaws.com"
            ).rstrip("/"),
            slack_webhook_url=e.get("SLACK_WEBHOOK_URL", ""),
            close_signature_key=e.get("CLOSE_WEBHOOK_SIGNATURE_KEY", ""),
            verify_signature=_bool(e.get("VERIFY_SIGNATURE"), False),
            delay_minutes=_int(e.get("DELAY_MINUTES"), 10),
            retry_interval_minutes=_int(e.get("RETRY_INTERVAL_MINUTES"), 5),
            max_lookup_attempts=_int(e.get("MAX_LOOKUP_ATTEMPTS"), 4),
            signature_max_age_seconds=_int(e.get("SIGNATURE_MAX_AGE_SECONDS"), 300),
            lead_owner_stub_enabled=_bool(e.get("LEAD_OWNER_STUB_ENABLED"), False),
        )
