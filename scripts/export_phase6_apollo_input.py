"""Build Apollo-backed Apify actor input from Phase 6 targets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_phase6_apify_contact_input import (
    DEFAULT_TARGETS_PATH,
    load_excluded_domains,
    load_targets,
)

DEFAULT_OUTPUT_PATH = Path("campaigns/phase-6/apollo-verified-contact-input.json")
DEFAULT_PERSON_TITLES = [
    "Founder",
    "Co-Founder",
    "CEO",
    "Chief Executive Officer",
    "CTO",
    "Chief Technology Officer",
    "VP Engineering",
    "Vice President Engineering",
    "Head of Engineering",
    "Head of Product",
    "Head of Operations",
]
DEFAULT_PERSON_SENIORITIES = [
    "founder",
    "owner",
    "c_suite",
    "vp",
    "head",
    "director",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets-path", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--exclude-results-path", action="append", type=Path, default=[])
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--min-score", type=int, default=20)
    parser.add_argument("--api-key-env", default="APOLLO_API_KEY")
    parser.add_argument("--per-company-search-limit", type=int, default=8)
    parser.add_argument("--max-contacts-per-company", type=int, default=2)
    parser.add_argument("--max-enrichments-per-run", type=int, default=50)
    parser.add_argument("--request-delay-ms", type=int, default=500)
    parser.add_argument("--keep-subdomains", action="store_true")
    args = parser.parse_args()

    targets = load_targets(
        args.targets_path,
        limit=args.limit,
        min_score=args.min_score,
        collapse_subdomains=not args.keep_subdomains,
        exclude_domains=load_excluded_domains(args.exclude_results_path),
        offset=args.offset,
    )
    payload = {
        "targets": targets,
        "apiKeyEnv": args.api_key_env,
        "maxItems": len(targets),
        "perCompanySearchLimit": args.per_company_search_limit,
        "maxContactsPerCompany": args.max_contacts_per_company,
        "maxEnrichmentsPerRun": args.max_enrichments_per_run,
        "personTitles": DEFAULT_PERSON_TITLES,
        "personSeniorities": DEFAULT_PERSON_SENIORITIES,
        "requestDelayMs": args.request_delay_ms,
        "revealPersonalEmails": False,
        "revealPhoneNumber": False,
        "runWaterfallEmail": False,
        "emitMissesToDataset": True,
    }

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"targets_exported: {len(targets)}")
    print(f"max_enrichments_per_run: {args.max_enrichments_per_run}")
    print(f"output_path: {args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
