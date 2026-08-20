# ats-jobs-enricher

Fetches job postings from detected ATS boards and emits normalized records for:

```text
POST /enrichment/job-postings
```

Supported sources:

- Greenhouse public board API
- Lever public postings API
- Ashby public posting API
- Workable/generic HTML fallback
- Generic careers pages with deterministic link/title extraction

Expected output shape:

```json
{
  "company_id": "uuid-or-null",
  "domain": "example.com",
  "ats_provider": "greenhouse",
  "board_token": "example",
  "board_url": "https://boards.greenhouse.io/example",
  "external_job_id": "123",
  "title": "Senior Backend Engineer",
  "department": "Engineering",
  "location": "Remote",
  "remote_policy": "remote",
  "employment_type": "full_time",
  "posted_at": "2026-08-20T10:00:00.000Z",
  "first_seen_at": "2026-08-20T10:00:00.000Z",
  "last_seen_at": "2026-08-20T10:00:00.000Z",
  "url": "https://boards.greenhouse.io/example/jobs/123",
  "description_text": "Job description text.",
  "stack_terms": ["python", "postgresql"],
  "seniority": "senior",
  "is_active": true,
  "raw_payload": {}
}
```

## Local Run

```bash
npm install
npm start
```

For isolated local validation:

```bash
CRAWLEE_STORAGE_DIR=/private/tmp/void-radar-ats-jobs-test npm start
```
