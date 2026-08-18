from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.ingestion import (
    SourceRecordIngestionResult,
    YCSourceRecordBatch,
)
from app.services.source_ingestion import ingest_yc_source_records

router = APIRouter()


@router.post(
    "/y-combinator/source-records",
    response_model=SourceRecordIngestionResult,
    status_code=201,
)
def ingest_yc_source_record_batch(
    batch: YCSourceRecordBatch,
    db: Session = Depends(get_db),
) -> SourceRecordIngestionResult:
    summary = ingest_yc_source_records(db, batch.records)

    return SourceRecordIngestionResult(
        source=summary.source,
        received=summary.received,
        inserted=summary.inserted,
        updated=summary.updated,
        duplicates=summary.duplicates,
    )
