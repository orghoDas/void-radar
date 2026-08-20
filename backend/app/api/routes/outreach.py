from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.outreach import (
    OutcomeImportRequest,
    OutcomeImportResult,
    OutreachExportRequest,
    OutreachExportResult,
)
from app.services.outreach_export import (
    export_send_ready_prospects,
    export_send_ready_prospects_csv,
    import_outcomes,
)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/export",
    response_model=OutreachExportResult,
    status_code=status.HTTP_200_OK,
)
def export_outreach_rows(
    request: OutreachExportRequest,
    db: DatabaseSession,
) -> OutreachExportResult:
    rows = export_send_ready_prospects(db, request)
    return OutreachExportResult(exported=len(rows), rows=rows)


@router.post("/export.csv", status_code=status.HTTP_200_OK)
def export_outreach_csv(
    request: OutreachExportRequest,
    db: DatabaseSession,
) -> Response:
    csv_body = export_send_ready_prospects_csv(db, request)
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="void-radar-outreach.csv"'},
    )


@router.post(
    "/outcomes",
    response_model=OutcomeImportResult,
    status_code=status.HTTP_201_CREATED,
)
def import_outreach_outcomes(
    request: OutcomeImportRequest,
    db: DatabaseSession,
) -> OutcomeImportResult:
    return import_outcomes(db, request.records)
