"""Insurance policy model.

Core relational fields are columns; genuinely variable, type-specific
attributes live in the ``metadata_json`` JSON column.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import PolicyStatus, PolicyType, PremiumFrequency


class Policy(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "policies"

    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Primary policyholder as a family member (nullable for imported legacy data).
    member_id: Mapped[str | None] = mapped_column(
        ForeignKey("family_members.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    policy_type: Mapped[str] = mapped_column(
        String(32), default=PolicyType.OTHER.value, index=True, nullable=False
    )
    insurer: Mapped[str] = mapped_column(String(200), nullable=False)
    policy_number: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    policyholder_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    premium: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    premium_frequency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sum_insured: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    renewal_date: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    nominee: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=PolicyStatus.ACTIVE.value, index=True, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Variable / type-specific attributes (waiting periods, deductibles, TPA,
    # claim contact, exclusions, coverage summary, ...).
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    family = relationship("Family", back_populates="policies")
    member = relationship("FamilyMember", back_populates="policies")
    documents = relationship("Document", back_populates="policy")
    claims = relationship("Claim", back_populates="policy")

    @property
    def metadata_(self) -> dict:
        return self.metadata_json or {}
