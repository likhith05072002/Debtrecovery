"""User management endpoints: list, invite, update role, deactivate."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password
from app.core.permissions import enforce_role
from app.dependencies import get_current_user, get_db
from app.models.database.user import Invitation, User

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class UserListItem(BaseModel):
    id: str
    email: str
    first_name: str | None
    last_name: str | None
    role: str
    is_active: bool
    email_verified: bool
    last_login_at: datetime | None
    created_at: datetime


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = Field(default="agent", pattern="^(admin|manager|agent|readonly)$")


class InviteResponse(BaseModel):
    id: str
    email: str
    role: str
    expires_at: datetime


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class UpdateUserRequest(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|manager|agent|readonly)$")
    is_active: bool | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[UserListItem])
async def list_users(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all users in the current organization. Requires manager+ role."""
    enforce_role(current_user.role, "manager")

    result = await db.execute(
        select(User)
        .where(User.organization_id == current_user.organization_id)
        .order_by(User.created_at.desc())
    )
    users = result.scalars().all()

    return [
        UserListItem(
            id=str(u.id),
            email=u.email,
            first_name=u.first_name,
            last_name=u.last_name,
            role=u.role,
            is_active=u.is_active,
            email_verified=u.email_verified,
            last_login_at=u.last_login_at,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/invite", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invite a new user to the organization. Requires admin+ role."""
    enforce_role(current_user.role, "admin")

    # Check if user already exists in this org
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )

    # Generate invitation token
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    invitation = Invitation(
        organization_id=current_user.organization_id,
        email=body.email,
        role=body.role,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invitation)
    await db.flush()

    # In production: send email with invite link containing raw_token
    # For now, return the token directly (dev mode)
    return InviteResponse(
        id=str(invitation.id),
        email=body.email,
        role=body.role,
        expires_at=invitation.expires_at,
    )


@router.post("/accept-invite", status_code=status.HTTP_201_CREATED)
async def accept_invite(body: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    """Accept an invitation and create a user account."""
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()

    result = await db.execute(
        select(Invitation).where(
            Invitation.token_hash == token_hash,
            Invitation.accepted_at == None,
        )
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired invitation")

    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invitation has expired")

    # Create user
    user = User(
        organization_id=invitation.organization_id,
        email=invitation.email,
        password_hash=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        role=invitation.role,
        is_active=True,
        email_verified=True,  # Accepted via email link
    )
    db.add(user)

    # Mark invitation as accepted
    invitation.accepted_at = datetime.now(timezone.utc)

    await db.flush()
    return {"user_id": str(user.id), "email": user.email}


@router.patch("/{user_id}", response_model=UserListItem)
async def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's role or active status. Requires admin+ role."""
    enforce_role(current_user.role, "admin")

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.organization_id == current_user.organization_id,
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Cannot modify owner
    if user.role == "owner" and current_user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify owner account")

    # Cannot deactivate yourself
    if user.id == current_user.id and body.is_active is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")

    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active

    return UserListItem(
        id=str(user.id),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_active=user.is_active,
        email_verified=user.email_verified,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user (soft delete). Requires admin+ role."""
    enforce_role(current_user.role, "admin")

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.organization_id == current_user.organization_id,
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot deactivate owner")
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")

    user.is_active = False
    return
