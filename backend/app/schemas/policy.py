"""Policy schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PolicyStatus, PolicyType, PremiumFrequency


class PolicyBase(BaseModel):
    policy_type: PolicyType = PolicyType.OTHER
    insurer: str = Field(min_length=1, max_length=200)
    policy_number: str = Field(min_length=1, max_length=120)
    policyholder_name: str | None = Field(default=None, max_length=200)
    member_id: str | None = None

    premium: Decimal | None = Field(default=None, ge=0)
    premium_frequency: PremiumFrequency | None = None
    sum_insured: Decimal | None = Field(default=None, ge=0)

    start_date: date | None = None
    expiry_date: date | None = None
    renewal_date: date | None = None
    maturity_date: date | None = None

    nominee: str | None = Field(default=None, max_length=200)
    status: PolicyStatus = PolicyStatus.ACTIVE
    notes: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class PolicyCreate(PolicyBase):
    family_id: str


class PolicyUpdate(BaseModel):
    policy_type: PolicyType | None = None
    insurer: str | None = Field(default=None, min_length=1, max_length=200)
    policy_number: str | None = Field(default=None, min_length=1, max_length=120)
    policyholder_name: str | None = Field(default=None, max_length=200)
    member_id: str | None = None
    premium: Decimal | None = Field(default=None, ge=0)
    premium_frequency: PremiumFrequency | None = None
    sum_insured: Decimal | None = Field(default=None, ge=0)
    start_date: date | None = None
    expiry_date: date | None = None
    renewal_date: date | None = None
    maturity_date: date | None = None
    nominee: str | None = Field(default=None, max_length=200)
    status: PolicyStatus | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    member_id: str | None
    created_by_user_id: str
    policy_type: str
    insurer: str
    policy_number: str
    policyholder_name: str | None
    premium: Decimal | None
    premium_frequency: str | None
    sum_insured: Decimal | None
    start_date: date | None
    expiry_date: date | None
    renewal_date: date | None
    maturity_date: date | None
    nominee: str | None
    status: str
    notes: str | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PolicySummary(BaseModel):
    """Dashboard aggregate over a set of policies."""

    active_policies: int
    total_annual_premium: Decimal
    total_life_coverage: Decimal
    total_health_coverage: Decimal
    total_other_coverage: Decimal
    currency: str = "INR"
    by_type: dict[str, int]
