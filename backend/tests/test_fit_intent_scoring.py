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
        connection.execute(
            text(
                """
                create table job_postings (
                    id text primary key,
                    company_id text not null,
                    ats_board_id text,
                    ats_provider text not null,
                    external_job_id text not null,
                    title text not null,
                    department text,
                    location text,
                    remote_policy text,
                    employment_type text,
                    posted_at timestamp,
                    first_seen_at timestamp not null,
                    last_seen_at timestamp not null,
                    url text not null,
                    description_text text,
                    stack_terms text not null default '[]',
                    seniority text,
                    is_active boolean not null default true,
                    raw_payload text not null default '{}',
                    missing_since_at timestamp,
                    missing_observation_count integer not null default 0,
                    created_at timestamp not null,
                    updated_at timestamp not null
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
                create table contacts (
                    id text primary key,
                    company_id text not null,
                    founder_id text,
                    full_name text,
                    role text,
                    email text,
                    contact_source text,
                    verification_status text not null default 'unverified',
                    confidence numeric not null default 0,
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
        seed_companies(connection)

    db = session_factory()
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), db


def test_scores_company_with_fit_x_intent_and_trigger_evidence() -> None:
    client, db = make_client()

    response = client.post("/scoring/companies/company-good", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["fit_score"] >= 80
    assert body["intent_score"] >= 80
    assert body["total_score"] == round(
        body["fit_score"] * body["intent_score"] / 100
    )
    assert body["disqualified"] is False
    assert body["trigger_evidence"][0]["signal_type"] == "STALE_ENGINEERING_ROLE"
    assert body["trigger_evidence"][0]["job_urls"] == [
        "https://boards.greenhouse.io/example-ai/jobs/job-1"
    ]

    stored = db.execute(
        text(
            """
            select fit_score, intent_score, total_score, score_version
            from scores
            where company_id = 'company-good'
            """
        )
    ).one()
    assert stored.fit_score == body["fit_score"]
    assert stored.intent_score == body["intent_score"]
    assert stored.total_score == body["total_score"]
    assert stored.score_version == "fit_intent_v0.1"


def test_suppressed_domain_is_disqualified_and_capped() -> None:
    client, _db = make_client()

    response = client.post("/scoring/companies/company-suppressed", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["disqualified"] is True
    assert body["fit_score"] <= 35
    assert body["intent_score"] <= 45
    assert body["total_score"] <= 16
    assert "Domain is suppressed." in body["penalties"]


def test_batch_scoring_scores_candidates_and_keeps_history() -> None:
    client, db = make_client()

    first = client.post("/scoring/companies", json={"limit": 10})
    second = client.post("/scoring/companies/company-good", json={})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["scored"] == 2

    score_count = db.execute(
        text("select count(*) from scores where company_id = 'company-good'")
    ).scalar_one()
    assert score_count == 2


def seed_companies(connection) -> None:
    connection.execute(
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
                created_at,
                updated_at
            )
            values
                (
                    'company-good',
                    'Example AI',
                    'example.ai',
                    'B2B SaaS workflow automation for logistics teams.',
                    'B2B SaaS logistics',
                    'United States',
                    'New York',
                    'seed',
                    45,
                    current_timestamp,
                    current_timestamp
                ),
                (
                    'company-suppressed',
                    'Suppressed Ops',
                    'suppressed-co.com',
                    'B2B SaaS operations software.',
                    'B2B SaaS',
                    'United States',
                    'Austin',
                    'series_a',
                    50,
                    current_timestamp,
                    current_timestamp
                )
            """
        )
    )
    connection.execute(
        text(
            """
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
            values
                (
                    'signal-good-stale',
                    'company-good',
                    'STALE_ENGINEERING_ROLE',
                    'Senior Backend Engineer role appears open for 90 days.',
                    'signal_enrichment',
                    'https://boards.greenhouse.io/example-ai/jobs/job-1',
                    '2026-08-19T00:00:00+00:00',
                    0.9,
                    '{"job_urls":["https://boards.greenhouse.io/example-ai/jobs/job-1"]}',
                    current_timestamp
                ),
                (
                    'signal-good-funding',
                    'company-good',
                    'FUNDING_EVENT',
                    'Example AI raised a seed round.',
                    'funding_news',
                    'https://news.example/example-ai',
                    '2026-08-18T00:00:00+00:00',
                    0.8,
                    '{}',
                    current_timestamp
                ),
                (
                    'signal-suppressed',
                    'company-suppressed',
                    'STALE_ENGINEERING_ROLE',
                    'Backend Engineer role appears open for 90 days.',
                    'signal_enrichment',
                    'https://jobs.example/suppressed/backend',
                    '2026-08-19T00:00:00+00:00',
                    0.9,
                    '{"job_urls":["https://jobs.example/suppressed/backend"]}',
                    current_timestamp
                )
            """
        )
    )
    connection.execute(
        text(
            """
            insert into job_postings (
                id,
                company_id,
                ats_provider,
                external_job_id,
                title,
                department,
                first_seen_at,
                last_seen_at,
                url,
                description_text,
                stack_terms,
                is_active,
                created_at,
                updated_at
            )
            values
                (
                    'job-good-1',
                    'company-good',
                    'greenhouse',
                    'job-1',
                    'Senior Backend Engineer',
                    'Engineering',
                    '2026-05-01T00:00:00+00:00',
                    '2026-08-19T00:00:00+00:00',
                    'https://boards.greenhouse.io/example-ai/jobs/job-1',
                    'Build APIs and integrations.',
                    '["python","postgresql"]',
                    true,
                    current_timestamp,
                    current_timestamp
                )
            """
        )
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
                'suppression-1',
                'suppressed-co.com',
                'do_not_contact',
                'manual',
                current_timestamp
            )
            """
        )
    )
