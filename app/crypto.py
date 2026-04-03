"""Symmetric encryption helpers for at-rest secrets (CF-005).

Derives a Fernet key from CAAMS_SECRET_KEY via SHA-256.  All values are
stored as base64url-encoded ciphertext; empty strings are stored as-is so
that "no password configured" remains distinguishable from an encrypted
empty string.
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    secret = os.environ.get("CAAMS_SECRET_KEY", "")
    key_bytes = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt_field(plaintext: str) -> str:
    """Encrypt *plaintext* and return a base64url ciphertext string.

    Returns an empty string unchanged so that "not configured" sentinel
    values are not accidentally encrypted.
    """
    if not plaintext:
        return plaintext
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_field(ciphertext: str) -> str:
    """Decrypt a value previously encrypted by :func:`encrypt_field`.

    Returns an empty string unchanged.  If decryption fails (e.g. the
    value was stored before encryption was introduced) returns the raw
    value so the admin can re-save it through the UI.
    """
    if not ciphertext:
        return ciphertext
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ciphertext
