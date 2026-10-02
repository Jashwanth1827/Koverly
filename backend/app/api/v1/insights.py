"""Reminder, calendar, dashboard, search, intelligence, assistant, audit,
emergency, and subscription endpoints."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentUser,
    DbSession,
    FamilyContext,
    FamilyCtx,
    require_role,
)
from app.core.config import settings
from app.models.enums import FamilyRole, SubscriptionPlan
from app.schemas.claim import (
    AuditLogOut,
    CalendarEvent,
    DashboardOut,
    EmergencyProfile,
    EmergencyShareCreate,
    EmergencyShareOut,
    IntelligenceResponse,
    ReminderCreate,
    ReminderOut,
    ReminderUpdate,
    SearchResponse,
    SubscriptionOut,
    SubscriptionUpdate,
)
from app.schemas.common import Message, Page
from app.schemas.claim import CoverageMap
from app.schemas.document import AskRequest, AskResponse
from app.services import (
    assistant_service,
    intelligence_service,
    misc_service,
    reminder_service,
)

router = APIRouter(tags=["insights"])

WriterCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.MEMBER))]
AdminCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.ADMIN))]


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@router.get("/families/{family_id}/dashboard", response_model=DashboardOut)
async def get_dashboard(ctx: FamilyCtx, db: DbSession) -> DashboardOut:
    return await misc_service.dashboard(db, ctx.family)


# --------------------------------------------------------------------------- #
# Reminders
# --------------------------------------------------------------------------- #
@router.post(
    "/families/{family_id}/reminders",
    response_model=ReminderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_reminder(
    payload: ReminderCreate, ctx: WriterCtx, db: DbSession
) -> ReminderOut:
    payload.family_id = ctx.family_id
    reminder = await reminder_service.create_reminder(db, payload, ctx.user)
    return ReminderOut.model_validate(reminder)


@router.get("/families/{family_id}/reminders", response_model=Page[ReminderOut])
async def list_reminders(
    ctx: FamilyCtx,
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[ReminderOut]:
    items, total = await reminder_service.list_reminders(
        db,
        ctx.family_id,
        status=status_filter,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page[ReminderOut](
        items=[ReminderOut.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/families/{family_id}/reminders/{reminder_id}", response_model=ReminderOut
)
async def update_reminder(
    reminder_id: str, payload: ReminderUpdate, ctx: WriterCtx, db: DbSession
) -> ReminderOut:
    reminder = await reminder_service.update_reminder(
        db, ctx.family_id, reminder_id, payload, ctx.user
    )
    return ReminderOut.model_validate(reminder)


@router.post(
    "/families/{family_id}/reminders/{reminder_id}/acknowledge",
    response_model=ReminderOut,
)
async def acknowledge_reminder(
    reminder_id: str, ctx: WriterCtx, db: DbSession
) -> ReminderOut:
    reminder = await reminder_service.acknowledge(
        db, ctx.family_id, reminder_id, ctx.user
    )
    return ReminderOut.model_validate(reminder)


@router.post(
    "/families/{family_id}/reminders/{reminder_id}/complete",
    response_model=ReminderOut,
)
async def complete_reminder(
    reminder_id: str, ctx: WriterCtx, db: DbSession
) -> ReminderOut:
    reminder = await reminder_service.complete(
        db, ctx.family_id, reminder_id, ctx.user
    )
    return ReminderOut.model_validate(reminder)


@router.delete("/families/{family_id}/reminders/{reminder_id}", response_model=Message)
async def delete_reminder(
    reminder_id: str, ctx: WriterCtx, db: DbSession
) -> Message:
    await reminder_service.delete_reminder(
        db, ctx.family_id, reminder_id, ctx.user
    )
    return Message(message="Reminder deleted.")


# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #
@router.get("/families/{family_id}/calendar", response_model=list[CalendarEvent])
async def get_calendar(
    ctx: FamilyCtx,
    db: DbSession,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
) -> list[CalendarEvent]:
    return await misc_service.calendar_events(
        db, ctx.family_id, start=start, end=end
    )


# --------------------------------------------------------------------------- #
# Insurance intelligence & coverage map
# --------------------------------------------------------------------------- #
@router.get(
    "/families/{family_id}/insurance-intelligence",
    response_model=IntelligenceResponse,
)
async def get_intelligence(ctx: FamilyCtx, db: DbSession) -> IntelligenceResponse:
    return await intelligence_service.generate(db, ctx.family_id)


@router.get("/families/{family_id}/coverage-map", response_model=CoverageMap)
async def get_coverage_map(ctx: FamilyCtx, db: DbSession) -> CoverageMap:
    return await intelligence_service.coverage_map(db, ctx.family_id)


# --------------------------------------------------------------------------- #
# Assistant
# --------------------------------------------------------------------------- #
@router.post("/assistant/ask", response_model=AskResponse)
async def ask(
    payload: AskRequest,
    user: CurrentUser,
    db: DbSession,
) -> AskResponse:
    # Resolve and authorize the family from the request body. load_family_context
    # raises 404 for families the caller does not belong to.
    from app.api.deps import load_family_context

    ctx = await load_family_context(db, user, payload.family_id)
    result = await assistant_service.answer(
        db,
        family_id=ctx.family_id,
        question=payload.question,
        policy_id=payload.policy_id,
        top_k=payload.top_k,
    )
    return AskResponse(**result.as_dict())


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
@router.get("/families/{family_id}/search", response_model=SearchResponse)
async def search(
    ctx: FamilyCtx,
    db: DbSession,
    q: str = Query(min_length=1, max_length=200),
) -> SearchResponse:
    results = await misc_service.search(db, ctx.family_id, q)
    return SearchResponse(query=q, results=results)


# --------------------------------------------------------------------------- #
# Audit logs
# --------------------------------------------------------------------------- #
@router.get("/families/{family_id}/audit-logs", response_model=Page[AuditLogOut])
async def list_audit_logs(
    ctx: AdminCtx,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[AuditLogOut]:
    from sqlalchemy import func, select

    from app.models.claim import AuditLog

    stmt = (
        select(AuditLog)
        .where(AuditLog.family_id == ctx.family_id)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    total = int(
        (
            await db.execute(
                select(func.count(AuditLog.id)).where(
                    AuditLog.family_id == ctx.family_id
                )
            )
        ).scalar_one()
    )
    items = list((await db.execute(stmt)).scalars().all())
    return Page[AuditLogOut](
        items=[AuditLogOut.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# --------------------------------------------------------------------------- #
# Emergency mode
# --------------------------------------------------------------------------- #
@router.get(
    "/families/{family_id}/emergency", response_model=EmergencyProfile
)
async def get_emergency_profile(
    ctx: FamilyCtx,
    db: DbSession,
    member_id: str | None = Query(default=None),
) -> EmergencyProfile:
    return await misc_service.emergency_profile(db, ctx.family, member_id)


@router.post(
    "/families/{family_id}/emergency/shares",
    response_model=EmergencyShareOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_emergency_share(
    payload: EmergencyShareCreate, ctx: WriterCtx, db: DbSession
) -> EmergencyShareOut:
    share = await misc_service.create_emergency_share(
        db,
        ctx.family,
        ctx.user,
        member_id=payload.member_id,
        ttl_minutes=payload.ttl_minutes,
        max_views=payload.max_views,
    )
    return EmergencyShareOut(
        id=share.id,
        token=share.token,
        url=f"/emergency/share/{share.token}",
        expires_at=share.expires_at,
        max_views=share.max_views,
        view_count=share.view_count,
    )


@router.delete(
    "/families/{family_id}/emergency/shares/{share_id}", response_model=Message
)
async def revoke_emergency_share(
    share_id: str, ctx: AdminCtx, db: DbSession
) -> Message:
    await misc_service.revoke_emergency_share(db, ctx.family, share_id, ctx.user)
    return Message(message="Share link revoked.")


# Public resolver (no auth) — returns only the curated emergency summary.
public_router = APIRouter(tags=["emergency"])


@public_router.get("/emergency/share/{token}", response_model=EmergencyProfile)
async def resolve_emergency_share(token: str, db: DbSession) -> EmergencyProfile:
    return await misc_service.resolve_emergency_share(db, token)


# --------------------------------------------------------------------------- #
# Subscription (billing abstraction — no real payments)
# --------------------------------------------------------------------------- #
@router.get(
    "/families/{family_id}/subscription", response_model=SubscriptionOut
)
async def get_subscription(ctx: FamilyCtx, db: DbSession) -> SubscriptionOut:
    subscription = await misc_service.get_or_create_subscription(db, ctx.family_id)
    return SubscriptionOut.model_validate(subscription)


@router.patch(
    "/families/{family_id}/subscription", response_model=SubscriptionOut
)
async def update_subscription(
    payload: SubscriptionUpdate, ctx: AdminCtx, db: DbSession
) -> SubscriptionOut:
    plan: SubscriptionPlan = payload.plan
    subscription = await misc_service.set_subscription_plan(
        db, ctx.family_id, plan, ctx.user
    )
    return SubscriptionOut.model_validate(subscription)


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
meta_router = APIRouter(tags=["meta"])


@meta_router.get("/config")
async def get_public_config() -> dict:
    """Non-sensitive configuration the frontend needs at runtime."""
    return {
        "app_name": settings.APP_NAME,
        "ai_provider": settings.AI_PROVIDER,
        "notification_backend": settings.NOTIFICATION_BACKEND,
        "storage_backend": settings.STORAGE_BACKEND,
        "max_upload_mb": settings.MAX_UPLOAD_BYTES // (1024 * 1024),
        "allowed_upload_types": settings.allowed_upload_types,
    }
