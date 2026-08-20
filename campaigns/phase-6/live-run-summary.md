# Phase 6 Live Run Summary

Date: 2026-08-20

## What Ran

- Applied the signal-first database schema through `database/migrations/0007_signal_first_pipeline.sql`.
- Ran live Apify HN Who Is Hiring discovery.
- Ingested 100 discovery records.
- Created or matched 100 hiring discovery signals.
- Scored the current signal-backed company set.
- Ran a bounded ATS detector pass on the strongest scored companies.
- Ingested 2 detected ATS boards and 8 ATS misses.
- Ran the jobs enricher for detected ATS boards.
- Ingested 1 job posting.
- Exported scored, signal-backed companies for provider-side contact lookup.

## Current Live Database Counts

- Companies: 194
- Signals: 110
- ATS boards: 2
- Job postings: 1
- Score rows: 192
- Contacts: 4
- Verified contacts: 0
- Exportable outreach rows at score >= 50: 0

## Generated Files

- `campaigns/phase-6/contact-provider-targets.csv`
  - 86 companies ready for Apollo or another contact provider.
  - Use this file to buy or verify contacts for the listed domains and target roles.
- `campaigns/phase-6/verified-contact-import-template.csv`
  - 86 matching rows with company, domain, target roles, score, reason-to-write, and evidence.
  - Fill `full_name`, `role`, `email`, `source_url`, and `provider_name` after provider verification.

## Hard Blocker

The Phase 6 export is blocked on verified contacts. This is intentional.

Do not guess emails, scrape LinkedIn, or use unverified contacts. The outreach export only allows contacts with `provider_verified` or `manual_verified` status.

## Next Command After Provider CSV Is Filled

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' backend/.venv/bin/python scripts/ingest_verified_provider_contacts.py campaigns/phase-6/verified-contact-import-template.csv --provider-name apollo
```

After import, use `POST /outreach/export.csv` or `POST /outreach/export` to create the campaign export.
