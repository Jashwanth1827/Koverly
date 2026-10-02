"""Domain enumerations shared across models and schemas."""

from __future__ import annotations

from enum import Enum


class FamilyRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


# Ordered capability levels — higher implies more privileges.
ROLE_RANK: dict[FamilyRole, int] = {
    FamilyRole.VIEWER: 1,
    FamilyRole.MEMBER: 2,
    FamilyRole.ADMIN: 3,
    FamilyRole.OWNER: 4,
}


class PolicyType(str, Enum):
    LIFE = "life"
    HEALTH = "health"
    MOTOR = "motor"
    HOME = "home"
    TRAVEL = "travel"
    PERSONAL_ACCIDENT = "personal_accident"
    OTHER = "other"


class PolicyStatus(str, Enum):
    ACTIVE = "active"
    LAPSED = "lapsed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PENDING = "pending"


class PremiumFrequency(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    HALF_YEARLY = "half_yearly"
    YEARLY = "yearly"
    SINGLE = "single"


class Relationship(str, Enum):
    SELF = "self"
    SPOUSE = "spouse"
    FATHER = "father"
    MOTHER = "mother"
    SON = "son"
    DAUGHTER = "daughter"
    BROTHER = "brother"
    SISTER = "sister"
    OTHER = "other"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class DocumentType(str, Enum):
    POLICY = "policy"
    CLAIM = "claim"
    OTHER = "other"


class ExtractionStatus(str, Enum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ClaimStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    DOCUMENTS_REQUIRED = "documents_required"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SETTLED = "settled"
    CLOSED = "closed"


class ReminderType(str, Enum):
    RENEWAL = "renewal"
    PREMIUM_PAYMENT = "premium_payment"
    POLICY_EXPIRY = "policy_expiry"
    DOCUMENT_EXPIRY = "document_expiry"
    CLAIM_FOLLOW_UP = "claim_follow_up"


class ReminderStatus(str, Enum):
    SCHEDULED = "scheduled"
    TRIGGERED = "triggered"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"


class SubscriptionPlan(str, Enum):
    FREE = "free"
    PRO = "pro"
    FAMILY_PRO = "family_pro"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


class AuditAction(str, Enum):
    POLICY_CREATED = "policy_created"
    POLICY_UPDATED = "policy_updated"
    POLICY_DELETED = "policy_deleted"
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_DELETED = "document_deleted"
    CLAIM_CREATED = "claim_created"
    CLAIM_UPDATED = "claim_updated"
    FAMILY_MEMBER_ADDED = "family_member_added"
    FAMILY_MEMBER_REMOVED = "family_member_removed"
    USER_INVITED = "user_invited"
    USER_ROLE_CHANGED = "user_role_changed"
    EMERGENCY_SHARE_CREATED = "emergency_share_created"
    EMERGENCY_SHARE_REVOKED = "emergency_share_revoked"
    FAMILY_CREATED = "family_created"
    FAMILY_DELETED = "family_deleted"
