# Void Radar

Void Radar is an internal prospect intelligence system for Void Studio.

It is designed to answer:

```text
Which companies should Void investigate, what could Void offer them, why does
the opportunity make sense, and why might now be a good time?
```

The project will be built phase by phase. The primary milestone is now a
signal-first Apify pipeline that finds companies with current buying triggers,
especially stale technical/product hiring needs, and exports provider-verified
or manually approved contacts for outreach.

See [docs/signal-first-apify-roadmap.md](docs/signal-first-apify-roadmap.md).

## Active Track

The active implementation path is the signal-first Apify roadmap:

1. Run commercial validation immediately with a narrow outreach wedge.
2. Discover companies from sources that produce domains and current trigger
   evidence.
3. Detect ATS/job boards and ingest job postings.
4. Create stale-hiring and related intent signals.
5. Score prospects with `fit x intent`, including decay and disqualifiers.
6. Resolve contacts only for qualified companies, through a provider or
   public-source manual review.
7. Export a suppression-checked send list and record outreach outcomes.

See [docs/signal-first-apify-roadmap.md](docs/signal-first-apify-roadmap.md).
Use [docs/outreach-validation-playbook.md](docs/outreach-validation-playbook.md)
for the parallel Phase 0 campaign workflow.

## Dropped Or Deferred

The previous YC/accelerator-first, dashboard-first approach is no longer the
primary build order.

Dropped from active MVP scope:

- YC/accelerators as the main market.
- Broad research on every company.
- In-house contact discovery across every company.
- Precision@20 as the main success metric.

Deferred until commercial validation proves the wedge:

- LLM intelligence before validation.
- Generic opportunity inference as the MVP.
- Dashboard-first delivery.

## Retained Foundation

The legacy docs still contain useful foundation work, but they are not the
active execution plan:

- [Void Radar Implementation Plan.md](<Void Radar Implementation Plan.md>)
- [docs/phase-01-foundation.md](docs/phase-01-foundation.md)
- [docs/phase-02-core-system.md](docs/phase-02-core-system.md)
- [docs/phase-03-yc-discovery.md](docs/phase-03-yc-discovery.md)
- [docs/phase-04-identity-resolution.md](docs/phase-04-identity-resolution.md)
- [docs/phase-05-contact-enrichment.md](docs/phase-05-contact-enrichment.md)

Retain the reusable pieces: FastAPI, PostgreSQL schema, Apify actor structure,
domain identity rules, evidence provenance, and contact provenance. YC and EF
adapters are archived legacy utilities only; they are not active discovery
sources for the MVP.
