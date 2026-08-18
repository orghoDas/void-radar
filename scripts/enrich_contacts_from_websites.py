#!/usr/bin/env python
from __future__ import annotations

import argparse
import html
import json
import re
import sys
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
from app.services.decision_maker_enrichment import (
    DecisionMakerCandidateRecord,
    ingest_decision_maker_candidates,
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
MAX_RESPONSE_BYTES = 250_000
READ_CHUNK_BYTES = 32_768
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
ROLE_PATTERN = re.compile(
    r"\b("
    r"co[- ]?founder|founder|founder\s*&\s*ceo|"
    r"ceo|coo|cmo|cro|cbo|cto|chief\s+[a-z ]+\s+officer|"
    r"head\s+of\s+(?:business|growth|partnerships|sales|revenue|product|marketing|operations)|"
    r"vp\s+(?:business|business development|growth|partnerships|sales|revenue|product|marketing|operations)|"
    r"vice\s+president\s+of\s+(?:business|business development|growth|partnerships|sales|revenue|product|marketing|operations)|"
    r"director\s+of\s+(?:business development|growth|partnerships|sales|revenue|product|marketing|operations)"
    r")\b",
    re.IGNORECASE,
)
PERSON_NAME_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
BLOCKED_PERSON_NAMES = {
    "Board Member",
    "Executive Team",
    "Leadership Team",
}
ORG_NAME_TERMS = {
    "Clinic",
    "Company",
    "Customer",
    "Customers",
    "Group",
    "Inc",
    "Labs",
    "Member",
    "Partners",
    "Platform",
    "Studio",
    "Team",
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
    decision_maker_candidates_found: int = 0
    decision_maker_candidates_inserted: int = 0
    decision_maker_candidate_duplicates: int = 0
    rejected: int = 0
    dry_run_records: list[dict[str, str]] = field(default_factory=list)
    dry_run_decision_makers: list[dict[str, str | None]] = field(default_factory=list)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect explicit public emails from company websites."
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--include-with-contacts", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-generic", action="store_true")
    parser.add_argument("--include-external-emails", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--domains",
        default=None,
        help="Optional comma-separated domain allowlist for focused dry-runs.",
    )
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
            verbose=args.verbose,
            domains=tuple(
                domain.strip()
                for domain in args.domains.split(",")
                if domain.strip()
            )
            if args.domains
            else None,
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
    verbose: bool = False,
    domains: tuple[str, ...] | None = None,
    opener: UrlOpener = urllib.request.urlopen,
) -> WebsiteEnrichmentSummary:
    targets = load_company_targets(
        db,
        limit=limit,
        include_with_contacts=include_with_contacts,
        domains=domains,
    )
    summary = WebsiteEnrichmentSummary(companies_scanned=len(targets))

    for company in targets:
        if verbose:
            print(
                f"Scanning {company.canonical_name} ({company.canonical_domain})",
                file=sys.stderr,
                flush=True,
            )
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
        decision_makers = collect_company_decision_makers(
            company,
            paths=paths,
            timeout=timeout,
            opener=opener,
            summary=summary,
        )
        summary.decision_maker_candidates_found += len(decision_makers)

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
            summary.dry_run_decision_makers.extend(
                {
                    "company": company.canonical_name,
                    "domain": company.canonical_domain,
                    "full_name": candidate.full_name,
                    "role": candidate.role,
                    "role_category": candidate.role_category,
                    "email": candidate.email,
                    "source_url": candidate.source_url,
                }
                for candidate in decision_makers
            )
        elif records:
            ingest_summary = ingest_contact_evidence(db, records)
            summary.contacts_created += ingest_summary.contacts_created
            summary.contacts_updated += ingest_summary.contacts_updated
            summary.evidence_created += ingest_summary.evidence_created
            summary.duplicates += ingest_summary.duplicates
            summary.rejected += ingest_summary.rejected
        if not dry_run and decision_makers:
            decision_maker_summary = ingest_decision_maker_candidates(
                db,
                decision_makers,
            )
            summary.decision_maker_candidates_inserted += (
                decision_maker_summary.inserted
            )
            summary.decision_maker_candidate_duplicates += (
                decision_maker_summary.duplicates
            )

        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return summary


