"""Pure-Python HS256 JWT implementation — no cryptography library required."""

import base64
import binascii
import hashlib
import hmac
import json
import time


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad < 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


class JWTError(Exception):
    pass


def encode(payload: dict, secret: str, algorithm: str = "HS256") -> str:
    if algorithm != "HS256":
        raise ValueError("Only HS256 supported")
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload, default=str).encode())
    signing_input = f"{header}.{body}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(sig)}"


def decode(token: str, secret: str, algorithms: list = None) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise JWTError("Invalid token format")
    header_b64, body_b64, sig_b64 = parts
    # Validate header algorithm before touching the signature — prevents
    # algorithm-confusion attacks (e.g. "alg": "none")
    try:
        header = json.loads(_b64url_decode(header_b64))
    except (binascii.Error, json.JSONDecodeError, ValueError):
        raise JWTError("Invalid header encoding")
    if header.get("alg") != "HS256":
        raise JWTError("Unsupported algorithm")
    signing_input = f"{header_b64}.{body_b64}".encode()
    expected_sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
    except (binascii.Error, ValueError):
        raise JWTError("Invalid signature encoding")
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise JWTError("Signature verification failed")
    try:
        payload = json.loads(_b64url_decode(body_b64))
    except (binascii.Error, json.JSONDecodeError, ValueError):
        raise JWTError("Invalid payload encoding")
    # Check expiry
    exp = payload.get("exp")
    if exp is not None and isinstance(exp, (int, float)):
        if time.time() > exp:
            raise JWTError("Token has expired")
    return payload
