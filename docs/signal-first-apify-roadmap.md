# Signal-First Apify Roadmap

This roadmap replaces the YC/accelerator-first build order as the primary
implementation path. YC and EF are archived legacy adapters, not active MVP
lead sources.

The new thesis:

```text
Find companies with a current reason to buy software help.
The strongest first trigger is a stale approved hiring need.
```

Void Radar should therefore start with:

```text
Discovery source
  -> company domain
  -> ATS/job-board detection
  -> stale technical/product/operations roles
  -> score by fit x intent
  -> resolve contacts only for qualified companies
  -> verify through provider data or manual evidence review
  -> send and record outcomes
```

The objective is not a large company database. The objective is qualified
conversations per week.

## Operating Principles

1. Source selection comes before architecture.
2. Prefer public APIs and stable structured feeds over browser scraping.
3. Apify owns collection and crawl execution, not canonical business logic.
4. The Python backend owns identity, validation, scoring, persistence, and
   outcomes.
5. Store raw responses before parsing when possible.
6. Use company domain as the main identity key.
7. Store signals as append-only events.
8. Gate expensive work behind cheap filters.
9. LLM output must be validated before persistence.
10. Prefer provider-backed contact resolution when available; otherwise use
    public-source candidates with manual approval. Do not guess emails.

## ASAP Delivery Target

The fastest useful version should be delivered in 10 working days.

Definition of useful:

```text
100 verified or manually approved targeted contacts exported for outreach
each with:
  company domain
  source provenance
  stale hiring or other trigger signal
  fit score
  intent score
  total score
  reason-to-write
  contact verification or manual-approval status
```

This delivery target intentionally includes outreach readiness. A ranked list
without contacts and a sendable reason is not the real MVP.

## Scope Decision

This roadmap is the active implementation plan.

Dropped from active MVP scope:

- YC/accelerators as the main market.
- Broad research on every company.
- Broad in-house contact discovery across every company.
- Precision@20 as the main success metric.

Deferred until the wedge produces commercial evidence:

- LLM intelligence before validation.
- Generic opportunity inference as the MVP.
- Dashboard-first delivery.

Retained as reusable foundation:

- FastAPI backend and PostgreSQL schema.
- Apify actor structure.
- Domain-first identity rules.
- Raw evidence and provenance rules.
- Contact provenance rules.
- Legacy YC/EF adapters as reference-only utilities.

## Phase 0 - Commercial Validation Starts Immediately

Timeline:

```text
Day 0 to Day 10, in parallel with engineering
```

Purpose:

Test whether the segment and message can create conversations before the
pipeline becomes an infrastructure project.

Actions:

- Define one narrow outreach wedge.
- Buy or manually assemble 100 to 200 contacts that match that wedge.
- Start sending-domain setup and warmup immediately.
- Draft outreach around specific observed pain, not generic capability.
- Record every send, bounce, reply, objection, and meeting.

Suggested first wedge:

```text
B2B SaaS, logistics, operations, or marketplace companies
with technical/product/engineering roles open more than 60 to 90 days
and no obvious large in-house engineering team.
```

Files to add or update:

- `docs/outreach-validation-playbook.md`
- `database/migrations/0007_signal_first_pipeline.sql`

Database work:

- Add `suppression` table if not already present.
- Add `outcomes` table for sends, opens, replies, bounces, unsubscribes, and
  meetings.
- Ensure contacts can record `provider_name`, `verified_at`, and
  `verification_status`.

Acceptance gate:

```text
At least 100 targeted messages sent or ready to send.
Every contact has source, verification status, and suppression check.
Early reply/bounce results are recorded against source and signal.
```

Do not wait for the scraper to be perfect before this phase starts.

## Phase 1 - Core Signal-First Data Model

Timeline:

```text
Day 1 to Day 2
```

Purpose:

Make the existing backend capable of representing the R&D architecture without
rewriting everything.

Current useful foundation:

- `companies` already exists.
- `sources` already exists.
- `source_records` already preserves raw payloads.
- `signals` already exists as an event-like table.
- `scores` already exists.
- `contacts` already exists.

Changes to plan:

- Keep `source_records` as the first raw store for structured source payloads.
- Add `raw_pages` only where Apify crawls arbitrary URLs and page body storage is
  needed.
- Extend `sources` with `tier`, `cadence`, `last_run_at`, and `politeness`
  metadata.
- Add a lightweight `jobs` table only if cron plus direct actor execution becomes
  hard to operate.
- Add ATS-specific tables only for normalized job-board state.

Proposed new tables:

```text
raw_pages
ats_boards
job_postings
suppression
outcomes
parser_versions
```

