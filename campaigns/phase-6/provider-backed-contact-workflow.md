# Provider-Backed Contact Workflow

Use this when public website crawling is not producing enough decision-maker
contacts.

## 1. Generate Apollo Input

```bash
backend/.venv/bin/python scripts/export_phase6_apollo_input.py --limit 30 --min-score 20
```

This writes:

```text
campaigns/phase-6/apollo-verified-contact-input.json
```

The input includes:

- scored company targets
- target titles and seniorities
- a hard enrichment cap
- phone and personal email enrichment disabled

## 2. Push The Actor

```bash
cd apify/apollo-verified-contact-enricher
apify push
```

Actor:

```text
apollo-verified-contact-enricher
```

## 3. Add Apollo Secret

In Apify, set the actor environment variable or secret:

```text
APOLLO_API_KEY
```

Do not commit provider keys into the repo.

## 4. Run The Actor

Paste this JSON as input:

```text
campaigns/phase-6/apollo-verified-contact-input.json
```

Keep the first run small:

```text
maxItems: 30
perCompanySearchLimit: 8
maxContactsPerCompany: 2
maxEnrichmentsPerRun: 50
```

## 5. Export Provider Contacts

After the actor finishes, export the dataset as CSV and save it as:

```text
campaigns/phase-6/apollo-verified-contacts.csv
```

Rows with `record_type=verified_provider_contact` can be imported.

## 6. Import Verified Contacts

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' backend/.venv/bin/python scripts/ingest_verified_provider_contacts.py campaigns/phase-6/apollo-verified-contacts.csv --provider-name apollo
```

## 7. Export Outreach

After import:

```text
POST /outreach/export.csv
```

or generate a local pilot CSV through the backend service.

## Rules

- Do not guess emails.
- Do not scrape LinkedIn.
- Do not import search-only contacts without a verified email.
- Keep enrichment caps low until yield is known.
- Let the backend suppression and score gates decide final send readiness.
