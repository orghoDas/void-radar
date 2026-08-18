#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urljoin

from app.db.session import get_session_factory
from app.schemas.contact_enrichment import ContactEvidenceRecord
from app.services.contact_enrichment import (
    extract_emails_from_text,
    ingest_contact_evidence,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_PATHS = (
    "/",
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/team",
    "/company/about-us",
)
DEFAULT_USER_AGENT = "VoidRadarContactCollector/0.1 (+https://www.voidstudio.tech/)"
MAX_RESPONSE_BYTES = 1_000_000
GENERIC_EMAIL_LOCAL_PARTS = {
    "admin",
    "billing",
    "careers",
    "contact",
    "hello",
    "help",
    "hi",
    "hr",
    "info",
    "jobs",
    "legal",
    "marketing",
    "media",
    "press",
    "privacy",
    "sales",
    "security",
    "support",
    "team",
}


class UrlOpener(Protocol):
    def __call__(
        self,
        request: urllib.request.Request,
        timeout: float,
    ) -> object:
        ...


@dataclass(frozen=True)
class CompanyTarget:
    id: str
    canonical_name: str
    canonical_domain: str


@dataclass(frozen=True)
class PageFetchResult:
    url: str
    status: int | None
    content_type: str | None
    content: str | None
    error: str | None = None


@dataclass
class WebsiteEnrichmentSummary:
    companies_scanned: int = 0
    pages_attempted: int = 0
    pages_fetched: int = 0
    emails_found: int = 0
    contact_records_prepared: int = 0
    contacts_created: int = 0
    contacts_updated: int = 0
    evidence_created: int = 0
    duplicates: int = 0
    rejected: int = 0
    dry_run_records: list[dict[str, str]] = field(default_factory=list)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect explicit public emails from company websites."
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--include-with-contacts", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-generic", action="store_true")
    parser.add_argument("--include-external-emails", action="store_true")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--delay-seconds", type=float, default=1)
    parser.add_argument(
        "--paths",
        default=",".join(DEFAULT_PATHS),
        help="Comma-separated URL paths to check on each domain.",
    )
    args = parser.parse_args()

    session_factory = get_session_factory()
    with session_factory() as db:
        summary = enrich_contacts_from_websites(
            db,
            limit=args.limit,
            include_with_contacts=args.include_with_contacts,
            dry_run=args.dry_run,
            timeout=args.timeout,
            delay_seconds=args.delay_seconds,
            paths=tuple(path.strip() for path in args.paths.split(",") if path.strip()),
            include_generic=args.include_generic,
            include_external_emails=args.include_external_emails,
        )

    print(json.dumps(summary_to_dict(summary), indent=2, sort_keys=True))


def enrich_contacts_from_websites(
    db: Session,
    *,
    limit: int,
    include_with_contacts: bool = False,
    dry_run: bool = False,
    timeout: float = 10,
    delay_seconds: float = 1,
    paths: tuple[str, ...] = DEFAULT_PATHS,
    include_generic: bool = False,
    include_external_emails: bool = False,
    opener: UrlOpener = urllib.request.urlopen,
) -> WebsiteEnrichmentSummary:
    targets = load_company_targets(
        db,
        limit=limit,
        include_with_contacts=include_with_contacts,
    )
    summary = WebsiteEnrichmentSummary(companies_scanned=len(targets))

    for company in targets:
        records = collect_company_contact_records(
            company,
            paths=paths,
            timeout=timeout,
            opener=opener,
            summary=summary,
            include_generic=include_generic,
            include_external_emails=include_external_emails,
        )
        summary.contact_records_prepared += len(records)

        if dry_run:
            summary.dry_run_records.extend(
                {
                    "company": company.canonical_name,
                    "domain": company.canonical_domain,
                    "email": record.email,
                    "source_url": str(record.source_url),
                }
                for record in records
            )
        elif records:
            ingest_summary = ingest_contact_evidence(db, records)
            summary.contacts_created += ingest_summary.contacts_created
            summary.contacts_updated += ingest_summary.contacts_updated
            summary.evidence_created += ingest_summary.evidence_created
            summary.duplicates += ingest_summary.duplicates
            summary.rejected += ingest_summary.rejected

        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return summary


