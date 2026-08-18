#!/usr/bin/env python3
"""Normalize and link YC source records into canonical companies."""

from __future__ import annotations

import argparse
import json

from app.db.session import get_session_factory
from app.services.identity_resolution import process_yc_source_records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of YC source records to process.",
    )
    args = parser.parse_args()

    session_factory = get_session_factory()
    db = session_factory()
    try:
        summary = process_yc_source_records(db, limit=args.limit)
    finally:
        db.close()

    print(
        json.dumps(
            {
                "source": summary.source,
                "scanned": summary.scanned,
                "companies_created": summary.companies_created,
                "companies_matched": summary.companies_matched,
                "aliases_created": summary.aliases_created,
                "source_identities_created": summary.source_identities_created,
                "founders_created": summary.founders_created,
                "founder_links_created": summary.founder_links_created,
                "founder_profiles_created": summary.founder_profiles_created,
                "review_items_created": summary.review_items_created,
                "skipped_already_linked": summary.skipped_already_linked,
            },
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
