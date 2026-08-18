#!/usr/bin/env python3
"""Parse and post Entrepreneurs First portfolio records to the backend."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.probe_accelerator_sources import ProbeRecord, parse_entrepreneur_first

DEFAULT_ENDPOINT = "http://localhost:8000/ingestion/entrepreneur-first/source-records"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "portfolio_html",
        type=Path,
        help="Saved Entrepreneurs First portfolio HTML file.",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"Backend ingestion endpoint. Default: {DEFAULT_ENDPOINT}",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Records per POST request.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print normalized records instead of posting them.",
    )
    args = parser.parse_args()

    records = read_entrepreneur_first_records(args.portfolio_html)
    if not records:
        print("No records found.", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps({"records": records}, indent=2, sort_keys=True))
        return 0

    totals = {"received": 0, "inserted": 0, "updated": 0, "duplicates": 0}
    for batch in chunked(records, args.batch_size):
        result = post_batch(args.endpoint, batch)
        for key in totals:
            totals[key] += int(result.get(key, 0))

    print(json.dumps(totals, indent=2, sort_keys=True))
    return 0


def read_entrepreneur_first_records(portfolio_html: Path) -> list[dict]:
    if not portfolio_html.is_file():
        raise FileNotFoundError(f"Portfolio HTML not found: {portfolio_html}")

    html = portfolio_html.read_text(encoding="utf-8", errors="replace")
    return [
        entrepreneur_first_record_to_payload(record)
        for record in parse_entrepreneur_first(html)
    ]


def entrepreneur_first_record_to_payload(record: ProbeRecord) -> dict:
    founded_year = record.year_or_stage
    tags = [
        value.strip()
        for value in (record.industry or "").split(",")
        if value.strip()
    ]

    return {
        "source": "entrepreneur_first",
        "source_url": record.source_url or "https://www.joinef.com/portfolio/",
        "source_company_id": record.source_record_id or record.company_name,
        "company_name": record.company_name,
        "website": record.website,
        "location": record.location,
        "industry": record.industry,
        "batch": None,
        "stage": None,
        "status": None,
        "employee_count": None,
        "description": record.description,
        "tags": tags,
        "founders": [
            {
                "name": person.name,
                "role": person.role,
                "linkedin_url": person.linkedin_url,
                "profile_url": None,
                "x_url": None,
                "bio": None,
                "email": None,
            }
            for person in record.people
            if person.name
        ],
        "founded_year": founded_year,
        "raw_source_payload": {
            "portfolio_source": "https://www.joinef.com/portfolio/",
            "source_record_id": record.source_record_id,
            "source_url": record.source_url,
            "founded_year": founded_year,
        },
    }


def post_batch(endpoint: str, records: list[dict]) -> dict:
    body = json.dumps({"records": records}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8")
        raise RuntimeError(f"Ingestion failed with {error.code}: {detail}") from error


def chunked(records: list[dict], size: int) -> list[list[dict]]:
    return [records[index : index + size] for index in range(0, len(records), size)]


if __name__ == "__main__":
    raise SystemExit(main())
