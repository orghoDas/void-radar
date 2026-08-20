from __future__ import annotations

from scripts.export_phase7_outreach_messages import (
    draft_for_row,
    first_name_from_email,
    project_area_from_observations,
    word_count,
)


def test_project_area_uses_manufacturing_context() -> None:
    observations = {
        "positioning": "AI Automation for Manufacturing.",
        "service_fit_evidence": ["Harmony connects to your ERP and QMS."],
    }

    assert project_area_from_observations(observations) == (
        "plant workflow and systems integration"
    )


def test_draft_stays_under_120_words_and_uses_email_first_name() -> None:
    row = {
        "company": "Tasklet",
        "domain": "tasklet.ai",
        "email": "andrew@tasklet.ai",
        "contact_name": "",
        "role": "CEO",
        "reason_to_write": "Tasklet posted in Ask HN.",
        "evidence_urls": "https://news.example/item",
        "company_id": "company-id",
        "contact_id": "contact-id",
        "score_id": "score-id",
    }
    observations = {
        "positioning": (
            "Accelerate your entire company with AI agents you can delegate real "
            "work to."
        ),
        "technology_mentions": ["ai", "api", "automation", "workflow"],
    }

    draft = draft_for_row(row, observations, "Orgho")

    assert draft["contact_name"] == "Andrew"
    assert word_count(draft["body"]) <= 120
    assert "agent workflow integrations" in draft["body"]


def test_first_name_from_email_falls_back_cleanly() -> None:
    assert first_name_from_email("greg@performance.fyi") == "Greg"
    assert first_name_from_email("hello+team@example.ai") == "Hello"
