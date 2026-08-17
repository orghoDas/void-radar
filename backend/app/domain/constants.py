from enum import StrEnum


class ServiceType(StrEnum):
    MVP = "MVP"
    WEB_APP = "WEB_APP"
    MOBILE_APP = "MOBILE_APP"
    DEDICATED_TEAM = "DEDICATED_TEAM"
    AI_INTEGRATION = "AI_INTEGRATION"
    BACKEND = "BACKEND"
    API = "API"
    ERP = "ERP"
    INTERNAL_PORTAL = "INTERNAL_PORTAL"
    CUSTOMER_PORTAL = "CUSTOMER_PORTAL"
    MARKETPLACE = "MARKETPLACE"
    AUTOMATION = "AUTOMATION"
    PRODUCT_REDESIGN = "PRODUCT_REDESIGN"
    WEBSITE = "WEBSITE"


class ProspectType(StrEnum):
    DIRECT_INTENT = "DIRECT_INTENT"
    TRIGGER = "TRIGGER"
    OPPORTUNITY = "OPPORTUNITY"
    ENGAGEMENT = "ENGAGEMENT"


class EvidenceKind(StrEnum):
    FACT = "FACT"
    OBSERVATION = "OBSERVATION"
    INFERENCE = "INFERENCE"
    RECOMMENDATION = "RECOMMENDATION"


SCORING_MODEL_VERSION = "prospect_score_v0.1"

SCORING_WEIGHTS: dict[str, float] = {
    "company_fit": 0.25,
    "opportunity_strength": 0.25,
    "timing": 0.20,
    "technical_capacity_gap": 0.15,
    "commercial_potential": 0.10,
    "source_confidence": 0.05,
}

