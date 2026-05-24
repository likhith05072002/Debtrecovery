"""Authentication endpoints: register, login, refresh, logout, password reset."""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
    TokenPair,
)
from app.dependencies import get_db, get_current_user
from app.models.database.organization import Organization
from app.models.database.user import User

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    organization_name: str = Field(min_length=2, max_length=200)


class RegisterResponse(BaseModel):
    user_id: str
    organization_id: str
    tokens: TokenPair


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str
    first_name: str | None
    last_name: str | None
    role: str
    organization_id: str
    organization_name: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new organization and its owner user."""
    # Check if email already exists
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Generate slug from org name
    slug = re.sub(r"[^a-z0-9]+", "-", body.organization_name.lower()).strip("-")
    # Ensure uniqueness
    existing_org = await db.execute(select(Organization).where(Organization.slug == slug))
    if existing_org.scalar_one_or_none():
        slug = f"{slug}-{secrets.token_hex(3)}"

    # Create organization
    org = Organization(
        name=body.organization_name,
        slug=slug,
        plan_tier="starter",
        status="active",
    )
    db.add(org)
    await db.flush()  # Get org.id

    # Create owner user
    user = User(
        organization_id=org.id,
        email=body.email,
        password_hash=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        role="owner",
        is_active=True,
        email_verified=False,
    )
    db.add(user)
    await db.flush()

    # Generate tokens
    tokens = create_token_pair(user.id, org.id, user.role)

    return RegisterResponse(
        user_id=str(user.id),
        organization_id=str(org.id),
        tokens=tokens,
    )


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with email and password."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)

    return create_token_pair(user.id, user.organization_id, user.role)


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new token pair."""
    try:
        payload = decode_token(body.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if payload.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    # Verify user still exists and is active
    user_id = uuid.UUID(payload.sub)
    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    # Issue new token pair (old refresh token is implicitly invalidated by short expiry)
    return create_token_pair(user.id, user.organization_id, user.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user=Depends(get_current_user)):
    """Logout current user (client should discard tokens)."""
    # In a production system, add the token's JTI to a Redis blacklist
    # For now, client-side token discard is sufficient
    return


@router.get("/me", response_model=UserResponse)
async def get_me(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get current authenticated user profile."""
    # Load org name
    result = await db.execute(select(Organization).where(Organization.id == current_user.organization_id))
    org = result.scalar_one_or_none()

    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        role=current_user.role,
        organization_id=str(current_user.organization_id),
        organization_name=org.name if org else None,
    )


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Request a password reset email. Always returns 202 to prevent email enumeration."""
    # In production: generate reset token, store in Redis with TTL, send email
    # For now, just acknowledge
    return {"message": "If the email exists, a reset link has been sent."}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Reset password using a reset token."""
    # In production: validate token from Redis, update password
    # Placeholder for now
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Password reset via email not yet configured",
    )
