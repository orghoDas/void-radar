# Apollo Verified Contact Enricher

This actor is the provider-backed Phase 6 path. It uses Apollo as the contact
verification provider and emits rows shaped for Void Radar's verified-provider
import.

## Why This Exists

The public website crawler produced very low decision-maker yield. This actor
keeps Apify as the orchestration layer but moves contact resolution to a real
provider.

## Required Secret

Preferred: set the encrypted actor input field:

```text
apolloApiKey
```

Alternative: set an Apify actor secret or environment variable:

```text
APOLLO_API_KEY
```

Do not paste the key into repo files.

## Input

Generate input from the repo:

```bash
backend/.venv/bin/python scripts/export_phase6_apollo_input.py --limit 30 --min-score 20
```

Then paste:

```text
campaigns/phase-6/apollo-verified-contact-input.json
```

into this actor.

## Output

Rows with `record_type=verified_provider_contact` are ready for:

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' backend/.venv/bin/python scripts/ingest_verified_provider_contacts.py campaigns/phase-6/apollo-verified-contacts.csv --provider-name apollo
```

The actor only emits rows where Apollo returns an explicit email with
`email_status=verified`.

## Apollo Endpoints

- People Search: `POST /api/v1/mixed_people/api_search`
- Bulk People Enrichment: `POST /api/v1/people/bulk_match`

People Search finds candidate Apollo person IDs by company domain/title. Bulk
People Enrichment is the credit-consuming step that can return verified email.

## Safety

- `maxEnrichmentsPerRun` caps paid enrichment attempts.
- Phone and waterfall enrichment are disabled by default.
- The actor does not guess emails.
- The backend still applies suppression and score gates before outreach export.
