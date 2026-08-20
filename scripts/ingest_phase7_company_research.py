"""Ingest Company Researcher output into raw_pages and observations."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db.session import get_engine
from app.identity.normalize import normalize_domain
from app.services.source_ingestion import SourceMetadata, content_hash, ensure_source
from sqlalchemy import text
from sqlalchemy.orm import Session

SOURCE_METADATA = SourceMetadata(
    source_key="phase7_company_research",
    name="Phase 7 Company Researcher",
    source_type="qualified_company_research",
    base_url="apify/company-researcher",
    terms_url=None,
)

OBSERVATION_FIELDS = [
    "positioning",
    "business_model_terms",
    "customer_terms",
    "technology_mentions",
    "service_fit_evidence",
    "contact_routes",
    "decision_maker_names",
    "research_summary",
]


@dataclass
class IngestSummary:
    rows_loaded: int = 0
    company_records: int = 0
    page_records: int = 0
    raw_pages_inserted: int = 0
    observations_inserted: int = 0
    rejected: int = 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("research_output_path", type=Path)
    args = parser.parse_args()

    rows = load_rows(args.research_output_path)
    with Session(get_engine()) as db:
        summary = ingest_rows(db, rows)

    for key, value in summary.__dict__.items():
        print(f"{key}: {value}")
    return 0 if summary.company_records or summary.page_records else 1


def ingest_rows(db: Session, rows: list[dict[str, Any]]) -> IngestSummary:
    source_id = ensure_source(db, SOURCE_METADATA)
    summary = IngestSummary(rows_loaded=len(rows))
    seen_pages: set[tuple[str, str, str]] = set()

    for row in rows:
        normalized = normalize_row(row)
        company_id = resolve_company_id(
            db,
            company_id=clean(normalized.get("company_id")),
            domain=clean(normalized.get("domain") or normalized.get("company_domain")),
        )
        if not company_id:
            summary.rejected += 1
            continue

        record_type = clean(normalized.get("record_type"))
        if record_type == "company_research":
            summary.company_records += 1
            pages = value_from_row(normalized, "page_records", default=[])
            if isinstance(pages, list):
                for page in pages:
                    if isinstance(page, dict) and insert_raw_page_once(
                        db,
                        source_id=source_id,
                        company_id=company_id,
                        page=page,
                        seen_pages=seen_pages,
                    ):
                        summary.raw_pages_inserted += 1

            for field_name in OBSERVATION_FIELDS:
                value = value_from_row(normalized, field_name)
                if is_empty_value(value):
                    continue
                insert_observation(
                    db,
                    company_id=company_id,
                    field_name=field_name,
                    value=value,
                    source_url=first_source_url(normalized),
                )
                summary.observations_inserted += 1
            continue

        if record_type == "page_research":
            summary.page_records += 1
            if insert_raw_page_once(
                db,
                source_id=source_id,
                company_id=company_id,
                page=normalized,
                seen_pages=seen_pages,
            ):
                summary.raw_pages_inserted += 1
            continue

    db.commit()
    return summary


def insert_raw_page_once(
    db: Session,
    *,
    source_id: str,
    company_id: str,
    page: dict[str, Any],
    seen_pages: set[tuple[str, str, str]],
) -> bool:
    url = clean(page.get("final_url") or page.get("url"))
    body = clean(page.get("page_text") or page.get("text_sample"))
    if not url or not body:
        return False
    page_hash = clean(page.get("content_hash")) or content_hash({"url": url, "body": body})
    key = (company_id, url, page_hash)
    if key in seen_pages:
        return False
    seen_pages.add(key)

    now = datetime.now(UTC)
    db.execute(
        text(raw_page_insert_sql(db)),
        {
            "id": str(uuid4()),
            "company_id": company_id,
            "source_id": source_id,
            "url": clean(page.get("url")) or url,
            "final_url": url,
            "body": body,
            "content_type": clean(page.get("content_type")) or None,
            "status_code": int_or_none(page.get("status_code")),
            "content_hash": page_hash,
            "fetched_at": now,
            "created_at": now,
        },
    )
    return True


def insert_observation(
    db: Session,
    *,
    company_id: str,
    field_name: str,
    value: Any,
    source_url: str | None,
) -> None:
    now = datetime.now(UTC)
    db.execute(
        text(json_insert_sql(db, observation_insert_sql(), "value")),
        {
            "id": str(uuid4()),
            "company_id": company_id,
            "evidence_kind": "OBSERVATION",
            "field_name": field_name,
            "value": json.dumps(value, sort_keys=True),
            "source": SOURCE_METADATA.source_key,
            "source_url": source_url,
            "collected_at": now,
            "confidence": 0.75,
            "created_at": now,
        },
    )


def resolve_company_id(
    db: Session,
    *,
    company_id: str,
    domain: str,
) -> str | None:
    if company_id:
        existing = db.execute(
            text("select id from companies where id = :company_id"),
            {"company_id": company_id},
        ).scalar_one_or_none()
        if existing:
            return str(existing)

    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        return None
    existing = db.execute(
        text("select id from companies where canonical_domain = :domain"),
        {"domain": normalized_domain},
    ).scalar_one_or_none()
    return str(existing) if existing else None


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise TypeError("JSON research output must be a list or object with items.")
        return [dict(row) for row in rows if isinstance(row, dict)]

    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        return list(csv.DictReader(csv_file))


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {clean(key): value for key, value in row.items() if key is not None}


def parse_jsonish(value: Any, default: Any = "") -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    text_value = clean(value)
    if not text_value:
        return default
    if text_value[0] not in "[{":
        return text_value
    try:
        return json.loads(text_value)
    except json.JSONDecodeError:
        return text_value


def value_from_row(row: dict[str, Any], field_name: str, default: Any = "") -> Any:
    direct_value = parse_jsonish(row.get(field_name), default=None)
    if not is_empty_value(direct_value):
        return direct_value

    flattened = rehydrate_flattened_field(row, field_name)
    if is_empty_value(flattened):
        return default
    return flattened


def rehydrate_flattened_field(row: dict[str, Any], field_name: str) -> Any:
    prefix = f"{field_name}/"
    tree: dict[str, Any] = {}
    for key, value in row.items():
        if not key.startswith(prefix):
            continue
        clean_value = parse_jsonish(value, default="")
        if is_empty_value(clean_value):
            continue
        suffix_parts = [part for part in key[len(prefix) :].split("/") if part]
        if not suffix_parts:
            continue
        insert_flattened_value(tree, suffix_parts, clean_value)
    return numeric_dicts_to_lists(tree)


def insert_flattened_value(node: dict[str, Any], parts: list[str], value: Any) -> None:
    current = node
    for part in parts[:-1]:
        existing = current.get(part)
        if not isinstance(existing, dict):
            existing = {}
            current[part] = existing
        current = existing
    current[parts[-1]] = value


def numeric_dicts_to_lists(value: Any) -> Any:
    if isinstance(value, dict):
        converted = {key: numeric_dicts_to_lists(item) for key, item in value.items()}
        if converted and all(str(key).isdigit() for key in converted):
            return [
                converted[key]
                for key in sorted(converted, key=lambda item: int(str(item)))
            ]
        return converted
    if isinstance(value, list):
        return [numeric_dicts_to_lists(item) for item in value]
    return value


def is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def first_source_url(row: dict[str, Any]) -> str | None:
    checked_urls = clean(row.get("checked_urls"))
    if checked_urls:
        return checked_urls.split(";", 1)[0]
    pages = value_from_row(row, "page_records", default=[])
    if isinstance(pages, list) and pages:
        first = pages[0]
        if isinstance(first, dict):
            return clean(first.get("final_url") or first.get("url")) or None
    return None


def raw_page_insert_sql(db: Session) -> str:
    body = ":body"
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        body = ":body"
    return f"""
        insert into raw_pages (
            id,
            company_id,
            source_id,
            url,
            final_url,
            body,
            content_type,
            status_code,
            content_hash,
            fetched_at,
            created_at
        )
        values (
            :id,
            :company_id,
            :source_id,
            :url,
            :final_url,
            {body},
            :content_type,
            :status_code,
            :content_hash,
            :fetched_at,
            :created_at
        )
    """


def observation_insert_sql() -> str:
    return """
        insert into observations (
            id,
            company_id,
            evidence_kind,
            field_name,
            value,
            source,
            source_url,
            collected_at,
            confidence,
            created_at
        )
        values (
            :id,
            :company_id,
            :evidence_kind,
            :field_name,
            :value,
            :source,
            :source_url,
            :collected_at,
            :confidence,
            :created_at
        )
    """


def json_insert_sql(db: Session, sql: str, field_name: str) -> str:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return sql.replace(f":{field_name}", f"cast(:{field_name} as jsonb)")
    return sql


def int_or_none(value: Any) -> int | None:
    text_value = clean(value)
    if not text_value:
        return None
    try:
        return int(float(text_value))
    except ValueError:
        return None


def clean(value: Any) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
