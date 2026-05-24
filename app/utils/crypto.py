"""
PII encryption helpers using Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).
Phone numbers and email addresses are stored encrypted at rest.
Lookups use SHA-256 hashes (stored separately).
"""
from __future__ import annotations

import hashlib
import os

from cryptography.fernet import Fernet

from app.config import get_settings


def _get_fernet() -> Fernet:
    settings = get_settings()
    key = settings.pii_encryption_key
    if not key:
        # Dev-only fallback — generates a new key each process restart (data unreadable across restarts)
        key = Fernet.generate_key().decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_pii(plaintext: str) -> str:
    """Encrypt a PII string and return a base64-encoded ciphertext."""
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt_pii(ciphertext: str) -> str:
    """Decrypt a PII ciphertext back to plaintext."""
    fernet = _get_fernet()
    return fernet.decrypt(ciphertext.encode()).decode()


def hash_pii(value: str) -> str:
    """Return a deterministic SHA-256 hex digest used for equality lookups."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
