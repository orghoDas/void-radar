from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.identity.normalize import normalize_domain
from app.schemas.signal_enrichment import (
    AtsBoardDetectionRecord,
    AtsBoardMissRecord,
    JobPostingRecord,
)

SIGNAL_ENRICHMENT_SOURCE = "signal_enrichment"
STALE_ROLE_DAYS = 60
STRONG_STALE_ROLE_DAYS = 90

ROLE_KEYWORDS = (
    "engineer",
    "engineering",
    "developer",
    "software",
    "backend",
    "front end",
    "frontend",
    "full stack",
    "fullstack",
    "platform",
    "data",
    "product",
    "automation",
    "devops",
    "site reliability",
    "sre",
)

SPIKE_WINDOW_DAYS = 30
SPIKE_RELEVANT_ROLE_COUNT = 3

TECH_STACK_TERMS = (
    "api",
    "apis",
    "aws",
    "azure",
    "django",
    "etl",
    "fastapi",
    "gcp",
    "integration",
    "integrations",
    "kubernetes",
    "migration",
    "next.js",
    "node",
    "postgres",
    "postgresql",
    "python",
    "react",
    "salesforce",
    "snowflake",
    "typescript",
    "workflow",
)

OPERATIONS_NEED_TERMS = (
    "automation",
    "back office",
    "business operations",
    "crm",
    "dashboard",
    "data pipeline",
    "internal tool",
    "internal tooling",
    "marketplace operations",
    "operations",
    "platform",
    "process",
    "reporting",
    "workflow",
)


@dataclass(frozen=True)
class RejectedSignalEnrichment:
    index: int
    reason: str


@dataclass(frozen=True)
class SignalEnrichmentSummary:
    source: str
    received: int
    accepted: int
    created: int
    updated: int
    duplicates: int
    signals_created: int
    inactive_marked: int = 0
    rejected_records: list[RejectedSignalEnrichment] = field(default_factory=list)

    @property
    def rejected(self) -> int:
        return len(self.rejected_records)


@dataclass(frozen=True)
class ObservedJobScope:
    company_id: str
    ats_provider: str
    ats_board_id: str | None


def ingest_ats_board_detections(
    db: Session,
    records: list[AtsBoardDetectionRecord],
) -> SignalEnrichmentSummary:
    created = 0
    updated = 0
    duplicates = 0
    signals_created = 0
    rejected_records: list[RejectedSignalEnrichment] = []

    for index, record in enumerate(records):
        company = resolve_company(db, record.company_id, record.domain)
        if not company:
            rejected_records.append(
                RejectedSignalEnrichment(index=index, reason="company_not_found")
            )
            continue

        board_key = ats_board_key(record)
        payload = ats_board_payload(record, company["domain"], board_key)
        existing = find_ats_board(db, company["id"], record.ats_provider, board_key)
        if existing:
            if existing["fingerprint"] == board_fingerprint(payload):
                duplicates += 1
                continue
            update_ats_board(db, str(existing["id"]), payload)
            updated += 1
        else:
            create_ats_board(db, company["id"], payload)
            created += 1

        insert_signal(
            db,
            company_id=company["id"],
            signal_type="ATS_BOARD_DETECTED",
            description=(
                f"{record.ats_provider.title()} job board detected for "
                f"{company['domain']}."
            ),
            source=SIGNAL_ENRICHMENT_SOURCE,
            source_url=str(record.evidence_url or record.careers_url or record.board_url),
            confidence=record.confidence,
            raw_evidence=payload,
        )
        signals_created += 1

    db.commit()
    return SignalEnrichmentSummary(
        source=SIGNAL_ENRICHMENT_SOURCE,
        received=len(records),
        accepted=len(records) - len(rejected_records),
        created=created,
        updated=updated,
        duplicates=duplicates,
        signals_created=signals_created,
        rejected_records=rejected_records,
    )


