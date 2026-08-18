# Void Radar

Void Radar is an internal prospect intelligence system for Void Studio.

It is designed to answer:

```text
Which companies should Void investigate, what could Void offer them, why does
the opportunity make sense, and why might now be a good time?
```

The project will be built phase by phase. The first milestone is one complete
YC-to-scoring loop before adding more sources, contact enrichment, monitoring,
automation, or outreach.

## Current Phase

Phase 1 defines the foundation:

- Initial ICP
- Void service taxonomy
- Prospect types
- Scoring rules
- Exclusion criteria
- Provenance and evidence rules

See [docs/phase-01-foundation.md](docs/phase-01-foundation.md).

Phase 2 creates the core system skeleton:

- FastAPI backend foundation
- PostgreSQL/Supabase schema migration
- Environment-based configuration
- Apify, frontend, and workflow boundaries

See [docs/phase-02-core-system.md](docs/phase-02-core-system.md).

Phase 3 adds the first trusted discovery source:

- YC company discovery actor
- Standardized raw YC source record shape
- FastAPI ingestion endpoint
- Idempotent `sources` and `source_records` persistence

See [docs/phase-03-yc-discovery.md](docs/phase-03-yc-discovery.md).

Phase 4 turns raw source records into canonical identities:

- Domain/name/location normalization
- Domain-first company creation
- Source-record-to-company linking
- Alias preservation
- Review state for ambiguous records

See [docs/phase-04-identity-resolution.md](docs/phase-04-identity-resolution.md).

Phase 5 enriches contacts only from explicit permitted evidence:

- Manual or provider-supplied contact evidence ingestion
- Public company website email collection
- CXO/head/business POC candidate discovery from public pages
- Entrepreneurs First source ingestion for founder/CXO LinkedIn evidence
- Contact provenance and duplicate handling

See [docs/phase-05-contact-enrichment.md](docs/phase-05-contact-enrichment.md).
