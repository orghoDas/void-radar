# Void Radar Phase 5 Contact Enrichment

Phase 5 turns verified founder/contact evidence into outreach-ready contact
records.

```text
public/permitted evidence
  -> validate source type + source URL
  -> resolve company by id or domain
  -> resolve or create founder link when a founder name is provided
  -> contacts
  -> contact_enrichment_evidence
```

## Policy

Emails are never guessed from names or domains.

Acceptable email sources:

- `company_website`
- `founder_personal_website`
- `public_profile`
- `trusted_source_payload`
- `verified_provider`
- `manual_review`

Every stored email must keep:

- source type
- source URL
- confidence
- verification status
- raw evidence metadata when available

## Database Changes

Migration:

```text
database/migrations/0005_contact_enrichment.sql
```

Adds provenance fields to `contacts`:

```text
source_url
source_type
provider_name
evidence
```

Adds:

```text
contact_enrichment_evidence
```

## API

Ingest explicit evidence:

```text
POST /contacts/enrichment/evidence
```

Extract emails from public page HTML/text already collected by an approved
workflow:

```text
POST /contacts/enrichment/public-page
```

Backfill emails that trusted source payloads already stored in founder profiles:

```text
POST /contacts/enrichment/founder-profiles/backfill
```

## CLI

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' \
  backend/.venv/bin/python scripts/ingest_contact_evidence.py contacts.json
```

Example `contacts.json`:

```json
{
  "records": [
    {
      "company_domain": "example.ai",
      "founder_name": "Jane Founder",
      "role": "CEO",
      "email": "jane@example.ai",
      "source_type": "founder_personal_website",
      "source_url": "https://jane.example.ai/contact"
    }
  ]
}
```

## Acceptance Criteria

- Public/manual/provider email evidence can be ingested.
- Emails without a resolvable company are rejected, not stored.
- Founder-level evidence creates or links founder records.
- Duplicate evidence does not create duplicate evidence rows.
- Existing contacts are updated rather than duplicated.
- All contacts keep source URL and verification metadata.
