import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.ingestion import YCCompanyRecord

YC_SOURCE_KEY = "y_combinator"


@dataclass(frozen=True)
class IngestionSummary:
    source: str
    received: int
    inserted: int
    duplicates: int


def ingest_yc_source_records(
    db: Session,
    records: list[YCCompanyRecord],
) -> IngestionSummary:
    source_id = ensure_yc_source(db)
    inserted = 0
    duplicates = 0

    for record in records:
        if source_record_exists(db, source_id, record.source_company_id):
            duplicates += 1
            continue

        payload = record.model_dump(mode="json")
        db.execute(
            text(source_record_insert_sql(db)),
            {
                "id": str(uuid4()),
                "source_id": source_id,
                "source_record_id": record.source_company_id,
                "raw_payload": json.dumps(payload, sort_keys=True),
                "source_url": str(record.source_url),
                "collected_at": datetime.now(UTC),
                "content_hash": content_hash(payload),
                "created_at": datetime.now(UTC),
            },
        )
        inserted += 1

    db.commit()

    return IngestionSummary(
        source=YC_SOURCE_KEY,
        received=len(records),
        inserted=inserted,
        duplicates=duplicates,
    )


def ensure_yc_source(db: Session) -> str:
    existing = db.execute(
        text("select id from sources where source_key = :source_key"),
        {"source_key": YC_SOURCE_KEY},
    ).scalar_one_or_none()

    if existing:
        return str(existing)

    source_id = str(uuid4())
    now = datetime.now(UTC)
    db.execute(
        text(
            """
            insert into sources (
                id,
                source_key,
                name,
                source_type,
                base_url,
                terms_url,
                enabled,
                created_at,
                updated_at
            )
            values (
                :id,
                :source_key,
                :name,
                :source_type,
                :base_url,
                :terms_url,
                :enabled,
                :created_at,
                :updated_at
            )
            """
        ),
        {
            "id": source_id,
            "source_key": YC_SOURCE_KEY,
            "name": "Y Combinator",
            "source_type": "trusted_company_source",
            "base_url": "https://www.ycombinator.com/companies",
            "terms_url": "https://www.ycombinator.com/legal",
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        },
    )

    return source_id


def source_record_exists(
    db: Session,
    source_id: str,
    source_record_id: str,
) -> bool:
    existing = db.execute(
        text(
            """
            select 1
            from source_records
            where source_id = :source_id
              and source_record_id = :source_record_id
            limit 1
            """
        ),
        {
            "source_id": source_id,
            "source_record_id": source_record_id,
        },
    ).scalar_one_or_none()

    return existing is not None


def content_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_record_insert_sql(db: Session) -> str:
    raw_payload_value = ":raw_payload"
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        raw_payload_value = "cast(:raw_payload as jsonb)"

    return f"""
        insert into source_records (
            id,
            source_id,
            source_record_id,
            raw_payload,
            source_url,
            collected_at,
            content_hash,
            created_at
        )
        values (
            :id,
            :source_id,
            :source_record_id,
            {raw_payload_value},
            :source_url,
            :collected_at,
            :content_hash,
            :created_at
        )
    """

