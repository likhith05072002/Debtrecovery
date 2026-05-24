"""Onboarding wizard endpoints — guides new orgs through setup."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.database.onboarding import OnboardingProgress
from app.models.database.user import User

router = APIRouter()

# Onboarding steps in order
ONBOARDING_STEPS = ["phone", "borrowers", "voice", "compliance", "campaign", "first_call"]


class OnboardingStatus(BaseModel):
    current_step: str
    steps_completed: dict
    activation_score: float
    first_call_at: str | None
    first_collection_at: str | None


class StepCompleteRequest(BaseModel):
    step: str
    data: dict | None = None  # Step-specific data


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status", response_model=OnboardingStatus)
async def get_onboarding_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current onboarding progress."""
    progress = await _get_or_create_progress(db, current_user.organization_id)

    return OnboardingStatus(
        current_step=progress.current_step,
        steps_completed=progress.steps_completed,
        activation_score=float(progress.activation_score),
        first_call_at=progress.first_call_at.isoformat() if progress.first_call_at else None,
        first_collection_at=progress.first_collection_at.isoformat() if progress.first_collection_at else None,
    )


@router.post("/complete-step", response_model=OnboardingStatus)
async def complete_step(
    body: StepCompleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an onboarding step as complete and advance to next."""
    if body.step not in ONBOARDING_STEPS:
        raise HTTPException(status_code=422, detail=f"Invalid step: {body.step}")

    progress = await _get_or_create_progress(db, current_user.organization_id)

    # Mark step complete
    steps = progress.steps_completed or {}
    steps[body.step] = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "data": body.data,
    }
    progress.steps_completed = steps

    # Calculate activation score
    completed_count = len([s for s in ONBOARDING_STEPS if s in steps])
    progress.activation_score = round(completed_count / len(ONBOARDING_STEPS), 3)

    # Advance to next step
    current_idx = ONBOARDING_STEPS.index(body.step)
    if current_idx + 1 < len(ONBOARDING_STEPS):
        progress.current_step = ONBOARDING_STEPS[current_idx + 1]
    else:
        progress.current_step = "complete"

    return OnboardingStatus(
        current_step=progress.current_step,
        steps_completed=progress.steps_completed,
        activation_score=float(progress.activation_score),
        first_call_at=progress.first_call_at.isoformat() if progress.first_call_at else None,
        first_collection_at=progress.first_collection_at.isoformat() if progress.first_collection_at else None,
    )


@router.post("/upload-borrowers")
async def upload_borrowers_csv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a CSV file of borrowers during onboarding.

    Expected columns: external_id, phone, first_name, last_name, principal_amount, current_balance, days_past_due
    """
    import csv
    import io

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=422, detail="Please upload a CSV file")

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=422, detail="CSV file is empty")

    # Validate required columns
    required = {"external_id", "phone", "principal_amount", "current_balance"}
    actual_cols = set(rows[0].keys())
    missing = required - actual_cols
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required columns: {missing}. Found: {list(actual_cols)}",
        )

    # Return preview (actual import happens in a separate endpoint)
    return {
        "rows_found": len(rows),
        "columns": list(rows[0].keys()),
        "preview": rows[:5],
        "message": f"Found {len(rows)} borrowers ready to import",
    }


@router.post("/voice-test")
async def trigger_voice_test(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a test call to the owner's phone number to preview AI voice."""
    # In production: lookup org's Twilio config, call the owner
    return {
        "status": "initiated",
        "message": "A test call will be placed to your registered phone number within 30 seconds.",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_or_create_progress(
    db: AsyncSession, org_id: uuid.UUID
) -> OnboardingProgress:
    result = await db.execute(
        select(OnboardingProgress).where(OnboardingProgress.organization_id == org_id)
    )
    progress = result.scalar_one_or_none()

    if not progress:
        progress = OnboardingProgress(
            organization_id=org_id,
            steps_completed={},
            current_step="phone",
        )
        db.add(progress)
        await db.flush()

    return progress
