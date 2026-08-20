from __future__ import annotations

import csv

from scripts.export_phase7_company_research_input import load_targets
from scripts.ingest_phase7_company_research import (
    first_source_url,
    parse_jsonish,
    value_from_row,
)


def test_load_targets_from_outreach_export_requires_contactable_rows(tmp_path) -> None:
    path = tmp_path / "outreach.csv"
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "company",
                "domain",
                "email",
                "score",
                "fit_score",
                "intent_score",
                "reason_to_write",
                "evidence_urls",
                "score_id",
                "company_id",
                "contact_id",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "company": "Tasklet",
                "domain": "tasklet.ai",
                "email": "andrew@tasklet.ai",
                "score": "34",
                "fit_score": "73",
                "intent_score": "46",
                "reason_to_write": "Hiring signal.",
                "evidence_urls": "https://news.example/item",
                "score_id": "score-id",
                "company_id": "company-id",
                "contact_id": "contact-id",
            }
        )
        writer.writerow(
            {
                "company": "No Contact",
                "domain": "nocontact.ai",
                "score": "34",
                "company_id": "company-no-contact",
            }
        )

    targets = load_targets(path, limit=10)

    assert targets == [
        {
            "company_id": "company-id",
            "company": "Tasklet",
            "domain": "tasklet.ai",
            "contact_id": "contact-id",
            "contact_email": "andrew@tasklet.ai",
            "contact_name": "",
            "contact_role": "",
            "reason_to_write": "Hiring signal.",
            "evidence_urls": "https://news.example/item",
            "score": 34,
            "fit_score": 73,
            "intent_score": 46,
            "score_id": "score-id",
        }
    ]


def test_parse_jsonish_supports_apify_json_strings() -> None:
    value = parse_jsonish('[{"final_url":"https://example.ai/","page_text":"Hi"}]')

    assert value == [{"final_url": "https://example.ai/", "page_text": "Hi"}]


def test_first_source_url_prefers_checked_urls_then_page_records() -> None:
    assert (
        first_source_url({"checked_urls": "https://example.ai/;https://example.ai/about"})
        == "https://example.ai/"
    )
    assert (
        first_source_url(
            {
                "page_records": (
                    '[{"final_url":"https://example.ai/about","page_text":"About"}]'
                )
            }
        )
        == "https://example.ai/about"
    )


def test_value_from_row_rehydrates_apify_flattened_arrays_and_objects() -> None:
    row = {
        "business_model_terms/0": "api",
        "business_model_terms/1": "subscription",
        "contact_routes/0/route_type": "mailto",
        "contact_routes/0/value": "hello@example.ai",
        "contact_routes/0/source_url": "https://example.ai/contact",
        "page_records/0/final_url": "https://example.ai/",
        "page_records/0/page_text": "Home page",
        "page_records/0/technology_mentions/0": "api",
        "page_records/1/final_url": "https://example.ai/about",
        "page_records/1/page_text": "About page",
    }

    assert value_from_row(row, "business_model_terms") == ["api", "subscription"]
    assert value_from_row(row, "contact_routes") == [
        {
            "route_type": "mailto",
            "value": "hello@example.ai",
            "source_url": "https://example.ai/contact",
        }
    ]
    assert value_from_row(row, "page_records") == [
        {
            "final_url": "https://example.ai/",
            "page_text": "Home page",
            "technology_mentions": ["api"],
        },
        {
            "final_url": "https://example.ai/about",
            "page_text": "About page",
        },
    ]
