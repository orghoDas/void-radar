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
        create_schema(connection)
        seed_export_data(connection)

    db = session_factory()
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), db


def test_exports_verified_unsuppressed_contacts_with_reason_and_evidence() -> None:
    client, _db = make_client()

    response = client.post(
        "/outreach/export",
        json={"limit": 100, "min_total_score": 50},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["exported"] == 1

    row = body["rows"][0]
    assert row["company"] == "Example AI"
    assert row["domain"] == "example.ai"
    assert row["email"] == "jane@example.ai"
    assert row["score"] == 82
    assert row["reason_to_write"] == "Backend role open for 104 days."
    assert row["evidence_urls"] == [
        "https://boards.greenhouse.io/example-ai/jobs/job-1"
    ]


def test_csv_export_excludes_suppressed_and_unverified_contacts() -> None:
    client, _db = make_client()

    response = client.post(
        "/outreach/export.csv",
        json={"limit": 100, "min_total_score": 50},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    csv_body = response.text
    assert "jane@example.ai" in csv_body
    assert "public@example.ai" not in csv_body
    assert "blocked@blocked.example" not in csv_body
    assert "reason_to_write" in csv_body


def test_imports_outcomes_by_exported_contact_email() -> None:
    client, db = make_client()

    response = client.post(
        "/outreach/outcomes",
        json={
            "records": [
                {
                    "email": "jane@example.ai",
                    "event": "positive_reply",
                    "source": "phase-0-manual",
                    "metadata": {"reply": "Interested"},
                    "occurred_at": "2026-08-20T12:00:00+00:00",
                },
                {
                    "email": "missing@example.ai",
                    "event": "bounced",
                },
            ]
        },
    )

    assert response.status_code == 201
    assert response.json()["inserted"] == 1
    assert response.json()["rejected"] == 1
    assert response.json()["rejected_records"][0]["reason"] == (
        "company_or_contact_not_found"
    )

    outcome = db.execute(
        text("select company_id, contact_id, email, event, metadata from outcomes")
    ).one()
    assert outcome.company_id == "company-good"
    assert outcome.contact_id == "contact-good"
    assert outcome.email == "jane@example.ai"
    assert outcome.event == "positive_reply"
    assert "Interested" in outcome.metadata


def create_schema(connection) -> None:
    connection.execute(
        text(
            """
            create table companies (
                id text primary key,
                canonical_name text not null,
                canonical_domain text,
                created_at timestamp not null,
                updated_at timestamp not null
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
                verified_at timestamp,
                created_at timestamp not null,
                updated_at timestamp not null
            )
            """
        )
    )
    connection.execute(
        text(
            """
            create table scores (
                id text primary key,
                company_id text not null,
                company_fit integer not null,
                opportunity_strength integer not null,
                timing integer not null,
                technical_capacity_gap integer not null,
                commercial_potential integer not null,
                source_confidence integer not null,
                overall_score integer not null,
                positive_reasons text not null default '[]',
                penalties text not null default '[]',
                fit_score integer,
                intent_score integer,
                total_score integer,
                score_version text,
                scoring_inputs text not null default '{}',
                calculated_at timestamp not null,
                model_version text not null
            )
            """
        )
    )
    connection.execute(
        text(
            """
            create table suppression (
                id text primary key,
                email text,
                domain text,
                reason text not null,
                source text,
                added_at timestamp not null
            )
            """
        )
    )
    connection.execute(
        text(
            """
            create table outcomes (
                id text primary key,
                company_id text,
                contact_id text,
                email text,
                event text not null,
                source text,
                signal_id text,
                metadata text not null default '{}',
                occurred_at timestamp not null,
                created_at timestamp not null
            )
            """
        )
    )


def seed_export_data(connection) -> None:
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
            values
                (
                    'company-good',
                    'Example AI',
                    'example.ai',
                    current_timestamp,
                    current_timestamp
                ),
                (
                    'company-blocked',
                    'Blocked Co',
                    'blocked-co.com',
                    current_timestamp,
                    current_timestamp
                )
            """
        )
    )
    connection.execute(
        text(
            """
            insert into contacts (
                id,
                company_id,
                full_name,
                role,
                email,
                contact_source,
                source_type,
                provider_name,
                verification_status,
                confidence,
                last_checked_at,
                verified_at,
                created_at,
                updated_at
            )
            values
                (
                    'contact-good',
                    'company-good',
                    'Jane Doe',
                    'VP Engineering',
                    'jane@example.ai',
                    'verified_provider',
                    'verified_provider',
                    'provider',
                    'provider_verified',
                    0.95,
                    '2026-08-20T10:00:00+00:00',
                    '2026-08-20T10:00:00+00:00',
                    current_timestamp,
                    current_timestamp
                ),
                (
                    'contact-public',
                    'company-good',
                    'Public Contact',
                    'Founder',
                    'public@example.ai',
                    'company_website',
                    'company_website',
                    null,
                    'public_source',
                    0.75,
                    current_timestamp,
                    null,
                    current_timestamp,
                    current_timestamp
                ),
                (
                    'contact-blocked',
                    'company-blocked',
                    'Blocked Person',
                    'CEO',
                    'blocked@blocked-co.com',
                    'manual_review',
                    'manual_review',
                    null,
                    'manual_verified',
                    0.9,
                    current_timestamp,
                    current_timestamp,
                    current_timestamp,
                    current_timestamp
                )
            """
        )
    )
    scoring_inputs = """
    {
      "trigger_evidence": [
        {
          "signal_id": "signal-1",
          "signal_type": "STALE_ENGINEERING_ROLE",
          "description": "Backend role open for 104 days.",
          "source_url": "https://boards.greenhouse.io/example-ai/jobs/job-1",
          "job_urls": ["https://boards.greenhouse.io/example-ai/jobs/job-1"]
        }
      ],
      "positive_reasons": ["Company has technical/product hiring intent."],
      "penalties": []
    }
    """
    connection.execute(
        text(
            """
            insert into scores (
                id,
                company_id,
                company_fit,
                opportunity_strength,
                timing,
                technical_capacity_gap,
                commercial_potential,
                source_confidence,
                overall_score,
                positive_reasons,
                penalties,
                fit_score,
                intent_score,
                total_score,
                score_version,
                scoring_inputs,
                calculated_at,
                model_version
            )
            values
                (
                    'score-good',
                    'company-good',
                    88,
                    93,
                    93,
                    85,
                    88,
                    90,
                    82,
                    '["Company has technical/product hiring intent."]',
                    '[]',
                    88,
                    93,
                    82,
                    'fit_intent_v0.1',
                    :scoring_inputs,
                    '2026-08-20T10:00:00+00:00',
                    'fit_intent_v0.1'
                ),
                (
                    'score-blocked',
                    'company-blocked',
                    90,
                    90,
                    90,
                    85,
                    90,
                    90,
                    81,
                    '["Company has technical/product hiring intent."]',
                    '[]',
                    90,
                    90,
                    81,
                    'fit_intent_v0.1',
                    :scoring_inputs,
                    '2026-08-20T10:00:00+00:00',
                    'fit_intent_v0.1'
                )
            """
        ),
        {"scoring_inputs": scoring_inputs},
    )
    connection.execute(
        text(
            """
            insert into suppression (
                id,
                domain,
                reason,
                source,
                added_at
            )
            values (
                'suppression-blocked-domain',
                'blocked-co.com',
                'do_not_contact',
                'manual',
                current_timestamp
            )
            """
        )
    )
