from __future__ import annotations

import json
from pathlib import Path

import pytest

from leadflow.config import Settings
from leadflow.delay_queue import MemoryScheduler
from leadflow.storage import MemoryBlobStore

SAMPLES = Path(__file__).resolve().parents[1] / "docs" / "samples"

# A valid 32-byte hex key for signature tests (never a real Close key).
TEST_SIGNATURE_KEY = "0123456789abcdef" * 4


@pytest.fixture
def sample_1() -> bytes:
    return (SAMPLES / "webhook_body_sample_1.json").read_bytes()


@pytest.fixture
def sample_2() -> bytes:
    return (SAMPLES / "webhook_body_sample_2.json").read_bytes()


@pytest.fixture
def lookup_2() -> dict:
    return json.loads((SAMPLES / "lead_owner_sample_2.json").read_text())


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env(
        {
            "STORAGE_ACCOUNT_URL": "https://example.blob.core.windows.net",
            "SERVICEBUS_FQDN": "example.servicebus.windows.net",
            "VERIFY_SIGNATURE": "false",
            "DELAY_MINUTES": "10",
        }
    )


@pytest.fixture
def signed_settings() -> Settings:
    return Settings.from_env(
        {
            "STORAGE_ACCOUNT_URL": "https://example.blob.core.windows.net",
            "SERVICEBUS_FQDN": "example.servicebus.windows.net",
            "VERIFY_SIGNATURE": "true",
            "CLOSE_WEBHOOK_SIGNATURE_KEY": TEST_SIGNATURE_KEY,
            "DELAY_MINUTES": "10",
        }
    )


@pytest.fixture
def store() -> MemoryBlobStore:
    return MemoryBlobStore()


@pytest.fixture
def scheduler() -> MemoryScheduler:
    return MemoryScheduler()
