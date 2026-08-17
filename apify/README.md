# Apify Actors

Apify is the collection and crawling layer for Void Radar.

Initial actors:

- `yc-company-discovery`: collects standardized company/founder records from Y Combinator.
- `company-researcher`: researches targeted pages for an already resolved company domain.

Apify should not own canonical identity resolution, scoring, or business logic.
Those live in the Python backend.

