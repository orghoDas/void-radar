from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.identity.normalize import normalize_domain
from app.schemas.outreach import (
    OutcomeImportResult,
    OutcomeRecord,
    OutcomeRejectedRecord,
    OutreachExportRequest,
    OutreachExportRow,
)


@dataclass(frozen=True)
class LatestScoreRow:
    score_id: str
    company_id: str
    company_name: str
    domain: str
    contact_id: str
    contact_name: str | None
    role: str | None
    email: str
    verified_at: datetime | None
    source: str | None
    score: int
    fit_score: int
    intent_score: int
    scoring_inputs: dict
    positive_reasons: list[str]
    penalties: list[str]


def export_send_ready_prospects(
    db: Session,
    request: OutreachExportRequest,
) -> list[OutreachExportRow]:
    rows = latest_score_contact_rows(db, request)
    export_rows: list[OutreachExportRow] = []

    for row in rows:
        trigger_evidence = row.scoring_inputs.get("trigger_evidence", [])
        evidence_urls = evidence_urls_from_trigger_evidence(trigger_evidence)
        if not evidence_urls:
            continue

        reason_to_write = reason_to_write_from_evidence(
            trigger_evidence,
            row.positive_reasons,
        )
        if not reason_to_write:
            continue

        export_rows.append(
            OutreachExportRow(
                company_id=row.company_id,
                score_id=row.score_id,
                contact_id=row.contact_id,
                company=row.company_name,
                domain=row.domain,
                contact_name=row.contact_name,
                role=row.role,
                email=row.email,
                verified_at=row.verified_at,
                source=row.source,
                score=row.score,
                fit_score=row.fit_score,
                intent_score=row.intent_score,
                reason_to_write=reason_to_write,
                evidence_urls=evidence_urls,
                positive_reasons=row.positive_reasons,
                penalties=row.penalties,
            )
        )
        if len(export_rows) >= request.limit:
            break

    return export_rows


def export_send_ready_prospects_csv(
    db: Session,
    request: OutreachExportRequest,
) -> str:
    rows = export_send_ready_prospects(db, request)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "company",
            "domain",
            "contact_name",
            "role",
            "email",
            "verified_at",
            "source",
            "score",
            "fit_score",
            "intent_score",
            "reason_to_write",
            "evidence_urls",
            "score_id",
            "company_id",
            "contact_id",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "company": row.company,
                "domain": row.domain,
                "contact_name": row.contact_name or "",
                "role": row.role or "",
                "email": row.email,
                "verified_at": row.verified_at.isoformat() if row.verified_at else "",
                "source": row.source or "",
                "score": row.score,
                "fit_score": row.fit_score,
                "intent_score": row.intent_score,
                "reason_to_write": row.reason_to_write,
                "evidence_urls": ";".join(row.evidence_urls),
                "score_id": row.score_id,
                "company_id": row.company_id,
                "contact_id": row.contact_id,
            }
        )
    return output.getvalue()


def import_outcomes(
    db: Session,
    records: list[OutcomeRecord],
) -> OutcomeImportResult:
    inserted = 0
    rejected_records: list[OutcomeRejectedRecord] = []

    for index, record in enumerate(records):
        resolved = resolve_outcome_target(db, record)
        if not resolved:
            rejected_records.append(
                OutcomeRejectedRecord(index=index, reason="company_or_contact_not_found")
            )
            continue

        db.execute(
            text(json_insert_sql(db, outcome_insert_sql(), ("metadata",))),
            {
                "id": str(uuid4()),
                "company_id": resolved["company_id"],
                "contact_id": resolved["contact_id"],
                "email": resolved["email"],
                "event": record.event,
                "source": record.source,
                "signal_id": record.signal_id,
                "metadata": json.dumps(record.metadata, sort_keys=True),
                "occurred_at": record.occurred_at or datetime.now(UTC),
                "created_at": datetime.now(UTC),
            },
        )
        inserted += 1

    db.commit()
    return OutcomeImportResult(
        received=len(records),
        accepted=inserted,
        inserted=inserted,
        rejected=len(rejected_records),
        rejected_records=rejected_records,
    )


