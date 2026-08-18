import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.identity_resolution import process_yc_source_records
from app.services.source_ingestion import YC_SOURCE_KEY


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
                create table identity_resolution_reviews (
                    id text primary key,
                    source_record_id text not null,
                    source text not null,
                    reason text not null,
                    normalized_name text,
                    normalized_domain text,
                    candidate_matches text not null default '[]',
                    confidence numeric not null default 0,
                    status text not null default 'pending',
                    created_at timestamp not null,
                    updated_at timestamp not null,
                    unique (source_record_id)
                )
                """
            )
        )

    return session_factory()


def test_process_yc_records_creates_companies_and_aliases() -> None:
    db = make_session()
    insert_source(db)
    insert_source_record(db, "record-1", yc_payload())

    summary = process_yc_source_records(db)

    assert summary.scanned == 1
    assert summary.companies_created == 1
    assert summary.aliases_created == 1
    assert summary.source_identities_created == 1
    assert summary.review_items_created == 0

    company = db.execute(
        text(
            """
            select canonical_name, canonical_domain, city, country
            from companies
            """
        )
    ).one()
    assert company.canonical_name == "Example AI"
    assert company.canonical_domain == "example.ai"
    assert company.city == "New York"
    assert company.country == "United States"

    linked_count = db.execute(
        text("select count(*) from source_records where company_id is not null")
    ).scalar_one()
    assert linked_count == 1

    source_identity = db.execute(
        text("select external_id, source_url from source_identities")
    ).one()
    assert source_identity.external_id == "record-1"
    assert source_identity.source_url == yc_payload()["source_url"]


def test_process_yc_records_is_idempotent_for_linked_records() -> None:
    db = make_session()
    insert_source(db)
    insert_source_record(db, "record-1", yc_payload())

    first = process_yc_source_records(db)
    second = process_yc_source_records(db)

    assert first.companies_created == 1
    assert second.companies_created == 0
    assert second.skipped_already_linked == 1
    assert second.source_identities_created == 0

    company_count = db.execute(text("select count(*) from companies")).scalar_one()
    assert company_count == 1

    source_identity_count = db.execute(
        text("select count(*) from source_identities")
    ).scalar_one()
    assert source_identity_count == 1


def test_process_yc_records_creates_founders_when_present() -> None:
    db = make_session()
    insert_source(db)
    payload = yc_payload()
    payload["founders"] = [
        {"name": "Jane Founder", "role": "CEO"},
        {"name": "Sam Builder"},
    ]
    insert_source_record(db, "record-1", payload)

    summary = process_yc_source_records(db)

    assert summary.founders_created == 2
    assert summary.founder_links_created == 2

    founders = db.execute(
        text("select full_name from founders order by full_name")
    ).all()
    assert [row.full_name for row in founders] == ["Jane Founder", "Sam Builder"]

    link_count = db.execute(text("select count(*) from company_founders")).scalar_one()
    assert link_count == 2


def test_process_yc_records_backfills_source_identity_for_already_linked_record() -> None:
    db = make_session()
    insert_source(db)
    insert_source_record(db, "record-1", yc_payload())

    first = process_yc_source_records(db)
    assert first.source_identities_created == 1

    db.execute(text("delete from source_identities"))
    db.commit()

    second = process_yc_source_records(db)

    assert second.skipped_already_linked == 1
    assert second.source_identities_created == 1

    source_identity_count = db.execute(
        text("select count(*) from source_identities")
    ).scalar_one()
    assert source_identity_count == 1


def test_process_yc_records_creates_review_item_for_missing_domain() -> None:
    db = make_session()
    insert_source(db)
    payload = yc_payload()
    payload["website"] = None
    insert_source_record(db, "record-1", payload)

    summary = process_yc_source_records(db)

    assert summary.companies_created == 0
    assert summary.review_items_created == 1

    review = db.execute(
        text("select reason, normalized_name from identity_resolution_reviews")
    ).one()
    assert review.reason == "missing_domain"
    assert review.normalized_name == "Example AI"


def insert_source(db: Session) -> None:
    db.execute(
        text(
            """
            insert into sources (
                id,
                source_key,
                name,
                source_type,
                enabled,
                created_at,
                updated_at
            )
            values (
                'source-1',
                :source_key,
                'Y Combinator',
                'trusted_company_source',
                true,
                current_timestamp,
                current_timestamp
            )
            """
        ),
        {"source_key": YC_SOURCE_KEY},
    )
    db.commit()


def insert_source_record(db: Session, source_record_id: str, payload: dict) -> None:
    db.execute(
        text(
            """
            insert into source_records (
                id,
                source_id,
                source_record_id,
                raw_payload,
                source_url,
                collected_at,
                created_at
            )
            values (
                :id,
                'source-1',
                :source_record_id,
                :raw_payload,
                :source_url,
                current_timestamp,
                current_timestamp
            )
            """
        ),
        {
            "id": source_record_id,
            "source_record_id": source_record_id,
            "raw_payload": json.dumps(payload),
            "source_url": payload["source_url"],
        },
    )
    db.commit()


def yc_payload() -> dict:
    return {
        "source": "y_combinator",
        "source_url": "https://www.ycombinator.com/companies/example-ai",
        "source_company_id": "example-ai",
        "company_name": "Example AI",
        "website": "https://www.example.ai/about",
        "location": "New York, NY, USA",
        "industry": "B2B SaaS",
        "batch": "S24",
        "stage": "Growth",
        "employee_count": 75,
        "description": "AI workflow platform for operations teams.",
        "founders": [],
    }
