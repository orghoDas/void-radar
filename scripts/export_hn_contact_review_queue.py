"""Build a manual review queue from contacts companies published themselves.

Hacker News "Who is Hiring" posters routinely include the address they want
applicants to use. That address is public, self-published, and tied to a
specific hiring need, which makes it the strongest provider-free contact
evidence available. Rows are emitted for human approval only: nothing here is
treated as verified until a reviewer sets ``review_status``.

Output matches ``scripts/build_phase6_manual_review_queue.py`` so the existing
``scripts/ingest_reviewed_apify_contacts.py`` importer can consume it.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

REVIEW_QUEUE_FIELDS = [
    "review_status", "suggested_decision", "candidate_quality", "priority_rank",
    "review_notes", "company", "company_domain", "full_name", "role", "email",
    "source_url", "source_excerpt", "reason_to_write", "evidence_urls", "score",
    "candidate_type", "is_generic_email", "is_company_domain_email",
    "has_name_evidence", "has_role_evidence", "confidence", "provider_name",
    "extraction", "record_type", "company_id",
]

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
GLUED_TLD_PATTERN = re.compile(r"^(?P<host>.+\.(?:com|org|net|io|ai|dev|co))(?P<extra>[a-z]{2,10})$")
VALID_TLDS = {
    "ai", "app", "at", "bot", "co", "com", "dev", "earth", "law", "run", "fr",
    "fyi", "io", "net", "no", "org", "space", "xyz", "foundation", "uk", "us",
    "care", "health", "tech", "cloud", "so", "sh", "me", "info", "biz",
}
# Addresses that are still a legitimate published hiring contact, but not a person.
GENERIC_LOCAL_PARTS = {
    "jobs", "careers", "hiring", "recruiting", "enghiring", "hello", "info",
    "contact", "team", "hr", "talent", "apply", "work", "hn", "hackernewshiring",
}
# Free-mail and aggregator hosts are never a company contact.
BLOCKED_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "protonmail.com", "example.com", "sentry.io", "github.com",
}


def repair_domain(host: str) -> str:
    if host.split(".")[-1] in VALID_TLDS:
        return host
    match = GLUED_TLD_PATTERN.match(host)
    return match.group("host") if match else host


def normalize_email(email: str) -> str | None:
    email = email.strip().lower().rstrip(".,;:)")
    if email.count("@") != 1:
        return None
    local, _, host = email.partition("@")
    host = repair_domain(host)
    if host.split(".")[-1] not in VALID_TLDS or host in BLOCKED_EMAIL_DOMAINS:
        return None
    # A local part that is empty once plus-addressing is stripped ("+hn@x.com")
    # is a capture artifact from surrounding text, not a real mailbox.
    if not local or not local.split("+", 1)[0]:
        return None
    if not re.match(r"^[a-z0-9][a-z0-9._%+-]*$", local):
        return None
    return f"{local}@{host}"


def base_local_part(email: str) -> str:
    """Strip plus-addressing so ``jeff+hn@x.com`` reads as ``jeff``."""
    return email.split("@", 1)[0].split("+", 1)[0]


QUERY = text(
    """
    with latest_score as (
        select distinct on (company_id) company_id, total_score, positive_reasons
        from scores order by company_id, calculated_at desc
    ),
    trigger_signal as (
        select distinct on (company_id) company_id, description, source_url, signal_type
        from signals
        where signal_type in (
            'STALE_ENGINEERING_ROLE', 'AGING_ENGINEERING_ROLE', 'HIRING_SPIKE',
            'TECH_STACK_NEED', 'OPERATIONS_SOFTWARE_NEED'
        )
        order by company_id,
            case signal_type
                when 'STALE_ENGINEERING_ROLE' then 1
                when 'AGING_ENGINEERING_ROLE' then 2
                when 'HIRING_SPIKE' then 3
                else 4
            end,
            confidence desc
    )
    select c.id::text as company_id, c.canonical_name as company,
           c.canonical_domain as domain, sr.raw_payload::text as body,
           sr.source_url as hn_url,
           coalesce(ls.total_score, 0) as score,
           ts.description as trigger_description,
           ts.source_url as trigger_url,
           ts.signal_type as trigger_type
    from source_records sr
    join sources s on s.id = sr.source_id
    join companies c on c.id = sr.company_id
    left join latest_score ls on ls.company_id = c.id
    left join trigger_signal ts on ts.company_id = c.id
    where s.source_key = 'hacker_news_who_is_hiring'
    """
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--min-score", type=int, default=0)
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = connection.execute(QUERY).mappings().all()

    queue: list[dict[str, object]] = []
    seen: set[str] = set()

    for row in rows:
        if row["score"] < args.min_score:
            continue

        company_domain = repair_domain(row["domain"] or "") or None
        for raw_email in EMAIL_PATTERN.findall(row["body"] or ""):
            email = normalize_email(raw_email)
            if not email or email in seen:
                continue
            seen.add(email)

            local = base_local_part(email)
            email_domain = email.split("@", 1)[1]
            is_generic = local in GENERIC_LOCAL_PARTS
            same_domain = bool(company_domain) and email_domain == company_domain

            if row["trigger_description"]:
                reason = row["trigger_description"]
                evidence = row["trigger_url"] or row["hn_url"]
            else:
                reason = f"{row['company']} published this address in Ask HN: Who is hiring?"
                evidence = row["hn_url"]

            queue.append({
                "review_status": "",
                # Personal address on the company's own domain is the strongest row.
                "suggested_decision": "approve" if (same_domain and not is_generic) else "review",
                "candidate_quality": "personal_company_domain" if (same_domain and not is_generic)
                    else "generic_company_domain" if same_domain
                    else "off_domain",
                "priority_rank": row["score"],
                "review_notes": "" if same_domain else f"email domain {email_domain} != company domain {company_domain}",
                "company": row["company"],
                "company_domain": company_domain,
                "full_name": "",
                "role": "",
                "email": email,
                "source_url": row["hn_url"],
                "source_excerpt": "Self-published hiring contact in Ask HN: Who is hiring?",
                "reason_to_write": reason,
                "evidence_urls": evidence,
                "score": row["score"],
                "candidate_type": "self_published_hiring_contact",
                "is_generic_email": is_generic,
                "is_company_domain_email": same_domain,
                "has_name_evidence": False,
                "has_role_evidence": bool(row["trigger_type"]),
                "confidence": 0.9 if same_domain and not is_generic else 0.7,
                "provider_name": "hn_self_published",
                "extraction": "regex_email_from_hn_comment",
                "record_type": "contact_candidate",
                "company_id": row["company_id"],
            })

    queue.sort(key=lambda item: (-int(item["priority_rank"] or 0), str(item["email"])))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_QUEUE_FIELDS)
        writer.writeheader()
        writer.writerows(queue)

    approve = sum(1 for item in queue if item["suggested_decision"] == "approve")
    print(f"queue rows: {len(queue)}")
    print(f"  suggested approve (personal, company domain): {approve}")
    print(f"  needs review: {len(queue) - approve}")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
