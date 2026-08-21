"""Build the ranked send-ready sheet from the contact review queue.

Ranks rows by the strength of the evidence behind them, so the reviewer works
the best prospects first rather than reading 200 rows in arbitrary order.

Nothing here marks a contact verified. Every row still needs a human to set
review_status in the queue before it can be imported and sent.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services.email_verification import check_email

OUTPUT_FIELDS = [
    "rank", "tier", "company", "domain", "email", "email_type",
    "deliverability", "score", "trigger_type", "reason_to_write", "evidence_url",
    "hn_source_url", "review_status", "company_id",
]

# A reason that only says the company posted on HN is a weak angle; every other
# agency reads the same thread. A stale or aging role is the real wedge.
GENERIC_REASON_MARKER = "published this address in Ask HN"


def trigger_type_of(reason: str) -> str:
    lowered = reason.lower()
    if "appears open for" in lowered:
        return "stale_role"
    if "relevant roles appeared" in lowered:
        return "hiring_spike"
    if "suggests internal tooling" in lowered:
        return "operations_need"
    if "mentions stack" in lowered:
        return "tech_stack_need"
    if GENERIC_REASON_MARKER in reason:
        return "hn_post_only"
    return "other"


def tier_of(row: dict[str, str], trigger: str) -> tuple[int, str]:
    """Lower sort key is better."""
    personal = row.get("is_generic_email", "").lower() == "false"
    on_domain = row.get("is_company_domain_email", "").lower() == "true"
    real_trigger = trigger not in {"hn_post_only", "other"}

    if real_trigger and personal and on_domain:
        return 0, "A_trigger_personal_ondomain"
    if real_trigger and on_domain:
        return 1, "B_trigger_generic_ondomain"
    if real_trigger:
        return 2, "C_trigger_offdomain"
    if personal and on_domain:
        return 3, "D_personal_ondomain_no_trigger"
    return 4, "E_weak"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue_path", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    with args.queue_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    # MX lookups are independent per row and dominated by network wait.
    with ThreadPoolExecutor(max_workers=16) as pool:
        checks = list(pool.map(lambda row: check_email(row.get("email", "")), rows))
    deliverability = {
        row.get("email"): check for row, check in zip(rows, checks)
    }

    enriched = []
    for row in rows:
        reason = row.get("reason_to_write", "")
        trigger = trigger_type_of(reason)
        tier_key, tier_name = tier_of(row, trigger)
        # An address whose domain cannot receive mail is a guaranteed bounce,
        # so it sorts below everything else regardless of trigger strength.
        if not deliverability[row.get("email")].sendable:
            tier_key, tier_name = 9, "Z_undeliverable"
        try:
            score = int(row.get("score") or 0)
        except ValueError:
            score = 0
        enriched.append((tier_key, -score, row, trigger, tier_name, score))

    enriched.sort(key=lambda item: (item[0], item[1], item[2].get("email", "")))
    if args.limit:
        enriched = enriched[: args.limit]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for index, (_key, _neg, row, trigger, tier_name, score) in enumerate(enriched, start=1):
            writer.writerow({
                "rank": index,
                "tier": tier_name,
                "company": row.get("company"),
                "domain": row.get("company_domain"),
                "email": row.get("email"),
                "email_type": "personal" if row.get("is_generic_email", "").lower() == "false" else "generic",
                "deliverability": deliverability[row.get("email")].result.value,
                "score": score,
                "trigger_type": trigger,
                "reason_to_write": row.get("reason_to_write"),
                "evidence_url": row.get("evidence_urls"),
                "hn_source_url": row.get("source_url"),
                "review_status": row.get("review_status") or "",
                "company_id": row.get("company_id"),
            })

    counts: dict[str, int] = {}
    for _key, _neg, _row, _trigger, tier_name, _score in enriched:
        counts[tier_name] = counts.get(tier_name, 0) + 1
    print(f"rows: {len(enriched)} -> {args.out}")
    for tier_name in sorted(counts):
        print(f"  {tier_name}: {counts[tier_name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