def load_company_targets(
    db: Session,
    *,
    limit: int,
    include_with_contacts: bool,
    domains: tuple[str, ...] | None = None,
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

    domain_filter = ""
    params: dict[str, object] = {"limit": limit}
    if domains:
        placeholders = []
        for index, domain in enumerate(domains):
            param_name = f"domain_{index}"
            placeholders.append(f":{param_name}")
            params[param_name] = domain
        domain_filter = f"and c.canonical_domain in ({', '.join(placeholders)})"

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
              {domain_filter}
              {contact_filter}
            order by c.canonical_name
            limit :limit
            """
        ),
        params,
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


def collect_company_decision_makers(
    company: CompanyTarget,
    *,
    paths: tuple[str, ...],
    timeout: float,
    opener: UrlOpener,
    summary: WebsiteEnrichmentSummary,
) -> list[DecisionMakerCandidateRecord]:
    candidates_by_source: dict[
        tuple[str, str, str, str],
        DecisionMakerCandidateRecord,
    ] = {}

    for url in company_urls(company.canonical_domain, paths):
        page = fetch_public_page(url, timeout=timeout, opener=opener)
        if not page.content:
            continue

        lines = text_lines_from_html(page.content)
        for index, line in enumerate(lines):
            previous_line = lines[index - 1] if index > 0 else None
            candidate = decision_maker_candidate_from_line(
                company=company,
                line=line,
                previous_line=previous_line,
                source_url=page.url,
                content_type=page.content_type,
                http_status=page.status,
            )
            if not candidate:
                continue

            key = (
                candidate.full_name or "",
                candidate.role,
                candidate.email or "",
                candidate.source_url,
            )
            candidates_by_source[key] = candidate

    return list(candidates_by_source.values())


def decision_maker_candidate_from_line(
    *,
    company: CompanyTarget,
    line: str,
    previous_line: str | None = None,
    source_url: str,
    content_type: str | None,
    http_status: int | None,
) -> DecisionMakerCandidateRecord | None:
    if len(line) > 240:
        return None

    role_matches = list(ROLE_PATTERN.finditer(line))
    if not role_matches:
        return None

    role_match = role_matches[-1]
    role = normalize_role(role_match.group(1))
    full_name = extract_name_near_role(line, role_match.start())
    if not full_name and previous_line:
        full_name = extract_person_name_from_fragment(previous_line)
    if full_name and not is_likely_person_name(full_name):
        full_name = None
    email = first_company_email(line, company.canonical_domain)

    if not full_name and not email:
        return None

    return DecisionMakerCandidateRecord(
        company_id=company.id,
        full_name=full_name,
        role=role,
        role_category=role_category(role),
        email=email,
        linkedin_url=None,
        x_url=None,
        profile_url=None,
        source_type="company_website",
        source_url=source_url,
        confidence=0.65 if full_name else 0.55,
        raw_evidence={
            "collector": "website_decision_maker_role",
            "company_name": company.canonical_name,
            "line": line,
            "content_type": content_type,
            "http_status": http_status,
        },
    )


def text_lines_from_html(value: str) -> list[str]:
    text_value = HTML_TAG_RE.sub("\n", value)
    text_value = html.unescape(text_value)
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in text_value.splitlines()
        if re.sub(r"\s+", " ", line).strip()
    ]


def extract_name_near_role(line: str, role_start: int) -> str | None:
    before_role = line[:role_start].strip(" -–—,|:()[]")
    before_role = before_role[-80:]
    name = extract_person_name_from_fragment(before_role)
    if name and not looks_like_role_fragment(name):
        return name

    if role_start == 0:
        return None

    after_role = line[role_start:].strip(" -–—,|:()[]")
    name = extract_person_name_from_fragment(after_role[:80])
    if name and not looks_like_role_fragment(name):
        return name
    return None


def extract_person_name_from_fragment(fragment: str) -> str | None:
    matches = PERSON_NAME_RE.findall(fragment)
    return matches[-1] if matches else None


def is_likely_person_name(value: str) -> bool:
    if value in BLOCKED_PERSON_NAMES:
        return False
    words = value.split()
    if len(words) < 2 or len(words) > 4:
        return False
    if any(word in ORG_NAME_TERMS for word in words):
        return False
    return not looks_like_role_fragment(value)


def looks_like_role_fragment(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered in {"ceo", "coo", "cmo", "cro", "cbo", "cto"}
        or lowered.startswith(
            ("chief ", "head of ", "vp ", "vice president", "director of ")
        )
    )


def first_company_email(line: str, company_domain: str) -> str | None:
    for email in extract_emails_from_text(line):
        if should_keep_email(
            email,
            company_domain=company_domain,
            include_generic=False,
            include_external_emails=False,
        ):
            return email
    return None


def normalize_role(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip())
    upper_roles = {"ceo", "coo", "cmo", "cro", "cbo", "cto", "vp"}
    if normalized.lower() in upper_roles:
        return normalized.upper()
    return normalized.title().replace("Ceo", "CEO").replace("Cto", "CTO")


def role_category(role: str) -> str:
    lowered = role.lower()
    if "founder" in lowered:
        return "founder"
    if lowered in {"ceo", "coo", "cmo", "cro", "cbo"} or "chief" in lowered:
        return "executive"
    if "business" in lowered:
        return "business"
    if "growth" in lowered:
        return "growth"
    if "partnership" in lowered:
        return "partnerships"
    if "product" in lowered:
        return "product"
    if "marketing" in lowered:
        return "marketing"
    if "sales" in lowered or "revenue" in lowered:
        return "sales"
    if "operation" in lowered:
        return "operations"
    if lowered == "cto":
        return "technical"
    return "other"


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

            body = read_limited_response(response)
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


def read_limited_response(response) -> bytes:
    chunks: list[bytes] = []
    bytes_read = 0
    while bytes_read < MAX_RESPONSE_BYTES:
        chunk = response.read(min(READ_CHUNK_BYTES, MAX_RESPONSE_BYTES - bytes_read))
        if not chunk:
            break
        chunks.append(chunk)
        bytes_read += len(chunk)
        if len(chunk) < READ_CHUNK_BYTES:
            break
    return b"".join(chunks)


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
        "decision_maker_candidates_found": summary.decision_maker_candidates_found,
        "decision_maker_candidates_inserted": (
            summary.decision_maker_candidates_inserted
        ),
        "decision_maker_candidate_duplicates": (
            summary.decision_maker_candidate_duplicates
        ),
        "rejected": summary.rejected,
        "dry_run_records": summary.dry_run_records,
        "dry_run_decision_makers": summary.dry_run_decision_makers,
    }


if __name__ == "__main__":
    main()
