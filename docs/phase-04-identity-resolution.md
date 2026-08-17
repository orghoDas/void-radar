# Void Radar Phase 4 Identity Resolution

Phase 4 turns raw trusted source records into canonical company identities.

```text
source_records
  -> field normalization
  -> domain-first identity resolution
  -> companies
  -> company_aliases
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

## Resolution Policy

Domain is the strongest identifier in this phase.

```text
normalized website domain exists?
  -> yes: find existing company by canonical_domain
      -> found: link source record
      -> not found: create candidate company and link source record
  -> no: create identity review item
```

The current implementation intentionally avoids fuzzy name merging. Fuzzy
matching can be added later once we have review UI and evidence display.

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

Process YC source records:

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
- YC source records can create canonical companies.
- Source records are linked to company IDs.
- Company aliases are preserved.
- Missing-domain records go to review state.
- Running the resolver twice does not create duplicate companies.

