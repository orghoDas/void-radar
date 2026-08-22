#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from urllib.parse import urljoin

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.services.contact_capture import (
    CONTACT_PATHS,
    CapturedContact,
    extract_emails,
    extract_phones,
    extract_web_presence,
    persist_contacts,
    persist_web_presence,
)
from app.services.email_verification import check_email

USER_AGENT = "VoidRadarPhaseDContactCollector/0.1 (+https://www.voidstudio.tech/)"
MAX_RESPONSE_BYTES = 80_000


@dataclass(frozen=True)
class DatasheetCompany:
    company_id: str
    name: str
    domain: str
    score: int
    company_type: str


@dataclass
class CaptureSummary:
    companies_selected: int = 0
    companies_scanned: int = 0
    pages_attempted: int = 0
    pages_fetched: int = 0
    website_contacts_found: int = 0
    website_contacts_stored: int = 0
    procurement_contacts_found: int = 0
    procurement_contacts_stored: int = 0
    web_presence_found: int = 0
    web_presence_stored: int = 0
    fetch_errors: int = 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Populate Phase D all-contact and web-presence tables."
    )
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--include-existing", action="store_true")
    parser.add_argument(
        "--paths",
        default=",".join(CONTACT_PATHS),
        help="Comma-separated URL paths to scan.",
    )
    parser.add_argument("--domains", help="Comma-separated focused domain list.")
    args = parser.parse_args()

    session_factory = get_session_factory()
    with session_factory() as db:
        companies = load_datasheet_companies(
            db,
            min_score=args.min_score,
            limit=args.limit,
            include_existing=args.include_existing,
            domains=tuple(d.strip() for d in args.domains.split(",") if d.strip())
            if args.domains else None,
        )
        summary = capture_phase_d(
            db,
            companies=companies,
            timeout=args.timeout,
            delay=args.delay,
            paths=tuple(path.strip() for path in args.paths.split(",") if path.strip()),
        )

    print(json.dumps(asdict(summary), indent=2, sort_keys=True))
    return 0


def load_datasheet_companies(
    db: Session,
    *,
    min_score: int,
    limit: int,
    include_existing: bool,
    domains: tuple[str, ...] | None,
) -> list[DatasheetCompany]:
    params: dict[str, object] = {"min_score": min_score, "limit": limit}
    domain_filter = ""
    if domains:
        placeholders = []
        for index, domain in enumerate(domains):
            key = f"domain_{index}"
            params[key] = domain
            placeholders.append(f":{key}")
        domain_filter = f"and c.canonical_domain in ({', '.join(placeholders)})"

    existing_filter = ""
    if not include_existing:
        existing_filter = """
          and not exists (
            select 1 from company_contacts_all ca where ca.company_id = c.id
          )
          and not exists (
            select 1 from company_web_presence wp where wp.company_id = c.id
          )
        """

    rows = db.execute(
        text(
            f"""
            with latest_scores as (
              select distinct on (company_id)
                  company_id,
                  coalesce(total_score, overall_score) as score,
                  calculated_at
              from scores
              order by company_id, calculated_at desc
            )
            select
                c.id::text as company_id,
                c.canonical_name as name,
                c.canonical_domain as domain,
                ls.score,
                cc.company_type
            from companies c
            join latest_scores ls on ls.company_id = c.id
            join company_classification cc on cc.company_id = c.id
            where ls.score >= :min_score
              and cc.company_type not in ('software_vendor', 'agency')
              and c.canonical_domain is not null
              and c.canonical_domain <> ''
              {domain_filter}
              {existing_filter}
            order by ls.score desc, c.canonical_name
            limit :limit
            """
        ),
        params,
    ).mappings().all()

    return [
        DatasheetCompany(
            company_id=row["company_id"],
            name=row["name"],
            domain=row["domain"],
            score=int(row["score"]),
            company_type=row["company_type"],
        )
        for row in rows
    ]


