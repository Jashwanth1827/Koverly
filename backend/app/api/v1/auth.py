"""Authentication endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.api.deps import CurrentUser, DbSession, rate_limit
from app.core.config import settings
from app.core.errors import AuthenticationError
from app.core.security import create_access_token
from app.schemas.user import (
    AuthTokensResponse,
    EmailRequest,
    MessageResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserLogin,
    UserOut,
    UserRegister,
    UserUpdate,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "koverly_refresh"


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


def _set_refresh_cookie(response: Response, raw_refresh: str) -> None:
    secure = settings.AUTH_COOKIE_SECURE
    samesite = settings.AUTH_COOKIE_SAMESITE.lower()
    if samesite not in {"lax", "strict", "none"}:
        samesite = "lax"
    if samesite == "none":
        secure = True
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=raw_refresh,
        httponly=True,
        secure=secure,
        samesite=samesite,
        domain=settings.AUTH_COOKIE_DOMAIN or None,
        path="/api/v1/auth",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def _clear_refresh_cookie(response: Response) -> None:
    samesite = settings.AUTH_COOKIE_SAMESITE.lower()
    if samesite == "none":
        secure = True
    else:
        secure = settings.AUTH_COOKIE_SECURE
    response.set_cookie(
        key=REFRESH_COOKIE,
        value="",
        httponly=True,
        secure=secure,
        samesite=samesite,
        domain=settings.AUTH_COOKIE_DOMAIN or None,
        path="/api/v1/auth",
        max_age=0,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit)],
)
async def register(payload: UserRegister, db: DbSession) -> TokenResponse:
    user = await auth_service.register_user(db, payload)
    token = auth_service.issue_token(user)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit)],
)
async def login(
    payload: UserLogin,
    request: Request,
    db: DbSession,
    response: Response,
) -> TokenResponse:
    ip, ua = _client_meta(request)
    user = await auth_service.authenticate(
        db, str(payload.email), payload.password, ip_address=ip, user_agent=ua
    )
    token = auth_service.issue_token(user)
    _, raw_refresh = await auth_service.create_refresh_token(
        db, user, user_agent=ua, ip_address=ip
    )
    _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/refresh", response_model=AuthTokensResponse)
async def refresh(
    request: Request,
    db: DbSession,
    response: Response,
    koverly_refresh: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> AuthTokensResponse:
    if not koverly_refresh:
        raise AuthenticationError("Refresh token required.")
    ip, ua = _client_meta(request)
    user, raw_refresh = await auth_service.rotate_refresh_token(
        db, koverly_refresh, user_agent=ua, ip_address=ip
    )
    if settings.REFRESH_TOKEN_ROTATE:
        _set_refresh_cookie(response, raw_refresh)
    access = create_access_token(user.id)
    return AuthTokensResponse(
        access_token=access,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    db: DbSession,
    response: Response,
    koverly_refresh: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> MessageResponse:
    if koverly_refresh:
        await auth_service.revoke_refresh_token(db, koverly_refresh)
    _clear_refresh_cookie(response)
    return MessageResponse(message="Logged out.")


@router.post("/logout-all", response_model=MessageResponse)
async def logout_all(user: CurrentUser, db: DbSession, response: Response) -> MessageResponse:
    await auth_service.revoke_all_refresh_tokens(db, user.id)
    _clear_refresh_cookie(response)
    return MessageResponse(message="Signed out of all sessions.")


@router.post("/verify-email/request", response_model=MessageResponse)
async def request_email_verification(
    user: CurrentUser, db: DbSession
) -> MessageResponse:
    await auth_service.create_email_verification_token(db, user)
    return MessageResponse(message="Verification email sent.")


@router.post("/verify-email/confirm", response_model=MessageResponse)
async def confirm_email_verification(
    payload: EmailRequest, db: DbSession, token: str | None = None
) -> MessageResponse:
    raw = token or payload.model_dump().get("token") if hasattr(payload, "model_dump") else None
    # Accept token in body via a flexible shape: { "token": "..." } or { "email": "..." } is not.
    # Pydantic EmailRequest only has email; use a raw dict to stay compatible with common clients.
    if raw is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="token is required")
    await auth_service.verify_email(db, raw)
    return MessageResponse(message="Email verified.")


@router.post("/password-reset/request", response_model=MessageResponse)
async def request_password_reset(
    payload: EmailRequest, db: DbSession
) -> MessageResponse:
    await auth_service.create_password_reset_token(db, str(payload.email))
    return MessageResponse(message="If an account exists, a reset email has been sent.")


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    payload: ResetPasswordRequest, db: DbSession
) -> MessageResponse:
    await auth_service.reset_password(db, payload.token, payload.password)
    return MessageResponse(message="Password updated.")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: UserUpdate, user: CurrentUser, db: DbSession
) -> UserOut:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)
