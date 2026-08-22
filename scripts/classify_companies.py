"""Classify companies as software builders or buyers (Phase C).

Runs only on companies that passed the cheap filters, which is what keeps model
spend proportional to qualified volume rather than to the whole database.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from urllib.parse import urljoin

import httpx
from app.services.company_classifier import (
    ClassificationPayload,
    ClassificationResult,
    classify_company,
    persist_classification,
)
from app.services.deep_enrichment import record_llm_usage
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
    select c.id::text as company_id, c.canonical_domain as domain,
           coalesce(l.total_score, 0) as score
    from companies c
    left join latest l on l.company_id = c.id
    where c.canonical_domain is not null
      and coalesce(l.total_score, 0) >= :min_score
      and (
        :shard_count = 1
        or mod(abs(hashtext(c.id::text)), :shard_count) = :shard_index
      )
      and not exists (
        select 1 from company_classification cc where cc.company_id = c.id
      )
    order by coalesce(l.total_score, 0) desc
    limit :limit
    """
)

PAGE_PATHS = ("", "/about", "/services")
PER_PAGE_BUDGET = 7000


def unclear_result(note: str) -> ClassificationResult:
    return ClassificationResult(
        payload=ClassificationPayload(
            company_type="unclear",
            builds_software="unknown",
            confidence=0.0,
        ),
        notes=[note],
    )


def classify_with_wall_timeout(
    client: OpenRouterClient,
    *,
    company_domain: str,
    page_text: str,
    seconds: float,
) -> ClassificationResult:
    if seconds <= 0:
        return classify_company(
            client, company_domain=company_domain, page_text=page_text
        )

    def handle_timeout(_signum: int, _frame: object) -> None:
        raise TimeoutError(f"classification exceeded {seconds:g}s wall timeout")

    previous = signal.signal(signal.SIGALRM, handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return classify_company(
            client, company_domain=company_domain, page_text=page_text
        )
    except TimeoutError as error:
        raise LlmError(str(error)) from error
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def fetch_pages(client: httpx.Client, domain: str) -> tuple[str, list[str]]:
    chunks: list[str] = []
    urls: list[str] = []
    for path in PAGE_PATHS:
        url = urljoin(f"https://{domain}", path) if path else f"https://{domain}"
        try:
            response = client.get(url)
            if response.status_code != 200:
                continue
        except httpx.HTTPError:
            continue
        chunks.append(condense_html_for_prompt(response.text, budget=PER_PAGE_BUDGET))
        urls.append(str(response.url))
    return "\n\n---\n\n".join(chunks), urls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-score", type=int, default=20)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--llm-timeout", type=float, default=90.0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    args = parser.parse_args()

    if args.shard_count < 1:
        print("--shard-count must be at least 1", file=sys.stderr)
        return 2
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        print("--shard-index must be between 0 and shard-count - 1", file=sys.stderr)
        return 2

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    try:
        llm = OpenRouterClient.from_settings()
        llm.timeout_seconds = args.llm_timeout
    except LlmError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    session = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]))()
    rows = session.execute(
        TARGETS,
        {
            "min_score": args.min_score,
            "limit": args.limit,
            "shard_count": args.shard_count,
            "shard_index": args.shard_index,
        },
    ).all()
    print(f"companies to classify: {len(rows)} (model: {llm.model})")

    counts: dict[str, int] = {}
    with httpx.Client(timeout=args.timeout, follow_redirects=True,
                      headers={"User-Agent": "void-radar/0.1"}) as http:
        for row in rows:
            page_text, urls = fetch_pages(http, row.domain)
            if not page_text:
                counts["no_pages"] = counts.get("no_pages", 0) + 1
                persist_classification(
                    session, company_id=row.company_id,
                    result=unclear_result("no accessible website pages fetched"),
                    model=llm.model, source_urls=[],
                )
                print(f"  {row.domain:34} unclear              no accessible pages")
                continue
            try:
                result = classify_with_wall_timeout(
                    llm,
                    company_domain=row.domain,
                    page_text=page_text,
                    seconds=args.llm_timeout,
                )
            except LlmError as error:
                counts["rejected"] = counts.get("rejected", 0) + 1
                record_llm_usage(
                    session, company_id=row.company_id, purpose="classification",
                    usage=llm.last_usage, succeeded=False, error=str(error)[:400],
                )
                persist_classification(
                    session, company_id=row.company_id,
                    result=unclear_result(f"classification rejected: {error}"),
                    model=llm.model, source_urls=urls,
                )
                print(f"  {row.domain}: rejected - {error}", file=sys.stderr)
                continue

            record_llm_usage(
                session, company_id=row.company_id,
                purpose="classification", usage=llm.last_usage,
            )
            persist_classification(
                session, company_id=row.company_id, result=result,
                model=llm.model, source_urls=urls,
            )
            verdict = result.payload.company_type
            counts[verdict] = counts.get(verdict, 0) + 1
            print(f"  {row.domain:34} {verdict:20} {result.payload.sector or ''}")
            time.sleep(args.delay)

    print()
    for key, value in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {key}: {value}")
    spend = session.execute(
        text("select coalesce(sum(cost_usd),0) from llm_usage where purpose='classification'")
    ).scalar()
    print(f"  spend: ${float(spend):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
