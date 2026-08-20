from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

VerifiedExportStatus = Literal["provider_verified", "manual_verified"]
OutcomeEvent = Literal[
    "sent",
    "opened",
    "clicked",
    "replied",
    "positive_reply",
    "negative_reply",
    "meeting_booked",
    "bounced",
    "complained",
    "unsubscribed",
]
EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


class OutreachExportRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
    min_total_score: int = Field(default=50, ge=0, le=100)
    verification_statuses: list[VerifiedExportStatus] = Field(
        default_factory=lambda: ["provider_verified", "manual_verified"]
    )


class OutreachExportRow(BaseModel):
    company_id: str
    score_id: str
    contact_id: str
    company: str
    domain: str
    contact_name: str | None
    role: str | None
    email: str
    verified_at: datetime | None
    source: str | None
    score: int
    fit_score: int
    intent_score: int
    reason_to_write: str
    evidence_urls: list[str]
    positive_reasons: list[str]
    penalties: list[str]


class OutreachExportResult(BaseModel):
    exported: int
    rows: list[OutreachExportRow]


class OutcomeRecord(BaseModel):
    company_id: str | None = None
    contact_id: str | None = None
    email: str | None = None
    event: OutcomeEvent
    source: str | None = None
    signal_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        email = value.strip().lower()
        if not EMAIL_RE.match(email):
            raise ValueError("email must be an explicit email address")
        return email


class OutcomeImportRequest(BaseModel):
    records: list[OutcomeRecord] = Field(min_length=1, max_length=1000)


class OutcomeRejectedRecord(BaseModel):
    index: int
    reason: str


class OutcomeImportResult(BaseModel):
    received: int
    accepted: int
    inserted: int
    rejected: int
    rejected_records: list[OutcomeRejectedRecord] = Field(default_factory=list)
