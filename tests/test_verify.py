import pytest

from leadflow.verify import SignatureError, compute_signature, verify_request
from tests.conftest import TEST_SIGNATURE_KEY

NOW = 1_800_000_000


def signed_headers(body: bytes, ts: int = NOW, key: str = TEST_SIGNATURE_KEY) -> dict:
    return {
        "Close-Sig-Timestamp": str(ts),
        "Close-Sig-Hash": compute_signature(key, str(ts), body),
    }


def test_valid_signature_passes(sample_2):
    verify_request(signed_headers(sample_2), sample_2, TEST_SIGNATURE_KEY, now=NOW)


def test_header_names_are_case_insensitive(sample_2):
    h = {k.lower(): v for k, v in signed_headers(sample_2).items()}
    verify_request(h, sample_2, TEST_SIGNATURE_KEY, now=NOW)


def test_tampered_body_fails(sample_2):
    with pytest.raises(SignatureError, match="mismatch"):
        verify_request(signed_headers(sample_2), sample_2 + b" ", TEST_SIGNATURE_KEY, now=NOW)


def test_wrong_key_fails(sample_2):
    with pytest.raises(SignatureError, match="mismatch"):
        verify_request(signed_headers(sample_2), sample_2, "ff" * 32, now=NOW)


def test_stale_timestamp_fails(sample_2):
    with pytest.raises(SignatureError, match="window"):
        verify_request(
            signed_headers(sample_2, ts=NOW - 600),
            sample_2,
            TEST_SIGNATURE_KEY,
            max_age_seconds=300,
            now=NOW,
        )


def test_missing_headers_fail(sample_2):
    with pytest.raises(SignatureError, match="missing"):
        verify_request({}, sample_2, TEST_SIGNATURE_KEY, now=NOW)


def test_unconfigured_key_fails(sample_2):
    with pytest.raises(SignatureError, match="not configured"):
        verify_request(signed_headers(sample_2), sample_2, "", now=NOW)


def test_non_hex_key_fails(sample_2):
    with pytest.raises(SignatureError, match="hex"):
        verify_request(signed_headers(sample_2), sample_2, "not-hex", now=NOW)
