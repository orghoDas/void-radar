"""Export a suppression-checked Phase 6 outreach pilot CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.db.session import get_engine
from app.schemas.outreach import OutreachExportRequest
from app.services.outreach_export import export_send_ready_prospects_csv
from sqlalchemy.orm import Session

DEFAULT_OUTPUT_PATH = Path("campaigns/phase-6/outreach-pilot-export.csv")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--min-total-score", type=int, default=20)
    parser.add_argument(
        "--verification-status",
        action="append",
        dest="verification_statuses",
        default=[],
        help="Allowed contact verification status. Can be passed multiple times.",
    )
    args = parser.parse_args()

    verification_statuses = args.verification_statuses or [
        "provider_verified",
        "manual_verified",
    ]
    request = OutreachExportRequest(
        min_total_score=args.min_total_score,
        limit=args.limit,
        verification_statuses=verification_statuses,
    )

    with Session(get_engine()) as db:
        csv_body = export_send_ready_prospects_csv(db, request)

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(csv_body, encoding="utf-8")
    row_count = max(0, len(csv_body.splitlines()) - 1)
    print(f"rows_exported: {row_count}")
    print(f"output_path: {args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
