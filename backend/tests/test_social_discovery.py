from app.services.social_discovery import (
    normalize_linkedin_companies,
    normalize_x_posts,
)


def test_non_technical_company_with_website_is_accepted() -> None:
    result = normalize_linkedin_companies([
        {
            "name": "Northgate Haulage",
            "website": "https://northgate-haulage.co.uk",
            "industry": "Logistics and Supply Chain",
            "description": "Regional freight and warehousing operator.",
            "employeeCount": 420,
        }
    ])
    assert len(result.records) == 1
    record = result.records[0]
    assert record["domain"] == "northgate-haulage.co.uk"
    assert record["employee_count"] == 420
    assert record["source"] == "linkedin_apify"


def test_software_company_is_filtered_out() -> None:
    """The revised thesis targets buyers, not builders."""
    result = normalize_linkedin_companies([
        {
            "name": "Devtools Inc",
            "website": "https://devtools.io",
            "industry": "Software Development",
            "description": "We build developer tools and open source libraries.",
        }
    ])
    assert result.records == []
    assert result.rejected["not_non_technical"] == 1


def test_linkedin_url_is_not_treated_as_a_company_domain() -> None:
    result = normalize_linkedin_companies([
        {"name": "Some Co", "website": "https://www.linkedin.com/company/some-co",
         "industry": "Logistics"}
    ])
    assert result.records == []
    assert result.rejected["no_resolvable_domain"] == 1


def test_vendor_field_rename_yields_zero_records_not_wrong_ones() -> None:
    """A third-party shape change must fail loudly, not silently."""
    result = normalize_linkedin_companies([
        {"orgTitle": "Renamed Co", "site": "https://renamed.co.uk"}
    ])
    assert result.records == []
    assert result.rejected["no_company_name"] == 1


def test_duplicate_domains_collapse() -> None:
    item = {"name": "Dup Co", "website": "https://dup.co.uk", "industry": "Manufacturing"}
    result = normalize_linkedin_companies([item, dict(item)])
    assert len(result.records) == 1
    assert result.rejected["duplicate_domain"] == 1


def test_employee_count_parses_banded_strings() -> None:
    result = normalize_linkedin_companies([
        {"name": "Band Co", "website": "https://band.co.uk",
         "industry": "Construction", "employeeCount": "201-500"}
    ])
    assert result.records[0]["employee_count"] == 201


def test_x_post_without_company_link_is_rejected() -> None:
    result = normalize_x_posts([{"text": "we are hiring!", "author": {"name": "Someone"}}])
    assert result.records == []
    assert result.rejected["no_resolvable_domain"] == 1


def test_x_post_linking_a_company_is_accepted() -> None:
    result = normalize_x_posts([
        {
            "text": "We need help modernising our warehouse system.",
            "expandedUrl": "https://acme-distribution.com/about",
            "url": "https://x.com/acme/status/1",
            "author": {"name": "Acme Distribution"},
        }
    ])
    assert len(result.records) == 1
    assert result.records[0]["domain"] == "acme-distribution.com"


def test_x_post_linking_a_shortener_is_rejected() -> None:
    result = normalize_x_posts([
        {"text": "news", "expandedUrl": "https://t.co/abc", "author": {"name": "X"}}
    ])
    assert result.records == []
    assert result.rejected["non_company_host"] == 1
