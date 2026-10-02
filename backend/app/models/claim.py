"""Claim, claim event (timeline), reminder, and audit log models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import ClaimStatus, ReminderStatus, ReminderType


class Claim(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "claims"

    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True, nullable=False
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    member_id: Mapped[str | None] = mapped_column(
        ForeignKey("family_members.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    claim_type: Mapped[str] = mapped_column(String(60), nullable=False)
    claim_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    approved_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 2), nullable=True
    )
    provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    incident_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    submission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), default=ClaimStatus.DRAFT.value, index=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    policy = relationship("Policy", back_populates="claims")
    member = relationship("FamilyMember")
    documents = relationship("Document", back_populates="claim")
    events = relationship(
        "ClaimEvent",
        back_populates="claim",
        cascade="all, delete-orphan",
        order_by="ClaimEvent.created_at",
    )


class ClaimEvent(Base, UUIDMixin, TimestampMixin):
    """Immutable timeline entry for a claim status transition."""

    __tablename__ = "claim_events"

    claim_id: Mapped[str] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    claim = relationship("Claim", back_populates="events")


class Reminder(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "reminders"

    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True, nullable=False
    )
    policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), index=True, nullable=True
    )
    claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True, nullable=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    reminder_type: Mapped[str] = mapped_column(
        String(24), default=ReminderType.RENEWAL.value, index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    # Days-before offsets, e.g. [30, 14, 7, 1].
    offsets: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ReminderStatus.SCHEDULED.value, index=True, nullable=False
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "audit_logs"

    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    family_id: Mapped[str | None] = mapped_column(
        ForeignKey("families.id", ondelete="SET NULL"), index=True, nullable=True
    )
    action: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class EmergencyShare(Base, UUIDMixin, TimestampMixin):
    """Time-limited, read-only access to a family's emergency summary.

    The share exposes only the curated emergency payload — never the account,
    vault, or full policy list.
    """

    __tablename__ = "emergency_shares"

    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    member_id: Mapped[str | None] = mapped_column(
        ForeignKey("family_members.id", ondelete="CASCADE"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    max_views: Mapped[int] = mapped_column(default=20, nullable=False)
    view_count: Mapped[int] = mapped_column(default=0, nullable=False)


class Subscription(Base, UUIDMixin, TimestampMixin):
    """Billing abstraction. No real payment processing is implemented."""

    __tablename__ = "subscriptions"

    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), unique=True, index=True,
        nullable=False,
    )
    plan: Mapped[str] = mapped_column(String(24), default="free", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    external_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
