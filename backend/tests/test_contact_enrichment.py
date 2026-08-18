from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.schemas.contact_enrichment import (
    ContactEvidenceRecord,
    PublicPageContactExtractionRequest,
)
from app.services.contact_enrichment import (
    extract_and_ingest_public_page_contacts,
    ingest_contact_evidence,
)


def make_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                create table companies (
                    id text primary key,
                    canonical_name text not null,
                    canonical_domain text,
                    created_at timestamp not null,
                    updated_at timestamp not null,
                    unique (canonical_domain)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                create table founders (
                    id text primary key,
                    full_name text not null,
                    location text,
                    bio text,
                    created_at timestamp not null,
                    updated_at timestamp not null
                )
                """
            )
        )
        connection.execute(
            text(
                """
                create table company_founders (
                    company_id text not null,
                    founder_id text not null,
                    role text,
                    source_id text,
                    confidence numeric not null default 0,
                    created_at timestamp not null,
                    primary key (company_id, founder_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                create table contacts (
                    id text primary key,
                    company_id text not null,
                    founder_id text,
                    full_name text,
                    role text,
                    email text,
                    contact_source text,
                    source_url text,
                    source_type text,
                    provider_name text,
                    verification_status text not null default 'unverified',
                    confidence numeric not null default 0,
                    evidence text not null default '{}',
                    last_checked_at timestamp,
                    created_at timestamp not null,
                    updated_at timestamp not null
                )
                """
            )
        )
        connection.execute(
            text(
                """
                create table contact_enrichment_evidence (
                    id text primary key,
                    company_id text not null,
                    founder_id text,
                    contact_id text,
                    full_name text,
                    role text,
                    email text not null,
                    source_type text not null,
                    source_url text not null,
                    provider_name text,
                    verification_status text not null default 'unverified',
                    confidence numeric not null default 0,
                    raw_evidence text not null default '{}',
                    created_at timestamp not null
                )
                """
            )
        )
        connection.execute(
            text(
                """
                insert into companies (
                    id,
                    canonical_name,
                    canonical_domain,
                    created_at,
                    updated_at
                )
                values (
                    'company-1',
                    'Example AI',
                    'example.ai',
                    current_timestamp,
                    current_timestamp
                )
                """
            )
        )

    return session_factory()


def test_ingests_public_founder_email_with_evidence() -> None:
    db = make_session()

    summary = ingest_contact_evidence(
        db,
        [
            ContactEvidenceRecord(
                company_domain="https://example.ai",
                founder_name="Jane Founder",
                role="CEO",
                email="Jane@Example.ai",
                source_type="founder_personal_website",
                source_url="https://jane.example.ai/contact",
            )
        ],
    )

    assert summary.accepted == 1
    assert summary.contacts_created == 1
    assert summary.evidence_created == 1

    contact = db.execute(
        text(
            """
            select full_name, email, source_url, verification_status, confidence
            from contacts
            """
        )
    ).one()
    assert contact.full_name == "Jane Founder"
    assert contact.email == "jane@example.ai"
    assert contact.source_url == "https://jane.example.ai/contact"
    assert contact.verification_status == "public_source"
    assert float(contact.confidence) == 0.9

    founder_link_count = db.execute(
        text("select count(*) from company_founders")
    ).scalar_one()
    assert founder_link_count == 1


def test_rejects_contact_evidence_without_resolved_company() -> None:
    db = make_session()

    summary = ingest_contact_evidence(
        db,
        [
            ContactEvidenceRecord(
                company_domain="missing.example",
                founder_name="Jane Founder",
                email="jane@example.ai",
                source_type="manual_review",
                source_url="https://docs.example/manual-review",
            )
        ],
    )

    assert summary.accepted == 0
    assert summary.rejected == 1
    assert summary.rejected_records[0].reason == "company_not_found"

    contact_count = db.execute(text("select count(*) from contacts")).scalar_one()
    assert contact_count == 0


def test_duplicate_evidence_updates_contact_without_duplicate_evidence() -> None:
    db = make_session()
    record = ContactEvidenceRecord(
        company_domain="example.ai",
        founder_name="Jane Founder",
        email="jane@example.ai",
        source_type="manual_review",
        source_url="https://docs.example/manual-review",
    )

    first = ingest_contact_evidence(db, [record])
    second = ingest_contact_evidence(db, [record])

    assert first.contacts_created == 1
    assert first.evidence_created == 1
    assert second.contacts_created == 0
    assert second.contacts_updated == 1
    assert second.evidence_created == 0
    assert second.duplicates == 1

    evidence_count = db.execute(
        text("select count(*) from contact_enrichment_evidence")
    ).scalar_one()
    assert evidence_count == 1


def test_extracts_emails_from_public_page_content() -> None:
    db = make_session()
    request = PublicPageContactExtractionRequest(
        company_domain="example.ai",
        founder_name="Jane Founder",
        source_type="company_website",
        source_url="https://example.ai/contact",
        content="<html>Email jane@example.ai or hello@example.ai.</html>",
    )

    summary = extract_and_ingest_public_page_contacts(db, request)

    assert summary.accepted == 2
    assert summary.contacts_created == 2

    emails = db.execute(text("select email from contacts order by email")).all()
    assert [row.email for row in emails] == ["hello@example.ai", "jane@example.ai"]
