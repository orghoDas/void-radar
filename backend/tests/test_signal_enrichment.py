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
                create table ats_boards (
                    id text primary key,
                    company_id text not null,
                    domain text not null,
                    ats_provider text not null,
                    board_key text not null,
                    board_token text,
                    board_url text,
                    careers_url text,
                    evidence_url text,
                    confidence numeric not null default 0,
                    raw_evidence text not null default '{}',
                    status text not null default 'detected',
                    first_detected_at timestamp not null,
                    last_detected_at timestamp not null,
                    created_at timestamp not null,
                    updated_at timestamp not null,
                    unique (company_id, ats_provider, board_key)
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
                    updated_at timestamp not null,
                    unique (company_id, ats_provider, external_job_id)
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

    db = session_factory()
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), db


def test_ingests_ats_board_detection_and_signal() -> None:
    client, db = make_client()

    response = client.post(
        "/enrichment/ats-boards",
        json={
            "records": [
                {
                    "domain": "https://example.ai",
                    "ats_provider": "greenhouse",
                    "board_token": "example-ai",
                    "board_url": "https://boards.greenhouse.io/example-ai",
                    "careers_url": "https://example.ai/careers",
                    "confidence": 0.92,
                    "evidence_url": "https://example.ai/careers",
                    "raw_evidence": {"selector": "a[href*='greenhouse']"},
                }
            ]
        },
    )

    assert response.status_code == 201
    assert response.json()["created"] == 1
    assert response.json()["signals_created"] == 1

    board = db.execute(
        text("select domain, ats_provider, board_key from ats_boards")
    ).one()
    assert board.domain == "example.ai"
    assert board.ats_provider == "greenhouse"
    assert board.board_key == "example-ai"

    signal_type = db.execute(text("select signal_type from signals")).scalar_one()
    assert signal_type == "ATS_BOARD_DETECTED"


