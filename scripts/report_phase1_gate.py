"""Answer the Phase 1 gate question directly.

    Which companies have had an engineering role open more than ninety days
    and no substantial in-house engineering presence?

Companies that have not yet been probed on GitHub are reported as `unknown`
rather than folded in with the clean ones. An unchecked company is not evidence
of absence, and quietly treating it as one would overstate the qualified list.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

GATE_QUERY = text(
    """
    with stale as (
        select
            s.company_id,
            max((s.raw_evidence -> 'signal' ->> 'age_days')::int) as max_age_days,
            count(*) as stale_roles,
            (array_agg(
                s.raw_evidence ->> 'title'
                order by (s.raw_evidence -> 'signal' ->> 'age_days')::int desc
            ))[1] as oldest_role,
            (array_agg(
                s.source_url
                order by (s.raw_evidence -> 'signal' ->> 'age_days')::int desc
            ))[1] as evidence_url
        from signals s
        where s.signal_type = 'STALE_ENGINEERING_ROLE'
          and (s.raw_evidence -> 'signal' ->> 'age_days')::int >= :min_days
        group by s.company_id
    ),
    github as (
        select distinct on (company_id)
            company_id, signal_type, description,
            (raw_evidence ->> 'public_repos')::int as public_repos
        from signals
        where signal_type in (
            'GITHUB_ENGINEERING_ORG_DETECTED',
            'GITHUB_ORG_SMALL_FOOTPRINT',
            'NO_GITHUB_ORG_FOUND'
        )
        order by company_id, detected_at desc
    ),
    latest_score as (
        select distinct on (company_id) company_id, fit_score, intent_score, total_score
        from scores order by company_id, calculated_at desc
    )
    select
        c.canonical_name as company,
        c.canonical_domain as domain,
        st.max_age_days,
        st.stale_roles,
        st.oldest_role,
        st.evidence_url,
        coalesce(ls.total_score, 0) as score,
        case
            when g.signal_type = 'GITHUB_ENGINEERING_ORG_DETECTED' then 'has_in_house_engineering'
            when g.signal_type is null then 'unknown_not_checked'
            else 'no_substantial_in_house_engineering'
        end as engineering_presence,
        coalesce(g.public_repos, 0) as public_repos
    from stale st
    join companies c on c.id = st.company_id
    left join github g on g.company_id = st.company_id
    left join latest_score ls on ls.company_id = st.company_id
    order by
        case
            when g.signal_type = 'GITHUB_ENGINEERING_ORG_DETECTED' then 2
            when g.signal_type is null then 1
            else 0
        end,
        coalesce(ls.total_score, 0) desc,
        st.max_age_days desc
    """
)

FIELDS = [
    "company", "domain", "engineering_presence", "max_age_days", "stale_roles",
    "oldest_role", "score", "public_repos", "evidence_url",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-days", type=int, default=90)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = [dict(r) for r in connection.execute(GATE_QUERY, {"min_days": args.min_days}).mappings()]

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["engineering_presence"]] = counts.get(row["engineering_presence"], 0) + 1

    qualified = counts.get("no_substantial_in_house_engineering", 0)
    unknown = counts.get("unknown_not_checked", 0)
    excluded = counts.get("has_in_house_engineering", 0)

    print(f"Companies with an engineering role open {args.min_days}+ days: {len(rows)}")
    print(f"  QUALIFIED  (no substantial in-house engineering): {qualified}")
    print(f"  excluded   (in-house engineering confirmed):      {excluded}")
    print(f"  unknown    (not yet probed on GitHub):            {unknown}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({k: row[k] for k in FIELDS} for row in rows)
        print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
