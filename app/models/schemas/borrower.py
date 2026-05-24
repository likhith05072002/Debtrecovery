from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator
import phonenumbers


class BorrowerCreate(BaseModel):
    external_id: str = Field(..., min_length=1, max_length=128)
    phone: str = Field(..., description="Phone number in any parseable format")
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    time_zone: str = "America/New_York"
    preferred_language: str = "en"
    original_creditor: Optional[str] = None
    principal_amount: Decimal = Field(..., gt=0)
    current_balance: Decimal = Field(..., gt=0)
    interest_rate: Optional[Decimal] = None
    days_past_due: int = Field(default=0, ge=0)
    debt_type: Optional[str] = None
    consent_recorded: bool = False

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        try:
            parsed = phonenumbers.parse(v, "US")
            if not phonenumbers.is_valid_number(parsed):
                raise ValueError("Invalid phone number")
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException as e:
            raise ValueError(f"Could not parse phone number: {e}") from e


class BorrowerUpdate(BaseModel):
    current_balance: Optional[Decimal] = None
    days_past_due: Optional[int] = None
    consent_recorded: Optional[bool] = None
    do_not_call: Optional[bool] = None
    time_zone: Optional[str] = None


class BorrowerProfile(BaseModel):
    id: uuid.UUID
    external_id: str
    first_name: Optional[str]
    last_name: Optional[str]
    time_zone: str
    preferred_language: str
    original_creditor: Optional[str]
    principal_amount: Decimal
    current_balance: Decimal
    days_past_due: int
    debt_type: Optional[str]
    do_not_call: bool
    opted_out: bool
    bankruptcy_filed: bool
    consent_recorded: bool
    engagement_score: Decimal
    repayment_likelihood: Decimal
    sentiment_trend: str
    avoidance_score: Decimal
    promise_kept_rate: Optional[Decimal]
    total_calls: int
    successful_contacts: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OptOutRequest(BaseModel):
    channel: str = Field(default="all", pattern="^(voice|sms|all)$")
    reason: Optional[str] = None