def test_ats_board_detection_is_idempotent() -> None:
    client, db = make_client()
    payload = {
        "records": [
            {
                "domain": "example.ai",
                "ats_provider": "lever",
                "board_token": "example-ai",
                "board_url": "https://jobs.lever.co/example-ai",
            }
        ]
    }

    first = client.post("/enrichment/ats-boards", json=payload)
    second = client.post("/enrichment/ats-boards", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["duplicates"] == 1
    assert second.json()["signals_created"] == 0

    board_count = db.execute(text("select count(*) from ats_boards")).scalar_one()
    assert board_count == 1


def test_ingests_stale_job_posting_and_signal() -> None:
    client, db = make_client()

    response = client.post(
        "/enrichment/job-postings",
        json={
            "records": [
                {
                    "domain": "example.ai",
                    "ats_provider": "greenhouse",
                    "external_job_id": "job-1",
                    "title": "Senior Backend Engineer",
                    "department": "Engineering",
                    "posted_at": "2020-01-01T00:00:00Z",
                    "url": "https://boards.greenhouse.io/example-ai/jobs/job-1",
                    "description_text": "Own backend services.",
                    "seniority": "senior",
                }
            ]
        },
    )

    assert response.status_code == 201
    assert response.json()["created"] == 1
    assert response.json()["signals_created"] == 1

    job = db.execute(
        text("select title, ats_provider from job_postings")
    ).one()
    assert job.title == "Senior Backend Engineer"
    assert job.ats_provider == "greenhouse"

    signal = db.execute(
        text("select signal_type, source_url from signals")
    ).one()
    assert signal.signal_type == "STALE_ENGINEERING_ROLE"
    assert signal.source_url == "https://boards.greenhouse.io/example-ai/jobs/job-1"


def test_duplicate_job_posting_refreshes_last_seen_without_new_signal() -> None:
    client, db = make_client()
    base_record = {
        "domain": "example.ai",
        "ats_provider": "greenhouse",
        "external_job_id": "job-1",
        "title": "Senior Backend Engineer",
        "department": "Engineering",
        "posted_at": "2026-01-01T00:00:00Z",
        "first_seen_at": "2026-01-01T00:00:00Z",
        "last_seen_at": "2026-02-01T00:00:00Z",
        "url": "https://boards.greenhouse.io/example-ai/jobs/job-1",
        "description_text": "Own backend services.",
        "seniority": "senior",
    }

    first = client.post("/enrichment/job-postings", json={"records": [base_record]})
    second_record = dict(base_record)
    second_record["last_seen_at"] = "2026-03-01T00:00:00Z"
    second = client.post("/enrichment/job-postings", json={"records": [second_record]})

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["duplicates"] == 1
    assert second.json()["signals_created"] == 0

    job = db.execute(
        text("select last_seen_at, is_active from job_postings")
    ).one()
    assert "2026-03-01" in str(job.last_seen_at)
    assert bool(job.is_active) is True

    signal_count = db.execute(text("select count(*) from signals")).scalar_one()
    assert signal_count == 1


def test_job_posting_creates_tech_stack_and_operations_signals() -> None:
    client, db = make_client()

    response = client.post(
        "/enrichment/job-postings",
        json={
            "records": [
                {
                    "domain": "example.ai",
                    "ats_provider": "greenhouse",
                    "external_job_id": "job-ops-1",
                    "title": "Product Operations Platform Engineer",
                    "department": "Operations",
                    "posted_at": "2026-08-10T00:00:00Z",
                    "url": "https://boards.greenhouse.io/example-ai/jobs/job-ops-1",
                    "description_text": (
                        "Build internal tooling, reporting workflows, and API "
                        "integrations for marketplace operations."
                    ),
                    "stack_terms": ["Python", "PostgreSQL"],
                }
            ]
        },
    )

    assert response.status_code == 201
    assert response.json()["signals_created"] == 2

    signal_types = db.execute(
        text("select signal_type from signals order by signal_type")
    ).scalars().all()
    assert signal_types == ["OPERATIONS_SOFTWARE_NEED", "TECH_STACK_NEED"]


def test_job_posting_batch_creates_hiring_spike_signal() -> None:
    client, db = make_client()

    records = [
        {
            "domain": "example.ai",
            "ats_provider": "greenhouse",
            "external_job_id": f"spike-{index}",
            "title": title,
            "department": "Engineering",
            "first_seen_at": "2026-08-18T00:00:00Z",
            "url": f"https://boards.greenhouse.io/example-ai/jobs/spike-{index}",
            "description_text": "Build core product services.",
        }
        for index, title in enumerate(
            [
                "Backend Engineer",
                "Frontend Engineer",
                "Software Engineer",
            ],
            start=1,
        )
    ]

    response = client.post("/enrichment/job-postings", json={"records": records})

    assert response.status_code == 201
    assert response.json()["signals_created"] == 1

    signal = db.execute(
        text("select signal_type, raw_evidence from signals")
    ).one()
    assert signal.signal_type == "HIRING_SPIKE"
    assert "spike-1" in signal.raw_evidence
    assert "spike-3" in signal.raw_evidence


def test_full_snapshot_marks_missing_jobs_inactive_after_threshold() -> None:
    client, db = make_client()
    old_job = {
        "domain": "example.ai",
        "ats_provider": "greenhouse",
        "external_job_id": "job-old",
        "title": "Backend Engineer",
        "department": "Engineering",
        "first_seen_at": "2026-08-01T00:00:00Z",
        "url": "https://boards.greenhouse.io/example-ai/jobs/job-old",
        "description_text": "Build core services.",
    }
    visible_job = {
        "domain": "example.ai",
        "ats_provider": "greenhouse",
        "external_job_id": "job-visible",
        "title": "Product Engineer",
        "department": "Engineering",
        "first_seen_at": "2026-08-02T00:00:00Z",
        "url": "https://boards.greenhouse.io/example-ai/jobs/job-visible",
        "description_text": "Build product services.",
    }

    initial = client.post(
        "/enrichment/job-postings",
        json={"records": [old_job, visible_job]},
    )
    first_missing = client.post(
        "/enrichment/job-postings",
        json={
            "records": [visible_job],
            "mark_missing_inactive": True,
            "missing_observation_threshold": 2,
            "snapshot_observed_at": "2026-08-10T00:00:00Z",
        },
    )
    second_missing = client.post(
        "/enrichment/job-postings",
        json={
            "records": [visible_job],
            "mark_missing_inactive": True,
            "missing_observation_threshold": 2,
            "snapshot_observed_at": "2026-08-11T00:00:00Z",
        },
    )

    assert initial.status_code == 201
    assert first_missing.status_code == 201
    assert second_missing.status_code == 201
    assert first_missing.json()["inactive_marked"] == 0
    assert second_missing.json()["inactive_marked"] == 1

    rows = db.execute(
        text(
            """
            select external_job_id, is_active, missing_observation_count
            from job_postings
            order by external_job_id
            """
        )
    ).mappings().all()
    assert rows[0]["external_job_id"] == "job-old"
    assert bool(rows[0]["is_active"]) is False
    assert rows[0]["missing_observation_count"] == 2
    assert rows[1]["external_job_id"] == "job-visible"
    assert bool(rows[1]["is_active"]) is True


def test_rejects_signal_enrichment_for_unknown_company() -> None:
    client, db = make_client()

    response = client.post(
        "/enrichment/ats-boards",
        json={
            "records": [
                {
                    "domain": "missing.example",
                    "ats_provider": "greenhouse",
                    "board_token": "missing",
                }
            ]
        },
    )

    assert response.status_code == 201
    assert response.json()["accepted"] == 0
    assert response.json()["rejected"] == 1
    assert response.json()["rejected_records"][0]["reason"] == "company_not_found"

    board_count = db.execute(text("select count(*) from ats_boards")).scalar_one()
    assert board_count == 0


def test_ingests_ats_board_miss_as_no_ats_signal() -> None:
    client, db = make_client()

    response = client.post(
        "/enrichment/ats-board-misses",
        json={
            "records": [
                {
                    "domain": "example.ai",
                    "careers_url": "https://example.ai/careers",
                    "evidence_url": "https://example.ai/careers",
                    "confidence": 0.7,
                    "raw_evidence": {"checked_paths": ["/careers", "/jobs"]},
                }
            ]
        },
    )

    assert response.status_code == 201
    assert response.json()["signals_created"] == 1

    signal = db.execute(
        text("select signal_type, source_url from signals")
    ).one()
    assert signal.signal_type == "NO_ATS_FOUND"
    assert signal.source_url == "https://example.ai/careers"


def test_ats_board_miss_is_idempotent_by_company_and_source_url() -> None:
    client, db = make_client()
    payload = {
        "records": [
            {
                "domain": "example.ai",
                "careers_url": "https://example.ai/careers",
                "evidence_url": "https://example.ai/careers",
            }
        ]
    }

    first = client.post("/enrichment/ats-board-misses", json=payload)
    second = client.post("/enrichment/ats-board-misses", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["duplicates"] == 1
    assert second.json()["signals_created"] == 0

    signal_count = db.execute(text("select count(*) from signals")).scalar_one()
    assert signal_count == 1


def test_non_technical_role_does_not_create_stale_engineering_signal() -> None:
    """Role relevance must come from the title, not the description body.

    A tech company's boilerplate mentions engineering in every posting, so
    matching the description marked underwriters and controllers as stale
    technical hiring needs.
    """
    client, db = make_client()

    response = client.post(
        "/enrichment/job-postings",
        json={
            "records": [
                {
                    "domain": "example.ai",
                    "ats_provider": "greenhouse",
                    "external_job_id": "job-underwriter",
                    "title": "Executive Underwriter",
                    "department": "Insurance",
                    "posted_at": "2020-01-01T00:00:00Z",
                    "url": "https://boards.greenhouse.io/example-ai/jobs/u-1",
                    "description_text": (
                        "Work closely with our engineering, product and data "
                        "platform teams to automate underwriting software."
                    ),
                }
            ]
        },
    )

    assert response.status_code == 201
    assert response.json()["created"] == 1
    assert response.json()["signals_created"] == 0

    signal_types = [
        row.signal_type
        for row in db.execute(text("select signal_type from signals")).all()
    ]
    assert "STALE_ENGINEERING_ROLE" not in signal_types
    assert "TECH_STACK_NEED" not in signal_types
    assert "OPERATIONS_SOFTWARE_NEED" not in signal_types
