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
                    unique (source_id, source_record_id)
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


def test_ingests_yc_source_records() -> None:
    client, db = make_client()

    response = client.post(
        "/ingestion/y-combinator/source-records",
        json={"records": [yc_record()]},
    )

    assert response.status_code == 201
    assert response.json() == {
        "source": "y_combinator",
        "received": 1,
        "inserted": 1,
        "duplicates": 0,
    }

    stored_count = db.execute(text("select count(*) from source_records")).scalar_one()
    assert stored_count == 1


def test_ingestion_is_idempotent_by_source_record_id() -> None:
    client, db = make_client()
    payload = {"records": [yc_record()]}

    first = client.post("/ingestion/y-combinator/source-records", json=payload)
    second = client.post("/ingestion/y-combinator/source-records", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["inserted"] == 0
    assert second.json()["duplicates"] == 1

    stored_count = db.execute(text("select count(*) from source_records")).scalar_one()
    assert stored_count == 1


def test_rejects_unknown_source() -> None:
    client, _db = make_client()
    record = yc_record()
    record["source"] = "not_yc"

    response = client.post(
        "/ingestion/y-combinator/source-records",
        json={"records": [record]},
    )

    assert response.status_code == 422


def test_rejects_missing_required_fields() -> None:
    client, _db = make_client()
    record = yc_record()
    del record["company_name"]

    response = client.post(
        "/ingestion/y-combinator/source-records",
        json={"records": [record]},
    )

    assert response.status_code == 422


def yc_record() -> dict:
    return {
        "source": "y_combinator",
        "source_url": "https://www.ycombinator.com/companies/example-ai",
        "source_company_id": "example-ai",
        "company_name": "Example AI",
        "website": "https://example.ai",
        "location": "New York, NY, USA",
        "industry": "B2B SaaS",
        "batch": "S24",
        "stage": "Active",
        "status": "Active",
        "employee_count": 75,
        "description": "AI workflow platform for operations teams.",
        "tags": ["b2b", "saas", "ai"],
        "founders": [{"name": "Jane Founder"}],
    }
