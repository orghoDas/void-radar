# Void Radar Lead Collection - Final Run

Date: 2026-08-21

Scope: lead collection. Sending and outcome capture are a later phase.

## Final State

| Metric | Session start | Final |
| --- | ---: | ---: |
| Companies | 194 | 780 |
| Discovery sources | 1 (HN) | 2 (HN, funding news) |
| ATS boards | 2 | 430 |
| Job postings | 1 | 2568 |
| Companies with job evidence | 1 | 268 |
| Companies with stale/aging role signals | 11 | 72 |
| Signals | 110 | 3873 |
| Companies scoring >= 50 | 0 | 136 |
| Contact candidates | 0 | 214 |
| Active generated parsers | 0 | 5 |

## Deliverables

- `campaigns/phase-6/send-ready-sheet.csv` - 214 leads ranked by evidence tier.
- `campaigns/phase-6/hn-self-published-contact-review-queue.csv` - approval queue
  feeding `scripts/ingest_reviewed_apify_contacts.py`.

Tiers in the send-ready sheet:

```text
A  40  real trigger + personal address on company domain
B  15  real trigger + generic on-domain address
C   4  real trigger, off-domain address
D  77  personal on-domain, HN post only
E  78  weak
```

## Phase Gates

- Phase 2 (300 companies): met - 780.
- Phase 3 (100 probed): met - 677 probed across four passes.
- Phase 4 (50 companies with job evidence): met - 268.
- Phase 4 (20 companies with intent signals): met - 72 stale/aging alone.
- Phase 5 (top 50 scored with reasons): met.
- Phase 7 (company researcher pilot): met previously.
- Phase 8 (>=1 source on generated selectors): met - 5 active parsers.
- Phase 6 (100 contacts exported): not met - 214 candidates await human approval.
- Phase 0 / 9 / 10: out of current scope; all require send outcomes.

## Bugs Found And Fixed

1. `ats-jobs-enricher` read Ashby `publishedDate`; the API returns `publishedAt`.
   Dated jobs went from 77 to 1499, which is what makes staleness computable.
2. Role relevance matched `ROLE_KEYWORDS` against full `description_text`.
   Tech-company boilerplate mentions engineering everywhere, so underwriters and
   controllers became stale technical roles. Relevance now comes from the title.
3. Companies file non-technical roles under an Engineering department, so a
   department gate could not catch them. Added a title-level veto.
4. `normalize_domain` had no TLD validation: `e.g`, `node.js`, `process.you`
   became companies. Now validated against a bundled IANA list, with repair for
   suffixes glued to the next word (`middesk.comat` -> `middesk.com`).
5. HN prose fallback parsed sentence boundaries as hostnames. Restricted to
   suffixes companies actually publish under.
6. ATS board tokens were harvested from `script[src]`, so embed widgets produced
   tokens of `js` and `embed`. Now validated.
7. One Lever 404 aborted a 338-board batch. Failures are recorded per board.
8. Funding article pages embed analytics scripts; `googletagmanager.com` was
   captured as a company domain. Blocklisted 18 tracker/CDN hosts.
9. Parser prompt truncated pages to 12k chars, which on modern careers pages is
   all `<head>` and scripts. The model correctly returned nulls. Condensing
   instead of truncating took one sample from 0 to 11 job-title mentions.

## Quarantine Results

`scripts/split_ats_detections.py` holds back boards that cannot be attributed:

- `whoishiringjobs.com`, a job aggregator, linked to 68 other companies' boards.
  Unquarantined it would have owned all of them and their jobs. Blocklisted
  along with 11 similar aggregators.
- `phase.law` linked to Pear VC's Ashby board from its homepage.
- Junk tokens from embed scripts.

Quarantined rows are kept for review, not dropped: a rebrand and a third-party
board look identical from the token alone.

## Known Limits

- Parser generation cleared only 3 of 58 boards that had produced no jobs. That
  population self-selects for Workday hosts and SPAs with no server-rendered job
  markup, which CSS selectors cannot reach. A headless browser is the fix.
- Generic careers-page extraction still yields some junk titles
  ("Simplify TasksConnect"), which inflates HIRING_SPIKE descriptions.
- Scoring does not apply a large-in-house-engineering-org disqualifier, so
  Stripe, MongoDB and N26 rank alongside small prospects.
- 5 legacy junk companies from before the parser fix remain (`e.g`, `issues.i`).
- `suppression` is empty. It must be populated before any send.