def ingest_ats_board_misses(
    db: Session,
    records: list[AtsBoardMissRecord],
) -> SignalEnrichmentSummary:
    signals_created = 0
    duplicates = 0
    rejected_records: list[RejectedSignalEnrichment] = []

    for index, record in enumerate(records):
        company = resolve_company(db, record.company_id, record.domain)
        if not company:
            rejected_records.append(
                RejectedSignalEnrichment(index=index, reason="company_not_found")
            )
            continue

        source_url = str(record.evidence_url or record.careers_url or "")
        if no_ats_signal_exists(db, company_id=company["id"], source_url=source_url):
            duplicates += 1
            continue

        insert_signal(
            db,
            company_id=company["id"],
            signal_type="NO_ATS_FOUND",
            description=f"No ATS board detected for {company['domain']}.",
            source=SIGNAL_ENRICHMENT_SOURCE,
            source_url=source_url or None,
            confidence=record.confidence,
            raw_evidence={
                "domain": normalize_domain(record.domain) or company["domain"],
                "careers_url": str(record.careers_url) if record.careers_url else None,
                "evidence_url": str(record.evidence_url) if record.evidence_url else None,
                "raw_evidence": record.raw_evidence,
            },
        )
        signals_created += 1

    db.commit()
    return SignalEnrichmentSummary(
        source=SIGNAL_ENRICHMENT_SOURCE,
        received=len(records),
        accepted=len(records) - len(rejected_records),
        created=0,
        updated=0,
        duplicates=duplicates,
        signals_created=signals_created,
        rejected_records=rejected_records,
    )


def ingest_job_postings(
    db: Session,
    records: list[JobPostingRecord],
    *,
    mark_missing_inactive: bool = False,
    missing_observation_threshold: int = 2,
    snapshot_observed_at: datetime | None = None,
) -> SignalEnrichmentSummary:
    created = 0
    updated = 0
    duplicates = 0
    signals_created = 0
    inactive_marked = 0
    rejected_records: list[RejectedSignalEnrichment] = []
    observed_jobs: dict[ObservedJobScope, set[str]] = {}

    for index, record in enumerate(records):
        company = resolve_company(db, record.company_id, record.domain)
        if not company:
            rejected_records.append(
                RejectedSignalEnrichment(index=index, reason="company_not_found")
            )
            continue

        ats_board_id = resolve_ats_board_id(
            db,
            company_id=company["id"],
            ats_provider=record.ats_provider,
            board_token=record.board_token,
            board_url=str(record.board_url) if record.board_url else None,
        )
        scope = ObservedJobScope(
            company_id=company["id"],
            ats_provider=record.ats_provider,
            ats_board_id=ats_board_id,
        )
        observed_jobs.setdefault(scope, set()).add(record.external_job_id)

        payload = job_posting_payload(record)
        existing = find_job_posting(
            db,
            company_id=company["id"],
            ats_provider=record.ats_provider,
            external_job_id=record.external_job_id,
        )
        if existing:
            if existing["fingerprint"] == job_fingerprint(payload):
                refresh_job_posting_observation(
                    db,
                    job_id=str(existing["id"]),
                    ats_board_id=ats_board_id,
                    last_seen_at=payload["last_seen_at"],
                    is_active=payload["is_active"],
                )
                duplicates += 1
                continue
            update_job_posting(db, str(existing["id"]), ats_board_id, payload)
            updated += 1
        else:
            create_job_posting(db, company["id"], ats_board_id, payload)
            created += 1

        signals_created += insert_job_signals(
            db,
            company_id=company["id"],
            record=record,
            payload=payload,
        )

    signals_created += insert_hiring_spike_signals(db, observed_jobs)
    if mark_missing_inactive:
        inactive_marked = mark_missing_job_observations(
            db,
            observed_jobs,
            missing_observation_threshold=missing_observation_threshold,
            observed_at=snapshot_observed_at or datetime.now(UTC),
        )

    db.commit()
    return SignalEnrichmentSummary(
        source=SIGNAL_ENRICHMENT_SOURCE,
        received=len(records),
        accepted=len(records) - len(rejected_records),
        created=created,
        updated=updated,
        duplicates=duplicates,
        signals_created=signals_created,
        inactive_marked=inactive_marked,
        rejected_records=rejected_records,
    )


