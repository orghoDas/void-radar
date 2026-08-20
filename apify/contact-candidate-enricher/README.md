# Contact Candidate Enricher

This actor scans a scored Void Radar company target list for public contact
candidates. It is designed to remove manual searching, not to invent or verify
emails.

## Input

Pass `targets` from `campaigns/phase-6/apify-contact-candidate-input.json`.

```json
{
  "targets": [
    {
      "company_id": "7ea08672-4f49-4a65-ba11-082c288be2b9",
      "company": "Brain Corp",
      "domain": "braincorp.com",
      "target_roles": "CTO; Founder; Head of Talent; VP Engineering",
      "reason_to_write": "Generic job board detected for braincorp.com.",
      "evidence_urls": "https://www.braincorp.com/careers",
      "score": 39
    }
  ],
  "maxItems": 25
}
```

## Output

Rows with `record_type=contact_candidate` contain:

- company identity fields
- candidate name, role, and email when found
- source URL and source excerpt
- `review_status=needs_review`

Download the dataset as CSV, review candidates, set strong rows to
`review_status=approved`, then import with:

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' backend/.venv/bin/python scripts/ingest_reviewed_apify_contacts.py path/to/apify-output.csv
```

Do not approve guessed emails, LinkedIn-only rows, or rows without source URLs.
