from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.identity import IdentityResolutionResult
from app.services.identity_resolution import process_yc_source_records

router = APIRouter()


@router.post(
    "/y-combinator/process-source-records",
    response_model=IdentityResolutionResult,
)
def process_yc_records(
    limit: int | None = Query(default=None, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> IdentityResolutionResult:
    summary = process_yc_source_records(db, limit=limit)

    return IdentityResolutionResult(
        source=summary.source,
        scanned=summary.scanned,
        companies_created=summary.companies_created,
        companies_matched=summary.companies_matched,
        aliases_created=summary.aliases_created,
        source_identities_created=summary.source_identities_created,
        founders_created=summary.founders_created,
        founder_links_created=summary.founder_links_created,
        founder_profiles_created=summary.founder_profiles_created,
        review_items_created=summary.review_items_created,
        skipped_already_linked=summary.skipped_already_linked,
    )
