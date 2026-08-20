from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

AtsProvider = Literal["greenhouse", "lever", "ashby", "workable", "generic"]


class AtsBoardDetectionRecord(BaseModel):
    company_id: str | None = None
    domain: str | None = None
    ats_provider: AtsProvider
    board_token: str | None = None
    board_url: HttpUrl | None = None
    careers_url: HttpUrl | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence_url: HttpUrl | None = None
    raw_evidence: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def has_company_identity_and_board_reference(self):
        if not self.company_id and not self.domain:
            raise ValueError("company_id or domain is required")
        if not self.board_token and not self.board_url and not self.careers_url:
            raise ValueError("board_token, board_url, or careers_url is required")
        return self


class AtsBoardDetectionBatch(BaseModel):
    records: list[AtsBoardDetectionRecord] = Field(min_length=1, max_length=500)


class AtsBoardMissRecord(BaseModel):
    company_id: str | None = None
    domain: str | None = None
    careers_url: HttpUrl | None = None
    evidence_url: HttpUrl | None = None
    confidence: float = Field(default=0.7, ge=0, le=1)
    raw_evidence: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def has_company_identity(self):
        if not self.company_id and not self.domain:
            raise ValueError("company_id or domain is required")
        return self


class AtsBoardMissBatch(BaseModel):
    records: list[AtsBoardMissRecord] = Field(min_length=1, max_length=500)


class JobPostingRecord(BaseModel):
    company_id: str | None = None
    domain: str | None = None
    ats_provider: AtsProvider
    board_token: str | None = None
    board_url: HttpUrl | None = None
    external_job_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    department: str | None = None
    location: str | None = None
    remote_policy: str | None = None
    employment_type: str | None = None
    posted_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    url: HttpUrl
    description_text: str | None = None
    stack_terms: list[str] = Field(default_factory=list)
    seniority: str | None = None
    is_active: bool = True
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def has_company_identity(self):
        if not self.company_id and not self.domain:
            raise ValueError("company_id or domain is required")
        return self


class JobPostingBatch(BaseModel):
    records: list[JobPostingRecord] = Field(min_length=1, max_length=1000)
    mark_missing_inactive: bool = False
    missing_observation_threshold: int = Field(default=2, ge=1, le=10)
    snapshot_observed_at: datetime | None = None


class SignalEnrichmentRejectedRecord(BaseModel):
    index: int
    reason: str


class SignalEnrichmentResult(BaseModel):
    source: str
    received: int
    accepted: int
    created: int
    updated: int
    duplicates: int
    signals_created: int
    inactive_marked: int = 0
    rejected: int
    rejected_records: list[SignalEnrichmentRejectedRecord] = Field(default_factory=list)
