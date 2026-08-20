from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

REQUIRED_COLUMNS = [
    "company",
    "domain",
    "segment",
    "country",
    "trigger_type",
    "trigger_summary",
    "trigger_url",
    "role_title",
    "role_age_days",
    "target_person",
    "target_role",
    "email",
    "email_source",
    "email_verification",
    "message_angle",
    "status",
    "outcome",
    "notes",
]

VALID_TRIGGER_TYPES = {
    "stale_hiring",
    "hiring_spike",
    "fresh_funding",
    "procurement",
    "product_launch",
    "manual_review",
}

VALID_EMAIL_SOURCES = {
    "company_website",
    "founder_personal_website",
    "public_profile",
    "trusted_source_payload",
    "verified_provider",
    "manual_review",
}

VALID_EMAIL_VERIFICATIONS = {
    "public_source",
    "provider_verified",
    "manual_verified",
}

GENERIC_EMAIL_LOCAL_PARTS = {
    "admin",
    "contact",
    "hello",
    "info",
    "sales",
    "support",
    "team",
}

EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


@dataclass
class ValidationIssue:
    row_number: int
    field: str
    message: str


@dataclass
class ValidationResult:
    rows_seen: int = 0
    send_ready: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def failed_rows(self) -> int:
        return len({issue.row_number for issue in self.issues})


def validate_campaign_csv(path: Path) -> ValidationResult:
    with path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        missing_columns = [
            column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])
        ]
        result = ValidationResult()
        if missing_columns:
            result.issues.append(
                ValidationIssue(
                    row_number=0,
                    field="header",
                    message=f"missing columns: {', '.join(missing_columns)}",
                )
            )
            return result

        for index, row in enumerate(reader, start=2):
            result.rows_seen += 1
            row_issues = validate_row(index, row)
            if row_issues:
                result.issues.extend(row_issues)
            else:
                result.send_ready += 1

        return result


def validate_row(row_number: int, row: dict[str, str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for field_name in (
        "company",
        "domain",
        "segment",
        "trigger_type",
        "trigger_summary",
        "trigger_url",
        "email",
        "email_source",
        "email_verification",
        "message_angle",
    ):
        if not clean(row.get(field_name)):
            issues.append(required_issue(row_number, field_name))

    if not clean(row.get("target_person")) and not clean(row.get("target_role")):
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="target_person",
                message="target_person or target_role is required",
            )
        )

    trigger_type = clean(row.get("trigger_type")).lower()
    if trigger_type and trigger_type not in VALID_TRIGGER_TYPES:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="trigger_type",
                message=f"must be one of: {', '.join(sorted(VALID_TRIGGER_TYPES))}",
            )
        )

    validate_domain(row_number, row, issues)
    validate_url(row_number, "trigger_url", row.get("trigger_url"), issues)
    validate_email(row_number, row, issues)
    validate_role_age(row_number, row, issues)

    email_source = clean(row.get("email_source")).lower()
    if email_source and email_source not in VALID_EMAIL_SOURCES:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="email_source",
                message=f"must be one of: {', '.join(sorted(VALID_EMAIL_SOURCES))}",
            )
        )

    email_verification = clean(row.get("email_verification")).lower()
    if email_verification and email_verification not in VALID_EMAIL_VERIFICATIONS:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="email_verification",
                message=(
                    "must be one of: "
                    f"{', '.join(sorted(VALID_EMAIL_VERIFICATIONS))}"
                ),
            )
        )

    return issues


def validate_domain(
    row_number: int,
    row: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    domain = normalize_domain(row.get("domain"))
    if not domain:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="domain",
                message="must be a company domain",
            )
        )


def validate_url(
    row_number: int,
    field_name: str,
    value: str | None,
    issues: list[ValidationIssue],
) -> None:
    parsed = urlparse(clean(value))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field=field_name,
                message="must be an absolute http(s) URL",
            )
        )


def validate_email(
    row_number: int,
    row: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    email = clean(row.get("email")).lower()
    if not email or not EMAIL_RE.match(email):
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="email",
                message="must be a valid explicit email",
            )
        )
        return

    local_part, _, email_domain = email.partition("@")
    company_domain = normalize_domain(row.get("domain"))
    if local_part in GENERIC_EMAIL_LOCAL_PARTS:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="email",
                message="must be a person-level email for Phase 0",
            )
        )
    if company_domain and email_domain != company_domain:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="email",
                message="email domain must match company domain",
            )
        )


def validate_role_age(
    row_number: int,
    row: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    if clean(row.get("trigger_type")).lower() != "stale_hiring":
        return

    raw_age = clean(row.get("role_age_days"))
    if not raw_age:
        issues.append(required_issue(row_number, "role_age_days"))
        return
    try:
        role_age_days = int(raw_age)
    except ValueError:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="role_age_days",
                message="must be an integer",
            )
        )
        return
    if role_age_days < 60:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="role_age_days",
                message="must be at least 60 for stale_hiring",
            )
        )


def normalize_domain(value: str | None) -> str | None:
    candidate = clean(value)
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    hostname = parsed.hostname
    if not hostname:
        return None
    hostname = hostname.lower().strip(".").removeprefix("www.")
    return hostname if "." in hostname else None


def required_issue(row_number: int, field_name: str) -> ValidationIssue:
    return ValidationIssue(
        row_number=row_number,
        field=field_name,
        message="is required",
    )


def clean(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def print_result(result: ValidationResult) -> None:
    print(f"rows_seen={result.rows_seen}")
    print(f"send_ready={result.send_ready}")
    print(f"failed_rows={result.failed_rows}")
    print(f"issues={len(result.issues)}")
    for issue in result.issues:
        print(f"row {issue.row_number}: {issue.field}: {issue.message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the Phase 0 manual outreach campaign CSV."
    )
    parser.add_argument("csv_path", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_campaign_csv(args.csv_path)
    print_result(result)
    return 1 if result.issues else 0


if __name__ == "__main__":
    sys.exit(main())