def latest_score_contact_rows(
    db: Session,
    request: OutreachExportRequest,
) -> list[LatestScoreRow]:
    status_filter, status_params = verification_status_filter(
        request.verification_statuses
    )
    rows = db.execute(
        text(
            f"""
            with latest_scores as (
                select s.*
                from scores s
                join (
                    select company_id, max(calculated_at) as calculated_at
                    from scores
                    group by company_id
                ) latest
                  on latest.company_id = s.company_id
                 and latest.calculated_at = s.calculated_at
            )
            select
                ls.id as score_id,
                ls.company_id,
                c.canonical_name as company_name,
                c.canonical_domain as domain,
                ct.id as contact_id,
                ct.full_name as contact_name,
                ct.role,
                ct.email,
                coalesce(ct.verified_at, ct.last_checked_at) as verified_at,
                coalesce(ct.provider_name, ct.source_type, ct.contact_source) as source,
                coalesce(ls.total_score, ls.overall_score) as score,
                coalesce(ls.fit_score, ls.company_fit) as fit_score,
                coalesce(ls.intent_score, ls.opportunity_strength) as intent_score,
                ls.scoring_inputs,
                ls.positive_reasons,
                ls.penalties
            from latest_scores ls
            join companies c on c.id = ls.company_id
            join contacts ct on ct.company_id = c.id
            where coalesce(ls.total_score, ls.overall_score) >= :min_total_score
              and ct.email is not null
              and ct.email <> ''
              and ct.verification_status in ({status_filter})
              and not exists (
                    select 1
                    from suppression sp
                    where lower(coalesce(sp.email, '')) = lower(ct.email)
                       or lower(coalesce(sp.domain, '')) = lower(c.canonical_domain)
              )
            order by
                coalesce(ls.total_score, ls.overall_score) desc,
                coalesce(ct.confidence, 0) desc,
                c.canonical_name,
                ct.email
            limit :query_limit
            """
        ),
        {
            "min_total_score": request.min_total_score,
            "query_limit": request.limit * 3,
            **status_params,
        },
    ).mappings()

    return [
        LatestScoreRow(
            score_id=str(row["score_id"]),
            company_id=str(row["company_id"]),
            company_name=str(row["company_name"]),
            domain=str(normalize_domain(row["domain"]) or row["domain"] or ""),
            contact_id=str(row["contact_id"]),
            contact_name=row["contact_name"],
            role=row["role"],
            email=str(row["email"]).lower(),
            verified_at=parse_datetime_value(row["verified_at"]),
            source=row["source"],
            score=int(row["score"]),
            fit_score=int(row["fit_score"]),
            intent_score=int(row["intent_score"]),
            scoring_inputs=load_json_value(row["scoring_inputs"]),
            positive_reasons=load_json_value(row["positive_reasons"], default=[]),
            penalties=load_json_value(row["penalties"], default=[]),
        )
        for row in rows
    ]


def verification_status_filter(statuses: list[str]) -> tuple[str, dict[str, str]]:
    params = {f"status_{index}": status for index, status in enumerate(statuses)}
    placeholders = ", ".join(f":{key}" for key in params)
    return placeholders, params


def evidence_urls_from_trigger_evidence(trigger_evidence: list[dict]) -> list[str]:
    urls: list[str] = []
    for evidence in trigger_evidence:
        for url in evidence.get("job_urls", []):
            if url and url not in urls:
                urls.append(str(url))
        source_url = evidence.get("source_url")
        if source_url and source_url not in urls:
            urls.append(str(source_url))
    return urls


def reason_to_write_from_evidence(
    trigger_evidence: list[dict],
    positive_reasons: list[str],
) -> str:
    for evidence in trigger_evidence:
        description = str(evidence.get("description") or "").strip()
        if description:
            return description
    return positive_reasons[0] if positive_reasons else ""


def resolve_outcome_target(db: Session, record: OutcomeRecord) -> dict | None:
    if record.contact_id:
        row = db.execute(
            text(
                """
                select id, company_id, email
                from contacts
                where id = :contact_id
                """
            ),
            {"contact_id": record.contact_id},
        ).mappings().first()
        if row:
            return {
                "company_id": str(row["company_id"]),
                "contact_id": str(row["id"]),
                "email": record.email or row["email"],
            }

    if record.company_id:
        company_exists = db.execute(
            text("select 1 from companies where id = :company_id"),
            {"company_id": record.company_id},
        ).scalar_one_or_none()
        if not company_exists:
            return None
        contact_id = None
        if record.email:
            contact_id = db.execute(
                text(
                    """
                    select id
                    from contacts
                    where company_id = :company_id
                      and lower(email) = :email
                    limit 1
                    """
                ),
                {"company_id": record.company_id, "email": record.email.lower()},
            ).scalar_one_or_none()
        return {
            "company_id": record.company_id,
            "contact_id": str(contact_id) if contact_id else record.contact_id,
            "email": record.email,
        }

    if record.email:
        row = db.execute(
            text(
                """
                select id, company_id, email
                from contacts
                where lower(email) = :email
                order by created_at desc
                limit 1
                """
            ),
            {"email": record.email.lower()},
        ).mappings().first()
        if row:
            return {
                "company_id": str(row["company_id"]),
                "contact_id": str(row["id"]),
                "email": row["email"],
            }

    return None


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


def load_json_value(value, default=None):
    if value is None:
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def json_insert_sql(db: Session, sql: str, fields: tuple[str, ...]) -> str:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return sql
    for json_field in fields:
        sql = sql.replace(f":{json_field}", f"cast(:{json_field} as jsonb)")
    return sql


def outcome_insert_sql() -> str:
    return """
        insert into outcomes (
            id,
            company_id,
            contact_id,
            email,
            event,
            source,
            signal_id,
            metadata,
            occurred_at,
            created_at
        )
        values (
            :id,
            :company_id,
            :contact_id,
            :email,
            :event,
            :source,
            :signal_id,
            :metadata,
            :occurred_at,
            :created_at
        )
    """
