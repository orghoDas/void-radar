from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.identity.normalize import (
    normalize_company_display_name,
    normalize_domain,
    normalize_location,
)
from app.services.source_ingestion import YC_SOURCE_KEY


@dataclass(frozen=True)
class IdentityResolutionSummary:
    source: str
    scanned: int
    companies_created: int
    companies_matched: int
    aliases_created: int
    review_items_created: int
    skipped_already_linked: int


def process_yc_source_records(
    db: Session,
    limit: int | None = None,
) -> IdentityResolutionSummary:
    rows = load_yc_source_records(db, limit=limit)

    companies_created = 0
    companies_matched = 0
    aliases_created = 0
    review_items_created = 0
    skipped_already_linked = 0

    for row in rows:
        source_record_id = str(row.id)
        if row.company_id:
            skipped_already_linked += 1
            mark_source_record_processed(
                db,
                source_record_id=source_record_id,
                status="linked",
                notes="Source record was already linked to a company.",
            )
            continue

        payload = parse_payload(row.raw_payload)
        company_name = normalize_company_display_name(payload.get("company_name"))
        domain = normalize_domain(payload.get("website"))

        if not company_name:
            review_items_created += create_review_item(
                db,
                source_record_id=source_record_id,
                reason="missing_company_name",
                normalized_name=None,
                normalized_domain=domain,
            )
            mark_source_record_processed(
                db,
                source_record_id=source_record_id,
                status="review_required",
                notes="Missing company name.",
            )
            continue

        if not domain:
            review_items_created += create_review_item(
                db,
                source_record_id=source_record_id,
                reason="missing_domain",
                normalized_name=company_name,
                normalized_domain=None,
            )
            mark_source_record_processed(
                db,
                source_record_id=source_record_id,
                status="review_required",
                notes="Missing official domain.",
            )
            continue

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

        aliases_created += ensure_company_alias(
            db,
            company_id=company_id,
            alias=company_name,
            alias_type="name",
            confidence=1,
        )

        aliases_created += ensure_source_aliases(db, company_id=company_id, payload=payload)
        link_source_record_to_company(db, source_record_id=source_record_id, company_id=company_id)
        mark_source_record_processed(
            db,
            source_record_id=source_record_id,
            status="linked",
            notes=f"Linked by canonical domain {domain}.",
        )

    db.commit()

    return IdentityResolutionSummary(
        source=YC_SOURCE_KEY,
        scanned=len(rows),
        companies_created=companies_created,
        companies_matched=companies_matched,
        aliases_created=aliases_created,
        review_items_created=review_items_created,
        skipped_already_linked=skipped_already_linked,
    )


def load_yc_source_records(db: Session, limit: int | None) -> list[Any]:
    limit_clause = "limit :limit" if limit else ""
    params = {"source_key": YC_SOURCE_KEY}
    if limit:
        params["limit"] = limit

    return list(
        db.execute(
            text(
                f"""
                select sr.id, sr.company_id, sr.raw_payload
                from source_records sr
                join sources s on s.id = sr.source_id
                where s.source_key = :source_key
                order by sr.created_at, sr.id
                {limit_clause}
                """
            ),
            params,
        )
    )


def parse_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload

    if isinstance(payload, str):
        return json.loads(payload)

    return dict(payload)


def find_company_by_domain(db: Session, domain: str) -> str | None:
    company_id = db.execute(
        text("select id from companies where canonical_domain = :domain"),
        {"domain": domain},
    ).scalar_one_or_none()

    return str(company_id) if company_id else None


def create_company_from_source(
    db: Session,
    payload: dict[str, Any],
    company_name: str,
    domain: str,
) -> str:
    company_id = str(uuid4())
    now = datetime.now(UTC)
    location = normalize_location(payload.get("location"))

    db.execute(
        text(
            """
            insert into companies (
                id,
                canonical_name,
                canonical_domain,
                description,
                industry,
                country,
                city,
                company_stage,
                employee_estimate,
                status,
                created_at,
                updated_at
            )
            values (
                :id,
                :canonical_name,
                :canonical_domain,
                :description,
                :industry,
                :country,
                :city,
                :company_stage,
                :employee_estimate,
                :status,
                :created_at,
                :updated_at
            )
            """
        ),
        {
            "id": company_id,
            "canonical_name": company_name,
            "canonical_domain": domain,
            "description": payload.get("description"),
            "industry": payload.get("industry"),
            "country": location.country,
            "city": location.city,
            "company_stage": payload.get("stage") or payload.get("batch"),
            "employee_estimate": payload.get("employee_count"),
            "status": "candidate",
            "created_at": now,
            "updated_at": now,
        },
    )

    return company_id