`signals` remains the canonical event log. `job_postings` stores normalized job
facts; `signals` stores interpreted triggers such as:

```text
STALE_ENGINEERING_ROLE
NEW_PRODUCT_ROLE
HIRING_SPIKE
NO_ATS_FOUND
GITHUB_ENGINEERING_ORG_DETECTED
TECH_STACK_LEGACY_SIGNAL
```

Files to update:

- `database/migrations/0007_signal_first_pipeline.sql`
- `backend/app/schemas/`
- `backend/app/services/`
- `backend/app/api/routes/`
- `docs/phase-02-core-system.md`

Acceptance gate:

```text
The database can store:
  raw source payloads
  discovered domains
  detected ATS boards
  job postings
  append-only signals
  scores
  contacts
  outreach outcomes
```

## Phase 2 - Discovery Sources That Produce Domains

Timeline:

```text
Day 2 to Day 4
```

Purpose:

Feed the pipeline with domains from sources that are easy, public, and
commercially plausible.

Priority source order:

1. HN Who Is Hiring and similar public hiring-intent forums.
2. ATS/job-board URLs discovered from scored company domains.
3. Funding/news RSS sources for recent funding events.
4. SEC EDGAR Form D for US private funding signals.
5. Niche job boards or directories with explicit current demand.

Apify actors:

```text
apify/hn-who-is-hiring-discovery
apify/funding-news-discovery
apify/ats-board-detector
apify/ats-jobs-enricher
apify/sec-form-d-discovery
```

The first ASAP build does not need all of these. It needs one proven
buying-trigger source that produces domains, then ATS enrichment and contact
resolution for qualified companies.

Actor output contract:

```json
{
  "source": "funding_news",
  "source_record_id": "stable-source-id",
  "source_url": "https://source.example/item",
  "company_name": "Example Co",
  "website": "https://example.com",
  "domain": "example.com",
  "location": "London, UK",
  "industry": "Logistics",
  "event_type": "funding",
  "event_date": "2026-08-20",
  "raw_source_payload": {}
}
```

Implementation started:

```text
apify/ats-board-detector
POST /enrichment/ats-boards
POST /enrichment/ats-board-misses
```

Backend flow:

```text
POST /ingestion/source-records
  -> validate source-specific payload
  -> persist source_records
  -> normalize domain
  -> create/update companies
  -> insert company_sources/provenance
  -> insert initial DISCOVERY or FUNDING signal
```

Files to update:

- `apify/README.md`
- `backend/app/api/routes/ingestion.py`
- `backend/app/schemas/ingestion.py`
- `backend/app/services/source_ingestion.py`
- `backend/app/services/identity_resolution.py`
- `scripts/ingest_*`

Acceptance gate:

```text
At least 300 normalized companies with clean domains.
No duplicate company records for the same domain.
Every company has source provenance.
Legacy YC/EF sources are not counted as active discovery success.
```

Implementation started:

```text
POST /ingestion/discovery/source-records
apify/funding-news-discovery
apify/hn-who-is-hiring-discovery
```

## Phase 3 - ATS Board Detection

Timeline:

```text
Day 3 to Day 5
```

Purpose:

Convert company domains into hiring-intent evidence.

Apify actor:

```text
apify/ats-board-detector
```

Input:

```json
{
  "companies": [
    {
      "company_id": "uuid",
      "domain": "example.com"
    }
  ]
}
```

Detection order:

1. Check common career page paths.
2. Check homepage links for career/jobs links.
3. Detect Greenhouse board tokens.
4. Detect Lever company slugs.
5. Detect Ashby board identifiers.
6. Detect Workable widgets or company slugs.
7. Store no-board evidence when nothing is found.

Supported targets:

```text
Greenhouse
Lever
Ashby
Workable
Generic careers page URL
```

Actor output contract:

```json
{
  "company_id": "uuid",
  "domain": "example.com",
  "ats_provider": "greenhouse",
  "board_token": "example",
  "board_url": "https://boards.greenhouse.io/example",
  "careers_url": "https://example.com/careers",
  "confidence": 0.92,
  "evidence_url": "https://example.com/careers",
  "raw_evidence": {}
}
```

Backend flow:

```text
POST /enrichment/ats-boards
  -> validate company/domain match
  -> upsert ats_boards
  -> insert ATS_BOARD_DETECTED signal
  -> insert NO_ATS_FOUND signal where useful
```

Acceptance gate:

```text
At least 100 companies probed for ATS boards.
Detected boards persist with provider, token, URL, confidence, and evidence.
Failures are recorded without blocking the batch.
```

## Phase 4 - Job Posting Ingestion And Stale Role Signals

Timeline:

```text
Day 5 to Day 7
```

