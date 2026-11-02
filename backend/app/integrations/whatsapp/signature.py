"""HMAC-SHA256 verification for Meta webhook X-Hub-Signature-256."""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """Return True when header matches sha256=<hmac(app_secret, body)>."""
    if not app_secret or not header:
        return False
    expected_prefix = "sha256="
    if not header.startswith(expected_prefix):
        return False
    digest = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(header[len(expected_prefix) :], digest)
