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
  -> decision_maker_candidates for CXO/head/business POC evidence
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

Decision-maker candidate migration:

```text
database/migrations/0006_decision_maker_candidates.sql
```

Adds:

```text
decision_maker_candidates
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

Collect public emails from company websites:

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' \
  backend/.venv/bin/python scripts/enrich_contacts_from_websites.py \
    --limit 10 \
    --dry-run
```

When the dry-run output looks good, run without `--dry-run`:

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' \
  backend/.venv/bin/python scripts/enrich_contacts_from_websites.py \
    --limit 10
```

The website collector checks only a small fixed list of public company pages and
stores explicit emails as company-level evidence. By default it skips generic
mailboxes like `sales@`, `support@`, and `info@`, and skips emails outside the
company domain. Use `--include-generic` or `--include-external-emails` when a
manual review workflow needs broader collection. It does not guess founder email
ownership.

The same collector also scans public page text for decision-maker titles:

- Founder / co-founder / CEO
- COO / CMO / CRO / CBO / other chief officer roles
- Head of Business / Growth / Partnerships / Sales / Revenue
- Head of Product / Marketing / Operations
- VP or Director roles in the same business-facing functions

Those people are stored as `decision_maker_candidates`. A candidate can exist
without an email, because names and roles are still useful for LinkedIn/manual
research. Email evidence remains separate and must still be explicit.

Ingest manually verified or provider-supplied evidence:

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
- Website collection supports dry-run before writing contacts.
- Website collection captures CXO/head/business POC candidates with source URL.
