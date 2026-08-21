"""Probe GitHub for in-house engineering presence and record disqualifying evidence.

Phase 1's gate asks which companies have a long-open engineering role *and no
substantial in-house engineering presence*. Headcount and job counts only infer
the second half; GitHub measures it.

Runs on scored survivors first, since GitHub's unauthenticated limit is 60
requests an hour and each company costs two.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from uuid import uuid4

import httpx
from app.services.github_disqualification import (
    GITHUB_API,
    fetch_org_metrics,
    signal_for,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

STALE_TARGET_QUERY = text(
    """
    select distinct c.id::text as company_id, c.canonical_domain as domain
    from signals s
    join companies c on c.id = s.company_id
    where s.signal_type = 'STALE_ENGINEERING_ROLE'
      and (s.raw_evidence -> 'signal' ->> 'age_days')::int >= :stale_days
      and c.canonical_domain is not null
      and not exists (
        select 1 from signals g
        where g.company_id = c.id
          and g.signal_type in (
            'GITHUB_ENGINEERING_ORG_DETECTED',
            'GITHUB_ORG_SMALL_FOOTPRINT',
            'NO_GITHUB_ORG_FOUND'
          )
      )
    limit :limit
    """
)

TARGET_QUERY = text(
    """
    with latest as (
        select distinct on (company_id) company_id, total_score
        from scores order by company_id, calculated_at desc
    )
    select c.id::text as company_id, c.canonical_domain as domain
    from latest l
    join companies c on c.id = l.company_id
    where c.canonical_domain is not null
      and l.total_score >= :min_score
      and not exists (
        select 1 from signals s
        where s.company_id = c.id
          and s.signal_type in (
            'GITHUB_ENGINEERING_ORG_DETECTED',
            'GITHUB_ORG_SMALL_FOOTPRINT',
            'NO_GITHUB_ORG_FOUND'
          )
      )
    order by l.total_score desc
    limit :limit
    """
)

INSERT_SIGNAL = text(
    """
    insert into signals (
        id, company_id, signal_type, description, source, source_url,
        detected_at, confidence, raw_evidence
    ) values (
        :id, :company_id, :signal_type, :description, 'github_disqualification',
        :source_url, now(), :confidence, cast(:raw_evidence as jsonb)
    )
    """
)


def wait_for_rate_limit(client: httpx.Client, headers: dict[str, str]) -> None:
    """Block until the core quota refills rather than failing the rest of the batch."""
    try:
        response = client.get(f"{GITHUB_API}/rate_limit", headers=headers)
        core = response.json()["resources"]["core"]
    except Exception:
        return
    if int(core.get("remaining", 1)) > 2:
        return
    sleep_for = max(0, int(core.get("reset", 0)) - int(time.time())) + 5
    print(f"  rate limit reached; waiting {sleep_for}s for reset", file=sys.stderr)
    time.sleep(sleep_for)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument(
        "--stale-days",
        type=int,
        default=0,
        help="Target companies with an engineering role open this many days instead of by score.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "void-radar/0.1"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print(
            "warning: no GITHUB_TOKEN set; unauthenticated limit is 60 requests/hour "
            "(2 per company)",
            file=sys.stderr,
        )

    engine = create_engine(database_url)
    session = sessionmaker(bind=engine)()
    if args.stale_days:
        rows = session.execute(
            STALE_TARGET_QUERY, {"stale_days": args.stale_days, "limit": args.limit}
        ).all()
    else:
        rows = session.execute(
            TARGET_QUERY, {"min_score": args.min_score, "limit": args.limit}
        ).all()
    print(f"companies to probe: {len(rows)}")

    counts = {"disqualified": 0, "small": 0, "not_found": 0}
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for row in rows:
            wait_for_rate_limit(client, headers)
            try:
                metrics = fetch_org_metrics(client, row.domain, headers=headers)
            except httpx.HTTPError as error:
                print(f"  {row.domain}: fetch failed - {error}", file=sys.stderr)
                continue

            signal_type, description, confidence = signal_for(metrics)
            session.execute(
                INSERT_SIGNAL,
                {
                    "id": str(uuid4()),
                    "company_id": row.company_id,
                    "signal_type": signal_type,
                    "description": description,
                    "source_url": (
                        f"https://github.com/{metrics.login}" if metrics.login else None
                    ),
                    "confidence": confidence,
                    "raw_evidence": __import__("json").dumps(metrics.as_evidence()),
                },
            )
            session.commit()

            if signal_type == "GITHUB_ENGINEERING_ORG_DETECTED":
                counts["disqualified"] += 1
                print(f"  {row.domain:32} DISQUALIFIED ({metrics.public_repos} repos)")
            elif signal_type == "GITHUB_ORG_SMALL_FOOTPRINT":
                counts["small"] += 1
            else:
                counts["not_found"] += 1
            time.sleep(args.delay)

    print(
        f"\ndisqualified: {counts['disqualified']} | "
        f"small footprint: {counts['small']} | no org: {counts['not_found']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
