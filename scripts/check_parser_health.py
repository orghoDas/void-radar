"""Flag generated parsers whose success rate has decayed (Phase 3).

Regeneration is triggered by measurement, not by schedule. Each parser records
a success rate; when it falls below the threshold the source is marked failed
and surfaced for regeneration, which is what makes the hybrid layer self-heal
without paying a model per page.
"""

from __future__ import annotations

import argparse
import os
import sys

from app.services.parser_generation import DEFAULT_SUCCESS_THRESHOLD
from sqlalchemy import create_engine, text

HEALTH = text(
    """
    select source_key, schema_version, status, success_rate, sample_size,
           generated_at, validated_at
    from parser_versions
    where status in ('active', 'candidate')
    order by success_rate asc nulls first, generated_at asc
    """
)

RETIRE = text(
    """
    update parser_versions
    set status = 'failed',
        notes = coalesce(notes, '') || :note,
        updated_at = now()
    where source_key = :source_key and status = 'active'
    """
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=DEFAULT_SUCCESS_THRESHOLD)
    parser.add_argument(
        "--retire-degraded",
        action="store_true",
        help="Mark parsers below the threshold as failed so they stop being used.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = [dict(r) for r in connection.execute(HEALTH).mappings()]

    degraded = [
        row for row in rows
        if row["success_rate"] is None or float(row["success_rate"]) < args.threshold
    ]

    print(f"parsers tracked: {len(rows)} | threshold: {args.threshold:.0%}")
    for row in rows:
        rate = row["success_rate"]
        marker = "NEEDS REGENERATION" if row in degraded else "ok"
        rate_text = f"{float(rate):.0%}" if rate is not None else "unmeasured"
        print(f"  {row['source_key']:44} {rate_text:>10} n={row['sample_size']:<4} {marker}")

    if degraded and args.retire_degraded:
        with engine.begin() as connection:
            for row in degraded:
                connection.execute(
                    RETIRE,
                    {
                        "source_key": row["source_key"],
                        "note": f" retired below {args.threshold:.0%} threshold;",
                    },
                )
        print(f"\nretired {len(degraded)} degraded parser(s); regenerate with "
              f"scripts/generate_careers_page_parser.py")
    elif degraded:
        print(f"\n{len(degraded)} parser(s) below threshold. "
              f"Re-run with --retire-degraded to stop using them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
