"""Import approved contact candidates from the Apify contact-candidate actor."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from app.db.session import get_engine
from app.schemas.contact_enrichment import ContactEvidenceRecord
from app.services.contact_enrichment import ingest_contact_evidence
from sqlalchemy.orm import Session

APPROVED_STATUSES = {"approved", "approve", "yes", "y", "true", "1"}
DEFAULT_PROVIDER_NAME = "apify-contact-candidate-enricher"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates_path", type=Path)
    parser.add_argument("--provider-name", default=DEFAULT_PROVIDER_NAME)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--import-all",
        action="store_true",
        help="Import every contact_candidate row without requiring review_status=approved.",
    )
    args = parser.parse_args()

    rows = load_rows(args.candidates_path)
    records = [
        contact_record_from_row(row, provider_name=args.provider_name)
        for row in rows
        if should_import_row(row, import_all=args.import_all)
    ]

    if not records:
        print("records_loaded: 0")
        print("hint: set review_status=approved on candidate rows before importing")
        return 1

    totals = {
        "received": 0,
        "accepted": 0,
        "contacts_created": 0,
        "contacts_updated": 0,
        "evidence_created": 0,
        "duplicates": 0,
        "rejected": 0,
    }
    with Session(get_engine()) as db:
        for batch in chunked(records, args.batch_size):
            summary = ingest_contact_evidence(db, batch)
            totals["received"] += summary.received
            totals["accepted"] += summary.accepted
            totals["contacts_created"] += summary.contacts_created
            totals["contacts_updated"] += summary.contacts_updated
            totals["evidence_created"] += summary.evidence_created
            totals["duplicates"] += summary.duplicates
            totals["rejected"] += summary.rejected

    for key, value in totals.items():
        print(f"{key}: {value}")
    return 0 if totals["accepted"] else 1


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise TypeError("JSON candidate file must be a list or object with items.")
        return [dict(row) for row in rows]

    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def should_import_row(row: dict[str, Any], *, import_all: bool) -> bool:
    if clean(row.get("record_type")) not in {"", "contact_candidate"}:
        return False
    if not clean(row.get("email")) or not clean(row.get("source_url")):
        return False
    if import_all:
        return True
    return clean(row.get("review_status")).lower() in APPROVED_STATUSES


def contact_record_from_row(
    row: dict[str, Any],
    *,
    provider_name: str,
) -> ContactEvidenceRecord:
    return ContactEvidenceRecord(
        company_id=clean(row.get("company_id")),
        company_domain=clean(row.get("company_domain") or row.get("domain")),
        full_name=clean(row.get("full_name")),
        role=clean(row.get("role")),
        email=clean(row.get("email")) or "",
        source_type="manual_review",
        source_url=clean(row.get("source_url")) or "",
        provider_name=clean(row.get("provider_name")) or provider_name,
        verification_status="manual_verified",
        confidence=float(clean(row.get("confidence")) or 0.9),
        raw_evidence={
            "collector": provider_name,
            "review_status": clean(row.get("review_status")),
            "reason_to_write": clean(row.get("reason_to_write")),
            "evidence_urls": clean(row.get("evidence_urls")),
            "score": clean(row.get("score")),
            "source_excerpt": clean(row.get("source_excerpt")),
            "extraction": clean(row.get("extraction")),
        },
    )


def chunked(records: list[ContactEvidenceRecord], size: int) -> list[list[ContactEvidenceRecord]]:
    return [records[index : index + size] for index in range(0, len(records), size)]


def clean(value: Any) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
