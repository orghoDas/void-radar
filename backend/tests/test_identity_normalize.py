from app.identity.normalize import (
    normalize_company_match_name,
    normalize_domain,
    normalize_location,
)


def test_normalize_domain_strips_scheme_www_and_path() -> None:
    assert normalize_domain("https://www.example.com/about") == "example.com"
    assert normalize_domain("http://flowai.com") == "flowai.com"
    assert normalize_domain("flowai.com/pricing") == "flowai.com"


def test_normalize_company_match_name_removes_common_suffixes() -> None:
    assert normalize_company_match_name("Flow AI Ltd.") == "flowai"
    assert normalize_company_match_name("FlowAI Technologies") == "flowaitechnologies"


def test_normalize_location_extracts_city_and_country() -> None:
    location = normalize_location("San Francisco, CA, USA; Remote")

    assert location.raw == "San Francisco, CA, USA; Remote"
    assert location.city == "San Francisco"
    assert location.country == "United States"

