"""Campaign management API endpoints."""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.database.campaign import Campaign, CampaignBorrower
from app.models.database.user import User
from app.models.schemas.campaign import AddBorrowersToCampaign, CampaignCreate, CampaignResponse

router = APIRouter()


@router.post("", response_model=CampaignResponse, status_code=201)
async def create_campaign(
    payload: CampaignCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    campaign = Campaign(
        organization_id=current_user.organization_id,
        name=payload.name,
        strategy_type=payload.strategy_type,
        max_attempts=payload.max_attempts,
        call_window_start=payload.call_window_start,
        call_window_end=payload.call_window_end,
        allowed_days=payload.allowed_days,
        retry_interval_hrs=payload.retry_interval_hrs,
        settlement_floor_pct=payload.settlement_floor_pct,
        created_by=current_user.id,
    )
    db.add(campaign)
    await db.flush()
    return campaign


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Campaign)
        .where(Campaign.organization_id == current_user.organization_id)
        .order_by(Campaign.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.organization_id == current_user.organization_id,
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/{campaign_id}/borrowers", status_code=201)
async def add_borrowers_to_campaign(
    campaign_id: uuid.UUID,
    payload: AddBorrowersToCampaign,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-add borrowers to a campaign."""
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.organization_id == current_user.organization_id,
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    added = 0
    for borrower_id in payload.borrower_ids:
        cb = CampaignBorrower(
            campaign_id=campaign_id,
            borrower_id=borrower_id,
            priority=payload.priority,
        )
        db.add(cb)
        added += 1

    return {"campaign_id": str(campaign_id), "borrowers_added": added}


@router.post("/{campaign_id}/start", status_code=202)
async def start_campaign(
    campaign_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activate a draft campaign."""
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.organization_id == current_user.organization_id,
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "draft":
        raise HTTPException(status_code=422, detail=f"Campaign is already {campaign.status}")
    campaign.status = "active"
    return {"status": "active", "campaign_id": str(campaign_id)}
