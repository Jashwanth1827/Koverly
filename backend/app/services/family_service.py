"""Family, membership, and family member services."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.integrations.storage import get_storage
from app.models.document import Document
from app.models.enums import AuditAction, FamilyRole, Relationship
from app.models.family import Family, FamilyMember
from app.models.user import User
from app.schemas.family import FamilyMemberCreate, FamilyMemberUpdate
from app.services import audit

logger = logging.getLogger("koverly.families")


async def create_family(db: AsyncSession, owner: User, name: str) -> Family:
    family = Family(name=name.strip(), owner_user_id=owner.id)
    db.add(family)
    await db.flush()

    # The owner is always represented as a member record with the owner role.
    owner_member = FamilyMember(
        family_id=family.id,
        user_id=owner.id,
        name=owner.full_name,
        relationship=Relationship.SELF.value,
        email=owner.email,
        phone=owner.phone,
        role=FamilyRole.OWNER.value,
        is_account_linked=True,
    )
    db.add(owner_member)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.FAMILY_CREATED.value,
        resource_type="family",
        resource_id=family.id,
        actor_user_id=owner.id,
        family_id=family.id,
        metadata={"name": family.name},
    )
    await audit.record(
        db,
        action=AuditAction.FAMILY_MEMBER_ADDED.value,
        resource_type="family",
        resource_id=family.id,
        actor_user_id=owner.id,
        family_id=family.id,
        metadata={"name": owner.full_name, "role": FamilyRole.OWNER.value},
    )
    await db.commit()
    await db.refresh(family)
    return family


async def list_families_for_user(db: AsyncSession, user: User) -> list[Family]:
    rows = await db.execute(
        select(Family)
        .join(FamilyMember, FamilyMember.family_id == Family.id)
        .where(FamilyMember.user_id == user.id)
        .order_by(Family.created_at)
    )
    return list(rows.scalars().unique().all())


async def update_family(
    db: AsyncSession, family: Family, *, name: str, actor: User
) -> Family:
    family.name = name.strip()
    await db.commit()
    await db.refresh(family)
    return family


async def delete_family(db: AsyncSession, family: Family, actor: User) -> None:
    """Permanently delete a family and everything that belongs to it.

    All family-scoped rows are removed via database ON DELETE CASCADE. Stored
    document files are collected *before* the rows disappear and purged from
    storage afterwards. An audit entry is written first (with its family link
    cleared) so the destructive action is recorded.
    """
    if family.owner_user_id != actor.id:
        raise PermissionDeniedError("Only the family owner can delete the family.")

    family_id = family.id
    family_name = family.name

    # Collect storage keys up front — the rows are gone after the delete.
    keys = (
        await db.execute(
            select(Document.storage_key).where(Document.family_id == family_id)
        )
    ).scalars().all()

    # Audit before deletion; the family link is nulled so the entry survives.
    await audit.record(
        db,
        action=AuditAction.FAMILY_DELETED.value,
        resource_type="family",
        resource_id=family_id,
        actor_user_id=actor.id,
        family_id=None,
        metadata={"name": family_name},
    )
    await db.flush()

    await db.delete(family)
    await db.commit()

    storage = get_storage()
    for key in keys:
        try:
            await storage.delete(key)
        except Exception:  # noqa: BLE001 - rows already gone; log and continue
            logger.exception("family_delete_storage_purge_failed key=%s", key)


async def list_members(db: AsyncSession, family_id: str) -> list[FamilyMember]:
    rows = await db.execute(
        select(FamilyMember)
        .where(FamilyMember.family_id == family_id)
        .order_by(FamilyMember.created_at)
    )
    return list(rows.scalars().all())


async def get_member(
    db: AsyncSession, family_id: str, member_id: str
) -> FamilyMember:
    member = await db.get(FamilyMember, member_id)
    if member is None or member.family_id != family_id:
        raise NotFoundError("Family member not found.")
    return member


async def add_member(
    db: AsyncSession, family_id: str, payload: FamilyMemberCreate, actor: User
) -> FamilyMember:
    member = FamilyMember(
        family_id=family_id,
        name=payload.name.strip(),
        relationship=payload.relationship.value,
        date_of_birth=payload.date_of_birth,
        phone=payload.phone,
        email=str(payload.email) if payload.email else None,
        blood_group=payload.blood_group,
        role=FamilyRole.MEMBER.value,
        is_account_linked=False,
    )
    db.add(member)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.FAMILY_MEMBER_ADDED.value,
        resource_type="family_member",
        resource_id=member.id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={"name": member.name, "relationship": member.relationship},
    )
    await db.commit()
    await db.refresh(member)
    return member


async def update_member(
    db: AsyncSession,
    family_id: str,
    member_id: str,
    payload: FamilyMemberUpdate,
    actor: User,
) -> FamilyMember:
    member = await get_member(db, family_id, member_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if field == "relationship" and value is not None:
            member.relationship = (
                value.value if isinstance(value, Relationship) else value
            )
        elif field == "email" and value is not None:
            member.email = str(value)
        else:
            setattr(member, field, value)
    await db.commit()
    await db.refresh(member)
    return member


async def remove_member(
    db: AsyncSession, family_id: str, member_id: str, actor: User
) -> None:
    member = await get_member(db, family_id, member_id)
    if member.user_id == actor.id:
        raise ValidationError("You cannot remove your own membership.")
    if member.role == FamilyRole.OWNER.value:
        raise ValidationError("The family owner cannot be removed.")
    await db.delete(member)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.FAMILY_MEMBER_REMOVED.value,
        resource_type="family_member",
        resource_id=member_id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={"name": member.name},
    )
    await db.commit()


async def invite_member(
    db: AsyncSession,
    family_id: str,
    *,
    email: str,
    role: FamilyRole,
    member_id: str | None,
    actor: User,
) -> FamilyMember:
    """Link an existing account to the family with a role.

    There is no email delivery in v1: the invite links an existing Koverly
    account to the family. If the account does not exist we return a clear
    error rather than silently creating an unusable membership.
    """
    if role == FamilyRole.OWNER:
        raise ValidationError("Ownership transfer is not supported here.")

    target = (
        await db.execute(select(User).where(User.email == email.lower()))
    ).scalar_one_or_none()
    if target is None:
        raise NotFoundError(
            "No Koverly account exists for that email. Ask them to sign up first."
        )

    existing = (
        await db.execute(
            select(FamilyMember).where(
                FamilyMember.family_id == family_id,
                FamilyMember.user_id == target.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("That person is already a member of this family.")

    if member_id:
        member = await get_member(db, family_id, member_id)
        if member.user_id is not None:
            raise ConflictError("That person record is already linked to an account.")
        member.user_id = target.id
        member.email = target.email
        member.role = role.value
        member.is_account_linked = True
    else:
        member = FamilyMember(
            family_id=family_id,
            user_id=target.id,
            name=target.full_name,
            relationship=Relationship.OTHER.value,
            email=target.email,
            role=role.value,
            is_account_linked=True,
        )
        db.add(member)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.USER_INVITED.value,
        resource_type="family_member",
        resource_id=member.id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={"email": target.email, "role": role.value},
    )
    await db.commit()
    await db.refresh(member)
    return member


async def change_role(
    db: AsyncSession,
    family_id: str,
    member_id: str,
    *,
    role: FamilyRole,
    actor: User,
) -> FamilyMember:
    member = await get_member(db, family_id, member_id)
    if member.role == FamilyRole.OWNER.value:
        raise ValidationError("The owner's role cannot be changed.")
    if role == FamilyRole.OWNER:
        raise ValidationError("Ownership transfer is not supported here.")
    previous = member.role
    member.role = role.value
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.USER_ROLE_CHANGED.value,
        resource_type="family_member",
        resource_id=member.id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={"from": previous, "to": role.value},
    )
    await db.commit()
    await db.refresh(member)
    return member


async def count_members(db: AsyncSession, family_id: str) -> int:
    return int(
        (
            await db.execute(
                select(func.count(FamilyMember.id)).where(
                    FamilyMember.family_id == family_id
                )
            )
        ).scalar_one()
    )