def capture_phase_d(
    db: Session,
    *,
    companies: list[DatasheetCompany],
    timeout: float,
    delay: float,
    paths: tuple[str, ...],
) -> CaptureSummary:
    summary = CaptureSummary(companies_selected=len(companies))
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html, text/plain;q=0.9, */*;q=0.1",
        },
    ) as client:
        for company in companies:
            summary.companies_scanned += 1
            baseline_presence = [base_website_presence(company)]
            summary.web_presence_found += len(baseline_presence)
            summary.web_presence_stored += persist_web_presence(
                db, company_id=company.company_id, entries=baseline_presence
            )

            procurement_contacts = collect_procurement_contacts(db, company)
            summary.procurement_contacts_found += len(procurement_contacts)
            summary.procurement_contacts_stored += persist_contacts(
                db, company_id=company.company_id, contacts=procurement_contacts
            )

            contacts, presence, pages_attempted, pages_fetched, fetch_errors = (
                collect_website_evidence(client, company, paths=paths)
            )
            summary.pages_attempted += pages_attempted
            summary.pages_fetched += pages_fetched
            summary.fetch_errors += fetch_errors
            summary.website_contacts_found += len(contacts)
            summary.web_presence_found += len(presence)
            summary.website_contacts_stored += persist_contacts(
                db, company_id=company.company_id, contacts=contacts
            )
            summary.web_presence_stored += persist_web_presence(
                db, company_id=company.company_id, entries=presence
            )

            if delay > 0:
                time.sleep(delay)

    return summary


def collect_website_evidence(
    client: httpx.Client,
    company: DatasheetCompany,
    *,
    paths: tuple[str, ...],
) -> tuple[list[CapturedContact], list[dict[str, str]], int, int, int]:
    contacts_by_key: dict[tuple[str | None, str | None, str], CapturedContact] = {}
    presence_by_url: dict[str, dict[str, str]] = {
        f"https://{company.domain}": base_website_presence(company)
    }
    pages_attempted = 0
    pages_fetched = 0
    fetch_errors = 0

    for path in paths:
        pages_attempted += 1
        url = urljoin(f"https://{company.domain}/", path.lstrip("/"))
        try:
            with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    continue
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type and "text" not in content_type:
                    continue
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        break
                    chunks.append(chunk)
                body = b"".join(chunks).decode(
                    response.encoding or "utf-8", errors="replace"
                )
        except httpx.HTTPError:
            fetch_errors += 1
            continue
        pages_fetched += 1
        page_url = str(response.url)

        for contact in [
            *extract_emails(body, page_url=page_url, company_domain=company.domain),
            *extract_phones(body, page_url=page_url),
        ]:
            key = (contact.email, contact.phone, contact.source_url)
            contacts_by_key[key] = contact

        for entry in extract_web_presence(body, page_url=page_url):
            presence_by_url[entry["url"]] = entry

    return (
        list(contacts_by_key.values()),
        list(presence_by_url.values()),
        pages_attempted,
        pages_fetched,
        fetch_errors,
    )


def base_website_presence(company: DatasheetCompany) -> dict[str, str]:
    return {
        "url": f"https://{company.domain}",
        "presence_kind": "website",
        "title": company.name[:120],
        "discovered_from": "company.canonical_domain",
    }


def collect_procurement_contacts(
    db: Session,
    company: DatasheetCompany,
) -> list[CapturedContact]:
    rows = db.execute(
        text(
            """
            select sr.source_url, sr.raw_payload, s.source_key
            from source_records sr
            join sources s on s.id = sr.source_id
            where sr.company_id = :company_id
              and s.source_type = 'procurement_discovery'
            """
        ),
        {"company_id": company.company_id},
    ).mappings().all()

    contacts: dict[tuple[str | None, str | None, str], CapturedContact] = {}
    for row in rows:
        payload = row["raw_payload"]
        email = normalized_email(payload.get("contact_email"))
        phone = normalized_text(payload.get("contact_phone"))
        full_name = normalized_text(payload.get("contact_name"))
        if not email and not phone and not full_name:
            continue
        host = email.split("@", 1)[1] if email and "@" in email else ""
        check = check_email(email).result.value if email else "no_email"
        source_url = row["source_url"] or payload.get("source_url") or ""
        contact = CapturedContact(
            email=email,
            full_name=full_name,
            role=None,
            phone=phone,
            contact_kind="person" if full_name else ("role_inbox" if email else "unknown"),
            on_company_domain=bool(email and host == company.domain.lower()),
            deliverability=check,
            source_type="procurement_notice",
            source_url=source_url,
            raw_evidence={
                "collector": "procurement_notice_contact",
                "source": row["source_key"],
                "source_record_id": payload.get("source_record_id"),
                "contact_is_portal": payload.get("contact_is_portal"),
            },
        )
        contacts[(contact.email, contact.phone, contact.source_url)] = contact

    return list(contacts.values())


def normalized_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if "@" in value else None


def normalized_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


if __name__ == "__main__":
    raise SystemExit(main())
