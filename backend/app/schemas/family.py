"""Family and family member schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import FamilyRole, Relationship


class FamilyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class FamilyUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class FamilyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    owner_user_id: str
    created_at: datetime


class FamilyMemberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    relationship: Relationship = Relationship.OTHER
    date_of_birth: date | None = None
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    blood_group: str | None = Field(default=None, max_length=8)


class FamilyMemberUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    relationship: Relationship | None = None
    date_of_birth: date | None = None
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    blood_group: str | None = Field(default=None, max_length=8)


class FamilyMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    user_id: str | None
    name: str
    relationship: str
    date_of_birth: date | None
    phone: str | None
    email: str | None
    blood_group: str | None
    role: str
    is_account_linked: bool
    created_at: datetime


class InviteMember(BaseModel):
    email: EmailStr
    role: FamilyRole = FamilyRole.MEMBER
    member_id: str | None = None


class RoleUpdate(BaseModel):
    role: FamilyRole


class FamilyAccessOut(BaseModel):
    """The caller's effective access to a family."""

    family: FamilyOut
    role: FamilyRole
    member_id: str | None