Purpose:

Make hiring failure measurable.

Apify actor:

```text
apify/ats-jobs-enricher
```

Implementation started:

```text
apify/ats-jobs-enricher
POST /enrichment/job-postings
```

Engineering status:

```text
Backend ingestion and deterministic signal generation are implemented.
Live acceptance counts still require running this against real company batches.
```

Provider strategy:

- Greenhouse: use public board JSON where available.
- Lever: use public postings JSON where available.
- Ashby: use public board endpoints where available.
- Workable: use public board/posting surfaces where available.
- Generic careers pages: deterministic extraction first, LLM only later.

Normalized job fields:

```text
external_job_id
title
department
location
remote_policy
employment_type
posted_at
first_seen_at
last_seen_at
url
description_text
stack_terms
seniority
is_active
```

Signal rules:

```text
STALE_ENGINEERING_ROLE:
  engineering/product/data/automation/backend/frontend role
  first_seen_at or posted_at older than threshold

HIRING_SPIKE:
  several relevant roles first seen in a short window

TECH_STACK_NEED:
  role description mentions stack or migration/integration pain

OPERATIONS_SOFTWARE_NEED:
  product/ops/data/platform role suggests internal tooling need
```

Default thresholds:

```text
strong intent: 90+ days open
medium intent: 60+ days open
fresh trigger: 0 to 30 days, only if role is highly relevant
```

Backend flow:

```text
POST /enrichment/job-postings
  -> validate board/company link
  -> upsert active job postings
  -> mark missing jobs inactive after repeated absence
  -> insert append-only signals
```

Snapshot note:

```text
Set mark_missing_inactive=true only for complete board snapshots.
Partial/sample runs should leave it false so they cannot deactivate jobs.
```

Acceptance gate:

```text
At least 50 companies have job posting evidence.
At least 20 companies have stale-role or hiring-intent signals.
Each signal points back to one or more job URLs.
```

## Phase 5 - Fit x Intent Scoring

Timeline:

```text
Day 7 to Day 8
```

Purpose:

Prioritize companies for expensive enrichment and contact purchase.

Engineering status:

```text
Backend fit x intent scoring is implemented.
Live acceptance counts still require scoring real signal batches.
```

Replace the old weighted score as the operating decision with:

```text
total_score = fit_score * intent_score / 100
```

Fit score:

```text
industry fit
company size fit
region fit
service fit
absence of strong disqualifiers
```

Intent score:

```text
stale relevant role
fresh funding event
hiring spike
procurement deadline
recent launch or expansion
```

Disqualifiers:

```text
large active public engineering org
agency/consultancy competitor
crypto-only or unclear business
unverified/free-mail domain
no accessible company website
suppressed domain
```

Backend work:

- Add `score_version`.
- Keep old score fields if useful for display.
- Store the scoring inputs and reasons as JSON.
- Record a score every time the model runs, not just latest score.

Acceptance gate:

```text
Top 50 companies each have:
  fit score
  intent score
  total score
  positive reasons
  penalties
  trigger evidence
```

## Phase 6 - Contact Resolution, Verification, And Export

Timeline:

```text
Day 8 to Day 10
```

Purpose:

Finish the actual MVP: send-ready prospects.

Engineering status:

```text
Suppression-safe contact export and outcome import are implemented.
Live acceptance still requires exporting 100 real provider-verified or manually
approved contacts.
```

Policy:

- Do not guess emails.
- Do not build SMTP probing.
- Do not scrape LinkedIn programmatically.
- Use manual or provider contacts for the first campaign.
- Verify provider contacts before export, or manually approve public-source
  candidates with source evidence.
- Check suppression before every send.

Provider abstraction:

```text
ContactProvider.resolve(company_domain, target_roles)
EmailVerifier.verify(email)
ManualReviewQueue.approve(public_source_candidate)
```

Target roles by signal:

```text
stale engineering roles:
  CTO, VP Engineering, Head of Product, COO, founder

operations/internal system signals:
  COO, Head of Operations, Head of Digital, CIO, founder

procurement:
  procurement contact, IT director, transformation lead
```

Export shape:

```json
{
  "company": "Example Co",
  "domain": "example.com",
  "contact_name": "Jane Doe",
  "role": "VP Engineering",
  "email": "jane@example.com",
  "verified_at": "2026-08-20T10:00:00Z",
  "source": "provider_or_manual_review",
  "score": 82,
  "reason_to_write": "Backend role open for 104 days; careers page still active.",
  "evidence_urls": ["https://boards.greenhouse.io/example/jobs/123"]
}
```

Acceptance gate:

