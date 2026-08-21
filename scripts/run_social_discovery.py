"""Run LinkedIn or X discovery through Apify Store actors and ingest results.

Store actors are third-party data products: their vendor operates the
collection, we pay per result, and their output is treated as untrusted input.
Normalisation and validation run before anything is posted for ingestion.

Actors are pay-per-event, so `--dry-run` shows what would be spent and run
without starting anything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from app.services.apify_runner import ApifyError, ApifyRunner
from app.services.social_discovery import (
    normalize_linkedin_companies,
    normalize_x_posts,
)

# Defaults point at established Store actors; override with --actor.
DEFAULT_ACTORS = {
    "linkedin": "harvestapi/linkedin-company-search",
    "x": "apidojo/tweet-scraper",
}

INGEST_URL = "http://127.0.0.1:8077/ingestion/discovery/source-records"

SOURCE_META = {
    "linkedin": ("linkedin_apify", "LinkedIn via Apify", "https://www.linkedin.com/"),
    "x": ("x_apify", "X via Apify", "https://x.com/"),
}


def post_records(source: str, records: list[dict]) -> dict:
    key, name, base = SOURCE_META[source]
    body = {
        "source": key, "source_name": name,
        "source_type": "social_discovery", "base_url": base,
        "records": records,
    }
    request = urllib.request.Request(
        INGEST_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        return {"ERROR": error.code, "body": error.read().decode()[:600]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("network", choices=["linkedin", "x"])
    parser.add_argument("--actor", help="Override the Store actor id.")
    parser.add_argument("--query", required=True, help="Search terms for the actor.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--allow-technical", action="store_true",
        help="Keep software companies too; off by default under the revised thesis.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    actor_id = args.actor or DEFAULT_ACTORS[args.network]

    if args.network == "linkedin":
        payload = {"searchQuery": args.query, "maxItems": args.limit}
    else:
        payload = {"searchTerms": [args.query], "maxItems": args.limit}

    if args.dry_run:
        print(f"would run {actor_id}")
        print(f"payload: {json.dumps(payload)}")
        print(f"cost: pay-per-event, up to {args.limit} results")
        return 0

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is required for ingestion", file=sys.stderr)
        return 2

    try:
        runner = ApifyRunner.from_settings()
        print(f"running {actor_id} (this can take several minutes)")
        items = runner.run_and_collect(actor_id, payload, limit=args.limit)
    except ApifyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"raw items returned: {len(items)}")
    if args.network == "linkedin":
        result = normalize_linkedin_companies(
            items, require_non_technical=not args.allow_technical
        )
    else:
        result = normalize_x_posts(items)

    print(f"usable records: {len(result.records)}")
    for reason, count in sorted(result.rejected.items(), key=lambda kv: -kv[1]):
        print(f"  rejected {reason}: {count}")

    if not result.records:
        print("nothing to ingest")
        return 0

    print(json.dumps(post_records(args.network, result.records), indent=2)[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
