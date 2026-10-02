"""Family, membership, and family member models.

Ownership chain::

    User --(FamilyMember.membership)--> Family --(FamilyMember)--> members

``FamilyMember`` serves two purposes:

* a *person* record describing an insured individual (name, relationship), and
* optionally a *membership* linking a ``User`` account to the family with a role.

A person without a ``user_id`` is a dependant who has no account yet.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship as orm_relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import FamilyRole, Relationship


class Family(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "families"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    members = orm_relationship(
        "FamilyMember",
        back_populates="family",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    # Deleting a family must remove its policies. Rely on the database
    # ON DELETE CASCADE rather than the ORM nulling out policy.family_id
    # (which is NOT NULL and would fail).
    policies = orm_relationship(
        "Policy", back_populates="family", passive_deletes=True
    )


class FamilyMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "family_members"
    __table_args__ = (
        UniqueConstraint("family_id", "user_id", name="uq_family_member_user"),
    )

    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Null for dependants without an account.
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # Person details
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    relationship: Mapped[str] = mapped_column(
        String(32), default=Relationship.OTHER.value, nullable=False
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Membership role (only meaningful when user_id is set). Person-only
    # records carry the MEMBER role value but grant no account access.
    role: Mapped[str] = mapped_column(
        String(16), default=FamilyRole.MEMBER.value, nullable=False
    )
    is_account_linked: Mapped[bool] = mapped_column(default=False, nullable=False)

    family = orm_relationship("Family", back_populates="members")
    user = orm_relationship("User", back_populates="memberships")
    policies = orm_relationship("Policy", back_populates="member")
