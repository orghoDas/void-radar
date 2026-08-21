"""Split ats-board-detector output into ingestable rows and a review queue.

The detector harvests board URLs from ``a[href]``, ``iframe[src]`` and
``script[src]``. Two things go wrong at scale:

1. Embed widgets yield tokens that are file or path fragments (``js``,
   ``embed``) rather than a company board slug.
2. A board reached through an outbound link can belong to a VC, parent, or
   partner. ``clickhouse.com`` linking to Langfuse's board is not ClickHouse's
   board, and ingesting it would attribute another company's roles.

A rebrand and a third-party board look identical from the token alone, so
mismatches are quarantined for a human rather than dropped.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RESERVED_BOARD_TOKENS = {
    "js", "css", "json", "api", "embed", "embeds", "widget", "widgets",
    "static", "assets", "cdn", "img", "images", "fonts", "script", "scripts",
    "style", "styles", "dist", "build", "public", "favicon", "robots",
}
ASSET_EXTENSION_PATTERN = re.compile(
    r"\.(js|mjs|css|json|map|png|jpe?g|svg|gif|ico|woff2?|txt|xml)$", re.IGNORECASE
)
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def is_valid_board_token(token: str | None) -> bool:
    if not token or len(token) < 2:
        return False
    if ASSET_EXTENSION_PATTERN.search(token):
        return False
    if token in RESERVED_BOARD_TOKENS:
        return False
    return bool(SLUG_PATTERN.match(token))


def token_matches_domain(token: str | None, domain: str | None) -> bool:
    slug = re.sub(r"[^a-z0-9]", "", (token or "").lower())
    host = re.sub(r"[^a-z0-9]", "", (domain or "").split(".")[0].lower())
    if not slug or not host:
        return False
    return slug in host or host in slug or slug[:5] == host[:5]


def classify(record: dict) -> tuple[str, str]:
    """Return ``(bucket, reason)`` where bucket is keep, quarantine, or miss."""
    if record.get("record_type") == "miss":
        return "miss", "no_board_found"

    if record.get("ats_provider") == "generic":
        return "keep", "generic_careers_page"

    token = (record.get("board_token") or "").lower()
    if not is_valid_board_token(token):
        return "quarantine", "invalid_board_token"

    if not token_matches_domain(token, record.get("domain")):
        # Could be a rebrand or a VC/partner board; a human has to decide.
        return "quarantine", "board_token_does_not_match_domain"

    return "keep", "token_matches_domain"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", type=Path, help="actor dataset directory")
    parser.add_argument("--keep", required=True, type=Path)
    parser.add_argument("--misses", required=True, type=Path)
    parser.add_argument("--quarantine", required=True, type=Path)
    args = parser.parse_args()

    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(args.dataset_dir.glob("*.json"))
    ]

    buckets: dict[str, list[dict]] = {"keep": [], "miss": [], "quarantine": []}
    reasons: dict[str, int] = {}
    for record in records:
        bucket, reason = classify(record)
        reasons[reason] = reasons.get(reason, 0) + 1
        if bucket == "quarantine":
            record = {**record, "quarantine_reason": reason}
        else:
            record = {key: value for key, value in record.items() if key != "record_type"}
        buckets[bucket].append(record)

    for path, rows in (
        (args.keep, buckets["keep"]),
        (args.misses, buckets["miss"]),
        (args.quarantine, buckets["quarantine"]),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print(f"records: {len(records)}")
    for bucket in ("keep", "miss", "quarantine"):
        print(f"  {bucket}: {len(buckets[bucket])}")
    print("reasons:")
    for reason, count in sorted(reasons.items(), key=lambda item: -item[1]):
        print(f"  {reason}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
