"""Insurance taxonomy.

The taxonomy exists to *organize* extracted information — never to make the
user classify anything. The user uploads a document; Koverly infers the
document class and insurance category/type/subtype from the document text and
maps them onto the existing ``PolicyType`` values used across the app.

Two layers:

* ``InsuranceCategory`` — the broad family (life, health, motor, ...). Broad
  enough to hold anything, including ``OTHER`` for the unexpected.
* ``PolicyType`` (from ``app.models.enums``) — the persisted policy type. The
  category maps onto it so dashboards, emergency mode, and coverage maps keep
  working without change.

Category-specific fields are *dynamic*: nothing is mandatory. A field that is
not present in the document is simply absent, never invented.
"""

from __future__ import annotations

from enum import Enum

from app.models.enums import PolicyType


class DocumentClass(str, Enum):
    """What a document actually is, before any policy interpretation."""

    INSURANCE_POLICY = "insurance_policy"
    POLICY_SCHEDULE = "policy_schedule"
    POLICY_CERTIFICATE = "policy_certificate"
    RENEWAL_DOCUMENT = "renewal_document"
    PREMIUM_RECEIPT = "premium_receipt"
    CLAIM_DOCUMENT = "claim_document"
    ENDORSEMENT = "endorsement"
    POLICY_WORDING = "policy_wording"
    PROPOSAL_DOCUMENT = "proposal_document"
    OTHER_INSURANCE_DOCUMENT = "other_insurance_document"
    NON_INSURANCE_DOCUMENT = "non_insurance_document"
    UNKNOWN = "unknown"


# Document classes that describe a policy and are therefore worth turning into
# a policy candidate. Wordings/receipts/claims are stored but not segmented
# into policy records.
POLICY_BEARING_CLASSES = {
    DocumentClass.INSURANCE_POLICY.value,
    DocumentClass.POLICY_SCHEDULE.value,
    DocumentClass.POLICY_CERTIFICATE.value,
    DocumentClass.RENEWAL_DOCUMENT.value,
    DocumentClass.PROPOSAL_DOCUMENT.value,
    DocumentClass.ENDORSEMENT.value,
    DocumentClass.OTHER_INSURANCE_DOCUMENT.value,
}

NON_INSURANCE_CLASSES = {
    DocumentClass.NON_INSURANCE_DOCUMENT.value,
    DocumentClass.UNKNOWN.value,
}


class InsuranceCategory(str, Enum):
    LIFE = "life"
    HEALTH = "health"
    MOTOR = "motor"
    PROPERTY = "property"
    TRAVEL = "travel"
    PERSONAL_ACCIDENT = "personal_accident"
    BUSINESS = "business"
    AGRICULTURE = "agriculture"
    MARINE = "marine"
    CYBER = "cyber"
    SPECIALTY = "specialty"
    OTHER = "other"


# Category -> persisted PolicyType. New categories that have no dedicated
# PolicyType collapse to ``other`` while their real category and all extracted
# detail are preserved, so information is never thrown away for lack of a slot.
CATEGORY_TO_POLICY_TYPE: dict[str, str] = {
    InsuranceCategory.LIFE.value: PolicyType.LIFE.value,
    InsuranceCategory.HEALTH.value: PolicyType.HEALTH.value,
    InsuranceCategory.MOTOR.value: PolicyType.MOTOR.value,
    InsuranceCategory.PROPERTY.value: PolicyType.HOME.value,
    InsuranceCategory.TRAVEL.value: PolicyType.TRAVEL.value,
    InsuranceCategory.PERSONAL_ACCIDENT.value: PolicyType.PERSONAL_ACCIDENT.value,
    InsuranceCategory.BUSINESS.value: PolicyType.OTHER.value,
    InsuranceCategory.AGRICULTURE.value: PolicyType.OTHER.value,
    InsuranceCategory.MARINE.value: PolicyType.OTHER.value,
    InsuranceCategory.CYBER.value: PolicyType.OTHER.value,
    InsuranceCategory.SPECIALTY.value: PolicyType.OTHER.value,
    InsuranceCategory.OTHER.value: PolicyType.OTHER.value,
}


