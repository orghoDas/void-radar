# Company Researcher

Phase 7 actor for qualified companies only.

This actor should run after a company is:

- scored
- suppression-safe
- contactable through a provider-verified or manually approved contact

It crawls a small same-domain page set and emits deterministic research fields:

- positioning
- business model terms
- customer terms
- technology mentions
- service-fit snippets
- contact routes
- explicitly visible decision-maker names
- raw page records

It does not create contacts. Any names or emails discovered here must be
validated before entering `contacts`.

## Input

Generate input from the current outreach pilot:

```bash
backend/.venv/bin/python scripts/export_phase7_company_research_input.py
```

This writes:

```text
campaigns/phase-7/company-researcher-input.json
```

## Run

```bash
cd apify/company-researcher
apify push
```

Then run the actor with:

```text
campaigns/phase-7/company-researcher-input.json
```

## Import

Export the actor dataset as JSON, then ingest:

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' backend/.venv/bin/python scripts/ingest_phase7_company_research.py path/to/company-researcher-output.json
```

The importer stores:

- page bodies in `raw_pages`
- deterministic research fields in `observations`
