from __future__ import annotations

from io import BytesIO
from typing import Self

from scripts.enrich_contacts_from_websites import (
    CompanyTarget,
    WebsiteEnrichmentSummary,
    collect_company_contact_records,
    company_urls,
    enrich_contacts_from_websites,
    fetch_public_page,
    should_keep_email,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


class FakeResponse:
    def __init__(
        self,
        *,
        body: str,
        url: str = "https://example.ai/contact",
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
    ) -> None:
        self._body = BytesIO(body.encode())
        self.url = url
        self.status = status
        self.headers = {"content-type": content_type}

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args) -> None:
        return None


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


def test_company_urls_uses_small_public_path_list() -> None:
    urls = company_urls("example.ai", ("/", "contact", "/about-us"))

    assert urls == [
        "https://example.ai/",
        "https://example.ai/contact",
        "https://example.ai/about-us",
    ]


def test_fetch_public_page_ignores_binary_content() -> None:
    def opener(_request, timeout):
        assert timeout == 3
        return FakeResponse(body="binary", content_type="image/png")

    page = fetch_public_page("https://example.ai/logo.png", timeout=3, opener=opener)

    assert page.content is None
    assert page.error == "non_textual_content_type"


def test_should_keep_email_defaults_to_person_like_same_domain_emails() -> None:
    assert should_keep_email(
        "jane@example.ai",
        company_domain="example.ai",
        include_generic=False,
        include_external_emails=False,
    )
    assert not should_keep_email(
        "sales@example.ai",
        company_domain="example.ai",
        include_generic=False,
        include_external_emails=False,
    )
    assert not should_keep_email(
        "jane@parent.example",
        company_domain="example.ai",
        include_generic=False,
        include_external_emails=False,
    )


def test_collect_company_contact_records_extracts_public_emails() -> None:
    def opener(request, timeout):
        del timeout
        if request.full_url.endswith("/contact"):
            return FakeResponse(
                body="Email jane@example.ai or support@example.ai.",
                url=request.full_url,
            )
        return FakeResponse(body="No contacts here.", url=request.full_url)

    summary = empty_summary()
    records = collect_company_contact_records(
        CompanyTarget(
            id="company-1",
            canonical_name="Example AI",
            canonical_domain="example.ai",
        ),
        paths=("/", "/contact"),
        timeout=3,
        opener=opener,
        summary=summary,
    )

    assert summary.pages_attempted == 2
    assert summary.pages_fetched == 2
    assert summary.emails_found == 2
    assert [record.email for record in records] == ["jane@example.ai"]
    assert all(record.source_type == "company_website" for record in records)


def test_enrich_contacts_from_websites_dry_run_does_not_write_contacts() -> None:
    db = make_session()

    def opener(_request, timeout):
        del timeout
        return FakeResponse(body="Reach us at jane@example.ai.")

    summary = enrich_contacts_from_websites(
        db,
        limit=1,
        dry_run=True,
        delay_seconds=0,
        paths=("/contact",),
        opener=opener,
    )

    assert summary.companies_scanned == 1
    assert summary.contact_records_prepared == 1
    assert summary.dry_run_records[0]["email"] == "jane@example.ai"
    contact_count = db.execute(text("select count(*) from contacts")).scalar_one()
    assert contact_count == 0


def test_enrich_contacts_from_websites_ingests_contacts() -> None:
    db = make_session()

    def opener(_request, timeout):
        del timeout
        return FakeResponse(body="Reach us at jane@example.ai.")

    summary = enrich_contacts_from_websites(
        db,
        limit=1,
        dry_run=False,
        delay_seconds=0,
        paths=("/contact",),
        opener=opener,
    )

    assert summary.contacts_created == 1
    assert summary.evidence_created == 1
    stored_email = db.execute(text("select email from contacts")).scalar_one()
    assert stored_email == "jane@example.ai"


def empty_summary():
    return WebsiteEnrichmentSummary()
