from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.signal_enrichment import (
    AtsBoardDetectionBatch,
    AtsBoardMissBatch,
    JobPostingBatch,
    SignalEnrichmentResult,
)
from app.services.signal_enrichment import (
    ingest_ats_board_detections,
    ingest_ats_board_misses,
    ingest_job_postings,
)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/ats-boards",
    response_model=SignalEnrichmentResult,
    status_code=status.HTTP_201_CREATED,
)
def ingest_ats_board_detection_batch(
    batch: AtsBoardDetectionBatch,
    db: DatabaseSession,
) -> SignalEnrichmentResult:
    summary = ingest_ats_board_detections(db, batch.records)
    return signal_enrichment_result_from_summary(summary)


@router.post(
    "/ats-board-misses",
    response_model=SignalEnrichmentResult,
    status_code=status.HTTP_201_CREATED,
)
def ingest_ats_board_miss_batch(
    batch: AtsBoardMissBatch,
    db: DatabaseSession,
) -> SignalEnrichmentResult:
    summary = ingest_ats_board_misses(db, batch.records)
    return signal_enrichment_result_from_summary(summary)


@router.post(
    "/job-postings",
    response_model=SignalEnrichmentResult,
    status_code=status.HTTP_201_CREATED,
)
def ingest_job_posting_batch(
    batch: JobPostingBatch,
    db: DatabaseSession,
) -> SignalEnrichmentResult:
    summary = ingest_job_postings(
        db,
        batch.records,
        mark_missing_inactive=batch.mark_missing_inactive,
        missing_observation_threshold=batch.missing_observation_threshold,
        snapshot_observed_at=batch.snapshot_observed_at,
    )
    return signal_enrichment_result_from_summary(summary)


def signal_enrichment_result_from_summary(summary) -> SignalEnrichmentResult:
    return SignalEnrichmentResult(
        source=summary.source,
        received=summary.received,
        accepted=summary.accepted,
        created=summary.created,
        updated=summary.updated,
        duplicates=summary.duplicates,
        signals_created=summary.signals_created,
        inactive_marked=summary.inactive_marked,
        rejected=summary.rejected,
        rejected_records=[
            {"index": item.index, "reason": item.reason}
            for item in summary.rejected_records
        ],
    )
