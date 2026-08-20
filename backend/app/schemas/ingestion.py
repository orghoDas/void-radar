from datetime import date
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class SourceFounderRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    role: str | None = None
    profile_url: HttpUrl | None = None
    linkedin_url: HttpUrl | None = None
    x_url: HttpUrl | None = None
    bio: str | None = None
    email: str | None = None


class YCFounderRecord(SourceFounderRecord):
    model_config = ConfigDict(extra="allow")


class YCCompanyRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str = Field(default="y_combinator")
    source_url: HttpUrl
    source_company_id: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    website: HttpUrl | None = None
    location: str | None = None
    industry: str | None = None
    batch: str | None = None
    stage: str | None = None
    status: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    founders: list[YCFounderRecord] = Field(default_factory=list)

    @field_validator("source")
    @classmethod
    def source_must_be_y_combinator(cls, value: str) -> str:
        if value != "y_combinator":
            raise ValueError("source must be y_combinator")
        return value


class EntrepreneurFirstCompanyRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str = Field(default="entrepreneur_first")
    source_url: HttpUrl
    source_company_id: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    website: HttpUrl | None = None
    location: str | None = None
    industry: str | None = None
    batch: str | None = None
    stage: str | None = None
    status: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    founders: list[SourceFounderRecord] = Field(default_factory=list)

    @field_validator("source")
    @classmethod
    def source_must_be_entrepreneur_first(cls, value: str) -> str:
        if value != "entrepreneur_first":
            raise ValueError("source must be entrepreneur_first")
        return value


class YCSourceRecordBatch(BaseModel):
    records: list[YCCompanyRecord] = Field(min_length=1, max_length=500)


class EntrepreneurFirstSourceRecordBatch(BaseModel):
    records: list[EntrepreneurFirstCompanyRecord] = Field(min_length=1, max_length=500)


class DiscoverySourceRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str = Field(min_length=1)
    source_url: HttpUrl
    source_record_id: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    website: HttpUrl | None = None
    domain: str | None = None
    location: str | None = None
    industry: str | None = None
    stage: str | None = None
    status: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    event_type: str | None = None
    event_date: date | None = None
    event_summary: str | None = None
    raw_source_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def has_domain_or_website(self):
        if not self.website and not self.domain:
            raise ValueError("website or domain is required")
        return self

    @field_validator("source", "source_record_id", "company_name", "domain")
    @classmethod
    def normalize_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DiscoverySourceRecordBatch(BaseModel):
    source: str = Field(min_length=1)
    source_name: str | None = None
    source_type: str = Field(default="discovery_source")
    base_url: HttpUrl | None = None
    terms_url: HttpUrl | None = None
    records: list[DiscoverySourceRecord] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def records_match_batch_source(self):
        mismatched = [
            record.source
            for record in self.records
            if record.source != self.source
        ]
        if mismatched:
            raise ValueError("all records must match batch source")
        return self


class SourceRecordIngestionResult(BaseModel):
    source: str
    received: int
    inserted: int
    updated: int
    duplicates: int


class DiscoveryIngestionRejectedRecord(BaseModel):
    index: int
    reason: str


class DiscoveryIngestionResult(BaseModel):
    source: str
    received: int
    accepted: int
    source_records_inserted: int
    source_records_updated: int
    duplicates: int
    companies_created: int
    companies_matched: int
    signals_created: int
    rejected: int
    rejected_records: list[DiscoveryIngestionRejectedRecord] = Field(default_factory=list)
