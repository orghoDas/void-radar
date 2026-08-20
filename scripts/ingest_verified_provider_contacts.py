"""Import verified provider contacts into Void Radar."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.db.session import get_engine
from app.schemas.contact_enrichment import ContactEvidenceRecord
from app.services.contact_enrichment import ingest_contact_evidence
from sqlalchemy.orm import Session

DEFAULT_PROVIDER_NAME = "provider"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--provider-name", default=DEFAULT_PROVIDER_NAME)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    rows = read_rows(args.csv_path)
    records = [
        contact_record_from_row(row, provider_name=args.provider_name)
        for row in rows
        if row.get("email")
    ]
    if not records:
        print("records_loaded: 0")
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


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def contact_record_from_row(
    row: dict[str, str],
    *,
    provider_name: str,
) -> ContactEvidenceRecord:
    source_url = first_url(row.get("source_url") or row.get("evidence_urls"))
    return ContactEvidenceRecord(
        company_id=clean(row.get("company_id")),
        company_domain=clean(row.get("company_domain") or row.get("domain")),
        full_name=clean(row.get("full_name") or row.get("contact_name")),
        role=clean(row.get("role")),
        email=clean(row.get("email")) or "",
        source_type="verified_provider",
        source_url=source_url,
        provider_name=clean(row.get("provider_name")) or provider_name,
        verification_status="provider_verified",
        confidence=float(clean(row.get("confidence")) or 0.95),
        raw_evidence={
            "provider_name": clean(row.get("provider_name")) or provider_name,
            "reason_to_write": clean(row.get("reason_to_write")),
            "evidence_urls": clean(row.get("evidence_urls")),
            "score": clean(row.get("score")),
        },
    )


def first_url(value: str | None) -> str:
    for part in clean(value).replace(",", ";").split(";"):
        url = part.strip()
        if url.startswith(("http://", "https://")):
            return url
    raise ValueError("source_url or evidence_urls must include an absolute URL")


def chunked(records: list[ContactEvidenceRecord], size: int) -> list[list[ContactEvidenceRecord]]:
    return [records[index : index + size] for index in range(0, len(records), size)]


def clean(value: str | None) -> str:
    return (value or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
