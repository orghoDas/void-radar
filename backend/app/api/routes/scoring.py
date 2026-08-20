from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.scoring import (
    CompanyScoreResult,
    ScoreBatchRequest,
    ScoreBatchResult,
    ScoreCompanyRequest,
)
from app.services.fit_intent_scoring import (
    score_companies,
    score_company,
)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/companies/{company_id}",
    response_model=CompanyScoreResult,
    status_code=status.HTTP_201_CREATED,
)
def score_single_company(
    company_id: str,
    request: ScoreCompanyRequest,
    db: DatabaseSession,
) -> CompanyScoreResult:
    return score_company(
        db,
        company_id=company_id,
        score_version=request.score_version,
    )


@router.post(
    "/companies",
    response_model=ScoreBatchResult,
    status_code=status.HTTP_201_CREATED,
)
def score_company_batch(
    request: ScoreBatchRequest,
    db: DatabaseSession,
) -> ScoreBatchResult:
    results = score_companies(
        db,
        company_ids=request.company_ids,
        limit=request.limit,
        score_version=request.score_version,
    )
    return ScoreBatchResult(scored=len(results), results=results)