def category_for_policy_type(policy_type: str) -> str:
    """Inverse mapping, used to seed a category from a stored policy type."""
    for category, mapped in CATEGORY_TO_POLICY_TYPE.items():
        if mapped == policy_type:
            return category
    return InsuranceCategory.OTHER.value


# Policy "type" (i.e. subtype) vocabulary per category. Free-form strings are
# allowed too — this list guides extraction, it does not constrain it.
POLICY_TYPES_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    InsuranceCategory.HEALTH.value: (
        "individual", "family_floater", "group_employer", "critical_illness",
        "top_up", "senior_citizen", "maternity", "hospital_cash",
        "personal_accident_rider", "other",
    ),
    InsuranceCategory.LIFE.value: (
        "term", "endowment", "ulip", "whole_life", "money_back", "annuity",
        "group_life", "pension", "other",
    ),
    InsuranceCategory.MOTOR.value: ("car", "two_wheeler", "commercial_vehicle", "other"),
    InsuranceCategory.PROPERTY.value: (
        "home", "household_contents", "fire", "shop", "office", "other",
    ),
    InsuranceCategory.TRAVEL.value: ("domestic", "international", "student", "other"),
    InsuranceCategory.PERSONAL_ACCIDENT.value: (
        "individual", "group", "disability", "other",
    ),
    InsuranceCategory.BUSINESS.value: (
        "liability", "fire", "burglary", "business_interruption", "other",
    ),
    InsuranceCategory.AGRICULTURE.value: ("crop", "livestock", "weather", "other"),
    InsuranceCategory.MARINE.value: ("cargo", "hull", "freight", "other"),
    InsuranceCategory.CYBER.value: ("individual", "business", "other"),
    InsuranceCategory.SPECIALTY.value: ("other",),
    InsuranceCategory.OTHER.value: ("other",),
}

# Motor subtype vocabulary (coverage level).
MOTOR_COVERAGE_SUBTYPES = ("comprehensive", "third_party", "own_damage", "other")


# Dynamic, category-specific fields. These are *optional* extras: they are
# extracted only when the document actually contains them, and are stored
# alongside the universal fields. Adding a category or a field here requires no
# schema change.
CATEGORY_FIELD_PROFILES: dict[str, tuple[str, ...]] = {
    InsuranceCategory.HEALTH.value: (
        "room_rent_limit", "co_payment", "deductible", "waiting_period",
        "pre_existing_conditions", "network_hospitals", "maternity",
        "restoration", "no_claim_bonus", "tpa", "claim_contact",
    ),
    InsuranceCategory.LIFE.value: (
        "life_assured", "nominee", "death_benefit", "maturity_benefit",
        "policy_term", "maturity_date", "riders",
    ),
    InsuranceCategory.MOTOR.value: (
        "vehicle_registration_number", "vehicle_make", "vehicle_model",
        "vehicle_variant", "vehicle_year", "idv", "no_claim_bonus", "addons",
        "third_party_cover", "own_damage_cover",
    ),
    InsuranceCategory.TRAVEL.value: (
        "destination", "trip_start", "trip_end", "medical_cover",
        "baggage_cover", "trip_cancellation", "emergency_evacuation",
    ),
    InsuranceCategory.PROPERTY.value: (
        "property_address", "property_type", "building_cover", "contents_cover",
    ),
    InsuranceCategory.PERSONAL_ACCIDENT.value: (
        "accidental_death_cover", "disability_cover", "hospitalisation_cover",
    ),
}


def fields_for_category(category: str) -> tuple[str, ...]:
    return CATEGORY_FIELD_PROFILES.get(category, ())


def valid_policy_type(category: str, policy_type: str | None) -> str:
    """Coerce a proposed policy type to the vocabulary, defaulting to other."""
    if not policy_type:
        return "other"
    allowed = POLICY_TYPES_BY_CATEGORY.get(category, ())
    return policy_type if policy_type in allowed else "other"
