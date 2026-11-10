"""Family and family member schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import FamilyRole, Relationship

# Common blood groups plus the "O+ve" style spelling. Kept permissive but
# bounded so obviously wrong values are rejected with a clear message.
_BLOOD_GROUPS = {
    "a+", "a-", "b+", "b-", "ab+", "ab-", "o+", "o-",
    "a1+", "a1-", "a2+", "a2-", "a1b+", "a1b-", "a2b+", "a2b-",
    "a+ve", "a-ve", "b+ve", "b-ve", "ab+ve", "ab-ve", "o+ve", "o-ve",
    "a1+ve", "a1-ve", "a2+ve", "a2-ve",
}


def _blank_to_none(value: object) -> object:
    """Treat empty/whitespace strings as absent.

    HTML inputs submit "" when left untouched; without this an empty date or
    email would fail validation as an "invalid request".
    """
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


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

    _normalize = field_validator("date_of_birth", "phone", "email", "blood_group", mode="before")(
        _blank_to_none
    )

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("blood_group", mode="after")
    @classmethod
    def _check_blood_group(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.lower() not in _BLOOD_GROUPS:
            raise ValueError("Blood group must be a value such as A+, B-, AB+ or O+.")
        return value


class FamilyMemberUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    relationship: Relationship | None = None
    date_of_birth: date | None = None
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    blood_group: str | None = Field(default=None, max_length=8)

    _normalize = field_validator("date_of_birth", "phone", "email", "blood_group", mode="before")(
        _blank_to_none
    )

    @field_validator("blood_group", mode="after")
    @classmethod
    def _check_blood_group(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.lower() not in _BLOOD_GROUPS:
            raise ValueError("Blood group must be a value such as A+, B-, AB+ or O+.")
        return value


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
