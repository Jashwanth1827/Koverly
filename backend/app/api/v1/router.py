"""Aggregate v1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, claims, documents, families, insights, policies

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(families.router)
api_router.include_router(policies.router)
api_router.include_router(documents.router)
api_router.include_router(claims.router)
api_router.include_router(insights.router)
api_router.include_router(insights.public_router)
api_router.include_router(insights.meta_router)
