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



def test_normalize_domain_rejects_prose_parsed_as_hostname() -> None:
    """Free-text discovery sources turn sentence fragments into hostnames."""
    assert normalize_domain("e.g") is None
    assert normalize_domain("node.js") is None
    assert normalize_domain("issues.i") is None
    assert normalize_domain("which.your") is None
    assert normalize_domain("welcome.we") is None


def test_normalize_domain_repairs_suffix_glued_to_next_word() -> None:
    assert normalize_domain("middesk.comat") == "middesk.com"
    assert normalize_domain("apexdp.comwe") == "apexdp.com"
    assert normalize_domain("histowiz.comabout") == "histowiz.com"
    assert normalize_domain("withclad.comclad") == "withclad.com"


def test_normalize_domain_keeps_uncommon_but_real_suffixes() -> None:
    assert normalize_domain("aeolus.earth") == "aeolus.earth"
    assert normalize_domain("kyra.health") == "kyra.health"
    assert normalize_domain("phase.law") == "phase.law"
    assert normalize_domain("cockpit.at") == "cockpit.at"
    assert normalize_domain("openrent.co.uk") == "openrent.co.uk"
