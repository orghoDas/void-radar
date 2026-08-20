# Void Radar Phase 4 Identity Resolution

> Status: retained foundation, not the active implementation plan. Domain-first
> identity resolution remains important, but the active build order is
> [signal-first-apify-roadmap.md](signal-first-apify-roadmap.md).

Phase 4 turns raw trusted source records into canonical company identities.

```text
source_records
  -> field normalization
  -> domain-first identity resolution
  -> companies
  -> company_aliases
  -> source_identities
  -> founders + company_founders when available
  -> founder_profiles when public profile links are available
  -> source_records.company_id
```

This phase does not research company websites, infer opportunities, detect
signals, score prospects, or enrich contacts.

## What This Phase Adds

- Company name normalization.
- Domain normalization.
- Location normalization.
- Domain-first canonical company creation.
- Source-record-to-company linking.
- Company alias preservation.
- External source identity preservation.
- Founder and company-founder link creation when source payloads include founder
  names.
- Founder profile/contact-link preservation when source payloads include public
  profile links.
- Review state for records that cannot be safely linked.

## Database Changes

Migration:

```text
database/migrations/0002_identity_resolution.sql
```

Adds source record processing fields:

```text
processing_status
processed_at
processing_notes
```

Adds review table:

```text
identity_resolution_reviews
```

Additional hardening migration:

```text
database/migrations/0003_source_identities_and_founders.sql
```

Adds:

```text
source_identities
founder name/location uniqueness index
```

Founder profile/contact-link migration:

```text
database/migrations/0004_founder_profiles.sql
```

Adds:

```text
founder_profiles
```

## Resolution Policy

Domain is the strongest identifier in this phase.

```text
normalized website domain exists?
  -> yes: find existing company by canonical_domain
      -> found: link source record
      -> not found: create candidate company and link source record
      -> store source external ID in source_identities
      -> create founders if payload includes founder names
      -> store public founder profile links if source provides them
  -> no: create identity review item
```

The current implementation intentionally avoids fuzzy name merging. Fuzzy
matching can be added later once we have review UI and evidence display.

Founder emails are not inferred. Store direct founder emails only when a public
or permitted enrichment source provides them with source URL and confidence.
YC/EF profile links are legacy evidence only and should not drive the active MVP
pipeline.

## Run Locally

Apply migrations:

```bash
/opt/homebrew/opt/postgresql@16/bin/psql \
  -h /tmp \
  -p 5432 \
  -d void_radar \
  -v ON_ERROR_STOP=1 \
  -f database/migrations/0002_identity_resolution.sql
```

```bash
/opt/homebrew/opt/postgresql@16/bin/psql \
  -h /tmp \
  -p 5432 \
  -d void_radar \
  -v ON_ERROR_STOP=1 \
  -f database/migrations/0003_source_identities_and_founders.sql
```

```bash
/opt/homebrew/opt/postgresql@16/bin/psql \
  -h /tmp \
  -p 5432 \
  -d void_radar \
  -v ON_ERROR_STOP=1 \
  -f database/migrations/0004_founder_profiles.sql
```

Legacy only: process YC source records:

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' \
  backend/.venv/bin/python scripts/process_yc_source_records.py
```

API endpoint:

```text
POST /identity/y-combinator/process-source-records
```

Optional limit:

```text
POST /identity/y-combinator/process-source-records?limit=10
```

## Acceptance Criteria

Phase 4 is complete when:

- Normalizers are tested.
- Legacy YC source records can create canonical companies.
- Source records are linked to company IDs.
- Company aliases are preserved.
- Source identities are preserved.
- Founder records are created only when source payloads include founders.
- Public founder profile links are preserved when present.
- Missing-domain records go to review state.
- Running the resolver twice does not create duplicate companies.
