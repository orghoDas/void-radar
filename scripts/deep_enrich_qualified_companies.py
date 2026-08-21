"""Deep-enrich qualified companies with runtime model extraction (Phase 3).

Runs strictly after scoring. Companies that failed fit or intent are never
crawled, which is what keeps the model bill proportional to qualified volume
rather than crawl volume.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urljoin

import httpx
from app.services.deep_enrichment import (
    EXTRACTION_METHOD,
    extract_company_profile,
    persist_enrichment,
    record_llm_usage,
)
from app.services.llm_client import LlmError, OpenRouterClient
from app.services.parser_generation import condense_html_for_prompt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TARGETS = text(
    """
    with latest as (
        select distinct on (company_id) company_id, total_score
        from scores order by company_id, calculated_at desc
    )
    select c.id::text as company_id, c.canonical_domain as domain, l.total_score
    from latest l
    join companies c on c.id = l.company_id
    where l.total_score >= :min_score
      and c.canonical_domain is not null
      and not exists (
        select 1 from company_enrichment e
        where e.company_id = c.id and e.extraction_method = :method
      )
    order by l.total_score desc
    limit :limit
    """
)

PAGE_PATHS = ("", "/about", "/team", "/contact")
PER_PAGE_BUDGET = 6000


def fetch_pages(client: httpx.Client, domain: str) -> tuple[str, list[str]]:
    base = f"https://{domain}"
    chunks: list[str] = []
    fetched: list[str] = []
    for path in PAGE_PATHS:
        url = urljoin(base, path) if path else base
        try:
            response = client.get(url)
            if response.status_code != 200:
                continue
        except httpx.HTTPError:
            continue
        condensed = condense_html_for_prompt(response.text, budget=PER_PAGE_BUDGET)
        chunks.append(f"URL: {url}\n{condensed}")
        fetched.append(url)
    return "\n\n---\n\n".join(chunks), fetched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    try:
        llm = OpenRouterClient.from_settings()
    except LlmError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    engine = create_engine(database_url)
    session = sessionmaker(bind=engine)()
    rows = session.execute(
        TARGETS,
        {"min_score": args.min_score, "limit": args.limit, "method": EXTRACTION_METHOD},
    ).all()
    print(f"qualified companies to enrich: {len(rows)} (model: {llm.model})")

    enriched = 0
    with httpx.Client(timeout=20.0, follow_redirects=True,
                      headers={"User-Agent": "void-radar/0.1"}) as http:
        for row in rows:
            page_text, urls = fetch_pages(http, row.domain)
            if not page_text:
                print(f"  {row.domain}: no pages fetched", file=sys.stderr)
                continue
            try:
                validated = extract_company_profile(
                    llm, company_domain=row.domain, page_text=page_text
                )
            except LlmError as error:
                record_llm_usage(
                    session, company_id=row.company_id, purpose="deep_enrichment",
                    usage=llm.last_usage, succeeded=False, error=str(error)[:400],
                )
                print(f"  {row.domain}: rejected - {error}", file=sys.stderr)
                continue

            record_llm_usage(
                session, company_id=row.company_id,
                purpose="deep_enrichment", usage=llm.last_usage,
            )
            persist_enrichment(
                session, company_id=row.company_id, validated=validated,
                model=llm.model, source_urls=urls,
            )
            enriched += 1
            dropped = len(validated.notes)
            print(
                f"  {row.domain:30} conf={validated.confidence:.2f} "
                f"routes={len(validated.profile.contact_routes)} "
                f"people={len(validated.profile.decision_makers)} "
                f"dropped={dropped}"
            )
            time.sleep(args.delay)

    spend = session.execute(
        text("select coalesce(sum(cost_usd),0), count(*) from llm_usage where purpose='deep_enrichment'")
    ).first()
    print(f"\nenriched: {enriched} | calls: {spend[1]} | spend: ${float(spend[0]):.4f}")
    if enriched:
        print(f"spend per qualified company: ${float(spend[0]) / enriched:.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
