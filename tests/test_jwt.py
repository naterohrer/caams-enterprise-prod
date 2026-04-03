"""Unit tests for the pure-Python JWT implementation in app/jwt_utils.py."""

import base64
import json
import time

import pytest

from app.jwt_utils import JWTError, decode, encode

SECRET = "test-secret-key-for-testing-only"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# encode / decode round-trip
# ---------------------------------------------------------------------------


def test_roundtrip_basic():
    payload = {"sub": "user1", "role": "admin"}
    token = encode(payload, SECRET)
    result = decode(token, SECRET)
    assert result["sub"] == "user1"
    assert result["role"] == "admin"


def test_roundtrip_with_exp():
    payload = {"sub": "u", "exp": int(time.time()) + 3600}
    token = encode(payload, SECRET)
    result = decode(token, SECRET)
    assert result["sub"] == "u"


def test_expired_token_raises():
    payload = {"sub": "u", "exp": int(time.time()) - 1}
    token = encode(payload, SECRET)
    with pytest.raises(JWTError, match="expired"):
        decode(token, SECRET)


# ---------------------------------------------------------------------------
# Security: algorithm confusion ("alg: none") attack
# ---------------------------------------------------------------------------


def test_alg_none_rejected():
    """A token crafted with 'alg: none' must be rejected."""
    header = _b64url_encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps({"sub": "attacker", "role": "admin"}).encode())
    # No signature segment (empty string after the second dot)
    forged = f"{header}.{body}."
    with pytest.raises(JWTError):
        decode(forged, SECRET)


def test_alg_rs256_rejected():
    """A token claiming RS256 must be rejected even with a valid-looking signature."""
    header = _b64url_encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps({"sub": "attacker"}).encode())
    sig = _b64url_encode(b"fakesig")
    forged = f"{header}.{body}.{sig}"
    with pytest.raises(JWTError, match="Unsupported algorithm"):
        decode(forged, SECRET)


# ---------------------------------------------------------------------------
# Security: tampered payload
# ---------------------------------------------------------------------------


def test_tampered_payload_rejected():
    """Modifying the payload after signing must fail signature verification."""
    payload = {"sub": "user1", "role": "viewer"}
    token = encode(payload, SECRET)

    header_b64, _, sig_b64 = token.split(".")
    evil_body = _b64url_encode(json.dumps({"sub": "user1", "role": "admin"}).encode())
    tampered = f"{header_b64}.{evil_body}.{sig_b64}"

    with pytest.raises(JWTError, match="Signature verification failed"):
        decode(tampered, SECRET)


def test_wrong_secret_rejected():
    token = encode({"sub": "user1"}, SECRET)
    with pytest.raises(JWTError, match="Signature verification failed"):
        decode(token, "wrong-secret")


# ---------------------------------------------------------------------------
# Malformed tokens
# ---------------------------------------------------------------------------


def test_missing_segments():
    with pytest.raises(JWTError):
        decode("only.two", SECRET)


def test_empty_token():
    with pytest.raises(JWTError):
        decode("", SECRET)


def test_invalid_header_encoding():
    with pytest.raises(JWTError):
        decode("!!!.body.sig", SECRET)


# ---------------------------------------------------------------------------
# encode only accepts HS256
# ---------------------------------------------------------------------------


def test_encode_rejects_non_hs256():
    with pytest.raises(ValueError):
        encode({"sub": "u"}, SECRET, algorithm="RS256")
