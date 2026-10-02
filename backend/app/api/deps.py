"""Shared FastAPI dependencies: authentication, authorization, rate limiting.

Authorization model
-------------------
Every user-owned resource is reachable only through a family. A request must
therefore resolve to a *family context* consisting of the family and the
caller's role within it. Services then scope every query by ``family_id``.

Capability ranks are enforced via :func:`require_role`, so a ``viewer`` can
never mutate data and a non-member can never read it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.rate_limit import rate_limiter
from app.core.security import decode_token
from app.db.session import get_db
from app.models.enums import FamilyRole, ROLE_RANK
from app.models.family import Family, FamilyMember
from app.models.user import User

logger = logging.getLogger("koverly.auth")

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication required.")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Session expired. Please sign in again.") from None
    except jwt.PyJWTError:
        raise AuthenticationError("Invalid authentication token.") from None
    if payload.get("typ") != "access":
        raise AuthenticationError("Invalid authentication token.")
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Invalid authentication token.")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is not available.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def rate_limit(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Coarse rate limit keyed by user id when available, else client IP."""
    identity = request.client.host if request.client else "unknown"
    if credentials and credentials.credentials:
        try:
            payload = decode_token(credentials.credentials)
            identity = f"user:{payload.get('sub')}"
        except jwt.PyJWTError:
            pass
    rate_limiter.check(identity)


@dataclass
class FamilyContext:
    family: Family
    member: FamilyMember | None
    role: FamilyRole
    user: User

    @property
    def family_id(self) -> str:
        return self.family.id

    def at_least(self, role: FamilyRole) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


async def load_family_context(
    db: AsyncSession, user: User, family_id: str
) -> FamilyContext:
    """Resolve the caller's membership and role for a family.

    Raises 404 (not 403) when the user has no access, to avoid disclosing the
    existence of families the caller does not belong to.
    """
    family = await db.get(Family, family_id)
    if family is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("Family not found.")

    membership = (
        await db.execute(
            select(FamilyMember).where(
                FamilyMember.family_id == family_id,
                FamilyMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if membership is None:
        # Owner recorded on the family always has access.
        if family.owner_user_id == user.id:
            return FamilyContext(
                family=family, member=None, role=FamilyRole.OWNER, user=user
            )
        from app.core.errors import NotFoundError

        raise NotFoundError("Family not found.")

    try:
        role = FamilyRole(membership.role)
    except ValueError:
        role = FamilyRole.MEMBER
    return FamilyContext(family=family, member=membership, role=role, user=user)


def require_role(minimum: FamilyRole):
    """Dependency factory enforcing a minimum capability within a family.

    Usage: ``ctx = Depends(require_role(FamilyRole.ADMIN))`` with ``family_id``
    provided as a path or query parameter.
    """

    async def _dep(
        family_id: str,
        db: DbSession,
        user: CurrentUser,
    ) -> FamilyContext:
        ctx = await load_family_context(db, user, family_id)
        if not ctx.at_least(minimum):
            raise PermissionDeniedError(
                "You do not have permission to perform this action."
            )
        return ctx

    return _dep


async def get_family_context(
    family_id: str,
    db: DbSession,
    user: CurrentUser,
) -> FamilyContext:
    """Any-role access to a family the caller belongs to."""
    return await load_family_context(db, user, family_id)


FamilyCtx = Annotated[FamilyContext, Depends(get_family_context)]


async def audit_request_context(
    request: Request,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> str:
    return x_request_id or "-"
