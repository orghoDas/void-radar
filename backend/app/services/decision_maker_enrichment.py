from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class DecisionMakerCandidateRecord:
    company_id: str
    full_name: str | None
    role: str
    role_category: str
    email: str | None
    linkedin_url: str | None
    x_url: str | None
    profile_url: str | None
    source_type: str
    source_url: str
    confidence: float
    raw_evidence: dict[str, Any]


@dataclass(frozen=True)
class DecisionMakerIngestionSummary:
    received: int
    inserted: int
    duplicates: int


def ingest_decision_maker_candidates(
    db: Session,
    candidates: list[DecisionMakerCandidateRecord],
) -> DecisionMakerIngestionSummary:
    inserted = 0
    duplicates = 0

    for candidate in candidates:
        if decision_maker_candidate_exists(db, candidate):
            duplicates += 1
            continue

        create_decision_maker_candidate(db, candidate)
        inserted += 1

    db.commit()

    return DecisionMakerIngestionSummary(
        received=len(candidates),
        inserted=inserted,
        duplicates=duplicates,
    )


def decision_maker_candidate_exists(
    db: Session,
    candidate: DecisionMakerCandidateRecord,
) -> bool:
    existing = db.execute(
        text(
            """
            select 1
            from decision_maker_candidates
            where company_id = :company_id
              and coalesce(lower(full_name), '') = :full_name
              and lower(role) = :role
              and role_category = :role_category
              and coalesce(lower(email), '') = :email
              and source_url = :source_url
            limit 1
            """
        ),
        {
            "company_id": candidate.company_id,
            "full_name": (candidate.full_name or "").lower(),
            "role": candidate.role.lower(),
            "role_category": candidate.role_category,
            "email": (candidate.email or "").lower(),
            "source_url": candidate.source_url,
        },
    ).scalar_one_or_none()

    return bool(existing)


def create_decision_maker_candidate(
    db: Session,
    candidate: DecisionMakerCandidateRecord,
) -> None:
    now = datetime.now(UTC)
    db.execute(
        text(decision_maker_insert_sql(db)),
        {
            "id": str(uuid4()),
            "company_id": candidate.company_id,
            "full_name": candidate.full_name,
            "role": candidate.role,
            "role_category": candidate.role_category,
            "email": candidate.email,
            "linkedin_url": candidate.linkedin_url,
            "x_url": candidate.x_url,
            "profile_url": candidate.profile_url,
            "source_type": candidate.source_type,
            "source_url": candidate.source_url,
            "confidence": candidate.confidence,
            "raw_evidence": json.dumps(candidate.raw_evidence, sort_keys=True),
            "created_at": now,
            "updated_at": now,
        },
    )


def decision_maker_insert_sql(db: Session) -> str:
    raw_evidence_value = ":raw_evidence"
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        raw_evidence_value = "cast(:raw_evidence as jsonb)"

    return f"""
        insert into decision_maker_candidates (
            id,
            company_id,
            full_name,
            role,
            role_category,
            email,
            linkedin_url,
            x_url,
            profile_url,
            source_type,
            source_url,
            confidence,
            raw_evidence,
            created_at,
            updated_at
        )
        values (
            :id,
            :company_id,
            :full_name,
            :role,
            :role_category,
            :email,
            :linkedin_url,
            :x_url,
            :profile_url,
            :source_type,
            :source_url,
            :confidence,
            {raw_evidence_value},
            :created_at,
            :updated_at
        )
    """
