"""Model package — imports register all tables on the metadata."""

from app.models.claim import (
    AuditLog,
    Claim,
    ClaimEvent,
    EmergencyShare,
    Reminder,
    Subscription,
)
from app.models.document import (
    Document,
    DocumentAnalysis,
    DocumentChunk,
    PolicyCandidateField,
    PolicyCandidateRecord,
    PolicyExtraction,
)
from app.models.enums import (
    AuditAction,
    ClaimStatus,
    DocumentStatus,
    DocumentType,
    ExtractionStatus,
    FamilyRole,
    PolicyStatus,
    PolicyType,
    PremiumFrequency,
    Relationship,
    ReminderStatus,
    ReminderType,
    ROLE_RANK,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.models.family import Family, FamilyMember
from app.models.policy import Policy
from app.models.user import User

__all__ = [
    "AuditAction",
    "AuditLog",
    "Claim",
    "ClaimEvent",
    "ClaimStatus",
    "Document",
    "DocumentAnalysis",
    "DocumentChunk",
    "DocumentStatus",
    "DocumentType",
    "EmergencyShare",
    "ExtractionStatus",
    "Family",
    "FamilyMember",
    "FamilyRole",
    "Policy",
    "PolicyCandidateField",
    "PolicyCandidateRecord",
    "PolicyExtraction",
    "PolicyStatus",
    "PolicyType",
    "PremiumFrequency",
    "Relationship",
    "Reminder",
    "ReminderStatus",
    "ReminderType",
    "ROLE_RANK",
    "Subscription",
    "SubscriptionPlan",
    "SubscriptionStatus",
    "User",
]
