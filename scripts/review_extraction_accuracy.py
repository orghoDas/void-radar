"""Sample model extractions for manual review, and report measured accuracy.

The Phase 3 gate asks for extraction accuracy sampled against manual review.
Accuracy that is assumed rather than measured is exactly the silent-failure
mode the brief warns about, so this records a human verdict per record and
reports the rate from those verdicts only.

  --export   write a sample to CSV for a human to fill in `verdict`
  --import   read verdicts back
  --report   accuracy over reviewed records
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

VERDICTS = {"accurate", "partly_accurate", "inaccurate"}

SAMPLE = text(
    """
    select e.id::text as enrichment_id, c.canonical_domain as domain,
           e.positioning, e.business_model, e.customer_type,
           e.technology_mentions::text as technology_mentions,
           e.contact_routes::text as contact_routes,
           e.decision_makers::text as decision_makers,
           e.service_fit_evidence, e.confidence,
           e.validation_notes::text as validation_notes,
           e.source_urls::text as source_urls
    from company_enrichment e
    join companies c on c.id = e.company_id
    where e.reviewed_at is null
    order by random()
    limit :limit
    """
)

FIELDS = [
    "verdict", "notes", "enrichment_id", "domain", "positioning", "business_model",
    "customer_type", "technology_mentions", "contact_routes", "decision_makers",
    "service_fit_evidence", "confidence", "validation_notes", "source_urls",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path)
    parser.add_argument("--import-file", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    engine = create_engine(database_url)

    if args.export:
        with engine.connect() as connection:
            rows = [dict(r) for r in connection.execute(SAMPLE, {"limit": args.limit}).mappings()]
        args.export.parent.mkdir(parents=True, exist_ok=True)
        with args.export.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({**{"verdict": "", "notes": ""}, **row})
        print(f"sampled {len(rows)} records -> {args.export}")
        print(f"set `verdict` to one of: {', '.join(sorted(VERDICTS))}")

    if args.import_file:
        applied = 0
        with args.import_file.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        with engine.begin() as connection:
            for row in rows:
                verdict = (row.get("verdict") or "").strip().lower()
                if verdict not in VERDICTS:
                    continue
                connection.execute(
                    text(
                        """
                        update company_enrichment
                        set reviewed_at = now(), review_verdict = :verdict,
                            updated_at = now()
                        where id = cast(:id as uuid)
                        """
                    ),
                    {"verdict": verdict, "id": row["enrichment_id"]},
                )
                applied += 1
        print(f"applied {applied} verdicts")

    if args.report:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    select review_verdict, count(*) from company_enrichment
                    where reviewed_at is not null group by 1
                    """
                )
            ).all()
            spend = connection.execute(
                text(
                    """
                    select coalesce(sum(cost_usd), 0),
                           count(*),
                           count(distinct company_id)
                    from llm_usage where succeeded
                    """
                )
            ).first()
        reviewed = sum(count for _, count in rows)
        accurate = sum(count for verdict, count in rows if verdict == "accurate")
        print("PHASE 3 GATE")
        total_cost, calls, companies = float(spend[0]), spend[1], spend[2]
        print(f"  model spend total: ${total_cost:.4f} over {calls} calls")
        if companies:
            print(f"  spend per qualified company: ${total_cost / companies:.5f}")
        if reviewed:
            for verdict, count in sorted(rows):
                print(f"  {verdict}: {count}")
            print(f"  accuracy (accurate / reviewed): {accurate}/{reviewed} = {accurate / reviewed:.0%}")
        else:
            print("  extraction accuracy: NOT MEASURED - no records reviewed yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
