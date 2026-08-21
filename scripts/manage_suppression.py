"""Populate and inspect the suppression list.

The brief treats suppression as non-optional: checked before every send,
without exception. It is both the legal minimum and the mechanism that keeps
bounce and complaint rates below provider thresholds.

Seeds the categories that can be known before any campaign runs - own domains,
competitors, and free-mail hosts - and imports unsubscribes and bounces from a
CSV afterwards.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text

INSERT = text(
    """
    insert into suppression (id, email, domain, reason, source, added_at)
    select cast(:id as uuid), cast(:email as text), cast(:domain as text),
           :reason, :source, now()
    where not exists (
        select 1 from suppression s
        where (cast(:email as text) is not null
               and lower(coalesce(s.email, '')) = lower(cast(:email as text)))
           or (cast(:domain as text) is not null
               and lower(coalesce(s.domain, '')) = lower(cast(:domain as text)))
    )
    """
)

# Free-mail hosts are never a business prospect, and sending to them from a
# cold domain attracts complaints disproportionately.
FREE_MAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "aol.com", "protonmail.com", "proton.me", "gmx.com", "mail.com",
]

# Aggregators and platform hosts that leaked into the company set previously.
PLATFORM_DOMAINS = [
    "whoishiringjobs.com", "weworkremotely.com", "remoteok.com", "wellfound.com",
    "builtin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
]


def add(connection, *, email=None, domain=None, reason: str, source: str) -> bool:
    result = connection.execute(
        INSERT,
        {
            "id": str(uuid4()), "email": email, "domain": domain,
            "reason": reason, "source": source,
        },
    )
    return result.rowcount > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="Add known-bad categories.")
    parser.add_argument("--own-domain", action="append", default=[],
                        help="Your own domains; repeatable.")
    parser.add_argument("--import-csv", type=Path,
                        help="CSV with email and/or domain plus optional reason.")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    engine = create_engine(database_url)
    added = 0
    with engine.begin() as connection:
        if args.seed:
            for domain in FREE_MAIL_DOMAINS:
                added += add(connection, domain=domain, reason="free_mail_domain", source="seed")
            for domain in PLATFORM_DOMAINS:
                added += add(connection, domain=domain, reason="platform_or_aggregator", source="seed")
        for domain in args.own_domain:
            added += add(connection, domain=domain, reason="own_domain", source="seed")

        if args.import_csv:
            with args.import_csv.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    email = (row.get("email") or "").strip() or None
                    domain = (row.get("domain") or "").strip() or None
                    if not email and not domain:
                        continue
                    added += add(
                        connection,
                        email=email, domain=domain,
                        reason=(row.get("reason") or "manual").strip(),
                        source=str(args.import_csv),
                    )

        total = connection.execute(text("select count(*) from suppression")).scalar()
        if args.list:
            rows = connection.execute(
                text("select reason, count(*) from suppression group by 1 order by 2 desc")
            ).all()
            for reason, count in rows:
                print(f"  {reason:28} {count}")

    print(f"added: {added} | suppression total: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
