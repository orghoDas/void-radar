"""Build a clean ATS probe target list from signal-backed companies.

Discovery sources that parse domains out of free text (notably
``hacker_news_who_is_hiring``) emit hosts that are not company domains:
prose fragments, link shorteners, ATS/host subdomains, and hostnames with the
following word glued onto the TLD. Probing those wastes requests and writes
junk ``NO_ATS_FOUND`` evidence, so filter before the detector runs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from app.identity.tld_data import IANA_TLDS
from sqlalchemy import create_engine, text

VALID_TLDS = IANA_TLDS

# Hosts that are never the prospect's own company domain.
NON_COMPANY_HOSTS = {
    # Job aggregators link out to hundreds of other companies' boards. Probing
    # one makes it appear to own every board it lists.
    "whoishiringjobs.com", "weworkremotely.com", "remoteok.com", "otta.com",
    "wellfound.com", "angel.co", "builtin.com", "dice.com", "indeed.com",
    "glassdoor.com", "ziprecruiter.com", "simplyhired.com", "jobs.lever.co",
    "bit.ly", "lnkd.in", "youtu.be", "youtube.com", "grnh.se",
    "arxiv.org", "techcrunch.com", "crunchbase.com", "themuse.com",
    "github.com", "github.io", "gitlab.com", "medium.com",
    "twitter.com", "x.com", "linkedin.com", "news.ycombinator.com",
    "docs.google.com", "forms.gle", "notion.so", "notion.com",
}

# Host prefixes that indicate an ATS/careers host rather than a root domain.
ATS_SUBDOMAIN_PREFIXES = ("careers.", "jobs.", "job.", "apply.", "boards.",
                          "engineering.", "share.", "go.", "app.", "secure7.")

# Third-party ATS platforms: the company is the label, not the registrable domain.
ATS_PLATFORM_SUFFIXES = ("applicantpro.com", "greenhouse.io", "lever.co",
                         "ashbyhq.com", "workable.com", "entertimeonline.com",
                         "bamboohr.com", "smartrecruiters.com", "teamtailor.com")

GLUED_TLD_PATTERN = re.compile(r"^(?P<host>.+\.(?:com|org|net|io|ai|dev|co))(?P<extra>[a-z]{2,10})$")


def repair_glued_tld(host: str) -> str:
    """Recover ``apexdp.comwe`` -> ``apexdp.com`` (parser glued the next word on).

    Only attempted when the host's own suffix is already invalid, so a genuine
    domain such as ``cockpit.at`` is never truncated.
    """
    if host.split(".")[-1] in VALID_TLDS:
        return host
    match = GLUED_TLD_PATTERN.match(host)
    if not match:
        return host
    return match.group("host")


def to_root_domain(host: str) -> str:
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    return ".".join(labels[-2:])


def classify(host: str) -> tuple[str | None, str]:
    """Return ``(probe_domain, reason)``; ``probe_domain`` is None when rejected."""
    host = host.strip().lower().strip(".")
    if not host or "." not in host:
        return None, "not_a_hostname"

    repaired = repair_glued_tld(host)
    repair_note = "repaired_glued_tld" if repaired != host else ""
    host = repaired

    if host.endswith(ATS_PLATFORM_SUFFIXES):
        return None, "ats_platform_host"

    if host in NON_COMPANY_HOSTS or to_root_domain(host) in NON_COMPANY_HOSTS:
        return None, "non_company_host"

    if host.split(".")[-1] not in VALID_TLDS:
        return None, "invalid_tld"

    if host.startswith(ATS_SUBDOMAIN_PREFIXES):
        root = to_root_domain(host)
        return root, "normalized_from_ats_subdomain"

    return host, repair_note or "ok"


QUERY = text(
    """
    select c.id::text as company_id, c.canonical_domain as domain, c.canonical_name as name
    from companies c
    where c.canonical_domain is not null
      and c.canonical_domain <> ''
      and exists (
        select 1 from signals g
        where g.company_id = c.id
          and g.signal_type in ('HIRING_DISCOVERY', 'FUNDING_EVENT')
      )
    order by c.canonical_domain
    """
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="actor input JSON path")
    parser.add_argument("--rejects", help="optional rejected-domain report path")
    # 0 means "however many targets we built", so a growing company set is never
    # silently truncated by a stale default. 1000 is the actor's schema maximum.
    parser.add_argument("--max-items", type=int, default=0)
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = connection.execute(QUERY).mappings().all()

    companies: list[dict[str, str]] = []
    rejects: list[dict[str, str]] = []
    seen: set[str] = set()

    for row in rows:
        probe_domain, reason = classify(row["domain"])
        if probe_domain is None:
            rejects.append({"domain": row["domain"], "name": row["name"], "reason": reason})
            continue
        if probe_domain in seen:
            rejects.append({"domain": row["domain"], "name": row["name"], "reason": "duplicate_after_normalization"})
            continue
        seen.add(probe_domain)
        companies.append({"company_id": row["company_id"], "domain": probe_domain})

    max_items = args.max_items or min(len(companies), 1000)
    if len(companies) > max_items:
        print(f"warning: {len(companies)} targets but maxItems={max_items}", file=sys.stderr)

    payload = {
        "companies": companies,
        "maxItems": max_items,
        "requestDelayMs": 400,
        "requestTimeoutMs": 10000,
        "includeGenericCareers": True,
        "emitMissesToDataset": True,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    if args.rejects:
        with open(args.rejects, "w", encoding="utf-8") as handle:
            json.dump(rejects, handle, indent=2)

    print(f"probe targets: {len(companies)}")
    print(f"rejected: {len(rejects)}")
    for reason in sorted({item['reason'] for item in rejects}):
        count = sum(1 for item in rejects if item["reason"] == reason)
        print(f"  {reason}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
