from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


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


class SourceRecordIngestionResult(BaseModel):
    source: str
    received: int
    inserted: int
    updated: int
    duplicates: int
