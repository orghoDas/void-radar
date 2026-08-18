from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

ContactSourceType = Literal[
    "company_website",
    "founder_personal_website",
    "public_profile",
    "trusted_source_payload",
    "verified_provider",
    "manual_review",
]

VerificationStatus = Literal[
    "unverified",
    "public_source",
    "provider_verified",
    "manual_verified",
]

PublicPageSourceType = Literal[
    "company_website",
    "founder_personal_website",
    "public_profile",
]

EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


class ContactEvidenceRecord(BaseModel):
    company_id: str | None = None
    company_domain: str | None = None
    founder_id: str | None = None
    founder_name: str | None = None
    full_name: str | None = None
    role: str | None = None
    email: str
    source_type: ContactSourceType
    source_url: HttpUrl
    provider_name: str | None = None
    verification_status: VerificationStatus | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    raw_evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not EMAIL_RE.match(email):
            raise ValueError("email must be an explicit email address")
        return email

    @field_validator("company_domain")
    @classmethod
    def normalize_company_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("founder_name", "full_name", "role", "provider_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ContactEvidenceBatch(BaseModel):
    records: list[ContactEvidenceRecord] = Field(min_length=1, max_length=500)


class PublicPageContactExtractionRequest(BaseModel):
    company_id: str | None = None
    company_domain: str | None = None
    founder_id: str | None = None
    founder_name: str | None = None
    full_name: str | None = None
    role: str | None = None
    source_type: PublicPageSourceType
    source_url: HttpUrl
    content: str = Field(min_length=1, max_length=500_000)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ContactEnrichmentRejectedRecord(BaseModel):
    index: int
    reason: str


class ContactEnrichmentResult(BaseModel):
    source: str
    received: int
    accepted: int
    contacts_created: int
    contacts_updated: int
    evidence_created: int
    duplicates: int
    rejected: int
    rejected_records: list[ContactEnrichmentRejectedRecord] = Field(default_factory=list)