def load_company_targets(
    db: Session,
    *,
    limit: int,
    include_with_contacts: bool,
) -> list[CompanyTarget]:
    contact_filter = ""
    if not include_with_contacts:
        contact_filter = """
            and not exists (
                select 1
                from contacts ct
                where ct.company_id = c.id
            )
        """

    rows = db.execute(
        text(
            f"""
            select
                c.id,
                c.canonical_name,
                c.canonical_domain
            from companies c
            where c.canonical_domain is not null
              and c.canonical_domain <> ''
              {contact_filter}
            order by c.canonical_name
            limit :limit
            """
        ),
        {"limit": limit},
    ).all()

    return [
        CompanyTarget(
            id=str(row.id),
            canonical_name=row.canonical_name,
            canonical_domain=row.canonical_domain,
        )
        for row in rows
    ]


def collect_company_contact_records(
    company: CompanyTarget,
    *,
    paths: tuple[str, ...],
    timeout: float,
    opener: UrlOpener,
    summary: WebsiteEnrichmentSummary,
    include_generic: bool = False,
    include_external_emails: bool = False,
) -> list[ContactEvidenceRecord]:
    records_by_email_source: dict[tuple[str, str], ContactEvidenceRecord] = {}

    for url in company_urls(company.canonical_domain, paths):
        summary.pages_attempted += 1
        page = fetch_public_page(url, timeout=timeout, opener=opener)
        if not page.content:
            continue

        summary.pages_fetched += 1
        emails = extract_emails_from_text(page.content)
        summary.emails_found += len(emails)

        for email in emails:
            if not should_keep_email(
                email,
                company_domain=company.canonical_domain,
                include_generic=include_generic,
                include_external_emails=include_external_emails,
            ):
                continue
            key = (email, page.url)
            records_by_email_source[key] = ContactEvidenceRecord(
                company_id=company.id,
                company_domain=company.canonical_domain,
                email=email,
                source_type="company_website",
                source_url=page.url,
                raw_evidence={
                    "collector": "website_public_email",
                    "company_name": company.canonical_name,
                    "content_type": page.content_type,
                    "http_status": page.status,
                },
            )

    return list(records_by_email_source.values())


def should_keep_email(
    email: str,
    *,
    company_domain: str,
    include_generic: bool,
    include_external_emails: bool,
) -> bool:
    local_part, _, email_domain = email.lower().partition("@")
    if not include_external_emails and email_domain != company_domain.lower():
        return False
    return include_generic or local_part not in GENERIC_EMAIL_LOCAL_PARTS


def company_urls(domain: str, paths: tuple[str, ...]) -> list[str]:
    base_url = f"https://{domain.strip('/')}/"
    return [urljoin(base_url, normalized_path(path)) for path in paths]


def normalized_path(path: str) -> str:
    if path == "/":
        return path
    return path if path.startswith("/") else f"/{path}"


def fetch_public_page(
    url: str,
    *,
    timeout: float,
    opener: UrlOpener,
) -> PageFetchResult:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html, text/plain;q=0.9, */*;q=0.1",
        },
        method="GET",
    )

    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            headers = getattr(response, "headers", {})
            content_type = headers.get("content-type", "")
            if content_type and not is_textual_content_type(content_type):
                return PageFetchResult(
                    url=url,
                    status=status,
                    content_type=content_type,
                    content=None,
                    error="non_textual_content_type",
                )

            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                body = body[:MAX_RESPONSE_BYTES]
            return PageFetchResult(
                url=getattr(response, "url", url),
                status=status,
                content_type=content_type or None,
                content=body.decode("utf-8", errors="ignore"),
            )
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError, OSError) as error:
        return PageFetchResult(
            url=url,
            status=getattr(error, "code", None),
            content_type=None,
            content=None,
            error=type(error).__name__,
        )


def is_textual_content_type(content_type: str) -> bool:
    lowered = content_type.lower()
    return any(
        content_kind in lowered
        for content_kind in ("text/html", "text/plain", "application/xhtml+xml")
    )


def summary_to_dict(summary: WebsiteEnrichmentSummary) -> dict:
    return {
        "companies_scanned": summary.companies_scanned,
        "pages_attempted": summary.pages_attempted,
        "pages_fetched": summary.pages_fetched,
        "emails_found": summary.emails_found,
        "contact_records_prepared": summary.contact_records_prepared,
        "contacts_created": summary.contacts_created,
        "contacts_updated": summary.contacts_updated,
        "evidence_created": summary.evidence_created,
        "duplicates": summary.duplicates,
        "rejected": summary.rejected,
        "dry_run_records": summary.dry_run_records,
    }


if __name__ == "__main__":
    main()
