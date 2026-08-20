"""Build a compact manual-review queue from Apify contact candidates."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT_PATH = Path("campaigns/phase-6/manual-contact-review-queue.csv")

GENERIC_LOCAL_PARTS = {
    "admin",
    "billing",
    "careers",
    "contact",
    "employment",
    "hello",
    "help",
    "hi",
    "hiring",
    "hr",
    "info",
    "jobs",
    "legal",
    "media",
    "membership",
    "office",
    "press",
    "privacy",
    "recruiting",
    "sales",
    "security",
    "support",
    "talent",
    "team",
}

APPROVABLE_GENERIC_LOCAL_PARTS = {
    "careers",
    "contact",
    "employment",
    "hello",
    "hi",
    "hiring",
    "hr",
    "jobs",
    "recruiting",
    "talent",
    "team",
}

GENERIC_SUBSTRINGS = (
    "career",
    "employ",
    "hiring",
    "recruit",
    "sales",
    "support",
    "talent",
)

REVIEW_QUEUE_FIELDS = [
    "review_status",
    "suggested_decision",
    "candidate_quality",
    "priority_rank",
    "review_notes",
    "company",
    "company_domain",
    "full_name",
    "role",
    "email",
    "source_url",
    "source_excerpt",
    "reason_to_write",
    "evidence_urls",
    "score",
    "candidate_type",
    "is_generic_email",
    "is_company_domain_email",
    "has_name_evidence",
    "has_role_evidence",
    "confidence",
    "provider_name",
    "extraction",
    "record_type",
    "company_id",
    "target_roles",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates_path", type=Path)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--min-score", type=int, default=20)
    parser.add_argument(
        "--include-generic",
        action="store_true",
        help="Keep fallback generic inbox candidates in the review queue.",
    )
    parser.add_argument(
        "--include-external",
        action="store_true",
        help="Keep external-domain email candidates in the review queue.",
    )
    args = parser.parse_args()

    rows = load_rows(args.candidates_path)
    queue = build_review_queue(
        rows,
        min_score=args.min_score,
        include_generic=args.include_generic,
        include_external=args.include_external,
    )

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    with args.output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=REVIEW_QUEUE_FIELDS)
        writer.writeheader()
        writer.writerows(queue)

    print(f"candidate_rows_loaded: {count_candidate_rows(rows)}")
    print(f"review_rows_exported: {len(queue)}")
    print(f"output_path: {args.output_path}")
    return 0 if queue else 1


def build_review_queue(
    rows: list[dict[str, Any]],
    *,
    min_score: int,
    include_generic: bool,
    include_external: bool,
) -> list[dict[str, str]]:
    queue = []
    for row in rows:
        normalized = normalize_row(row)
        if normalized.get("record_type") != "contact_candidate":
            continue
        if int_or_zero(normalized.get("score")) < min_score:
            continue
        email = normalized.get("email", "").lower()
        if not email or "@" not in email:
            continue

        classification = classify_candidate(normalized)
        if classification["candidate_type"] == "external_email" and not include_external:
            continue
        if classification["is_generic_email"] and not include_generic:
            continue

        queue.append(review_row(normalized, classification))

    queue.sort(
        key=lambda row: (
            int_or_zero(row["priority_rank"]),
            -int_or_zero(row["score"]),
            row["company"].lower(),
            row["email"].lower(),
        )
    )
    return queue


def review_row(row: dict[str, str], classification: dict[str, str]) -> dict[str, str]:
    quality = candidate_quality(row, classification)
    suggested_decision = suggested_decision_for(quality)
    return {
        "review_status": clean(row.get("review_status")) or "needs_review",
        "suggested_decision": suggested_decision,
        "candidate_quality": quality,
        "priority_rank": str(priority_rank_for(quality)),
        "review_notes": review_notes_for(quality),
        "company": row.get("company", ""),
        "company_domain": row.get("company_domain") or row.get("domain", ""),
        "full_name": row.get("full_name", ""),
        "role": row.get("role", ""),
        "email": row.get("email", "").lower(),
        "source_url": row.get("source_url", ""),
        "source_excerpt": row.get("source_excerpt", ""),
        "reason_to_write": row.get("reason_to_write", ""),
        "evidence_urls": row.get("evidence_urls", ""),
        "score": row.get("score", ""),
        "candidate_type": classification["candidate_type"],
        "is_generic_email": classification["is_generic_email"],
        "is_company_domain_email": classification["is_company_domain_email"],
        "has_name_evidence": classification["has_name_evidence"],
        "has_role_evidence": classification["has_role_evidence"],
        "confidence": row.get("confidence", ""),
        "provider_name": row.get("provider_name", ""),
        "extraction": row.get("extraction", ""),
        "record_type": row.get("record_type", ""),
        "company_id": row.get("company_id", ""),
        "target_roles": row.get("target_roles", ""),
    }


def candidate_quality(row: dict[str, str], classification: dict[str, str]) -> str:
    if classification["candidate_type"] == "external_email":
        return "reject_external_domain"
    if classification["candidate_type"] == "low_value_generic_inbox":
        return "reject_low_value_generic"
    if classification["candidate_type"] == "generic_inbox":
        return "fallback_generic_inbox"
    if truthy(classification["has_name_evidence"]) and truthy(
        classification["has_role_evidence"]
    ):
        return "strong_direct_person"
    if truthy(classification["has_role_evidence"]):
        return "role_backed_direct_email"
    if row.get("extraction") == "mailto_link":
        return "mailto_direct_email"
    return "direct_email_needs_context"


def suggested_decision_for(quality: str) -> str:
    if quality == "strong_direct_person":
        return "inspect_source_then_approve"
    if quality in {"role_backed_direct_email", "mailto_direct_email"}:
        return "inspect_source"
    if quality == "fallback_generic_inbox":
        return "fallback_only"
    if quality.startswith("reject_"):
        return "reject"
    return "inspect_source"


def priority_rank_for(quality: str) -> int:
    ranks = {
        "strong_direct_person": 10,
        "role_backed_direct_email": 20,
        "mailto_direct_email": 30,
        "direct_email_needs_context": 40,
        "fallback_generic_inbox": 80,
        "reject_external_domain": 90,
        "reject_low_value_generic": 95,
    }
    return ranks.get(quality, 99)


def review_notes_for(quality: str) -> str:
    notes = {
        "strong_direct_person": "Best candidate: named person, role evidence, company-domain email.",
        "role_backed_direct_email": "Good candidate if the source confirms this role belongs to the email owner.",
        "mailto_direct_email": "Check source page and approve only if it is a real useful contact.",
        "direct_email_needs_context": "Needs manual source check before approval.",
        "fallback_generic_inbox": "Use only if no direct person exists for this company.",
        "reject_external_domain": "External-domain address; usually not importable.",
        "reject_low_value_generic": "Generic inbox with weak outreach value.",
    }
    return notes.get(quality, "Review source evidence before approving.")


def classify_candidate(row: dict[str, str]) -> dict[str, str]:
    email = row.get("email", "").lower()
    local_part, _, email_domain = email.partition("@")
    company_domain = (row.get("company_domain") or row.get("domain", "")).lower()
    is_company_domain_email = bool(company_domain and email_domain == company_domain)
    generic_local_part = generic_local_part_for(local_part)
    is_generic_email = bool(generic_local_part)
    candidate_type = row.get("candidate_type") or "direct_person"

    if not is_company_domain_email:
        candidate_type = "external_email"
    elif is_generic_email:
        candidate_type = (
            "generic_inbox"
            if generic_local_part in APPROVABLE_GENERIC_LOCAL_PARTS
            else "low_value_generic_inbox"
        )

    return {
        "candidate_type": candidate_type,
        "is_generic_email": str(is_generic_email).lower(),
        "is_company_domain_email": str(is_company_domain_email).lower(),
        "has_name_evidence": str(bool(row.get("full_name"))).lower(),
        "has_role_evidence": str(bool(row.get("role"))).lower(),
    }


def generic_local_part_for(local_part: str) -> str:
    if local_part in GENERIC_LOCAL_PARTS:
        return local_part
    without_digits = local_part.rstrip("0123456789")
    if without_digits in GENERIC_LOCAL_PARTS:
        return without_digits
    for substring in GENERIC_SUBSTRINGS:
        if substring in local_part:
            if substring == "career":
                return "careers"
            if substring == "employ":
                return "employment"
            if substring == "recruit":
                return "recruiting"
            return substring
    return ""


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise TypeError("JSON candidate file must be a list or object with items.")
        return [dict(row) for row in rows if isinstance(row, dict)]

    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        return list(csv.DictReader(csv_file))


def count_candidate_rows(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if clean(row.get("record_type")) == "contact_candidate")


def normalize_row(row: dict[str, Any]) -> dict[str, str]:
    return {clean(key): clean(value) for key, value in row.items() if key is not None}


def truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "y"}


def int_or_zero(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 0


def clean(value: object) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
