# Legacy YC/EF Adapters

YC and Entrepreneur First are removed from the active MVP path.

They are archived because the current product is:

```text
buying trigger -> company domain -> founder/CXO lead -> contact evidence
```

YC/EF portfolio data can be useful for ingestion tests and historical reference,
but it does not reliably create the trigger-backed lead flow we need now.

## Keep As Legacy

- `apify/yc-company-discovery`
- `scripts/ingest_yc_dataset.py`
- `scripts/process_yc_source_records.py`
- `scripts/ingest_entrepreneur_first_dataset.py`
- `scripts/process_entrepreneur_first_source_records.py`
- `scripts/probe_accelerator_sources.py`
- YC/EF ingestion and identity-resolution tests

## Active Sources Instead

- HN Who Is Hiring and similar public hiring-intent threads.
- ATS/job boards discovered from scored domains.
- Funding/news sources where the event is recent and source-backed.
- Niche directories/job boards with explicit current demand.

## Deletion Rule

Do not hard-delete the legacy adapters until their API routes and tests are
unwired in a dedicated cleanup pass. Until then, source reports and roadmap docs
should exclude YC/EF from active MVP decisions.
