# Void Radar Phase 3 YC Discovery

Phase 3 builds the first trusted discovery source:

```text
Y Combinator
  -> yc-company-discovery Apify actor
  -> standardized raw records
  -> FastAPI ingestion
  -> sources + source_records
```

This phase is intentionally discovery-only. It preserves raw source records and
provenance, but does not normalize companies, create canonical company records,
resolve domains, call AI, score prospects, or build dashboard views.

## Source Access

The public YC startup directory is available at:

```text
https://www.ycombinator.com/companies
```

The current directory is JavaScript-heavy, so the first actor reads a structured
public YC company feed by default:

```text
https://yc-oss.github.io/api/companies/all.json
```

The actor still treats YC as the underlying trusted source by preserving YC
company URLs and source company identifiers in every record.

Before production scheduling, review the active source terms and rate limits.

## Actor

Location:

```text
apify/yc-company-discovery/
```

Default behavior:

- Fetch structured YC company records.
- Filter toward Void's current ICP:
  - USA and Europe.
  - Mid-to-large companies by default using `minEmployees`.
- Emit standardized records.
- Preserve original raw payload under `raw_source_payload`.
- Save lightweight resume state to Apify key-value storage.

Local validation command:

```bash
cd apify/yc-company-discovery
CRAWLEE_STORAGE_DIR=/private/tmp/void-radar-yc-test npm start
```

Standard output shape:

```json
{
  "source": "y_combinator",
  "source_url": "https://www.ycombinator.com/companies/example-ai",
  "source_company_id": "example-ai",
  "company_name": "Example AI",
  "website": "https://example.ai",
  "location": "New York, NY, USA",
  "industry": "B2B SaaS",
  "batch": "S24",
  "stage": "Active",
  "status": "Active",
  "employee_count": 75,
  "description": "AI workflow platform for operations teams.",
  "tags": ["b2b", "saas", "ai"],
  "founders": [{"name": "Jane Founder"}]
}
```

## Backend Ingestion

Endpoint:

```text
POST /ingestion/y-combinator/source-records
```

Request:

```json
{
  "records": [
    {
      "source": "y_combinator",
      "source_url": "https://www.ycombinator.com/companies/example-ai",
      "source_company_id": "example-ai",
      "company_name": "Example AI",
      "website": "https://example.ai",
      "location": "New York, NY, USA",
      "industry": "B2B SaaS",
      "batch": "S24",
      "founders": [{"name": "Jane Founder"}]
    }
  ]
}
```

Response:

```json
{
  "source": "y_combinator",
  "received": 1,
  "inserted": 1,
  "duplicates": 0
}
```

Persistence rules:

- Ensure `sources.source_key = y_combinator` exists.
- Store every accepted record in `source_records`.
- Preserve the full validated record in `raw_payload`.
- Store `source_url`, `source_record_id`, `collected_at`, and `content_hash`.
- Use `source_id + source_record_id` for idempotency.
- Do not write canonical companies yet.

Local dataset handoff:

```bash
python3 scripts/ingest_yc_dataset.py \
  /private/tmp/void-radar-yc-test/datasets/default
```

Apify Console JSON export handoff:

```bash
python3 scripts/ingest_yc_dataset.py \
  /Users/orghodas/Downloads/yc-cloud-export.json
```

The script accepts either:

- a local Apify dataset directory containing one `.json` file per record
- a single Apify JSON export file containing an array of records
- a wrapped export shaped like `{"items": [...]}`

The backend must be running and connected to a database with
`database/migrations/0001_core_schema.sql` applied before using the handoff
script.

## Current Source Limitation

The structured YC company feed does not currently include founder names. The
actor outputs `founders: []` when founder data is unavailable and preserves the
raw source payload for later review. Founder-specific collection should be added
only if a reliable permitted source is confirmed.

## Deferred to Phase 4

Phase 3 does not:

- Normalize company names.
- Normalize domains.
- Normalize founder names.
- Create canonical company records.
- Merge aliases.
- Resolve uncertain matches.
- Verify official domains.

Those are Phase 4 identity-resolution responsibilities.

## Acceptance Criteria

Phase 3 is complete when:

- `yc-company-discovery` can produce standardized YC records.
- The backend accepts batches of YC records.
- Raw payloads and source URLs are preserved.
- Duplicate source records are skipped.
- Invalid records are rejected.
- Backend tests pass.
