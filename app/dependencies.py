from __future__ import annotations

import uuid
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.auth import decode_token, hash_api_key
from app.core.tenant import TenantContext, set_current_tenant
from app.models.database.base import AsyncSessionLocal

# ── Security scheme ───────────────────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=False)


# ── Database dependency ───────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Redis dependency ──────────────────────────────────────────────────────────

async def get_redis(settings: Settings = Depends(get_settings)) -> AsyncGenerator[aioredis.Redis, None]:
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


# ── Auth dependencies ─────────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> "User":
    """Extract and validate current user from JWT or API key.

    Sets tenant context for the request.
    """
    from app.models.database.user import User, APIKey

    token = None

    # Try Bearer token first
    if credentials:
        token = credentials.credentials
    else:
        # Check for API key in X-API-Key header
        api_key_header = request.headers.get("X-API-Key")
        if api_key_header:
            return await _authenticate_api_key(api_key_header, db, request)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode JWT
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    # Check Redis blacklist for revoked tokens
    # (Optional: implement if logout/token revocation is needed)

    # Load user from DB
    user_id = uuid.UUID(payload.sub)
    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    # Set tenant context
    set_current_tenant(user.organization_id)
    request.state.user_id = user.id
    request.state.org_id = user.organization_id

    return user


async def _authenticate_api_key(key: str, db: AsyncSession, request: Request) -> "User":
    """Authenticate via API key and return a synthetic user-like object."""
    from app.models.database.user import APIKey, User
    from datetime import datetime, timezone

    key_hash = hash_api_key(key)
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Check expiration
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key expired",
        )

    # Update last_used_at
    api_key.last_used_at = datetime.now(timezone.utc)

    # Load the user who created the key (for role context), or use a default admin-level user
    if api_key.created_by:
        result = await db.execute(select(User).where(User.id == api_key.created_by))
        user = result.scalar_one_or_none()
        if user:
            set_current_tenant(api_key.organization_id)
            request.state.user_id = user.id
            request.state.org_id = api_key.organization_id
            return user

    # Fallback: create a virtual user with the org context
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API key owner not found",
    )


async def get_current_org_id(
    request: Request,
    current_user=Depends(get_current_user),
) -> uuid.UUID:
    """Get the current organization ID from request context."""
    return current_user.organization_id


def get_tenant_context(
    current_user=Depends(get_current_user),
) -> TenantContext:
    """Get full tenant context for the current request."""
    return TenantContext(
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        role=current_user.role,
    )


# ── Optional auth (for endpoints that work both ways) ─────────────────────────

async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> "User | None":
    """Return current user if authenticated, None otherwise."""
    from app.models.database.user import User

    if not credentials:
        return None

    try:
        payload = decode_token(credentials.credentials)
        if payload.type != "access":
            return None
        user_id = uuid.UUID(payload.sub)
        result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
        return result.scalar_one_or_none()
    except (JWTError, ValueError):
        return None
