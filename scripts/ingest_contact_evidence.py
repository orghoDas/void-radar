#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.session import get_session_factory
from app.schemas.contact_enrichment import ContactEvidenceRecord
from app.services.contact_enrichment import ingest_contact_evidence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest permitted founder/company contact evidence."
    )
    parser.add_argument(
        "evidence_file",
        type=Path,
        help="JSON list or object with a records array.",
    )
    args = parser.parse_args()

    records = load_records(args.evidence_file)

    session_factory = get_session_factory()
    with session_factory() as db:
        summary = ingest_contact_evidence(db, records)

    print(
        json.dumps(
            {
                "source": summary.source,
                "received": summary.received,
                "accepted": summary.accepted,
                "contacts_created": summary.contacts_created,
                "contacts_updated": summary.contacts_updated,
                "evidence_created": summary.evidence_created,
                "duplicates": summary.duplicates,
                "rejected": summary.rejected,
                "rejected_records": [
                    {"index": item.index, "reason": item.reason}
                    for item in summary.rejected_records
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )


def load_records(path: Path) -> list[ContactEvidenceRecord]:
    payload = json.loads(path.read_text())
    items = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise TypeError("Evidence file must be a JSON list or an object with records.")
    return [ContactEvidenceRecord.model_validate(item) for item in items]


if __name__ == "__main__":
    main()
