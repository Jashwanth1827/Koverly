"""Claim, reminder, audit, intelligence, emergency, and billing schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ClaimStatus,
    ReminderStatus,
    ReminderType,
    SubscriptionPlan,
)


class ClaimCreate(BaseModel):
    policy_id: str
    family_id: str
    member_id: str | None = None
    claim_type: str = Field(min_length=1, max_length=60)
    claim_amount: Decimal | None = Field(default=None, ge=0)
    provider: str | None = Field(default=None, max_length=200)
    incident_date: date | None = None
    submission_date: date | None = None
    description: str | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ClaimUpdate(BaseModel):
    claim_type: str | None = Field(default=None, min_length=1, max_length=60)
    claim_amount: Decimal | None = Field(default=None, ge=0)
    approved_amount: Decimal | None = Field(default=None, ge=0)
    provider: str | None = Field(default=None, max_length=200)
    incident_date: date | None = None
    submission_date: date | None = None
    status: ClaimStatus | None = None
    description: str | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None


class ClaimEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    note: str | None
    actor_user_id: str | None
    created_at: datetime


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    policy_id: str
    member_id: str | None
    claim_type: str
    claim_amount: Decimal | None
    approved_amount: Decimal | None
    provider: str | None
    incident_date: date | None
    submission_date: date | None
    status: str
    description: str | None
    notes: str | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ClaimDetail(ClaimOut):
    events: list[ClaimEventOut] = Field(default_factory=list)


class ReminderCreate(BaseModel):
    family_id: str
    policy_id: str | None = None
    claim_id: str | None = None
    reminder_type: ReminderType = ReminderType.RENEWAL
    title: str = Field(min_length=1, max_length=200)
    due_date: date
    offsets: list[int] = Field(default_factory=lambda: [30, 14, 7, 1])


class ReminderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: date | None = None
    offsets: list[int] | None = None
    status: ReminderStatus | None = None


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    policy_id: str | None
    claim_id: str | None
    reminder_type: str
    title: str
    due_date: date
    offsets: list[int]
    status: str
    last_triggered_at: datetime | None
    acknowledged_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_user_id: str | None
    family_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    metadata_json: dict[str, Any]
    created_at: datetime


class IntelligenceItem(BaseModel):
    kind: str  # expiring | missing_info | potential_overlap | action
    severity: str  # info | warning | critical
    title: str
    detail: str
    policy_id: str | None = None
    member_id: str | None = None
    due_date: date | None = None


class CoverageNode(BaseModel):
    category: str
    policy_count: int
    total_coverage: Decimal
    policyholders: list[str]
    nearest_expiry: date | None
    missing_info: list[str]
    attention: list[str]


class CoverageMap(BaseModel):
    family_id: str
    categories: list[CoverageNode]


class IntelligenceResponse(BaseModel):
    family_id: str
    generated_at: datetime
    items: list[IntelligenceItem]


class CalendarEvent(BaseModel):
    id: str
    kind: str  # renewal | premium | claim | document | policy
    title: str
    date: date
    policy_id: str | None = None
    claim_id: str | None = None
    status: str | None = None


class EmergencyContact(BaseModel):
    label: str
    value: str


class EmergencyPolicy(BaseModel):
    policy_id: str
    policy_type: str
    insurer: str
    policy_number: str
    sum_insured: Decimal | None
    tpa: str | None
    claim_contact: str | None
    expiry_date: date | None
    document_ids: list[str]


class FamilyMemberEmergency(BaseModel):
    id: str
    name: str
    relationship: str
    blood_group: str | None
    date_of_birth: date | None


class EmergencyProfile(BaseModel):
    family_id: str
    family_name: str
    generated_at: datetime
    member: FamilyMemberEmergency | None = None
    policies: list[EmergencyPolicy]
    contacts: list[EmergencyContact]
    claim_instructions: list[str]


class EmergencyShareCreate(BaseModel):
    member_id: str | None = None
    ttl_minutes: int = Field(default=60, ge=5, le=1440)
    max_views: int = Field(default=20, ge=1, le=200)


class EmergencyShareOut(BaseModel):
    id: str
    token: str
    url: str
    expires_at: datetime
    max_views: int
    view_count: int


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    plan: str
    status: str
    provider: str | None
    current_period_end: datetime | None


class SubscriptionUpdate(BaseModel):
    plan: SubscriptionPlan


class DashboardOut(BaseModel):
    family_id: str
    family_name: str
    active_policies: int
    total_annual_premium: Decimal
    total_life_coverage: Decimal
    total_health_coverage: Decimal
    total_other_coverage: Decimal
    upcoming_renewals: list[IntelligenceItem]
    pending_actions: list[IntelligenceItem]
    recent_claims: list[ClaimOut]
    alerts: list[IntelligenceItem]
    by_type: dict[str, int]


class SearchResult(BaseModel):
    kind: str
    id: str
    title: str
    subtitle: str | None = None
    policy_id: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
