from __future__ import annotations

from scripts.probe_accelerator_sources import (
    parse_antler,
    parse_entrepreneur_first,
    parse_seedcamp,
    parse_techstars,
    summarize_records,
)


def test_parse_entrepreneur_first_captures_founders_and_linkedin() -> None:
    records = parse_entrepreneur_first(
        """
        <div class="tile tile--company" data-companyname="Tractable">
          <div class="tile__description">AI for accident recovery.</div>
          <a class='locationtag'>London</a>
          <a class='categorytag'>AI</a>
          <div class="meta__row__role text-xsml">Founding CEO</div>
          <a class="text-link" href="https://www.linkedin.com/in/alexdalyac">
            Alex Dalyac
          </a>
          <div class="meta__row__role text-xsml">CTO</div>
          <a class="text-link" href="https://www.linkedin.com/in/razvanranca">
            Razvan Ranca
          </a>
        </div><!-- /tile--company -->
        """
    )

    assert len(records) == 1
    assert records[0].company_name == "Tractable"
    assert records[0].description == "AI for accident recovery."
    assert records[0].location == "London"
    assert records[0].industry == "AI"
    assert records[0].people[0].name == "Alex Dalyac"
    assert records[0].people[0].role == "Founding CEO"
    assert records[0].people[0].linkedin_url == "https://www.linkedin.com/in/alexdalyac"
    assert records[0].people[1].role == "CTO"


def test_parse_seedcamp_captures_company_website_and_description() -> None:
    records = parse_seedcamp(
        """
        <div class="company__item mix ai dev-tools">
          <a href="https://example.ai" target="_blank"
             class="noline company__item__link">
            <span class="company__item__name">Example AI</span>
            <span class="company__item__year">2024</span>
            <div class="company__item__description__content">
              Builds practical AI tooling.
            </div>
          </a>
        </div>
        """
    )

    assert len(records) == 1
    assert records[0].company_name == "Example AI"
    assert records[0].website == "https://example.ai"
    assert records[0].description == "Builds practical AI tooling."
    assert records[0].industry == "ai, dev tools"
    assert records[0].year_or_stage == "2024"


def test_parse_antler_captures_cms_fields() -> None:
    records = parse_antler(
        """
        <div role="listitem">
          <a href="https://www.company.example">
            <div fs-cmsfilter-field="name">Company Example</div>
            <div fs-cmsfilter-field="description">Workflow automation.</div>
            <div fs-cmsfilter-field="location">Berlin</div>
            <div fs-cmsfilter-field="sector">B2B SaaS</div>
            <div fs-cmsfilter-field="year">2025</div>
          </a>
        </div>
        """
    )

    assert len(records) == 1
    assert records[0].company_name == "Company Example"
    assert records[0].website == "https://www.company.example"
    assert records[0].location == "Berlin"
    assert records[0].industry == "B2B SaaS"
    assert records[0].year_or_stage == "2025"


def test_parse_techstars_captures_structured_company_records() -> None:
    records = parse_techstars(
        r"""
        {\"id\":\"7f6ecc51-baaa-4128-9fe6-d3b19161f9dd\",\"name\":\"Chainalysis\",\"vertical\":\"Fintech\",
        \"stage\":\"Seed\",\"description\":\"Blockchain intelligence\",
        \"website\":\"https://www.chainalysis.com\",
        \"linkedin_url\":\"https://www.linkedin.com/company/chainalysis\",
        \"session_year\":2014}
        """
    )

    assert len(records) == 1
    assert records[0].company_name == "Chainalysis"
    assert records[0].website == "https://www.chainalysis.com"
    assert records[0].company_linkedin_url == (
        "https://www.linkedin.com/company/chainalysis"
    )
    assert records[0].industry == "Fintech"
    assert records[0].year_or_stage == "2014"


def test_summarize_records_counts_people_and_contact_fields() -> None:
    records = parse_entrepreneur_first(
        """
        <div class="tile tile--company" data-companyname="Tractable">
          <a class='categorytag'>AI</a>
          <div class="meta__row__role text-xsml">Founding CEO</div>
          <a class="text-link" href="https://www.linkedin.com/in/alexdalyac">
            Alex Dalyac
          </a>
        </div><!-- /tile--company -->
        """
    )

    result = summarize_records(
        source_key="entrepreneur_first",
        source_label="Entrepreneurs First",
        source_url="https://www.joinef.com/portfolio/",
        records=records,
        limit=50,
        notes=[],
    )

    assert result.records_found == 1
    assert result.company_names == 1
    assert result.people == 1
    assert result.people_with_linkedin == 1
    assert result.industries == 1
