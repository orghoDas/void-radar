# Provider-Free Contact Candidate Workflow

Use this when we are not using Apollo or another paid contact provider. This
keeps the full pipeline moving with Apify plus manual review, but it does not
pretend public-page candidates are provider-verified contacts.

## 1. Generate Clean Apify Input

```bash
backend/.venv/bin/python scripts/export_phase6_apify_contact_input.py --limit 20 --min-score 20
```

This writes:

```text
campaigns/phase-6/apify-contact-candidate-input.json
```

The default export skips obvious noisy HN domains, URL shorteners, malformed TLDs,
subdomains, and rows where the company name is really a job title or comment.

## 2. Run The Apify Actor

Actor:

```text
apify/contact-candidate-enricher
```

Input:

Paste the full JSON from:

```text
campaigns/phase-6/apify-contact-candidate-input.json
```

Keep defaults for the first run:

```text
maxItems: 20
maxPagesPerCompany: 12
includeGenericEmails: false
includeExternalEmails: false
emitMissesToDataset: true
```

For a provider-free fallback pass where generic company inboxes are allowed into
review, run the same actor with:

```text
includeGenericEmails: true
```

Only import a generic inbox when it is the best available fallback for a scored
company.

## 3. Download Results

After the actor finishes:

1. Open the actor run.
2. Open Output or Storage -> Dataset.
3. Export as CSV.

Rows with `record_type=contact_candidate` are the useful rows.
Rows with `record_type=miss` only show what was checked.

## 4. Build A Compact Review Queue

Convert the raw Apify dataset into a smaller queue:

```bash
backend/.venv/bin/python scripts/build_phase6_manual_review_queue.py path/to/apify-output.csv --include-generic
```

This writes:

```text
campaigns/phase-6/manual-contact-review-queue.csv
```

The queue prioritizes:

- named people with role evidence
- direct company-domain emails with role evidence
- direct company-domain emails needing context
- generic inboxes as fallback only

It excludes external-domain emails by default.

## 5. Review Candidates

For rows that are real people with usable evidence, set:

```text
review_status=approved
```

Only approve rows with:

- real email
- real source URL
- person or role evidence in `source_excerpt`
- no guessed email pattern

Do not approve direct-contact rows with:

- generic emails like info@ or support@
- LinkedIn-only evidence
- no source URL
- guessed first.last@domain emails

Generic inboxes can be approved only as fallback rows when:

- the company is highly scored
- there is a clear reason-to-write
- no better named contact was found
- the inbox is appropriate for outreach, such as `hello@`, `contact@`, `jobs@`,
  `careers@`, `hr@`, or `recruiting@`

## 6. Import Approved Rows

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' backend/.venv/bin/python scripts/ingest_reviewed_apify_contacts.py campaigns/phase-6/manual-contact-review-queue.csv
```

The importer ignores `needs_review` rows by default. Approved rows are imported
as:

```text
source_type=manual_review
verification_status=manual_verified
```

## 7. Export Outreach

After import, use:

```text
POST /outreach/export.csv
```

The export will include only scored, unsuppressed companies with verified or
manually approved contacts.

## Provider-Backed Path Is Optional

Public crawling has low decision-maker yield. Use a paid contact provider only
when the campaign needs real verified contact volume. Apollo was one attempted
provider, but it is not required by the backend or Apify architecture.

Generate Apollo input:

```bash
backend/.venv/bin/python scripts/export_phase6_apollo_input.py --limit 30 --min-score 20
```

Push the provider actor:

```bash
cd apify/apollo-verified-contact-enricher
apify push
```

Set this Apify secret/environment variable:

```text
APOLLO_API_KEY
```

Run the actor with:

```text
campaigns/phase-6/apollo-verified-contact-input.json
```

Export its dataset as CSV, then import:

```bash
DATABASE_URL='postgresql+psycopg:///void_radar?host=/tmp' backend/.venv/bin/python scripts/ingest_verified_provider_contacts.py campaigns/phase-6/apollo-verified-contacts.csv --provider-name apollo
```
