"""Authentication service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError, ValidationError
from app.core.security import (
    create_access_token,
    generate_raw_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from app.integrations.notifications import NotificationMessage, get_notification_backend
from app.models.auth_token import (
    EmailVerificationToken,
    LoginAttempt,
    PasswordResetToken,
    RefreshToken,
)
from app.models.user import User
from app.schemas.user import UserRegister


def _now() -> datetime:
    return datetime.now(UTC)


async def _record_login_attempt(
    db: AsyncSession,
    *,
    email: str | None,
    ip_address: str | None,
    user_agent: str | None,
    success: bool,
) -> None:
    db.add(
        LoginAttempt(
            email=email.lower() if email else None,
            ip_address=ip_address,
            success=success,
            user_agent=user_agent[:255] if user_agent else None,
        )
    )


async def _check_lockout(
    db: AsyncSession,
    user: User,
    *,
    ip_address: str | None,
    email: str | None,
) -> None:
    now = _now()
    if user.locked_until and user.locked_until > now:
        raise AuthenticationError("Account temporarily locked. Try again later.")

    # Global lock per IP to blunt credential stuffing.
    if ip_address and settings.LOGIN_MAX_ATTEMPTS_IP > 0:
        cutoff = now - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
        result = await db.execute(
            select(LoginAttempt).where(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.success.is_(False),
                LoginAttempt.created_at >= cutoff,
            )
        )
        if len(result.scalars().all()) >= settings.LOGIN_MAX_ATTEMPTS_IP:
            raise AuthenticationError("Too many login attempts. Try again later.")


async def _reset_lockout(user: User) -> None:
    user.failed_login_count = 0
    user.last_failed_login_at = None
    user.locked_until = None


async def _register_failure(db: AsyncSession, user: User) -> None:
    now = _now()
    user.failed_login_count = (user.failed_login_count or 0) + 1
    user.last_failed_login_at = now
    if (
        settings.LOGIN_MAX_ATTEMPTS > 0
        and user.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS
    ):
        user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    await db.commit()


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
        is_verified=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(
    db: AsyncSession,
    email: str,
    password: str,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> User:
    normalized = email.lower()
    user = await get_user_by_email(db, normalized)
    # Always perform a verification to reduce user-enumeration timing leaks.
    if user is None:
        hash_password(password)
        await _record_login_attempt(
            db, email=normalized, ip_address=ip_address, user_agent=user_agent, success=False
        )
        await db.commit()
        raise AuthenticationError("Incorrect email or password.")
    await _check_lockout(db, user, ip_address=ip_address, email=normalized)
    if not verify_password(password, user.password_hash):
        await _record_login_attempt(
            db, email=normalized, ip_address=ip_address, user_agent=user_agent, success=False
        )
        await _register_failure(db, user)
        raise AuthenticationError("Incorrect email or password.")
    if not user.is_active:
        await _record_login_attempt(
            db, email=normalized, ip_address=ip_address, user_agent=user_agent, success=False
        )
        await db.commit()
        raise AuthenticationError("Account is not available.")
    await _record_login_attempt(
        db, email=normalized, ip_address=ip_address, user_agent=user_agent, success=True
    )
    await _reset_lockout(user)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    await db.commit()
    await db.refresh(user)
    return user


def issue_token(user: User) -> str:
    return create_access_token(user.id)


async def create_refresh_token(
    db: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
    family_id: str | None = None,
) -> tuple[RefreshToken, str]:
    raw = generate_raw_token(48)
    token_hash = hash_token(raw)
    expires = _now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    row = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        family_id=family_id,
        expires_at=expires,
        user_agent=user_agent[:255] if user_agent else None,
        ip_address=ip_address[:64] if ip_address else None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, raw


async def rotate_refresh_token(
    db: AsyncSession,
    raw_token: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, str]:
    token_hash = hash_token(raw_token)
    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise AuthenticationError("Invalid refresh token.")
    if row.expires_at < _now():
        raise AuthenticationError("Refresh token expired.")
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is not available.")
    if settings.REFRESH_TOKEN_ROTATE:
        new_row, new_raw = await create_refresh_token(
            db,
            user,
            user_agent=user_agent,
            ip_address=ip_address,
            family_id=row.family_id,
        )
        row.revoked_at = _now()
        row.replaced_by_id = new_row.id
        await db.commit()
        return user, new_raw
    return user, raw_token


async def revoke_refresh_token(db: AsyncSession, raw_token: str) -> None:
    token_hash = hash_token(raw_token)
    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return
    row.revoked_at = _now()
    await db.commit()


async def revoke_all_refresh_tokens(db: AsyncSession, user_id: str) -> int:
    rows = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    )
    count = 0
    for row in rows.scalars().all():
        row.revoked_at = _now()
        count += 1
    await db.commit()
    return count


async def create_email_verification_token(db: AsyncSession, user: User) -> str:
    await db.execute(
        delete(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
        )
    )
    raw = generate_raw_token(32)
    row = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(raw),
        expires_at=_now() + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS),
    )
    db.add(row)
    await db.commit()
    backend = get_notification_backend()
    await backend.send(
        NotificationMessage(
            recipient=user.email,
            subject="Verify your Koverly email",
            body=(
                "Verify your email address to secure your Koverly account.\n\n"
                f"Use this token: {raw}\n\n"
                "If you did not create this account, you can ignore this message."
            ),
        )
    )
    return raw


async def verify_email(db: AsyncSession, raw_token: str) -> User:
    token_hash = hash_token(raw_token)
    row = (
        await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == token_hash
            )
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at < _now():
        raise ValidationError("Invalid or expired email verification token.")
    user = await db.get(User, row.user_id)
    if user is None:
        raise ValidationError("Invalid or expired email verification token.")
    user.is_verified = True
    row.used_at = _now()
    await db.commit()
    await db.refresh(user)
    return user


async def create_password_reset_token(db: AsyncSession, email: str) -> str | None:
    user = await get_user_by_email(db, email)
    # Always return success shape to avoid user enumeration.
    if user is None:
        return None
    await db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    )
    raw = generate_raw_token(32)
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(raw),
        expires_at=_now() + timedelta(hours=settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS),
    )
    db.add(row)
    await db.commit()
    backend = get_notification_backend()
    await backend.send(
        NotificationMessage(
            recipient=user.email,
            subject="Reset your Koverly password",
            body=(
                "Someone requested a password reset for your Koverly account.\n\n"
                f"Use this token: {raw}\n\n"
                "If this wasn't you, ignore this message and your password will stay the same."
            ),
        )
    )
    return raw


async def reset_password(db: AsyncSession, raw_token: str, new_password: str) -> User:
    token_hash = hash_token(raw_token)
    row = (
        await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash
            )
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at < _now():
        raise ValidationError("Invalid or expired password reset token.")
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise ValidationError("Invalid or expired password reset token.")
    user.password_hash = hash_password(new_password)
    row.used_at = _now()
    await _reset_lockout(user)
    await revoke_all_refresh_tokens(db, user.id)
    await db.commit()
    await db.refresh(user)
    return user
