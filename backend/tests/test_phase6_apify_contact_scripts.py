from __future__ import annotations

import csv
import json

from scripts.export_phase6_apify_contact_input import (
    load_excluded_domains,
    load_targets,
)
from scripts.build_phase6_manual_review_queue import build_review_queue
from scripts.ingest_reviewed_apify_contacts import (
    contact_record_from_row,
    should_import_row,
)


def test_load_targets_filters_noisy_domains_and_score(tmp_path) -> None:
    path = tmp_path / "targets.csv"
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "company_id",
                "company",
                "domain",
                "target_roles",
                "reason_to_write",
                "evidence_urls",
                "score",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "company_id": "company-good",
                "company": "Good Co",
                "domain": "good.co",
                "target_roles": "CTO",
                "reason_to_write": "Hiring signal.",
                "evidence_urls": "https://news.example/item",
                "score": "34",
            }
        )
        writer.writerow(
            {
                "company_id": "company-noisy",
                "company": "Noisy",
                "domain": "apexdp.comwe",
                "score": "34",
            }
        )
        writer.writerow(
            {
                "company_id": "company-low",
                "company": "Low",
                "domain": "low.co",
                "score": "10",
            }
        )

    targets = load_targets(path, limit=10, min_score=20)

    assert targets == [
        {
            "company_id": "company-good",
            "company": "Good Co",
            "domain": "good.co",
            "target_roles": "CTO",
            "reason_to_write": "Hiring signal.",
            "evidence_urls": "https://news.example/item",
            "score": 34,
        }
    ]


def test_load_targets_can_exclude_previous_actor_result_domains(tmp_path) -> None:
    targets_path = tmp_path / "targets.csv"
    with targets_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "company_id",
                "company",
                "domain",
                "target_roles",
                "reason_to_write",
                "evidence_urls",
                "score",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "company_id": "company-old",
                "company": "Old Co",
                "domain": "old.co",
                "score": "30",
            }
        )
        writer.writerow(
            {
                "company_id": "company-new",
                "company": "New Co",
                "domain": "new.co",
                "score": "30",
            }
        )

    results_path = tmp_path / "results.csv"
    with results_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["company_domain"])
        writer.writeheader()
        writer.writerow({"company_domain": "old.co"})

    targets = load_targets(
        targets_path,
        limit=10,
        min_score=20,
        exclude_domains=load_excluded_domains([results_path]),
    )

    assert [target["domain"] for target in targets] == ["new.co"]


def test_load_targets_supports_offset_after_filters(tmp_path) -> None:
    path = tmp_path / "targets.csv"
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["company_id", "company", "domain", "score"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "company_id": "company-one",
                "company": "One Co",
                "domain": "one.co",
                "score": "30",
            }
        )
        writer.writerow(
            {
                "company_id": "company-two",
                "company": "Two Co",
                "domain": "two.co",
                "score": "30",
            }
        )

    targets = load_targets(path, limit=10, min_score=20, offset=1)

    assert [target["domain"] for target in targets] == ["two.co"]


def test_should_import_row_requires_approval_by_default() -> None:
    row = {
        "record_type": "contact_candidate",
        "review_status": "needs_review",
        "email": "jane@example.ai",
        "source_url": "https://example.ai/team",
    }

    assert should_import_row(row, import_all=False) is False
    assert should_import_row({**row, "review_status": "approved"}, import_all=False)
    assert should_import_row(row, import_all=True)


