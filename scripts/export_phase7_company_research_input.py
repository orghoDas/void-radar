"""Build Company Researcher input from the send-ready outreach pilot CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

DEFAULT_OUTREACH_PATH = Path("campaigns/phase-6/outreach-pilot-export.csv")
DEFAULT_OUTPUT_PATH = Path("campaigns/phase-7/company-researcher-input.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outreach-path", type=Path, default=DEFAULT_OUTREACH_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--max-pages-per-company", type=int, default=10)
    parser.add_argument("--request-delay-ms", type=int, default=500)
    parser.add_argument("--no-page-text", action="store_true")
    args = parser.parse_args()

    targets = load_targets(args.outreach_path, limit=args.limit)
    payload = {
        "targets": targets,
        "maxItems": len(targets),
        "maxPagesPerCompany": args.max_pages_per_company,
        "requestDelayMs": args.request_delay_ms,
        "includePageText": not args.no_page_text,
        "emitPageRecords": True,
    }

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"targets_exported: {len(targets)}")
    print(f"output_path: {args.output_path}")
    return 0


def load_targets(path: Path, *, limit: int) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        rows = [normalize_row(row) for row in csv.DictReader(csv_file)]

    targets = []
    for row in rows:
        if not clean(row.get("company_id")) or not clean(row.get("domain")):
            continue
        if not clean(row.get("contact_id")) or not clean(row.get("email")):
            continue
        targets.append(
            {
                "company_id": clean(row.get("company_id")),
                "company": clean(row.get("company")),
                "domain": clean(row.get("domain")),
                "contact_id": clean(row.get("contact_id")),
                "contact_email": clean(row.get("email")),
                "contact_name": clean(row.get("contact_name")),
                "contact_role": clean(row.get("role")),
                "reason_to_write": clean(row.get("reason_to_write")),
                "evidence_urls": clean(row.get("evidence_urls")),
                "score": int(clean(row.get("score")) or 0),
                "fit_score": int(clean(row.get("fit_score")) or 0),
                "intent_score": int(clean(row.get("intent_score")) or 0),
                "score_id": clean(row.get("score_id")),
            }
        )
        if len(targets) >= limit:
            break
    return targets


def normalize_row(row: dict[str, Any]) -> dict[str, str]:
    return {clean(key): clean(value) for key, value in row.items() if key is not None}


def clean(value: Any) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
