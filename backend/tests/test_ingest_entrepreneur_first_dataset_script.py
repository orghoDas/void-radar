from __future__ import annotations

from scripts.ingest_entrepreneur_first_dataset import read_entrepreneur_first_records


def test_read_entrepreneur_first_records_from_portfolio_html(tmp_path) -> None:
    portfolio = tmp_path / "ef.html"
    portfolio.write_text(
        """
        <div class="tile tile--company" data-companyname="Tractable"
             data-companyslug="tractable">
          <a class='locationtag'>London</a>
          <a class='categorytag'>Insurance</a>
          <div class="tile__description">AI for accident recovery.</div>
          <div class="meta__row__role text-xsml">Founding CEO</div>
          <a class="text-link" href="https://www.linkedin.com/in/adalyac/">
            Alex Dalyac
          </a>
        </div><!-- /tile--company -->
        """,
        encoding="utf-8",
    )

    records = read_entrepreneur_first_records(portfolio)

    assert records == [
        {
            "source": "entrepreneur_first",
            "source_url": "https://www.joinef.com/portfolio/#tractable",
            "source_company_id": "tractable",
            "company_name": "Tractable",
            "website": None,
            "location": "London",
            "industry": "Insurance",
            "batch": None,
            "stage": None,
            "status": None,
            "employee_count": None,
            "description": "AI for accident recovery.",
            "tags": ["Insurance"],
            "founders": [
                {
                    "name": "Alex Dalyac",
                    "role": "Founding CEO",
                    "linkedin_url": "https://www.linkedin.com/in/adalyac/",
                    "profile_url": None,
                    "x_url": None,
                    "bio": None,
                    "email": None,
                }
            ],
            "founded_year": None,
            "raw_source_payload": {
                "portfolio_source": "https://www.joinef.com/portfolio/",
                "source_record_id": "tractable",
                "source_url": "https://www.joinef.com/portfolio/#tractable",
                "founded_year": None,
            },
        }
    ]
