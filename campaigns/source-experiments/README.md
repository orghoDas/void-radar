# Source Experiments

Use this folder to evaluate real-world lead sources before widening contact
crawling.

The loop is:

```text
source sample
  -> discovery ingestion
  -> company identity
  -> trigger signals
  -> fit x intent scoring
  -> contact review/provider step
  -> outreach outcome
```

## Source Decision Rules

Scale a source only when it proves at least one of these:

- many clean domains become trigger-backed scored companies
- scored companies produce usable contacts
- outreach from that source gets replies or meetings

Drop or rework a source when:

- many records do not resolve to company domains
- companies get no useful trigger signal
- signals score low after fit penalties
- contact discovery is mostly generic inboxes

## Current Candidate Sources

Start with bounded samples:

| Source | Sample | Why |
| --- | ---: | --- |
| HN Who Is Hiring | 100 to 300 posts | Already implemented; good hiring-intent source. |
| ATS boards from scored companies | 50 to 100 boards | Stronger stale-role and role-detail evidence. |
| Funding/news feeds | 50 to 100 events | Budget-timing signal, weaker pain signal. |
| Niche job boards/directories | 50 to 100 companies | Potentially cleaner vertical fit than broad HN. |

## Report Command

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' backend/.venv/bin/python scripts/report_source_experiments.py
```

This writes:

```text
campaigns/source-experiments/source-quality-report.csv
campaigns/source-experiments/source-quality-report.md
```

Use the report decision column to decide whether the next sprint should scale a
source, fix contact resolution, or drop/rework the source.
