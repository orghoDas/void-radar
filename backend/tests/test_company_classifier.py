import pytest

from app.services.company_classifier import validate_classification
from app.services.llm_client import LlmError

VENDOR_PAGE = (
    "Acme Software builds a developer platform. We ship our SDK to thousands "
    "of engineering teams and maintain open source libraries."
)
UNIVERSITY_PAGE = (
    "Huddinge kommun ansvarar för skola, omsorg och samhällsservice för våra "
    "invånare. Vi upphandlar IT-system från externa leverantörer."
)


def test_vendor_with_attested_evidence_is_excluded() -> None:
    result = validate_classification(
        {
            "company_type": "software_vendor",
            "builds_software": "true",
            "sector": "developer tools",
            "engineering_signals": ["We ship our SDK to thousands of engineering teams"],
            "confidence": 0.9,
        },
        page_text=VENDOR_PAGE,
    )
    assert result.payload.company_type == "software_vendor"
    assert result.excluded is True
    assert result.notes == []


def test_non_english_buyer_is_classified_without_keyword_lists() -> None:
    """The reason this is a model and not a word list."""
    result = validate_classification(
        {
            "company_type": "non_technical_buyer",
            "builds_software": "false",
            "sector": "municipality",
            "buyer_signals": ["Vi upphandlar IT-system från externa leverantörer"],
            "confidence": 0.85,
        },
        page_text=UNIVERSITY_PAGE,
    )
    assert result.payload.company_type == "non_technical_buyer"
    assert result.payload.sector == "municipality"
    assert result.excluded is False


def test_builder_verdict_without_evidence_is_downgraded_not_trusted() -> None:
    """An exclusion is a destructive act; it must be shown, not asserted."""
    result = validate_classification(
        {
            "company_type": "agency",
            "builds_software": "true",
            "engineering_signals": [],
            "confidence": 0.95,
        },
        page_text=UNIVERSITY_PAGE,
    )
    assert result.payload.company_type == "unclear"
    assert result.excluded is False
    assert any("downgraded" in note for note in result.notes)


def test_fabricated_quote_is_dropped() -> None:
    result = validate_classification(
        {
            "company_type": "software_vendor",
            "engineering_signals": [
                "We ship our SDK to thousands of engineering teams",
                "We employ four hundred developers in-house",
            ],
            "confidence": 0.9,
        },
        page_text=VENDOR_PAGE,
    )
    assert result.payload.engineering_signals == [
        "We ship our SDK to thousands of engineering teams"
    ]
    assert any("unattested" in note for note in result.notes)


def test_short_quotes_are_rejected_as_accidental_matches() -> None:
    result = validate_classification(
        {"company_type": "non_technical_buyer", "buyer_signals": ["IT", "skola"]},
        page_text=UNIVERSITY_PAGE,
    )
    assert result.payload.buyer_signals == []
    assert all("short" in note for note in result.notes)


def test_invalid_company_type_is_rejected() -> None:
    with pytest.raises(LlmError):
        validate_classification(
            {"company_type": "something_else"}, page_text=VENDOR_PAGE
        )


def test_confidence_falls_when_validation_intervened() -> None:
    clean = validate_classification(
        {"company_type": "non_technical_buyer",
         "buyer_signals": ["Vi upphandlar IT-system från externa leverantörer"],
         "confidence": 0.9},
        page_text=UNIVERSITY_PAGE,
    )
    dirty = validate_classification(
        {"company_type": "non_technical_buyer",
         "buyer_signals": ["Vi upphandlar IT-system från externa leverantörer",
                           "We have no invented engineering department at all"],
         "confidence": 0.9},
        page_text=UNIVERSITY_PAGE,
    )
    assert dirty.payload.confidence < clean.payload.confidence


def test_json_boolean_is_coerced_not_rejected() -> None:
    """JSON has native booleans; the model returns true, not the string "true"."""
    result = validate_classification(
        {
            "company_type": "software_vendor",
            "builds_software": True,
            "engineering_signals": ["We ship our SDK to thousands of engineering teams"],
        },
        page_text=VENDOR_PAGE,
    )
    assert result.payload.builds_software == "true"

    absent = validate_classification(
        {"company_type": "unclear", "builds_software": None}, page_text=VENDOR_PAGE
    )
    assert absent.payload.builds_software == "unknown"


def test_null_content_raises_llm_error_not_typeerror() -> None:
    """A refusal or length cap must skip one record, not abort the batch."""
    import httpx

    from app.services.llm_client import OpenRouterClient

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": None}, "finish_reason": "length"}],
                "usage": {},
            }

    client = OpenRouterClient(api_key="x", base_url="https://example", model="m")
    original = httpx.post
    httpx.post = lambda *a, **k: FakeResponse()
    try:
        with pytest.raises(LlmError) as error:
            client.complete_json(system_prompt="s", user_prompt="u")
        assert "no text content" in str(error.value)
    finally:
        httpx.post = original
