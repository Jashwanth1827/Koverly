"""Authentication service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, ConflictError
from app.core.security import (
    create_access_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.user import User
from app.schemas.user import UserRegister


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def register_user(db: AsyncSession, payload: UserRegister) -> User:
    email = payload.email.lower()
    if await get_user_by_email(db, email):
        raise ConflictError(
            "An account with this email already exists.",
            code="EMAIL_IN_USE",
        )
    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        phone=payload.phone,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(db, email)
    # Always perform a verification to reduce user-enumeration timing leaks.
    if user is None:
        hash_password(password)
        raise AuthenticationError("Incorrect email or password.")
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Incorrect email or password.")
    if not user.is_active:
        raise AuthenticationError("Account is not available.")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        await db.commit()
    return user


def issue_token(user: User) -> str:
    return create_access_token(user.id)
