"""Generate and validate a deterministic careers-page parser (Phase 8).

Greenhouse, Lever, Ashby and Workable expose public APIs, so they need no model.
Generic careers pages are where deterministic extraction fails, and they are
re-crawled on a cadence, so paying a model once per layout and replaying the
selectors is the whole point of this phase.

The model proposes selectors; this script replays them against the sampled
pages and only persists an active parser above the success threshold.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx
from app.services.llm_client import LlmError, OpenRouterClient
from app.services.parser_generation import (
    DEFAULT_SUCCESS_THRESHOLD,
    PageSample,
    generate_and_validate,
    load_active_parser,
    validate_selectors,
)

# A careers page is only "repeated" across re-crawls of the same domain, so the
# per-domain parser validates against its single page. A page that yields just
# one job is usually a false positive (a nav link, a "no openings" notice), so
# require two before trusting the selectors.
PER_DOMAIN_MIN_SAMPLE_SIZE = 1
PER_DOMAIN_MIN_JOBS = 2
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

SAMPLE_QUERY = text(
    """
    select b.domain, coalesce(b.careers_url, b.board_url) as url
    from ats_boards b
    where b.ats_provider = 'generic'
      and coalesce(b.careers_url, b.board_url) is not null
    order by b.last_detected_at desc
    limit :limit
    """
)

# Boards the deterministic enricher already handles need no model call. The ones
# that returned nothing are where a generated parser actually buys something.
MISSING_JOBS_QUERY = text(
    """
    select b.domain, coalesce(b.careers_url, b.board_url) as url
    from ats_boards b
    where b.ats_provider = 'generic'
      and coalesce(b.careers_url, b.board_url) is not null
      and not exists (
        select 1 from job_postings j where j.company_id = b.company_id
      )
    order by b.last_detected_at desc
    limit :limit
    """
)

USER_AGENT = "void-radar-parser-generator/0.1 (+https://github.com/orghoDas/void-radar)"


def fetch_samples(urls: list[tuple[str, str]], timeout: float) -> list[PageSample]:
    samples: list[PageSample] = []
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for domain, url in urls:
            try:
                response = client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as error:
                print(f"  skip {domain}: {error}", file=sys.stderr)
                continue
            samples.append(PageSample(url=str(response.url), html=response.text))
            print(f"  fetched {domain} ({len(response.text)} bytes)")
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-key", default="careers_page")
    parser.add_argument("--schema-version", default="v1")
    parser.add_argument("--sample-size", type=int, default=8)
    parser.add_argument(
        "--only-missing-jobs",
        action="store_true",
        help="Target only generic boards that produced no jobs deterministically.",
    )
    parser.add_argument("--threshold", type=float, default=DEFAULT_SUCCESS_THRESHOLD)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--revalidate",
        action="store_true",
        help="Replay the stored active parser against fresh samples; no model call.",
    )
    parser.add_argument(
        "--per-domain",
        action="store_true",
        help=(
            "Generate one parser per careers page, keyed careers_page:<domain>. "
            "Careers pages do not share a layout across companies; the reusable "
            "structure is the same domain re-crawled on a cadence."
        ),
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    engine = create_engine(database_url)
    session = sessionmaker(bind=engine)()

    query = MISSING_JOBS_QUERY if args.only_missing_jobs else SAMPLE_QUERY
    rows = session.execute(query, {"limit": args.sample_size}).all()
    if not rows:
        print("no generic careers boards found; run the ATS detector first", file=sys.stderr)
        return 1

    print(f"sampling {len(rows)} generic careers pages")
    samples = fetch_samples([(row.domain, row.url) for row in rows], args.timeout)
    if not samples:
        print("no pages could be fetched", file=sys.stderr)
        return 1

    if args.revalidate:
        selectors = load_active_parser(session, args.source_key)
        if selectors is None:
            print(f"no active parser for source_key={args.source_key}", file=sys.stderr)
            return 1
        validation = validate_selectors(selectors, samples)
        print(json.dumps({
            "source_key": args.source_key,
            "success_rate": round(validation.success_rate, 4),
            "sample_size": validation.sample_size,
            "pages_succeeded": validation.pages_succeeded,
            "meets_threshold": validation.meets_threshold(args.threshold),
        }, indent=2))
        return 0

    try:
        client = OpenRouterClient.from_settings()
    except LlmError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"generating selectors with {client.model}")

    if args.per_domain:
        active = 0
        for sample in samples:
            host = httpx.URL(sample.url).host or sample.url
            source_key = f"{args.source_key}:{host}"
            try:
                result = generate_and_validate(
                    session, client,
                    source_key=source_key,
                    schema_version=args.schema_version,
                    samples=[sample],
                    threshold=args.threshold,
                    min_sample_size=PER_DOMAIN_MIN_SAMPLE_SIZE,
                    min_jobs_per_page=PER_DOMAIN_MIN_JOBS,
                )
            except LlmError as error:
                print(f"  {host}: rejected - {error}", file=sys.stderr)
                continue
            active += result["status"] == "active"
            jobs = result["page_results"][0]["jobs_found"]
            print(f"  {host}: {result['status']} ({jobs} jobs)")
        print(f"\nactive parsers: {active}/{len(samples)}")
        return 0

    try:
        result = generate_and_validate(
            session,
            client,
            source_key=args.source_key,
            schema_version=args.schema_version,
            samples=samples,
            threshold=args.threshold,
        )
    except LlmError as error:
        print(f"model output rejected: {error}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    if result["status"] != "active":
        print(
            "\nparser stored as failed: success rate below threshold, "
            "so it will not be used for extraction",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
