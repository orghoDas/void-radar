from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.identity.normalize import normalize_company_display_name, normalize_domain
from app.schemas.ingestion import DiscoverySourceRecord, DiscoverySourceRecordBatch
from app.services.identity_resolution import (
    create_company_from_source,
    ensure_company_alias,
    ensure_source_identity,
    find_company_by_domain,
    update_company_from_source,
)
from app.services.source_ingestion import (
    SourceMetadata,
    content_hash,
    ensure_source,
    find_source_record_hash,
    source_record_insert_sql,
    update_source_record,
)


@dataclass(frozen=True)
class RejectedDiscoveryRecord:
    index: int
    reason: str


@dataclass(frozen=True)
class DiscoveryIngestionSummary:
    source: str
    received: int
    accepted: int
    source_records_inserted: int
    source_records_updated: int
    duplicates: int
    companies_created: int
    companies_matched: int
    signals_created: int
    rejected_records: list[RejectedDiscoveryRecord] = field(default_factory=list)

    @property
    def rejected(self) -> int:
        return len(self.rejected_records)


def ingest_discovery_source_records(
    db: Session,
    batch: DiscoverySourceRecordBatch,
) -> DiscoveryIngestionSummary:
    source_metadata = SourceMetadata(
        source_key=batch.source,
        name=batch.source_name or title_from_source_key(batch.source),
        source_type=batch.source_type,
        base_url=str(batch.base_url) if batch.base_url else source_base_url(batch.records),
        terms_url=str(batch.terms_url) if batch.terms_url else None,
    )
    source_id = ensure_source(db, source_metadata)

    source_records_inserted = 0
    source_records_updated = 0
    duplicates = 0
    companies_created = 0
    companies_matched = 0
    signals_created = 0
    rejected_records: list[RejectedDiscoveryRecord] = []

    for index, record in enumerate(batch.records):
        payload = record.model_dump(mode="json")
        domain = normalize_domain(record.domain or str(record.website or ""))
        company_name = normalize_company_display_name(record.company_name)
        if not domain:
            rejected_records.append(
                RejectedDiscoveryRecord(index=index, reason="missing_domain")
            )
            continue
        if not company_name:
            rejected_records.append(
                RejectedDiscoveryRecord(index=index, reason="missing_company_name")
            )
            continue

        source_record_result = upsert_source_record(db, source_id, record, payload)
        if source_record_result == "inserted":
            source_records_inserted += 1
        elif source_record_result == "updated":
            source_records_updated += 1
        else:
            duplicates += 1

        company_id = find_company_by_domain(db, domain)
        if company_id:
            companies_matched += 1
            update_company_from_source(db, company_id=company_id, payload=payload)
        else:
            company_id = create_company_from_source(
                db,
                payload=payload,
                company_name=company_name,
                domain=domain,
            )
            companies_created += 1

        ensure_company_alias(
            db,
            company_id=company_id,
            alias=company_name,
            alias_type="name",
            confidence=1,
            source_key=batch.source,
        )
        ensure_source_identity(
            db,
            company_id=company_id,
            source_id=source_id,
            external_id=record.source_record_id,
            source_url=str(record.source_url),
        )
        link_latest_source_record_to_company(
            db,
            source_id=source_id,
            source_record_id=record.source_record_id,
            company_id=company_id,
        )

        if create_discovery_signal(db, company_id=company_id, record=record):
            signals_created += 1

    db.commit()
    return DiscoveryIngestionSummary(
        source=batch.source,
        received=len(batch.records),
        accepted=len(batch.records) - len(rejected_records),
        source_records_inserted=source_records_inserted,
        source_records_updated=source_records_updated,
        duplicates=duplicates,
        companies_created=companies_created,
        companies_matched=companies_matched,
        signals_created=signals_created,
        rejected_records=rejected_records,
    )


def upsert_source_record(
    db: Session,
    source_id: str,
    record: DiscoverySourceRecord,
    payload: dict,
) -> str:
    payload_hash = content_hash(payload)
    existing_hash = find_source_record_hash(db, source_id, record.source_record_id)
    if existing_hash is not None:
        if existing_hash != payload_hash:
            update_source_record(
                db,
                source_id=source_id,
                source_record_id=record.source_record_id,
                raw_payload=json.dumps(payload, sort_keys=True),
                source_url=str(record.source_url),
                content_hash=payload_hash,
            )
            return "updated"
        return "duplicate"

    now = datetime.now(UTC)
    db.execute(
        text(source_record_insert_sql(db)),
        {
            "id": str(uuid4()),
            "source_id": source_id,
            "source_record_id": record.source_record_id,
            "raw_payload": json.dumps(payload, sort_keys=True),
            "source_url": str(record.source_url),
            "collected_at": now,
            "content_hash": payload_hash,
            "created_at": now,
        },
    )
    return "inserted"


