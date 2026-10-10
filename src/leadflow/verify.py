"""Close webhook signature verification.

Close signs each delivery with two headers:

    Close-Sig-Timestamp   Unix time (seconds) at which the request was signed
    Close-Sig-Hash        hex HMAC-SHA256 over (timestamp + raw body), keyed with the
                          subscription's signature_key (itself a hex string)

Reference: https://developer.close.com/topics/webhooks/#signature-verification
"""

from __future__ import annotations

import hashlib
import hmac
import time


class SignatureError(ValueError):
    """The request failed signature verification."""


def compute_signature(signature_key_hex: str, timestamp: str, body: bytes) -> str:
    key = bytes.fromhex(signature_key_hex)
    message = timestamp.encode("utf-8") + body
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def verify_request(
    headers: dict[str, str],
    body: bytes,
    signature_key_hex: str,
    max_age_seconds: int = 300,
    now: float | None = None,
) -> None:
    """Raise SignatureError unless the request carries a valid, fresh Close signature."""
    if not signature_key_hex:
        raise SignatureError("signature key is not configured")
    lower = {k.lower(): v for k, v in headers.items()}
    timestamp = lower.get("close-sig-timestamp", "")
    received = lower.get("close-sig-hash", "")
    if not timestamp or not received:
        raise SignatureError("missing Close-Sig-Timestamp or Close-Sig-Hash header")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise SignatureError("Close-Sig-Timestamp is not an integer") from exc
    current = time.time() if now is None else now
    if abs(current - ts) > max_age_seconds:
        raise SignatureError("signature timestamp is outside the accepted window")
    try:
        expected = compute_signature(signature_key_hex, timestamp, body)
    except ValueError as exc:
        raise SignatureError("signature key is not valid hex") from exc
    if not hmac.compare_digest(expected, received.lower()):
        raise SignatureError("signature mismatch")