def update_company_from_source(
    db: Session,
    company_id: str,
    payload: dict[str, Any],
) -> None:
    location = normalize_location(payload.get("location"))

    db.execute(
        text(
            """
            update companies
            set
                description = coalesce(description, :description),
                industry = coalesce(industry, :industry),
                country = coalesce(country, :country),
                city = coalesce(city, :city),
                company_stage = coalesce(company_stage, :company_stage),
                employee_estimate = coalesce(employee_estimate, :employee_estimate),
                updated_at = :updated_at
            where id = :company_id
            """
        ),
        {
            "company_id": company_id,
            "description": payload.get("description"),
            "industry": payload.get("industry"),
            "country": location.country,
            "city": location.city,
            "company_stage": payload.get("stage") or payload.get("batch"),
            "employee_estimate": payload.get("employee_count"),
            "updated_at": datetime.now(UTC),
        },
    )


def ensure_source_aliases(
    db: Session,
    company_id: str,
    payload: dict[str, Any],
) -> int:
    aliases_created = 0
    raw_payload = payload.get("raw_source_payload") or {}
    former_names = raw_payload.get("former_names") or []

    for alias in former_names:
        aliases_created += ensure_company_alias(
            db,
            company_id=company_id,
            alias=alias,
            alias_type="former_name",
            confidence=0.95,
        )

    return aliases_created


def ensure_company_alias(
    db: Session,
    company_id: str,
    alias: str | None,
    alias_type: str,
    confidence: float,
) -> int:
    normalized_alias = normalize_company_display_name(alias)
    if not normalized_alias:
        return 0

    existing = db.execute(
        text(
            """
            select 1
            from company_aliases
            where company_id = :company_id
              and alias = :alias
              and alias_type = :alias_type
            limit 1
            """
        ),
        {
            "company_id": company_id,
            "alias": normalized_alias,
            "alias_type": alias_type,
        },
    ).scalar_one_or_none()

    if existing:
        return 0

    db.execute(
        text(
            """
            insert into company_aliases (
                id,
                company_id,
                alias,
                alias_type,
                source,
                confidence,
                created_at
            )
            values (
                :id,
                :company_id,
                :alias,
                :alias_type,
                :source,
                :confidence,
                :created_at
            )
            """
        ),
        {
            "id": str(uuid4()),
            "company_id": company_id,
            "alias": normalized_alias,
            "alias_type": alias_type,
            "source": YC_SOURCE_KEY,
            "confidence": confidence,
            "created_at": datetime.now(UTC),
        },
    )

    return 1


def link_source_record_to_company(
    db: Session,
    source_record_id: str,
    company_id: str,
) -> None:
    db.execute(
        text(
            """
            update source_records
            set company_id = :company_id
            where id = :source_record_id
            """
        ),
        {
            "source_record_id": source_record_id,
            "company_id": company_id,
        },
    )


def mark_source_record_processed(
    db: Session,
    source_record_id: str,
    status: str,
    notes: str,
) -> None:
    db.execute(
        text(
            """
            update source_records
            set
                processing_status = :status,
                processed_at = :processed_at,
                processing_notes = :notes
            where id = :source_record_id
            """
        ),
        {
            "source_record_id": source_record_id,
            "status": status,
            "processed_at": datetime.now(UTC),
            "notes": notes,
        },
    )


def create_review_item(
    db: Session,
    source_record_id: str,
    reason: str,
    normalized_name: str | None,
    normalized_domain: str | None,
) -> int:
    existing = db.execute(
        text(
            """
            select 1
            from identity_resolution_reviews
            where source_record_id = :source_record_id
            limit 1
            """
        ),
        {"source_record_id": source_record_id},
    ).scalar_one_or_none()

    if existing:
        return 0

    now = datetime.now(UTC)
    db.execute(
        text(review_insert_sql(db)),
        {
            "id": str(uuid4()),
            "source_record_id": source_record_id,
            "source": YC_SOURCE_KEY,
            "reason": reason,
            "normalized_name": normalized_name,
            "normalized_domain": normalized_domain,
            "candidate_matches": json.dumps([]),
            "confidence": 0,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        },
    )

    return 1


def review_insert_sql(db: Session) -> str:
    candidate_matches_value = ":candidate_matches"
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        candidate_matches_value = "cast(:candidate_matches as jsonb)"

    return f"""
        insert into identity_resolution_reviews (
            id,
            source_record_id,
            source,
            reason,
            normalized_name,
            normalized_domain,
            candidate_matches,
            confidence,
            status,
            created_at,
            updated_at
        )
        values (
            :id,
            :source_record_id,
            :source,
            :reason,
            :normalized_name,
            :normalized_domain,
            {candidate_matches_value},
            :confidence,
            :status,
            :created_at,
            :updated_at
        )
    """

