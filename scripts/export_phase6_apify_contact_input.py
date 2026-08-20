"""Build Apify contact-candidate actor input from Phase 6 targets."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_TARGETS_PATH = Path("campaigns/phase-6/contact-provider-targets.csv")
DEFAULT_OUTPUT_PATH = Path("campaigns/phase-6/apify-contact-candidate-input.json")

DEFAULT_SKIP_DOMAINS = {
    "arxiv.org",
    "bit.ly",
    "applicantpro.com",
    "github.com",
    "github.io",
    "lnkd.in",
    "linkedin.com",
    "medium.com",
    "node.js",
    "grnh.se",
    "techcrunch.com",
    "entertimeonline.com",
    "welcome.we",
    "youtube.com",
    "youtu.be",
}

ALLOWED_PILOT_TLDS = {
    "ai",
    "app",
    "at",
    "bot",
    "co",
    "com",
    "dev",
    "earth",
    "foundation",
    "fr",
    "fyi",
    "health",
    "io",
    "law",
    "net",
    "no",
    "org",
    "run",
    "se",
    "space",
    "us",
}

NOISY_COMPANY_NAME_FRAGMENTS = (
    "in this role",
    "please email",
    "from the founders",
    "newco",
    "role:",
    "sent you a message",
    "software engineer",
    "submitted the form",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets-path", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--exclude-results-path",
        action="append",
        type=Path,
        default=[],
        help="CSV/JSON actor result file whose company domains should be skipped.",
    )
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--min-score", type=int, default=20)
    parser.add_argument("--max-pages-per-company", type=int, default=12)
    parser.add_argument("--request-delay-ms", type=int, default=500)
    parser.add_argument("--include-generic-emails", action="store_true")
    parser.add_argument("--include-external-emails", action="store_true")
    parser.add_argument(
        "--keep-subdomains",
        action="store_true",
        help="Keep source subdomains instead of collapsing them to the root domain.",
    )
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
        "maxItems": len(targets),
        "maxPagesPerCompany": args.max_pages_per_company,
        "requestDelayMs": args.request_delay_ms,
        "includeGenericEmails": args.include_generic_emails,
        "includeExternalEmails": args.include_external_emails,
        "emitMissesToDataset": True,
    }

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"targets_exported: {len(targets)}")
    print(f"output_path: {args.output_path}")
    return 0


def load_targets(
    path: Path,
    *,
    limit: int,
    min_score: int,
    collapse_subdomains: bool = True,
    exclude_domains: set[str] | None = None,
    offset: int = 0,
) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        rows = [normalize_row(row) for row in csv.DictReader(csv_file)]

    exclude_domains = exclude_domains or set()
    targets = []
    skipped_for_offset = 0
    for row in rows:
        domain = normalize_target_domain(
            clean(row.get("domain")),
            collapse_subdomains=collapse_subdomains,
        )
        if not is_clean_domain(domain):
            continue
        if domain in exclude_domains:
            continue
        company = clean_company_name(row.get("company"))
        if not is_clean_company(company):
            continue
        score = int(clean(row.get("score")) or 0)
        if score < min_score:
            continue
        if skipped_for_offset < offset:
            skipped_for_offset += 1
            continue
        targets.append(
            {
                "company_id": clean(row.get("company_id")),
                "company": company,
                "domain": domain,
                "target_roles": clean(row.get("target_roles")),
                "reason_to_write": clean(row.get("reason_to_write")),
                "evidence_urls": clean(row.get("evidence_urls")),
                "score": score,
            }
        )
        if len(targets) >= limit:
            break

    return targets


def load_excluded_domains(paths: list[Path]) -> set[str]:
    domains = set()
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("items") if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise TypeError(f"{path} must be a JSON list or object with items.")
            for row in rows:
                if isinstance(row, dict):
                    add_domain_from_row(domains, row)
            continue

        with path.open(newline="", encoding="utf-8-sig") as csv_file:
            for row in csv.DictReader(csv_file):
                add_domain_from_row(domains, normalize_row(row))
    return domains


def add_domain_from_row(domains: set[str], row: dict[str, object]) -> None:
    domain = clean(
        row.get("company_domain")
        or row.get("domain")
        or row.get("website")
        or row.get("canonical_domain")
    )
    if domain:
        domains.add(domain)


def normalize_target_domain(domain: str, *, collapse_subdomains: bool) -> str:
    labels = domain.lower().strip(".").split(".")
    if collapse_subdomains and len(labels) > 2:
        return ".".join(labels[-2:])
    return ".".join(labels)


def is_clean_domain(domain: str) -> bool:
    if not domain or domain in DEFAULT_SKIP_DOMAINS:
        return False
    if domain.count(".") != 1:
        return False
    suffix = domain.rsplit(".", 1)[-1]
    if not suffix.isalpha() or not 2 <= len(suffix) <= 12:
        return False
    return suffix in ALLOWED_PILOT_TLDS


def is_clean_company(company: str) -> bool:
    lowered = company.lower()
    return bool(company) and not any(
        fragment in lowered for fragment in NOISY_COMPANY_NAME_FRAGMENTS
    )


def clean_company_name(value: object) -> str:
    return clean(value).rstrip(" (").strip()


def normalize_row(row: dict[str, object]) -> dict[str, str]:
    normalized = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized[clean(key)] = clean(value)
    return normalized


def clean(value: object) -> str:
    if isinstance(value, list):
        return " ".join(clean(item) for item in value)
    return str(value or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