```text
100 provider-verified or manually approved contacts exported.
Every export row has a reason-to-write and evidence URL.
Suppressed emails/domains are excluded.
Outcomes can be re-imported after sending.
```

## Phase 7 - Company Researcher For Qualified Companies Only

Timeline:

```text
Week 3
```

Purpose:

Use Apify for long-tail website research only after cheap scoring identifies
companies worth deeper inspection.

Existing actor:

```text
apify/company-researcher
```

Current implementation status:

```text
Deterministic pilot implemented for send-ready companies.
LLM summarization is still deferred.
```

Change in behavior:

- Do not run for every discovered company.
- Run only for top-tier scored companies.
- Crawl a small page set.
- Store raw pages and deterministic extracted fields.
- Send cleaned page text to LLM only when needed.

Target pages:

```text
homepage
about
product
pricing
customers
case studies
careers
blog/news
team
contact
```

Output:

```text
positioning
business model
customer type
technology mentions
contact routes
decision-maker names if explicitly visible
service-fit evidence
```

Acceptance gate:

```text
Model spend per qualified company is known.
At least 25 enriched companies are manually sampled.
No model-derived contact enters contacts without validation.
```

Pilot files:

- `scripts/export_phase7_company_research_input.py`
- `scripts/ingest_phase7_company_research.py`
- `campaigns/phase-7/company-research-workflow.md`

## Phase 8 - Hybrid Parser Generation

Timeline:

```text
Week 3 to Week 4
```

Purpose:

Use LLMs to generate deterministic parsers for repeated source layouts, instead
of paying an LLM to extract the same structure every run.

Parser lifecycle:

```text
fetch representative pages
  -> ask LLM for selectors/schema mapping
  -> validate against 5 to 10 known pages
  -> persist parser version
  -> run parser deterministically
  -> monitor success rate
  -> regenerate when success falls below threshold
```

Parser storage:

```text
source
schema_version
selector_json
generated_at
validated_at
success_rate
sample_size
status
```

Acceptance gate:

```text
At least one repeated-layout source uses generated deterministic selectors.
Parser success rate is measured per run.
Failed parser output is rejected, not stored as fact.
```

## Phase 9 - Segment C Expansion

Timeline:

```text
Week 4 onward
```

Purpose:

Add less-contested, higher-value markets after the first hiring-intent loop
works.

Priority sources:

```text
public procurement portals
government tender APIs
trade association directories
industry member directories
Google Places or local directories for narrow vertical/geography tests
```

First Segment C wedge:

```text
logistics, manufacturing, distribution, healthcare operations, or professional
services companies with procurement/software/internal systems indicators.
```

Acceptance gate:

```text
Reply rates are attributable by source and signal type.
At least one Segment C source produces qualified conversations.
Scoring weights are revised from real outcomes.
```

## Phase 10 - Dashboard And Feedback Loop

Timeline:

```text
After 100-contact export is working
```

Purpose:

Build UI around decisions and outcomes, not raw data volume.

Dashboard views:

```text
Qualified prospects
Signal review
ATS/job evidence
Contact verification status
Export batches
Outcomes by source
Outcomes by signal type
Suppression list
Parser/source health
```

Metrics:

```text
qualified conversations per week
contacts exported
bounce rate
reply rate
positive reply rate
source parse success rate
records added per source
model spend per qualified company
verification pass rate
queue age
```

Acceptance gate:

```text
Void can see which sources and signals create replies.
Manual review updates scoring inputs or labels.
Outcome data influences future scoring.
```

## Implementation Order For The Next Sprint

Build in this exact order:

1. Add `0007_signal_first_pipeline.sql`.
2. Add backend schemas/services/routes for ATS board ingestion.
3. Add `apify/ats-board-detector`.
4. Add backend schemas/services/routes for job posting ingestion.
5. Add `apify/ats-jobs-enricher`.
6. Add signal generation for stale roles.
7. Add fit x intent scoring.
8. Add CSV export for top scored contacts/prospects.
9. Add manual/provider contact ingestion if provider integration is not ready.
10. Send the first 100-contact campaign and import outcomes.

## What To Defer

Defer these until after the first 100-contact send:

- Full dashboard.
- n8n orchestration.
- General-purpose crawler.
- Proxy rotation or anti-detection.
- LinkedIn automation.
- In-house email guessing.
- In-house email verification.
- Broad accelerator coverage.
- More than one or two discovery sources.
- Runtime LLM extraction for every company.

## Success Definition

Void Radar is successful when it reliably produces:

```text
qualified conversations per week / engineering hours spent
```

The first technical milestone is not source coverage. It is:

```text
100 verified contacts with strong trigger evidence exported within 10 working days.
```

Everything that does not help reach that milestone should wait.
