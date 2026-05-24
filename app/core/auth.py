"""JWT authentication and password hashing utilities."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.config import get_settings

# ── Password hashing ─────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT tokens ────────────────────────────────────────────────────────────────

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
ALGORITHM = "HS256"  # Using HS256 with app_secret_key; upgrade to RS256 for production multi-service


class TokenPayload(BaseModel):
    sub: str  # user_id
    org: str  # organization_id
    role: str
    type: str  # "access" or "refresh"
    exp: datetime
    iat: datetime
    jti: str  # unique token id for blacklisting


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "role": role,
        "type": "access",
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": now,
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)


def create_refresh_token(user_id: uuid.UUID, org_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "role": role,
        "type": "refresh",
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "iat": now,
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)


def create_token_pair(user_id: uuid.UUID, org_id: uuid.UUID, role: str) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user_id, org_id, role),
        refresh_token=create_refresh_token(user_id, org_id, role),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    settings = get_settings()
    payload = jwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
    return TokenPayload(
        sub=payload["sub"],
        org=payload["org"],
        role=payload["role"],
        type=payload["type"],
        exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        iat=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
        jti=payload["jti"],
    )


# ── API Key utilities ─────────────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    """Generate an API key. Returns (full_key, key_hash, key_prefix)."""
    raw_key = f"dc_{secrets.token_hex(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]
    return raw_key, key_hash, key_prefix


def hash_api_key(key: str) -> str:
    """Hash an API key for storage/lookup."""
    return hashlib.sha256(key.encode()).hexdigest()
