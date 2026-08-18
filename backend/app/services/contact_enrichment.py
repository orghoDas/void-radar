from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.identity.normalize import normalize_company_display_name, normalize_domain
from app.schemas.contact_enrichment import (
    ContactEvidenceRecord,
    PublicPageContactExtractionRequest,
)

CONTACT_ENRICHMENT_SOURCE = "contact_enrichment"

DEFAULT_CONFIDENCE_BY_SOURCE_TYPE = {
    "company_website": 0.75,
    "founder_personal_website": 0.9,
    "public_profile": 0.8,
    "trusted_source_payload": 0.8,
    "verified_provider": 0.95,
    "manual_review": 0.9,
}

DEFAULT_VERIFICATION_BY_SOURCE_TYPE = {
    "company_website": "public_source",
    "founder_personal_website": "public_source",
    "public_profile": "public_source",
    "trusted_source_payload": "public_source",
    "verified_provider": "provider_verified",
    "manual_review": "manual_verified",
}

EMAIL_CANDIDATE_RE = re.compile(
    r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RejectedContactEvidence:
    index: int
    reason: str


@dataclass(frozen=True)
class ContactEnrichmentSummary:
    source: str
    received: int
    accepted: int
    contacts_created: int
    contacts_updated: int
    evidence_created: int
    duplicates: int
    rejected_records: list[RejectedContactEvidence] = field(default_factory=list)

    @property
    def rejected(self) -> int:
        return len(self.rejected_records)


def ingest_contact_evidence(
    db: Session,
    records: list[ContactEvidenceRecord],
) -> ContactEnrichmentSummary:
    contacts_created = 0
    contacts_updated = 0
    evidence_created = 0
    duplicates = 0
    rejected_records: list[RejectedContactEvidence] = []

    for index, record in enumerate(records):
        company_id = resolve_company_id(db, record.company_id, record.company_domain)
        if not company_id:
            rejected_records.append(
                RejectedContactEvidence(index=index, reason="company_not_found")
            )
            continue

        founder_id = resolve_founder_id(
            db,
            company_id=company_id,
            founder_id=record.founder_id,
            founder_name=record.founder_name or record.full_name,
            role=record.role,
        )
        full_name = normalize_company_display_name(
            record.full_name or record.founder_name
        )
        confidence = confidence_for_record(record)
        verification_status = verification_status_for_record(record)

        existing_contact_id = find_contact_id(
            db,
            company_id=company_id,
            founder_id=founder_id,
            email=record.email,
            full_name=full_name,
        )
        if existing_contact_id:
            update_contact(
                db,
                contact_id=existing_contact_id,
                full_name=full_name,
                role=record.role,
                contact_source=record.source_type,
                source_url=str(record.source_url),
                source_type=record.source_type,
                provider_name=record.provider_name,
                verification_status=verification_status,
                confidence=confidence,
                evidence=record.raw_evidence,
            )
            contacts_updated += 1
            contact_id = existing_contact_id
        else:
            contact_id = create_contact(
                db,
                company_id=company_id,
                founder_id=founder_id,
                full_name=full_name,
                role=record.role,
                email=record.email,
                contact_source=record.source_type,
                source_url=str(record.source_url),
                source_type=record.source_type,
                provider_name=record.provider_name,
                verification_status=verification_status,
                confidence=confidence,
                evidence=record.raw_evidence,
            )
            contacts_created += 1

        if ensure_contact_evidence(
            db,
            company_id=company_id,
            founder_id=founder_id,
            contact_id=contact_id,
            full_name=full_name,
            role=record.role,
            email=record.email,
            source_type=record.source_type,
            source_url=str(record.source_url),
            provider_name=record.provider_name,
            verification_status=verification_status,
            confidence=confidence,
            raw_evidence=record.raw_evidence,
        ):
            evidence_created += 1
        else:
            duplicates += 1

    db.commit()

    return ContactEnrichmentSummary(
        source=CONTACT_ENRICHMENT_SOURCE,
        received=len(records),
        accepted=len(records) - len(rejected_records),
        contacts_created=contacts_created,
        contacts_updated=contacts_updated,
        evidence_created=evidence_created,
        duplicates=duplicates,
        rejected_records=rejected_records,
    )


def extract_and_ingest_public_page_contacts(
    db: Session,
    request: PublicPageContactExtractionRequest,
) -> ContactEnrichmentSummary:
    emails = extract_emails_from_text(request.content)
    records = [
        ContactEvidenceRecord(
            company_id=request.company_id,
            company_domain=request.company_domain,
            founder_id=request.founder_id,
            founder_name=request.founder_name,
            full_name=request.full_name,
            role=request.role,
            email=email,
            source_type=request.source_type,
            source_url=request.source_url,
            confidence=request.confidence,
            raw_evidence={"extraction": "email_regex", "source_url": str(request.source_url)},
        )
        for email in emails
    ]

    if not records:
        return ContactEnrichmentSummary(
            source=CONTACT_ENRICHMENT_SOURCE,
            received=0,
            accepted=0,
            contacts_created=0,
            contacts_updated=0,
            evidence_created=0,
            duplicates=0,
        )

    return ingest_contact_evidence(db, records)


def backfill_contacts_from_founder_profiles(db: Session) -> ContactEnrichmentSummary:
    rows = db.execute(
        text(
            """
            select
                fp.founder_id,
                fp.company_id,
                fp.source,
                fp.source_url,
                fp.profile_url,
                fp.linkedin_url,
                fp.x_url,
                fp.email,
                fp.confidence,
                f.full_name,
                cf.role
            from founder_profiles fp
            join founders f on f.id = fp.founder_id
            left join company_founders cf
                on cf.founder_id = fp.founder_id
               and cf.company_id = fp.company_id
            where fp.email is not null
              and fp.email <> ''
              and fp.company_id is not null
            order by fp.created_at, fp.id
            """
        )
    ).all()

    records = [
        ContactEvidenceRecord(
            company_id=str(row.company_id),
            founder_id=str(row.founder_id),
            full_name=row.full_name,
            role=row.role,
            email=row.email,
            source_type="trusted_source_payload",
            source_url=row.source_url or row.profile_url,
            confidence=float(row.confidence or 0.8),
            raw_evidence={
                "founder_profile_source": row.source,
                "profile_url": row.profile_url,
                "linkedin_url": row.linkedin_url,
                "x_url": row.x_url,
            },
        )
        for row in rows
        if row.source_url or row.profile_url
    ]

    return ingest_contact_evidence(db, records)


def extract_emails_from_text(value: str) -> list[str]:
    emails = {
        match.group(1).strip().lower().rstrip(".,;:)")
        for match in EMAIL_CANDIDATE_RE.finditer(value)
    }
    return sorted(email for email in emails if is_valid_email_candidate(email))


def is_valid_email_candidate(email: str) -> bool:
    if ".." in email:
        return False
    local_part, _, domain = email.partition("@")
    if not local_part or not domain or "." not in domain:
        return False
    blocked_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
    return not email.endswith(blocked_extensions)


def resolve_company_id(
    db: Session,
    company_id: str | None,
    company_domain: str | None,
) -> str | None:
    if company_id:
        existing = db.execute(
            text("select id from companies where id = :company_id"),
            {"company_id": company_id},
        ).scalar_one_or_none()
        if existing:
            return str(existing)

    domain = normalize_domain(company_domain)
    if not domain:
        return None

    existing = db.execute(
        text("select id from companies where canonical_domain = :domain"),
        {"domain": domain},
    ).scalar_one_or_none()
    return str(existing) if existing else None


def resolve_founder_id(
    db: Session,
    company_id: str,
    founder_id: str | None,
    founder_name: str | None,
    role: str | None,
) -> str | None:
    if founder_id:
        existing = db.execute(
            text(
                """
                select id
                from founders
                where id = :founder_id
                """
            ),
            {"founder_id": founder_id},
        ).scalar_one_or_none()
        if existing:
            ensure_company_founder_link(
                db,
                company_id=company_id,
                founder_id=str(existing),
                role=role,
            )
            return str(existing)

    full_name = normalize_company_display_name(founder_name)
    if not full_name:
        return None

    existing = db.execute(
        text(
            """
            select f.id
            from founders f
            join company_founders cf on cf.founder_id = f.id
            where cf.company_id = :company_id
              and lower(f.full_name) = lower(:full_name)
            limit 1
            """
        ),
        {"company_id": company_id, "full_name": full_name},
    ).scalar_one_or_none()
    if existing:
        return str(existing)

    founder_id = db.execute(
        text(
            """
            select id
            from founders
            where lower(full_name) = lower(:full_name)
            limit 1
            """
        ),
        {"full_name": full_name},
    ).scalar_one_or_none()

    if not founder_id:
        founder_id = create_founder(db, full_name)

    ensure_company_founder_link(
        db,
        company_id=company_id,
        founder_id=str(founder_id),
        role=role,
    )
    return str(founder_id)


def create_founder(db: Session, full_name: str) -> str:
    founder_id = str(uuid4())
    now = datetime.now(UTC)
    db.execute(
        text(
            """
            insert into founders (
                id,
                full_name,
                created_at,
                updated_at
            )
            values (
                :id,
                :full_name,
                :created_at,
                :updated_at
            )
            """
        ),
        {
            "id": founder_id,
            "full_name": full_name,
            "created_at": now,
            "updated_at": now,
        },
    )
    return founder_id


def ensure_company_founder_link(
    db: Session,
    company_id: str,
    founder_id: str,
    role: str | None,
) -> None:
    existing = db.execute(
        text(
            """
            select 1
            from company_founders
            where company_id = :company_id
              and founder_id = :founder_id
            """
        ),
        {"company_id": company_id, "founder_id": founder_id},
    ).scalar_one_or_none()
    if existing:
        if role:
            db.execute(
                text(
                    """
                    update company_founders
                    set role = coalesce(role, :role)
                    where company_id = :company_id
                      and founder_id = :founder_id
                    """
                ),
                {"company_id": company_id, "founder_id": founder_id, "role": role},
            )
        return

    db.execute(
        text(
            """
            insert into company_founders (
                company_id,
                founder_id,
                role,
                confidence,
                created_at
            )
            values (
                :company_id,
                :founder_id,
                :role,
                :confidence,
                :created_at
            )
            """
        ),
        {
            "company_id": company_id,
            "founder_id": founder_id,
            "role": role,
            "confidence": 0.9,
            "created_at": datetime.now(UTC),
        },
    )


def find_contact_id(
    db: Session,
    company_id: str,
    founder_id: str | None,
    email: str,
    full_name: str | None,
) -> str | None:
    if founder_id:
        row = db.execute(
            text(
                """
                select id
                from contacts
                where company_id = :company_id
                  and founder_id = :founder_id
                  and lower(email) = :email
                limit 1
                """
            ),
            {
                "company_id": company_id,
                "founder_id": founder_id,
                "email": email.lower(),
            },
        ).scalar_one_or_none()
        return str(row) if row else None

    row = db.execute(
        text(
            """
            select id
            from contacts
            where company_id = :company_id
              and founder_id is null
              and lower(email) = :email
              and coalesce(lower(full_name), '') = :full_name
            limit 1
            """
        ),
        {
            "company_id": company_id,
            "email": email.lower(),
            "full_name": (full_name or "").lower(),
        },
    ).scalar_one_or_none()
    return str(row) if row else None


def create_contact(
    db: Session,
    company_id: str,
    founder_id: str | None,
    full_name: str | None,
    role: str | None,
    email: str,
    contact_source: str,
    source_url: str,
    source_type: str,
    provider_name: str | None,
    verification_status: str,
    confidence: float,
    evidence: dict[str, Any],
) -> str:
    contact_id = str(uuid4())
    now = datetime.now(UTC)
    db.execute(
        text(contact_insert_sql(db)),
        {
            "id": contact_id,
            "company_id": company_id,
            "founder_id": founder_id,
            "full_name": full_name,
            "role": role,
            "email": email,
            "contact_source": contact_source,
            "source_url": source_url,
            "source_type": source_type,
            "provider_name": provider_name,
            "verification_status": verification_status,
            "confidence": confidence,
            "evidence": json.dumps(evidence, sort_keys=True),
            "last_checked_at": now,
            "created_at": now,
            "updated_at": now,
        },
    )
    return contact_id


def update_contact(
    db: Session,
    contact_id: str,
    full_name: str | None,
    role: str | None,
    contact_source: str,
    source_url: str,
    source_type: str,
    provider_name: str | None,
    verification_status: str,
    confidence: float,
    evidence: dict[str, Any],
) -> None:
    db.execute(
        text(contact_update_sql(db)),
        {
            "id": contact_id,
            "full_name": full_name,
            "role": role,
            "contact_source": contact_source,
            "source_url": source_url,
            "source_type": source_type,
            "provider_name": provider_name,
            "verification_status": verification_status,
            "confidence": confidence,
            "evidence": json.dumps(evidence, sort_keys=True),
            "last_checked_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        },
    )


def ensure_contact_evidence(
    db: Session,
    company_id: str,
    founder_id: str | None,
    contact_id: str,
    full_name: str | None,
    role: str | None,
    email: str,
    source_type: str,
    source_url: str,
    provider_name: str | None,
    verification_status: str,
    confidence: float,
    raw_evidence: dict[str, Any],
) -> bool:
    if evidence_exists(
        db,
        company_id=company_id,
        founder_id=founder_id,
        email=email,
        source_type=source_type,
        source_url=source_url,
    ):
        return False

    now = datetime.now(UTC)
    db.execute(
        text(evidence_insert_sql(db)),
        {
            "id": str(uuid4()),
            "company_id": company_id,
            "founder_id": founder_id,
            "contact_id": contact_id,
            "full_name": full_name,
            "role": role,
            "email": email,
            "source_type": source_type,
            "source_url": source_url,
            "provider_name": provider_name,
            "verification_status": verification_status,
            "confidence": confidence,
            "raw_evidence": json.dumps(raw_evidence, sort_keys=True),
            "created_at": now,
        },
    )
    return True


def evidence_exists(
    db: Session,
    company_id: str,
    founder_id: str | None,
    email: str,
    source_type: str,
    source_url: str,
) -> bool:
    founder_filter = "founder_id = :founder_id" if founder_id else "founder_id is null"
    existing = db.execute(
        text(
            f"""
            select 1
            from contact_enrichment_evidence
            where company_id = :company_id
              and {founder_filter}
              and lower(email) = :email
              and source_type = :source_type
              and source_url = :source_url
            limit 1
            """
        ),
        {
            "company_id": company_id,
            "founder_id": founder_id,
            "email": email.lower(),
            "source_type": source_type,
            "source_url": source_url,
        },
    ).scalar_one_or_none()
    return bool(existing)


def confidence_for_record(record: ContactEvidenceRecord) -> float:
    if record.confidence is not None:
        return record.confidence
    return DEFAULT_CONFIDENCE_BY_SOURCE_TYPE[record.source_type]


def verification_status_for_record(record: ContactEvidenceRecord) -> str:
    if record.verification_status:
        return record.verification_status
    return DEFAULT_VERIFICATION_BY_SOURCE_TYPE[record.source_type]


def contact_insert_sql(db: Session) -> str:
    evidence_value = ":evidence"
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        evidence_value = "cast(:evidence as jsonb)"

    return f"""
        insert into contacts (
            id,
            company_id,
            founder_id,
            full_name,
            role,
            email,
            contact_source,
            source_url,
            source_type,
            provider_name,
            verification_status,
            confidence,
            evidence,
            last_checked_at,
            created_at,
            updated_at
        )
        values (
            :id,
            :company_id,
            :founder_id,
            :full_name,
            :role,
            :email,
            :contact_source,
            :source_url,
            :source_type,
            :provider_name,
            :verification_status,
            :confidence,
            {evidence_value},
            :last_checked_at,
            :created_at,
            :updated_at
        )
    """


def contact_update_sql(db: Session) -> str:
    evidence_value = ":evidence"
    confidence_value = "max(confidence, :confidence)"
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        evidence_value = "cast(:evidence as jsonb)"
        confidence_value = "greatest(confidence, :confidence)"

    return f"""
        update contacts
        set
            full_name = coalesce(full_name, :full_name),
            role = coalesce(role, :role),
            contact_source = :contact_source,
            source_url = :source_url,
            source_type = :source_type,
            provider_name = :provider_name,
            verification_status = :verification_status,
            confidence = {confidence_value},
            evidence = {evidence_value},
            last_checked_at = :last_checked_at,
            updated_at = :updated_at
        where id = :id
    """


def evidence_insert_sql(db: Session) -> str:
    raw_evidence_value = ":raw_evidence"
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        raw_evidence_value = "cast(:raw_evidence as jsonb)"

    return f"""
        insert into contact_enrichment_evidence (
            id,
            company_id,
            founder_id,
            contact_id,
            full_name,
            role,
            email,
            source_type,
            source_url,
            provider_name,
            verification_status,
            confidence,
            raw_evidence,
            created_at
        )
        values (
            :id,
            :company_id,
            :founder_id,
            :contact_id,
            :full_name,
            :role,
            :email,
            :source_type,
            :source_url,
            :provider_name,
            :verification_status,
            :confidence,
            {raw_evidence_value},
            :created_at
        )
    """
