from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    strategy_type: str = Field(..., pattern="^(auto|reminder|negotiation|settlement|escalation)$")
    max_attempts: int = Field(default=5, ge=1, le=20)
    call_window_start: time = time(9, 0)
    call_window_end: time = time(20, 0)
    allowed_days: list[int] = Field(default=[1, 2, 3, 4, 5])
    retry_interval_hrs: Decimal = Field(default=Decimal("24.0"), ge=0)
    settlement_floor_pct: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)


class CampaignResponse(BaseModel):
    id: uuid.UUID
    name: str
    strategy_type: str
    status: str
    max_attempts: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AddBorrowersToCampaign(BaseModel):
    borrower_ids: list[uuid.UUID]
    priority: int = Field(default=5, ge=1, le=10)
