# ats-board-detector

Detects applicant tracking system boards for already resolved company domains.

This is Phase 3 of the signal-first pipeline:

```text
company domain
  -> homepage/careers probe
  -> ATS board detection
  -> POST /enrichment/ats-boards
```

Supported detections:

- Greenhouse
- Lever
- Ashby
- Workable
- Generic careers page fallback

Expected positive output shape:

```json
{
  "company_id": "uuid-or-null",
  "domain": "example.com",
  "ats_provider": "greenhouse",
  "board_token": "example",
  "board_url": "https://boards.greenhouse.io/example",
  "careers_url": "https://example.com/careers",
  "confidence": 0.92,
  "evidence_url": "https://example.com/careers",
  "raw_evidence": {}
}
```

Post positive dataset records to:

```text
POST /enrichment/ats-boards
```

Misses are written to Apify key-value storage as `ATS_MISSES` by default. If
`emitMissesToDataset=true`, misses are pushed with `record_type: "miss"` and can
be posted to:

```text
POST /enrichment/ats-board-misses
```

## Local Run

```bash
npm install
npm start
```

For isolated local validation:

```bash
CRAWLEE_STORAGE_DIR=/private/tmp/void-radar-ats-test npm start
```
