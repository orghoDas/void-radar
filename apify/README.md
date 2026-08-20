# Apify Actors

Apify is the collection and crawling layer for Void Radar.

Active actors:

- `funding-news-discovery`: collects public funding/news feed items that expose company domains and event signals.
- `hn-who-is-hiring-discovery`: collects public Hacker News "Who is Hiring" comments with company domains and hiring intent.
- `ats-board-detector`: detects Greenhouse, Lever, Ashby, Workable, and generic careers pages for resolved company domains.
- `ats-jobs-enricher`: fetches normalized job postings from detected ATS boards.
- `contact-candidate-enricher`: crawls targeted company pages and emits reviewable public-source contact candidates for scored companies.
- `apollo-verified-contact-enricher`: optional provider-backed actor that uses Apollo People Search and Bulk People Enrichment to emit verified-provider contact rows for scored companies when the Apollo plan allows API access.
- `company-researcher`: researches targeted pages for an already resolved company domain.

Legacy actors:

- `yc-company-discovery`: archived adapter for historical ingestion tests only.
  It is not an active MVP lead source.

Apify should not own canonical identity resolution, scoring, or business logic.
Those live in the Python backend.

Provider-free operation is supported: run `contact-candidate-enricher`, build a
manual review queue with `scripts/build_phase6_manual_review_queue.py`, approve
usable rows, and import them as `manual_review` / `manual_verified` evidence.
