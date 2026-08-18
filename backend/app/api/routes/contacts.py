from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.contact_enrichment import (
    ContactEnrichmentResult,
    ContactEvidenceBatch,
    PublicPageContactExtractionRequest,
)
from app.services.contact_enrichment import (
    backfill_contacts_from_founder_profiles,
    extract_and_ingest_public_page_contacts,
    ingest_contact_evidence,
)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/enrichment/evidence",
    response_model=ContactEnrichmentResult,
    status_code=status.HTTP_201_CREATED,
)
def ingest_founder_contact_evidence(
    batch: ContactEvidenceBatch,
    db: DatabaseSession,
) -> ContactEnrichmentResult:
    summary = ingest_contact_evidence(db, batch.records)
    return enrichment_result_from_summary(summary)


@router.post(
    "/enrichment/public-page",
    response_model=ContactEnrichmentResult,
    status_code=status.HTTP_201_CREATED,
)
def extract_founder_contact_evidence_from_public_page(
    request: PublicPageContactExtractionRequest,
    db: DatabaseSession,
) -> ContactEnrichmentResult:
    summary = extract_and_ingest_public_page_contacts(db, request)
    return enrichment_result_from_summary(summary)


@router.post(
    "/enrichment/founder-profiles/backfill",
    response_model=ContactEnrichmentResult,
)
def backfill_founder_profile_contacts(
    db: DatabaseSession,
) -> ContactEnrichmentResult:
    summary = backfill_contacts_from_founder_profiles(db)
    return enrichment_result_from_summary(summary)


def enrichment_result_from_summary(summary) -> ContactEnrichmentResult:
    return ContactEnrichmentResult(
        source=summary.source,
        received=summary.received,
        accepted=summary.accepted,
        contacts_created=summary.contacts_created,
        contacts_updated=summary.contacts_updated,
        evidence_created=summary.evidence_created,
        duplicates=summary.duplicates,
        rejected=summary.rejected,
        rejected_records=[
            {"index": item.index, "reason": item.reason}
            for item in summary.rejected_records
        ],
    )