def resolve_company(
    db: Session,
    company_id: str | None,
    domain_value: str | None,
) -> dict[str, str] | None:
    if company_id:
        row = db.execute(
            text(
                """
                select id, canonical_domain
                from companies
                where id = :company_id
                """
            ),
            {"company_id": company_id},
        ).mappings().first()
        if row:
            return {
                "id": str(row["id"]),
                "domain": str(row["canonical_domain"] or normalize_domain(domain_value) or ""),
            }

    domain = normalize_domain(domain_value)
    if not domain:
        return None

    row = db.execute(
        text(
            """
            select id, canonical_domain
            from companies
            where canonical_domain = :domain
            """
        ),
        {"domain": domain},
    ).mappings().first()
    if not row:
        return None

    return {"id": str(row["id"]), "domain": str(row["canonical_domain"] or domain)}


def ats_board_key(record: AtsBoardDetectionRecord) -> str:
    if record.board_token:
        return record.board_token.strip().lower()
    if record.board_url:
        return str(record.board_url).rstrip("/").lower()
    if record.careers_url:
        return str(record.careers_url).rstrip("/").lower()
    raise ValueError("board reference is required")


def ats_board_payload(
    record: AtsBoardDetectionRecord,
    domain: str,
    board_key: str,
) -> dict:
    return {
        "domain": normalize_domain(record.domain) or domain,
        "ats_provider": record.ats_provider,
        "board_key": board_key,
        "board_token": clean_optional_text(record.board_token),
        "board_url": str(record.board_url) if record.board_url else None,
        "careers_url": str(record.careers_url) if record.careers_url else None,
        "evidence_url": str(record.evidence_url) if record.evidence_url else None,
        "confidence": record.confidence,
        "raw_evidence": record.raw_evidence,
    }


def job_posting_payload(record: JobPostingRecord) -> dict:
    now = datetime.now(UTC)
    return {
        "ats_provider": record.ats_provider,
        "external_job_id": record.external_job_id,
        "title": record.title.strip(),
        "department": clean_optional_text(record.department),
        "location": clean_optional_text(record.location),
        "remote_policy": clean_optional_text(record.remote_policy),
        "employment_type": clean_optional_text(record.employment_type),
        "posted_at": record.posted_at,
        "first_seen_at": record.first_seen_at or record.posted_at or now,
        "last_seen_at": record.last_seen_at or now,
        "url": str(record.url),
        "description_text": clean_optional_text(record.description_text),
        "stack_terms": sorted(
            {term.strip().lower() for term in record.stack_terms if term.strip()}
        ),
        "seniority": clean_optional_text(record.seniority),
        "is_active": record.is_active,
        "raw_payload": record.raw_payload,
    }


def find_ats_board(
    db: Session,
    company_id: str,
    ats_provider: str,
    board_key: str,
):
    row = db.execute(
        text(
            """
            select
                id,
                domain,
                ats_provider,
                board_key,
                board_token,
                board_url,
                careers_url,
                evidence_url,
                confidence,
                raw_evidence
            from ats_boards
            where company_id = :company_id
              and ats_provider = :ats_provider
              and board_key = :board_key
            """
        ),
        {
            "company_id": company_id,
            "ats_provider": ats_provider,
            "board_key": board_key,
        },
    ).mappings().first()
    if not row:
        return None

    payload = {
        "domain": row["domain"],
        "ats_provider": row["ats_provider"],
        "board_key": row["board_key"],
        "board_token": row["board_token"],
        "board_url": row["board_url"],
        "careers_url": row["careers_url"],
        "evidence_url": row["evidence_url"],
        "confidence": float(row["confidence"]),
        "raw_evidence": load_json_value(row["raw_evidence"]),
    }
    return {"id": row["id"], "fingerprint": board_fingerprint(payload)}


