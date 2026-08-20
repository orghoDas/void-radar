# Phase 7 Company Research Workflow

Phase 7 is not broad research. Run it only for send-ready companies.

```text
send-ready outreach row
  -> company-researcher input
  -> small same-domain crawl
  -> raw_pages
  -> observations
  -> better outreach context
```

## 1. Export Research Input

```bash
backend/.venv/bin/python scripts/export_phase7_company_research_input.py
```

Output:

```text
campaigns/phase-7/company-researcher-input.json
```

## 2. Run Apify Actor

Actor:

```text
company-researcher
```

Input:

```text
campaigns/phase-7/company-researcher-input.json
```

Keep the first run small:

```text
maxItems: 3
maxPagesPerCompany: 10
includePageText: true
emitPageRecords: true
```

## 3. Export Dataset

Export the dataset as JSON when possible. JSON preserves nested page records
better than CSV.

Suggested local path:

```text
campaigns/phase-7/company-researcher-output.json
```

## 4. Import Research

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' backend/.venv/bin/python scripts/ingest_phase7_company_research.py campaigns/phase-7/company-researcher-output.json
```

## Rules

- Do not run this actor for every discovered company.
- Do not turn model-derived names into contacts without validation.
- Keep deterministic extraction first.
- Add LLM summarization only after the source/contact loop is commercially useful.
