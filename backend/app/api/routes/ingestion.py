from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.ingestion import (
    DiscoveryIngestionResult,
    DiscoverySourceRecordBatch,
    EntrepreneurFirstSourceRecordBatch,
    SourceRecordIngestionResult,
    YCSourceRecordBatch,
)
from app.services.discovery_ingestion import ingest_discovery_source_records
from app.services.source_ingestion import (
    ingest_entrepreneur_first_source_records,
    ingest_yc_source_records,
)

router = APIRouter()
DB_DEPENDENCY = Depends(get_db)


@router.post(
    "/y-combinator/source-records",
    response_model=SourceRecordIngestionResult,
    status_code=201,
)
def ingest_yc_source_record_batch(
    batch: YCSourceRecordBatch,
    db: Session = DB_DEPENDENCY,
) -> SourceRecordIngestionResult:
    summary = ingest_yc_source_records(db, batch.records)

    return SourceRecordIngestionResult(
        source=summary.source,
        received=summary.received,
        inserted=summary.inserted,
        updated=summary.updated,
        duplicates=summary.duplicates,
    )


@router.post(
    "/entrepreneur-first/source-records",
    response_model=SourceRecordIngestionResult,
    status_code=201,
)
def ingest_entrepreneur_first_source_record_batch(
    batch: EntrepreneurFirstSourceRecordBatch,
    db: Session = DB_DEPENDENCY,
) -> SourceRecordIngestionResult:
    summary = ingest_entrepreneur_first_source_records(db, batch.records)

    return SourceRecordIngestionResult(
        source=summary.source,
        received=summary.received,
        inserted=summary.inserted,
        updated=summary.updated,
        duplicates=summary.duplicates,
    )


@router.post(
    "/discovery/source-records",
    response_model=DiscoveryIngestionResult,
    status_code=201,
)
def ingest_discovery_source_record_batch(
    batch: DiscoverySourceRecordBatch,
    db: Session = DB_DEPENDENCY,
) -> DiscoveryIngestionResult:
    summary = ingest_discovery_source_records(db, batch)

    return DiscoveryIngestionResult(
        source=summary.source,
        received=summary.received,
        accepted=summary.accepted,
        source_records_inserted=summary.source_records_inserted,
        source_records_updated=summary.source_records_updated,
        duplicates=summary.duplicates,
        companies_created=summary.companies_created,
        companies_matched=summary.companies_matched,
        signals_created=summary.signals_created,
        rejected=summary.rejected,
        rejected_records=[
            {"index": item.index, "reason": item.reason}
            for item in summary.rejected_records
        ],
    )