def test_contact_record_from_row_maps_approved_candidate_to_manual_review() -> None:
    row = {
        "company_id": "company-id",
        "company_domain": "example.ai",
        "full_name": "Jane Founder",
        "role": "Founder",
        "email": "Jane@Example.AI",
        "source_url": "https://example.ai/team",
        "provider_name": "apify-contact-candidate-enricher",
        "confidence": "0.9",
        "review_status": "approved",
        "reason_to_write": "Hiring signal.",
        "evidence_urls": "https://news.example/item",
        "score": "34",
        "source_excerpt": "Jane Founder jane@example.ai",
        "extraction": "role_line_with_email",
    }

    record = contact_record_from_row(row, provider_name="apify")

    assert record.company_id == "company-id"
    assert record.company_domain == "example.ai"
    assert record.email == "jane@example.ai"
    assert record.source_type == "manual_review"
    assert record.verification_status == "manual_verified"
    assert record.raw_evidence["review_status"] == "approved"


def test_json_candidate_rows_are_plain_json_serializable() -> None:
    row = {
        "record_type": "contact_candidate",
        "review_status": "approved",
        "email": "jane@example.ai",
        "source_url": "https://example.ai/team",
    }

    assert json.loads(json.dumps(row)) == row


def test_build_review_queue_prioritizes_named_direct_contacts() -> None:
    rows = [
        {
            "record_type": "contact_candidate",
            "review_status": "needs_review",
            "company": "Example",
            "company_domain": "example.ai",
            "full_name": "Jane Founder",
            "role": "Founder",
            "email": "jane@example.ai",
            "source_url": "https://example.ai/team",
            "score": "34",
        },
        {
            "record_type": "contact_candidate",
            "review_status": "needs_review",
            "company": "Example",
            "company_domain": "example.ai",
            "email": "hello@example.ai",
            "source_url": "https://example.ai/contact",
            "score": "34",
        },
    ]

    queue = build_review_queue(
        rows,
        min_score=20,
        include_generic=True,
        include_external=False,
    )

    assert [row["candidate_quality"] for row in queue] == [
        "strong_direct_person",
        "fallback_generic_inbox",
    ]
    assert queue[0]["suggested_decision"] == "inspect_source_then_approve"


def test_build_review_queue_excludes_generic_by_default() -> None:
    rows = [
        {
            "record_type": "contact_candidate",
            "review_status": "needs_review",
            "company": "Example",
            "company_domain": "example.ai",
            "email": "hello@example.ai",
            "source_url": "https://example.ai/contact",
            "score": "34",
        }
    ]

    queue = build_review_queue(
        rows,
        min_score=20,
        include_generic=False,
        include_external=False,
    )

    assert queue == []


def test_build_review_queue_excludes_external_emails_by_default() -> None:
    rows = [
        {
            "record_type": "contact_candidate",
            "review_status": "needs_review",
            "company": "Example",
            "company_domain": "example.ai",
            "email": "jane@personal.dev",
            "source_url": "https://example.ai/team",
            "score": "34",
        }
    ]

    queue = build_review_queue(
        rows,
        min_score=20,
        include_generic=True,
        include_external=False,
    )

    assert queue == []


def test_build_review_queue_treats_team_and_employment_as_generic_fallback() -> None:
    rows = [
        {
            "record_type": "contact_candidate",
            "review_status": "needs_review",
            "company": "Railway",
            "company_domain": "railway.com",
            "email": "team@railway.com",
            "source_url": "https://railway.com/",
            "score": "23",
        },
        {
            "record_type": "contact_candidate",
            "review_status": "needs_review",
            "company": "Stellar Science",
            "company_domain": "stellarscience.com",
            "email": "employment2@stellarscience.com",
            "source_url": "https://www.stellarscience.com/careers/",
            "score": "23",
        },
        {
            "record_type": "contact_candidate",
            "review_status": "needs_review",
            "company": "PostHog",
            "company_domain": "posthog.com",
            "email": "tosales@posthog.com",
            "source_url": "https://posthog.com/talk-to-a-human",
            "score": "23",
        },
    ]

    queue = build_review_queue(
        rows,
        min_score=20,
        include_generic=True,
        include_external=False,
    )

    assert [row["candidate_quality"] for row in queue] == [
        "fallback_generic_inbox",
        "fallback_generic_inbox",
        "reject_low_value_generic",
    ]
