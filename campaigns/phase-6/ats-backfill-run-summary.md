# ATS Backfill And Provider-Free Contact Run

Date: 2026-08-21

## What Ran

- Built a filtered ATS probe target list from signal-backed companies.
- Ran `apify/ats-board-detector` locally across 79 clean domains.
- Ingested 61 ATS boards and 17 board misses.
- Ran `apify/ats-jobs-enricher` across all 61 boards.
- Ingested 452 job postings and regenerated deterministic signals.
- Re-scored all 194 companies.
- Built a provider-free contact review queue from self-published HN addresses.

## Before / After

| Metric | Before | After |
| --- | ---: | ---: |
| ATS boards | 2 | 61 |
| Job postings | 1 | 452 |
| Jobs with `posted_at` | 1 | 316 |
| Companies with job evidence | 1 | 41 |
| Companies with intent signals | 0 | 35 |
| Roles open 90+ days | 0 | 86 |
| Companies scoring >= 50 | 0 | 20 |
| Contact candidates with a trigger | 0 | 22 |

## Phase Gates

- Phase 3 (100 companies probed): **not met** - 79 probed, limited by the
  clean-domain supply, not by the detector.
- Phase 4 (50 companies with job evidence): **not met** - 41.
- Phase 4 (20 companies with stale/intent signals): **met** - 35.
- Phase 6 (100 exported contacts): **not met** - 22 candidates pending review.

## Bugs Found And Fixed

1. `apify/ats-jobs-enricher` read `job.publishedDate` for Ashby, but the Ashby
   posting API returns `publishedAt`. All 239 Ashby jobs were dateless, so no
   staleness could be computed. Fixed; dated jobs went from 77 to 316.

2. `backend/app/services/signal_enrichment.py` decided role relevance by
   matching `ROLE_KEYWORDS` against the full job blob including
   `description_text`. Tech-company boilerplate mentions engineering in every
   posting, so `STALE_ENGINEERING_ROLE` fired on "Executive Underwriter",
   "Controller", and "Social Media & Content Lead". Relevance now comes from
   title and department; term matching still uses the full description.
   Job-derived signals fell from 824 to 383, all verified technical roles.
   Regression test: `test_non_technical_role_does_not_create_stale_engineering_signal`.

## Known Issues Not Fixed

- `normalize_domain()` in `backend/app/identity/normalize.py` does no TLD
  validation, so HN comment prose became companies: `e.g`, `node.js`,
  `process.you`, `which.your`, `welcome.we`, `issues.i`. It also glues the
  following word onto the TLD (`middesk.comat`, `apexdp.comwe`,
  `histowiz.comabout`, `withclad.comclad`). 17 of 96 HN companies are junk.
  `scripts/build_ats_probe_targets.py` filters and repairs these at read time;
  the parser itself is still wrong.
- Scoring does not apply the "large in-house engineering org" disqualifier.
  Stripe, PostHog, and Railway all score 61 with intent 100.
- One third-party board was quarantined: `phase.law` linked to Pear VC's Ashby
  board from its homepage. Pulling jobs from it would attribute another
  company's roles. See `/tmp/ats-quarantine.json`. The detector has no guard for
  boards discovered via outbound homepage links.
- 20 of 61 boards failed to yield jobs, mostly generic careers pages.

## Next Command

Review and set `review_status` in:

```text
campaigns/phase-6/hn-self-published-contact-review-queue.csv
```

Then import approved rows:

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' \
  backend/.venv/bin/python scripts/ingest_reviewed_apify_contacts.py \
  campaigns/phase-6/hn-self-published-contact-review-queue.csv \
  --provider-name hn_self_published
```
