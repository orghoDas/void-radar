import pytest

from app.services.deep_enrichment import validate_profile
from app.services.llm_client import LlmError

PAGE = "Acme builds warehouse software. Contact jane@acme.com. Our CTO is Dana Reed."


def test_valid_output_is_accepted() -> None:
    result = validate_profile(
        {
            "positioning": "Warehouse software for distributors.",
            "business_model": "B2B SaaS",
            "customer_type": "Distributors",
            "technology_mentions": ["Python", "Postgres", "Python"],
            "contact_routes": ["jane@acme.com"],
            "decision_makers": [{"name": "Dana Reed", "role": "CTO"}],
            "service_fit_evidence": "Small team, legacy stack.",
        },
        company_domain="acme.com",
        page_text=PAGE,
    )
    assert result.profile.contact_routes == ["jane@acme.com"]
    assert result.profile.technology_mentions == ["Python", "Postgres"]
    assert result.notes == []
    assert result.confidence > 0.5


def test_off_domain_email_is_dropped_as_likely_fabrication() -> None:
    """The load-bearing cross-reference from the brief."""
    result = validate_profile(
        {"contact_routes": ["jane@acme.com", "ceo@totally-different.com"]},
        company_domain="acme.com",
        page_text=PAGE,
    )
    assert result.profile.contact_routes == ["jane@acme.com"]
    assert any("off-domain" in note for note in result.notes)


def test_person_not_present_in_page_text_is_dropped() -> None:
    result = validate_profile(
        {"decision_makers": [{"name": "Dana Reed"}, {"name": "Invented Person"}]},
        company_domain="acme.com",
        page_text=PAGE,
    )
    names = [p.name for p in result.profile.decision_makers]
    assert names == ["Dana Reed"]
    assert any("unattested" in note for note in result.notes)


def test_malformed_email_is_dropped() -> None:
    result = validate_profile(
        {"contact_routes": ["not-an-email", "jane@acme.com"]},
        company_domain="acme.com",
        page_text=PAGE,
    )
    assert result.profile.contact_routes == ["jane@acme.com"]
    assert any("malformed" in note for note in result.notes)


def test_unbounded_lists_are_truncated() -> None:
    result = validate_profile(
        {"technology_mentions": [f"tech{i}" for i in range(200)]},
        company_domain="acme.com",
        page_text=PAGE,
    )
    assert len(result.profile.technology_mentions) <= 25


def test_wrong_types_are_rejected_not_coerced_silently() -> None:
    with pytest.raises(LlmError):
        validate_profile(
            {"positioning": {"nested": "object"}},
            company_domain="acme.com",
            page_text=PAGE,
        )


def test_confidence_drops_when_validation_had_to_intervene() -> None:
    clean = validate_profile(
        {"positioning": "x", "contact_routes": ["jane@acme.com"]},
        company_domain="acme.com", page_text=PAGE,
    )
    dirty = validate_profile(
        {"positioning": "x", "contact_routes": ["jane@acme.com", "a@evil.com", "b@evil.com"]},
        company_domain="acme.com", page_text=PAGE,
    )
    assert dirty.confidence < clean.confidence
