from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import create_app


def make_client() -> tuple[TestClient, Session]:
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
                create table sources (
                    id text primary key,
                    source_key text not null unique,
                    name text not null,
                    source_type text not null,
                    base_url text,
                    terms_url text,
                    enabled boolean not null default true,
                    created_at timestamp not null,
                    updated_at timestamp not null
                )
                """
            )
        )
        connection.execute(
            text(
                """
                create table source_records (
                    id text primary key,
                    source_id text not null,
                    source_record_id text,
                    company_id text,
                    raw_payload text not null,
                    source_url text,
                    collected_at timestamp not null,
                    content_hash text,
                    created_at timestamp not null,
                    processing_status text not null default 'pending',
                    processed_at timestamp,
                    processing_notes text,
                    unique (source_id, source_record_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                create table companies (
                    id text primary key,
                    canonical_name text not null,
                    canonical_domain text,
                    description text,
                    industry text,
                    country text,
                    city text,
                    company_stage text,
                    employee_estimate integer,
                    status text not null default 'candidate',
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
                create table company_aliases (
                    id text primary key,
                    company_id text not null,
                    alias text not null,
                    alias_type text not null default 'name',
                    source text,
                    confidence numeric not null default 0,
                    created_at timestamp not null,
                    unique (company_id, alias, alias_type)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                create table source_identities (
                    id text primary key,
                    company_id text not null,
                    source_id text not null,
                    external_id text not null,
                    source_url text,
                    confidence numeric not null default 1,
                    first_seen_at timestamp not null,
                    last_seen_at timestamp not null,
                    unique (source_id, external_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                create table signals (
                    id text primary key,
                    company_id text,
                    founder_id text,
                    signal_type text not null,
                    description text not null,
                    source text,
                    source_url text,
                    detected_at timestamp not null,
                    confidence numeric not null default 0,
                    raw_evidence text,
                    created_at timestamp not null
                )
                """
            )
        )

    db = session_factory()
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), db


def test_ingests_generic_discovery_record_into_company_and_signal() -> None:
    client, db = make_client()

    response = client.post(
        "/ingestion/discovery/source-records",
        json={
            "source": "funding_news",
            "source_name": "Funding News",
            "source_type": "funding_news",
            "base_url": "https://news.example",
            "records": [discovery_record()],
        },
    )

    assert response.status_code == 201
    assert response.json()["source_records_inserted"] == 1
    assert response.json()["companies_created"] == 1
    assert response.json()["signals_created"] == 1

    company = db.execute(
        text("select canonical_name, canonical_domain from companies")
    ).one()
    assert company.canonical_name == "Example AI"
    assert company.canonical_domain == "example.ai"

    source_identity = db.execute(
        text("select external_id from source_identities")
    ).scalar_one()
    assert source_identity == "article-1"

    signal = db.execute(
        text("select signal_type, source from signals")
    ).one()
    assert signal.signal_type == "FUNDING_EVENT"
    assert signal.source == "funding_news"


def test_generic_discovery_is_idempotent_by_source_record_id() -> None:
    client, db = make_client()
    payload = {
        "source": "funding_news",
        "records": [discovery_record()],
    }

    first = client.post("/ingestion/discovery/source-records", json=payload)
    second = client.post("/ingestion/discovery/source-records", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["duplicates"] == 1
    assert second.json()["companies_matched"] == 1

    company_count = db.execute(text("select count(*) from companies")).scalar_one()
    source_record_count = db.execute(
        text("select count(*) from source_records")
    ).scalar_one()
    signal_count = db.execute(text("select count(*) from signals")).scalar_one()
    assert company_count == 1
    assert source_record_count == 1
    assert signal_count == 1


def test_generic_discovery_rejects_mismatched_batch_source() -> None:
    client, _db = make_client()
    record = discovery_record()
    record["source"] = "other_source"

    response = client.post(
        "/ingestion/discovery/source-records",
        json={
            "source": "funding_news",
            "records": [record],
        },
    )

    assert response.status_code == 422


def test_generic_discovery_creates_hiring_discovery_signal() -> None:
    client, db = make_client()
    record = discovery_record()
    record["source"] = "hacker_news_who_is_hiring"
    record["source_record_id"] = "hn-comment-1"
    record["source_url"] = "https://news.ycombinator.com/item?id=1"
    record["event_type"] = "hiring"

    response = client.post(
        "/ingestion/discovery/source-records",
        json={
            "source": "hacker_news_who_is_hiring",
            "source_name": "Hacker News Who is Hiring",
            "source_type": "hiring_discovery",
            "base_url": "https://news.ycombinator.com",
            "records": [record],
        },
    )

    assert response.status_code == 201

    signal_type = db.execute(text("select signal_type from signals")).scalar_one()
    assert signal_type == "HIRING_DISCOVERY"


def discovery_record() -> dict:
    return {
        "source": "funding_news",
        "source_url": "https://news.example/example-ai-raises-seed",
        "source_record_id": "article-1",
        "company_name": "Example AI",
        "website": "https://example.ai",
        "domain": "example.ai",
        "location": "New York, USA",
        "industry": "B2B SaaS",
        "stage": None,
        "status": "active",
        "employee_count": None,
        "description": "Example AI raises seed funding.",
        "tags": ["funding"],
        "event_type": "funding",
        "event_date": "2026-08-20",
        "event_summary": "Example AI raises seed funding.",
        "raw_source_payload": {"title": "Example AI raises seed funding"},
    }
