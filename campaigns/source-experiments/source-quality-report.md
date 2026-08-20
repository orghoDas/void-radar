# Source Quality Report

This report measures real-world discovery sources through the full lead funnel.

```text
source -> company -> signal -> score -> contact -> outcome
```

| Source | Records | Signals | Score >=20 | Contacts | Outcomes | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| hacker_news_who_is_hiring | 100 | 100 | 90 | 3 | 0 sent / 0 positive / 0 meetings | ready_for_small_outreach |
| signal_enrichment | 0 | 10 | 10 | 0 | 0 sent / 0 positive / 0 meetings | needs_more_sample |
| phase7_company_research | 0 | 0 | 0 | 0 | 0 sent / 0 positive / 0 meetings | needs_more_sample |

## Next Actions

- `hacker_news_who_is_hiring`: Run a small suppression-checked outreach test.
- `signal_enrichment`: Collect a larger sample before deciding.
- `phase7_company_research`: Collect a larger sample before deciding.
