"""Model package — imports register all tables on the metadata."""

from app.models.auth_token import (
    EmailVerificationToken,
    LoginAttempt,
    PasswordResetToken,
    RefreshToken,
)
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
    ROLE_RANK,
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
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.models.family import Family, FamilyMember
from app.models.policy import Policy
from app.models.user import User

__all__ = [
    "ROLE_RANK",
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
    "EmailVerificationToken",
    "EmergencyShare",
    "ExtractionStatus",
    "Family",
    "FamilyMember",
    "FamilyRole",
    "LoginAttempt",
    "PasswordResetToken",
    "Policy",
    "PolicyCandidateField",
    "PolicyCandidateRecord",
    "PolicyExtraction",
    "PolicyStatus",
    "PolicyType",
    "PremiumFrequency",
    "RefreshToken",
    "Relationship",
    "Reminder",
    "ReminderStatus",
    "ReminderType",
    "Subscription",
    "SubscriptionPlan",
    "SubscriptionStatus",
    "User",
]
