from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreCompanyRequest(BaseModel):
    score_version: str | None = None


class ScoreBatchRequest(BaseModel):
    company_ids: list[str] | None = Field(default=None, max_length=500)
    limit: int = Field(default=50, ge=1, le=500)
    score_version: str | None = None


class CompanyScoreResult(BaseModel):
    company_id: str
    score_id: str
    score_version: str
    fit_score: int
    intent_score: int
    total_score: int
    positive_reasons: list[str]
    penalties: list[str]
    trigger_evidence: list[dict]
    disqualified: bool


class ScoreBatchResult(BaseModel):
    scored: int
    results: list[CompanyScoreResult]
