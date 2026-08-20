# hn-who-is-hiring-discovery

Collects public Hacker News "Who is Hiring" comments through the Algolia HN API
and emits standardized domain-producing discovery records for Void Radar.

This is a Phase 2 discovery actor with unusually strong alignment to the new
pipeline: each record already contains a hiring-intent context.

Expected output shape:

```json
{
  "source": "hacker_news_who_is_hiring",
  "source_url": "https://news.ycombinator.com/item?id=123",
  "source_record_id": "123",
  "company_name": "Example AI",
  "website": "https://example.ai",
  "domain": "example.ai",
  "location": "Remote",
  "industry": null,
  "stage": null,
  "status": "active",
  "employee_count": null,
  "description": "Hiring post text.",
  "tags": ["hiring", "hacker_news"],
  "event_type": "hiring",
  "event_date": "2026-08-20",
  "event_summary": "Example AI is hiring.",
  "raw_source_payload": {}
}
```

POST exported records to:

```text
POST /ingestion/discovery/source-records
```

Envelope:

```json
{
  "source": "hacker_news_who_is_hiring",
  "source_name": "Hacker News Who is Hiring",
  "source_type": "hiring_discovery",
  "base_url": "https://news.ycombinator.com",
  "records": []
}
```
