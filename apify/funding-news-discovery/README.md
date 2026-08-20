# funding-news-discovery

Collects public funding/news RSS or Atom feed items and emits standardized
domain-producing discovery records for Void Radar.

This actor is intentionally simple. It is a Phase 2 source adapter, not an
intelligence layer.

Responsibilities:

- Fetch configured public RSS/Atom feeds.
- Parse items deterministically.
- Extract company name, source URL, event date, summary, and a candidate domain.
- Preserve the raw feed item.
- Emit records compatible with:

```text
POST /ingestion/discovery/source-records
```

Expected output shape:

```json
{
  "source": "funding_news",
  "source_url": "https://news.example/article",
  "source_record_id": "https://news.example/article",
  "company_name": "Example AI",
  "website": "https://example.ai",
  "domain": "example.ai",
  "location": null,
  "industry": null,
  "stage": null,
  "status": "active",
  "employee_count": null,
  "description": "Example AI raises seed funding.",
  "tags": ["funding"],
  "event_type": "funding",
  "event_date": "2026-08-20",
  "event_summary": "Example AI raises seed funding.",
  "raw_source_payload": {}
}
```

## Default Input

```json
{
  "maxItems": 50,
  "includeArticleFetch": false,
  "requestDelayMs": 500,
  "feeds": [
    {
      "source": "funding_news",
      "sourceName": "Funding News",
      "url": "https://www.uktech.news/feed",
      "eventType": "funding"
    }
  ]
}
```

## Local Run

```bash
npm install
npm start
```

For isolated local validation:

```bash
CRAWLEE_STORAGE_DIR=/private/tmp/void-radar-funding-news-test npm start
```

On Apify, export the dataset and POST it to:

```text
POST /ingestion/discovery/source-records
```

Use this envelope:

```json
{
  "source": "funding_news",
  "source_name": "Funding News",
  "source_type": "funding_news",
  "base_url": "https://www.uktech.news",
  "records": []
}
```
