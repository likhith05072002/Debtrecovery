"""Organization management endpoints: settings, API keys."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import generate_api_key
from app.core.permissions import enforce_role
from app.dependencies import get_current_user, get_db
from app.models.database.organization import Organization
from app.models.database.user import APIKey

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class OrgResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan_tier: str
    status: str
    agent_name: str
    agency_name: str
    max_concurrent_calls: int
    settings: dict | None
    created_at: datetime


class UpdateOrgRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    agent_name: str | None = Field(default=None, max_length=100)
    agency_name: str | None = Field(default=None, max_length=200)
    max_concurrent_calls: int | None = Field(default=None, ge=1, le=100)
    settings: dict | None = None


class APIKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default=["*"])
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class APIKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: list[str] | None
    is_active: bool
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class APIKeyCreateResponse(APIKeyResponse):
    key: str  # Only returned on creation


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=OrgResponse)
async def get_organization(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current organization details."""
    result = await db.execute(
        select(Organization).where(Organization.id == current_user.organization_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    return OrgResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        plan_tier=org.plan_tier,
        status=org.status,
        agent_name=org.agent_name,
        agency_name=org.agency_name,
        max_concurrent_calls=org.max_concurrent_calls,
        settings=org.settings,
        created_at=org.created_at,
    )


@router.patch("", response_model=OrgResponse)
async def update_organization(
    body: UpdateOrgRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update organization settings. Requires admin+ role."""
    enforce_role(current_user.role, "admin")

    result = await db.execute(
        select(Organization).where(Organization.id == current_user.organization_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    if body.name is not None:
        org.name = body.name
    if body.agent_name is not None:
        org.agent_name = body.agent_name
    if body.agency_name is not None:
        org.agency_name = body.agency_name
    if body.max_concurrent_calls is not None:
        org.max_concurrent_calls = body.max_concurrent_calls
    if body.settings is not None:
        org.settings = body.settings

    return OrgResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        plan_tier=org.plan_tier,
        status=org.status,
        agent_name=org.agent_name,
        agency_name=org.agency_name,
        max_concurrent_calls=org.max_concurrent_calls,
        settings=org.settings,
        created_at=org.created_at,
    )


# ── API Keys ─────────────────────────────────────────────────────────────────

@router.post("/api-keys", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: APIKeyCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key for the organization. Requires admin+ role."""
    enforce_role(current_user.role, "admin")

    raw_key, key_hash, key_prefix = generate_api_key()

    expires_at = None
    if body.expires_in_days:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)

    api_key = APIKey(
        organization_id=current_user.organization_id,
        created_by=current_user.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=body.name,
        scopes=body.scopes,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.flush()

    return APIKeyCreateResponse(
        id=str(api_key.id),
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        key=raw_key,  # Only time the full key is returned
        scopes=api_key.scopes,
        is_active=api_key.is_active,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all API keys for the organization. Requires admin+ role."""
    enforce_role(current_user.role, "admin")

    result = await db.execute(
        select(APIKey)
        .where(APIKey.organization_id == current_user.organization_id)
        .order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()

    return [
        APIKeyResponse(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes,
            is_active=k.is_active,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
            created_at=k.created_at,
        )
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke (deactivate) an API key. Requires admin+ role."""
    enforce_role(current_user.role, "admin")

    result = await db.execute(
        select(APIKey).where(
            APIKey.id == key_id,
            APIKey.organization_id == current_user.organization_id,
        )
    )
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    key.is_active = False
    return
