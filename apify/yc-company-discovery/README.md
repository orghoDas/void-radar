# yc-company-discovery

Collects public YC company records and emits standardized raw source records for
Void Radar.

Responsibilities:

- Collect YC company records.
- Preserve source URL and source company ID.
- Output standardized raw records.
- Filter toward the Phase 1 ICP by region and employee count when configured.
- Save lightweight resume state in the Apify key-value store.
- Avoid deep AI analysis.

Expected output shape:

```json
{
  "source": "y_combinator",
  "source_url": "https://www.ycombinator.com/companies/example",
  "source_company_id": "example",
  "company_name": "Example AI",
  "website": "https://example.ai",
  "location": "San Francisco, CA, USA",
  "industry": "B2B SaaS",
  "batch": "S24",
  "founders": [
    {"name": "Jane Founder"}
  ]
}
```

## Default Input

```json
{
  "maxItems": 50,
  "minEmployees": 50,
  "includeFounderDetails": true,
  "detailRequestDelayMs": 300,
  "regions": ["United States", "USA", "United Kingdom", "UK", "Europe"],
  "includeUnknownLocation": false,
  "sourceUrl": "https://yc-oss.github.io/api/companies/all.json",
  "startOffset": 0
}
```

## Local Run

```bash
npm install
npm start
```

For isolated local validation:

```bash
CRAWLEE_STORAGE_DIR=/private/tmp/void-radar-yc-test npm start
```

On Apify, the actor writes records to the default dataset. The next backend step
is to POST those records to:

```text
POST /ingestion/y-combinator/source-records
```

Phase 3 intentionally stores source records only. Normalization, canonical
company creation, domain resolution, and merge decisions are Phase 4 work.

## Founder Details

The structured public feed used by this actor does not include founder names by
itself. When `includeFounderDetails` is enabled, the actor fetches each public
YC company profile page and extracts founder names, roles, bios, and public
profile links when present.

Direct emails are not inferred. The actor only preserves emails if they are
explicitly present in the public source payload.