def link_latest_source_record_to_company(
    db: Session,
    source_id: str,
    source_record_id: str,
    company_id: str,
) -> None:
    db.execute(
        text(
            """
            update source_records
            set
                company_id = :company_id,
                processing_status = 'linked',
                processed_at = :processed_at,
                processing_notes = 'Linked during generic discovery ingestion.'
            where source_id = :source_id
              and source_record_id = :source_record_id
            """
        ),
        {
            "company_id": company_id,
            "processed_at": datetime.now(UTC),
            "source_id": source_id,
            "source_record_id": source_record_id,
        },
    )


def create_discovery_signal(
    db: Session,
    company_id: str,
    record: DiscoverySourceRecord,
) -> bool:
    signal_type = signal_type_for_record(record)
    if not signal_type:
        return False

    description = (
        record.event_summary
        or record.description
        or f"{record.company_name} discovered from {record.source}."
    )
    now = datetime.now(UTC)
    detected_at = datetime.combine(record.event_date, datetime.min.time(), UTC)
    if not record.event_date:
        detected_at = now
    source_url = str(record.source_url)

    if discovery_signal_exists(
        db,
        company_id=company_id,
        signal_type=signal_type,
        source=record.source,
        source_url=source_url,
    ):
        return False

    db.execute(
        text(json_insert_sql(db, signal_insert_sql(), "raw_evidence")),
        {
            "id": str(uuid4()),
            "company_id": company_id,
            "signal_type": signal_type,
            "description": description,
            "source": record.source,
            "source_url": source_url,
            "detected_at": detected_at,
            "confidence": signal_confidence(signal_type),
            "raw_evidence": json.dumps(record.model_dump(mode="json"), sort_keys=True),
            "created_at": now,
        },
    )
    return True


def discovery_signal_exists(
    db: Session,
    *,
    company_id: str,
    signal_type: str,
    source: str,
    source_url: str,
) -> bool:
    existing = db.execute(
        text(
            """
            select 1
            from signals
            where company_id = :company_id
              and signal_type = :signal_type
              and source = :source
              and source_url = :source_url
            limit 1
            """
        ),
        {
            "company_id": company_id,
            "signal_type": signal_type,
            "source": source,
            "source_url": source_url,
        },
    ).scalar_one_or_none()
    return bool(existing)


def signal_type_for_record(record: DiscoverySourceRecord) -> str | None:
    event_type = (record.event_type or "").strip().lower()
    if event_type in {"funding", "funding_news", "funding_announcement"}:
        return "FUNDING_EVENT"
    if event_type in {"launch", "product_launch"}:
        return "PRODUCT_LAUNCH"
    if event_type in {"hiring", "hiring_post", "who_is_hiring"}:
        return "HIRING_DISCOVERY"
    if event_type in {"discovery", "company_discovery"}:
        return "DISCOVERY"
    return None


def signal_confidence(signal_type: str) -> float:
    if signal_type == "FUNDING_EVENT":
        return 0.8
    if signal_type == "PRODUCT_LAUNCH":
        return 0.75
    if signal_type == "HIRING_DISCOVERY":
        return 0.85
    return 0.6


def source_base_url(records: list[DiscoverySourceRecord]) -> str:
    if not records:
        return ""
    parsed = records[0].source_url
    return f"{parsed.scheme}://{parsed.host}" if parsed.host else str(parsed)


def title_from_source_key(source_key: str) -> str:
    return source_key.replace("_", " ").replace("-", " ").title()


def json_insert_sql(db: Session, sql: str, field_name: str) -> str:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return sql
    return sql.replace(f":{field_name}", f"cast(:{field_name} as jsonb)")


def signal_insert_sql() -> str:
    return """
        insert into signals (
            id,
            company_id,
            signal_type,
            description,
            source,
            source_url,
            detected_at,
            confidence,
            raw_evidence,
            created_at
        )
        values (
            :id,
            :company_id,
            :signal_type,
            :description,
            :source,
            :source_url,
            :detected_at,
            :confidence,
            :raw_evidence,
            :created_at
        )
    """