def create_ats_board(db: Session, company_id: str, payload: dict) -> str:
    board_id = str(uuid4())
    now = datetime.now(UTC)
    db.execute(
        text(json_insert_sql(db, ats_board_insert_sql(), ("raw_evidence",))),
        {
            "id": board_id,
            "company_id": company_id,
            **serialize_payload(payload),
            "first_detected_at": now,
            "last_detected_at": now,
            "created_at": now,
            "updated_at": now,
        },
    )
    return board_id


def update_ats_board(db: Session, board_id: str, payload: dict) -> None:
    db.execute(
        text(json_insert_sql(db, ats_board_update_sql(), ("raw_evidence",))),
        {
            "id": board_id,
            **serialize_payload(payload),
            "last_detected_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        },
    )


def resolve_ats_board_id(
    db: Session,
    company_id: str,
    ats_provider: str,
    board_token: str | None,
    board_url: str | None,
) -> str | None:
    if not board_token and not board_url:
        return None

    board_key = (board_token or board_url or "").rstrip("/").lower()
    row = db.execute(
        text(
            """
            select id
            from ats_boards
            where company_id = :company_id
              and ats_provider = :ats_provider
              and board_key = :board_key
            """
        ),
        {
            "company_id": company_id,
            "ats_provider": ats_provider,
            "board_key": board_key,
        },
    ).scalar_one_or_none()
    return str(row) if row else None


def find_job_posting(
    db: Session,
    company_id: str,
    ats_provider: str,
    external_job_id: str,
):
    row = db.execute(
        text(
            """
            select
                id,
                ats_provider,
                external_job_id,
                title,
                department,
                location,
                remote_policy,
                employment_type,
                posted_at,
                first_seen_at,
                last_seen_at,
                url,
                description_text,
                stack_terms,
                seniority,
                is_active,
                raw_payload
            from job_postings
            where company_id = :company_id
              and ats_provider = :ats_provider
              and external_job_id = :external_job_id
            """
        ),
        {
            "company_id": company_id,
            "ats_provider": ats_provider,
            "external_job_id": external_job_id,
        },
    ).mappings().first()
    if not row:
        return None

    payload = {
        "ats_provider": row["ats_provider"],
        "external_job_id": row["external_job_id"],
        "title": row["title"],
        "department": row["department"],
        "location": row["location"],
        "remote_policy": row["remote_policy"],
        "employment_type": row["employment_type"],
        "posted_at": row["posted_at"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "url": row["url"],
        "description_text": row["description_text"],
        "stack_terms": load_json_value(row["stack_terms"], default=[]),
        "seniority": row["seniority"],
        "is_active": bool(row["is_active"]),
        "raw_payload": load_json_value(row["raw_payload"]),
    }
    return {"id": row["id"], "fingerprint": job_fingerprint(payload)}


def create_job_posting(
    db: Session,
    company_id: str,
    ats_board_id: str | None,
    payload: dict,
) -> str:
    job_id = str(uuid4())
    now = datetime.now(UTC)
    db.execute(
        text(json_insert_sql(db, job_posting_insert_sql(), ("stack_terms", "raw_payload"))),
        {
            "id": job_id,
            "company_id": company_id,
            "ats_board_id": ats_board_id,
            **serialize_payload(payload),
            "missing_since_at": None,
            "missing_observation_count": 0,
            "created_at": now,
            "updated_at": now,
        },
    )
    return job_id


def update_job_posting(
    db: Session,
    job_id: str,
    ats_board_id: str | None,
    payload: dict,
) -> None:
    db.execute(
        text(json_insert_sql(db, job_posting_update_sql(), ("stack_terms", "raw_payload"))),
        {
            "id": job_id,
            "ats_board_id": ats_board_id,
            **serialize_payload(payload),
            "missing_since_at": None,
            "missing_observation_count": 0,
            "updated_at": datetime.now(UTC),
        },
    )


def refresh_job_posting_observation(
    db: Session,
    *,
    job_id: str,
    ats_board_id: str | None,
    last_seen_at: datetime,
    is_active: bool,
) -> None:
    db.execute(
        text(
            """
            update job_postings
            set
                ats_board_id = coalesce(:ats_board_id, ats_board_id),
                last_seen_at = :last_seen_at,
                is_active = :is_active,
                missing_since_at = null,
                missing_observation_count = 0,
                updated_at = :updated_at
            where id = :id
            """
        ),
        {
            "id": job_id,
            "ats_board_id": ats_board_id,
            "last_seen_at": last_seen_at,
            "is_active": is_active,
            "updated_at": datetime.now(UTC),
        },
    )


def insert_job_signals(
    db: Session,
    *,
    company_id: str,
    record: JobPostingRecord,
    payload: dict,
) -> int:
    created = 0
    for signal in job_signals(record):
        if insert_signal_once(
            db,
            company_id=company_id,
            signal_type=signal["signal_type"],
            description=signal["description"],
            source=SIGNAL_ENRICHMENT_SOURCE,
            source_url=str(record.url),
            confidence=signal["confidence"],
            raw_evidence=payload | {"signal": signal, "job_urls": [str(record.url)]},
        ):
            created += 1
    return created


def job_signals(record: JobPostingRecord) -> list[dict]:
    signals = []
    stale_signal = stale_role_signal(record)
    if stale_signal:
        signals.append(stale_signal)

    tech_stack_signal = tech_stack_need_signal(record)
    if tech_stack_signal:
        signals.append(tech_stack_signal)

    operations_signal = operations_software_need_signal(record)
    if operations_signal:
        signals.append(operations_signal)

    return signals


def stale_role_signal(record: JobPostingRecord) -> dict | None:
    if is_non_technical_title(record.title):
        return None
    if not is_relevant_role_text(role_title_text(record)):
        return None

    reference_time = record.posted_at or record.first_seen_at
    if not reference_time:
        return None
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)

    age_days = max(0, (datetime.now(UTC) - reference_time).days)
    if age_days < STALE_ROLE_DAYS:
        return None

    if age_days >= STRONG_STALE_ROLE_DAYS:
        signal_type = "STALE_ENGINEERING_ROLE"
        confidence = 0.9
    else:
        signal_type = "AGING_ENGINEERING_ROLE"
        confidence = 0.75

    return {
        "signal_type": signal_type,
        "confidence": confidence,
        "age_days": age_days,
        "description": f"{record.title.strip()} role appears open for {age_days} days.",
    }


def tech_stack_need_signal(record: JobPostingRecord) -> dict | None:
    if is_non_technical_title(record.title):
        return None
    if not is_relevant_role_text(role_title_text(record)):
        return None

    text_value = job_text(record)

    matched_terms = matched_keywords(text_value, TECH_STACK_TERMS)
    if not matched_terms:
        return None

    return {
        "signal_type": "TECH_STACK_NEED",
        "confidence": 0.7,
        "matched_terms": matched_terms,
        "description": (
            f"{record.title.strip()} mentions stack or integration needs: "
            f"{', '.join(matched_terms[:5])}."
        ),
    }


def operations_software_need_signal(record: JobPostingRecord) -> dict | None:
    if is_non_technical_title(record.title):
        return None

    text_value = job_text(record)
    matched_terms = matched_keywords(text_value, OPERATIONS_NEED_TERMS)
    if not matched_terms:
        return None
    if not any(
        keyword in role_title_text(record)
        for keyword in ("operations", "platform", "product", "data", "automation")
    ):
        return None

    return {
        "signal_type": "OPERATIONS_SOFTWARE_NEED",
        "confidence": 0.75,
        "matched_terms": matched_terms,
        "description": (
            f"{record.title.strip()} suggests internal tooling or operations "
            f"software need: {', '.join(matched_terms[:5])}."
        ),
    }


def insert_hiring_spike_signals(
    db: Session,
    observed_jobs: dict[ObservedJobScope, set[str]],
) -> int:
    created = 0
    for scope, external_job_ids in observed_jobs.items():
        rows = active_observed_job_rows(db, scope, external_job_ids)
        relevant_rows = [
            row
            for row in rows
            if is_recent_relevant_job(row, window_days=SPIKE_WINDOW_DAYS)
        ]
        if len(relevant_rows) < SPIKE_RELEVANT_ROLE_COUNT:
            continue

        job_urls = [str(row["url"]) for row in relevant_rows if row["url"]]
        source_url = job_urls[0] if job_urls else None
        titles = [str(row["title"]) for row in relevant_rows[:5]]
        if insert_signal_once(
            db,
            company_id=scope.company_id,
            signal_type="HIRING_SPIKE",
            description=(
                f"{len(relevant_rows)} relevant roles appeared within "
                f"{SPIKE_WINDOW_DAYS} days: {', '.join(titles)}."
            ),
            source=SIGNAL_ENRICHMENT_SOURCE,
            source_url=source_url,
            confidence=0.8,
            raw_evidence={
                "ats_provider": scope.ats_provider,
                "ats_board_id": scope.ats_board_id,
                "window_days": SPIKE_WINDOW_DAYS,
                "job_count": len(relevant_rows),
                "job_urls": job_urls,
                "titles": titles,
            },
        ):
            created += 1
    return created


def active_observed_job_rows(
    db: Session,
    scope: ObservedJobScope,
    external_job_ids: set[str],
) -> list[dict]:
    board_filter = (
        "and ats_board_id = :ats_board_id"
        if scope.ats_board_id
        else "and ats_board_id is null"
    )
    rows = db.execute(
        text(
            f"""
            select
                id,
                external_job_id,
                title,
                department,
                first_seen_at,
                url,
                description_text,
                stack_terms
            from job_postings
            where company_id = :company_id
              and ats_provider = :ats_provider
              and is_active = true
              {board_filter}
            """
        ),
        {
            "company_id": scope.company_id,
            "ats_provider": scope.ats_provider,
            "ats_board_id": scope.ats_board_id,
        },
    ).mappings()
    return [
        dict(row)
        for row in rows
        if str(row["external_job_id"]) in external_job_ids
    ]


def is_recent_relevant_job(row: dict, *, window_days: int) -> bool:
    text_value = " ".join(
        str(value)
        for value in (
            row.get("title"),
            row.get("department"),
            row.get("description_text"),
            " ".join(load_json_value(row.get("stack_terms"), default=[])),
        )
        if value
    ).lower()
    if not is_relevant_role_text(row_role_title_text(row)):
        return False

    first_seen_at = parse_datetime_value(row.get("first_seen_at"))
    if not first_seen_at:
        return False
    return max(0, (datetime.now(UTC) - first_seen_at).days) <= window_days


def mark_missing_job_observations(
    db: Session,
    observed_jobs: dict[ObservedJobScope, set[str]],
    *,
    missing_observation_threshold: int,
    observed_at: datetime,
) -> int:
    inactive_marked = 0
    for scope, observed_external_ids in observed_jobs.items():
        board_filter = (
            "and ats_board_id = :ats_board_id"
            if scope.ats_board_id
            else "and ats_board_id is null"
        )
        rows = db.execute(
            text(
                f"""
                select
                    id,
                    external_job_id,
                    missing_observation_count
                from job_postings
                where company_id = :company_id
                  and ats_provider = :ats_provider
                  and is_active = true
                  {board_filter}
                """
            ),
            {
                "company_id": scope.company_id,
                "ats_provider": scope.ats_provider,
                "ats_board_id": scope.ats_board_id,
            },
        ).mappings()

        for row in rows:
            if str(row["external_job_id"]) in observed_external_ids:
                continue
            next_count = int(row["missing_observation_count"] or 0) + 1
            should_deactivate = next_count >= missing_observation_threshold
            db.execute(
                text(
                    """
                    update job_postings
                    set
                        missing_since_at = coalesce(missing_since_at, :observed_at),
                        missing_observation_count = :missing_observation_count,
                        is_active = :is_active,
                        updated_at = :updated_at
                    where id = :id
                    """
                ),
                {
                    "id": row["id"],
                    "observed_at": observed_at,
                    "missing_observation_count": next_count,
                    "is_active": not should_deactivate,
                    "updated_at": datetime.now(UTC),
                },
            )
            if should_deactivate:
                inactive_marked += 1
    return inactive_marked


def job_text(record: JobPostingRecord) -> str:
    return " ".join(
        value
        for value in (
            record.title,
            record.department,
            record.description_text,
            " ".join(record.stack_terms),
        )
        if value
    ).lower()


# Some companies file non-technical roles under an Engineering department, so a
# department check cannot catch these. A title that is unambiguously a
# non-building role vetoes the signal regardless of department. Deliberately
# excludes "sales engineer" and "solutions engineer", which are technical.
NON_TECHNICAL_TITLE_TERMS = (
    "account executive",
    "account manager",
    "business development",
    "sales development",
    "sales representative",
    "underwriter",
    "controller",
    "recruiter",
    "talent partner",
    "social media",
    "office manager",
    "executive assistant",
    "paralegal",
    "bookkeeper",
)


def is_non_technical_title(title: str | None) -> bool:
    lowered = (title or "").lower()
    return any(term in lowered for term in NON_TECHNICAL_TITLE_TERMS)


def role_title_text(record: JobPostingRecord) -> str:
    """Role relevance is decided by the job title, not the description body.

    Description text at a tech company mentions engineering in boilerplate, so
    matching against it marks every role - underwriter, controller, account
    executive - as a technical hiring need.
    """
    return " ".join(
        value for value in (record.title, record.department) if value
    ).lower()


def row_role_title_text(row: dict) -> str:
    return " ".join(
        str(value)
        for value in (row.get("title"), row.get("department"))
        if value
    ).lower()


def is_relevant_role_text(text_value: str) -> bool:
    return any(keyword in text_value for keyword in ROLE_KEYWORDS)


def matched_keywords(text_value: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text_value]


def insert_signal(
    db: Session,
    *,
    company_id: str,
    signal_type: str,
    description: str,
    source: str,
    source_url: str | None,
    confidence: float,
    raw_evidence: dict,
) -> str:
    signal_id = str(uuid4())
    now = datetime.now(UTC)
    db.execute(
        text(json_insert_sql(db, signal_insert_sql(), ("raw_evidence",))),
        {
            "id": signal_id,
            "company_id": company_id,
            "signal_type": signal_type,
            "description": description,
            "source": source,
            "source_url": source_url,
            "detected_at": now,
            "confidence": confidence,
            "raw_evidence": json.dumps(raw_evidence, sort_keys=True, default=json_default),
            "created_at": now,
        },
    )
    return signal_id


def insert_signal_once(
    db: Session,
    *,
    company_id: str,
    signal_type: str,
    description: str,
    source: str,
    source_url: str | None,
    confidence: float,
    raw_evidence: dict,
) -> bool:
    if signal_exists(
        db,
        company_id=company_id,
        signal_type=signal_type,
        source=source,
        source_url=source_url,
    ):
        return False
    insert_signal(
        db,
        company_id=company_id,
        signal_type=signal_type,
        description=description,
        source=source,
        source_url=source_url,
        confidence=confidence,
        raw_evidence=raw_evidence,
    )
    return True


def signal_exists(
    db: Session,
    *,
    company_id: str,
    signal_type: str,
    source: str,
    source_url: str | None,
) -> bool:
    existing = db.execute(
        text(
            """
            select 1
            from signals
            where company_id = :company_id
              and signal_type = :signal_type
              and source = :source
              and coalesce(source_url, '') = coalesce(:source_url, '')
            limit 1
            """
        ),
        {
            "company_id": company_id,
            "signal_type": signal_type,
            "source": source,
            "source_url": source_url,
        },
    ).scalar_one_or_none()
    return bool(existing)


def no_ats_signal_exists(db: Session, company_id: str, source_url: str) -> bool:
    existing = db.execute(
        text(
            """
            select 1
            from signals
            where company_id = :company_id
              and signal_type = 'NO_ATS_FOUND'
              and coalesce(source_url, '') = :source_url
            limit 1
            """
        ),
        {
            "company_id": company_id,
            "source_url": source_url,
        },
    ).scalar_one_or_none()
    return bool(existing)


def board_fingerprint(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, default=json_default)


def job_fingerprint(payload: dict) -> str:
    comparable = dict(payload)
    comparable.pop("posted_at", None)
    comparable.pop("first_seen_at", None)
    comparable.pop("last_seen_at", None)
    return json.dumps(comparable, sort_keys=True, default=json_default)


def serialize_payload(payload: dict) -> dict:
    serialized = dict(payload)
    for key in ("raw_evidence", "raw_payload", "stack_terms"):
        if key in serialized:
            serialized[key] = json.dumps(
                serialized[key],
                sort_keys=True,
                default=json_default,
            )
    return serialized


def json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def load_json_value(value, default=None):
    if value is None:
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def parse_datetime_value(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def json_insert_sql(db: Session, sql: str, fields: tuple[str, ...]) -> str:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return sql
    for json_field in fields:
        sql = sql.replace(f":{json_field}", f"cast(:{json_field} as jsonb)")
    return sql


def ats_board_insert_sql() -> str:
    return """
        insert into ats_boards (
            id,
            company_id,
            domain,
            ats_provider,
            board_key,
            board_token,
            board_url,
            careers_url,
            evidence_url,
            confidence,
            raw_evidence,
            status,
            first_detected_at,
            last_detected_at,
            created_at,
            updated_at
        )
        values (
            :id,
            :company_id,
            :domain,
            :ats_provider,
            :board_key,
            :board_token,
            :board_url,
            :careers_url,
            :evidence_url,
            :confidence,
            :raw_evidence,
            'detected',
            :first_detected_at,
            :last_detected_at,
            :created_at,
            :updated_at
        )
    """


def ats_board_update_sql() -> str:
    return """
        update ats_boards
        set
            domain = :domain,
            board_token = :board_token,
            board_url = :board_url,
            careers_url = :careers_url,
            evidence_url = :evidence_url,
            confidence = :confidence,
            raw_evidence = :raw_evidence,
            status = 'detected',
            last_detected_at = :last_detected_at,
            updated_at = :updated_at
        where id = :id
    """


def job_posting_insert_sql() -> str:
    return """
        insert into job_postings (
            id,
            company_id,
            ats_board_id,
            ats_provider,
            external_job_id,
            title,
            department,
            location,
            remote_policy,
            employment_type,
            posted_at,
            first_seen_at,
            last_seen_at,
            url,
            description_text,
            stack_terms,
            seniority,
            is_active,
            raw_payload,
            missing_since_at,
            missing_observation_count,
            created_at,
            updated_at
        )
        values (
            :id,
            :company_id,
            :ats_board_id,
            :ats_provider,
            :external_job_id,
            :title,
            :department,
            :location,
            :remote_policy,
            :employment_type,
            :posted_at,
            :first_seen_at,
            :last_seen_at,
            :url,
            :description_text,
            :stack_terms,
            :seniority,
            :is_active,
            :raw_payload,
            :missing_since_at,
            :missing_observation_count,
            :created_at,
            :updated_at
        )
    """


def job_posting_update_sql() -> str:
    return """
        update job_postings
        set
            ats_board_id = coalesce(:ats_board_id, ats_board_id),
            title = :title,
            department = :department,
            location = :location,
            remote_policy = :remote_policy,
            employment_type = :employment_type,
            posted_at = :posted_at,
            first_seen_at = first_seen_at,
            last_seen_at = :last_seen_at,
            url = :url,
            description_text = :description_text,
            stack_terms = :stack_terms,
            seniority = :seniority,
            is_active = :is_active,
            raw_payload = :raw_payload,
            missing_since_at = :missing_since_at,
            missing_observation_count = :missing_observation_count,
            updated_at = :updated_at
        where id = :id
    """


def signal_insert_sql() -> str:
    return """
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
        values (
            :id,
            :company_id,
            :signal_type,
            :description,
            :source,
            :source_url,
            :detected_at,
            :confidence,
            :raw_evidence,
            :created_at
        )
    """
