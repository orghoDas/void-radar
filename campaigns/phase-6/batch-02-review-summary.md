# Batch 02 Contact Candidate Review

Date: 2026-08-20

Input:

- `campaigns/phase-6/apify-contact-candidate-input-batch-02.json`

Raw actor output:

- `campaigns/phase-6/apify-contact-candidates-batch-02.csv`

## Result

- Rows: 39
- Misses: 26
- Contact candidates: 13
- Approved rows: 0
- Imported rows: 0

## Decision

Do not import this batch.

The candidate rows were either generic inboxes or extraction artifacts:

- Cogram produced concatenated page text such as `preferencescontacthi@cogram.com`.
- Kyra Health produced concatenated page text such as `uscontactconnectinfo@kyra.health`.
- AusRehab produced generic `office@` rows.
- CoVar produced a domain-name inbox row.

None of these are target decision-maker contacts.

## Actor Fix Applied

`apify/contact-candidate-enricher` was tightened after this run:

- Inserts line breaks before extracting page text.
- Extracts `mailto:` links separately.
- Rejects generic local parts such as `office`.
- Rejects domain-name inboxes such as `covar@covar.com`.
- Rejects long local parts that look like concatenated UI text.
- Deduplicates candidates by company domain and email.

Push the actor again before rerunning batch 02.

## Rerun Result

Rerun output:

- `campaigns/phase-6/apify-contact-candidates-batch-02-rerun.csv`

Result:

- Rows: 30
- Misses: 28
- Contact candidates: 2
- Approved rows: 0
- Imported rows: 0

Decision:

Do not import this rerun either.

The remaining candidates were generic or malformed:

- `membership@atria.org`
- `%20office@ausrehab.com`

Additional actor fix applied:

- Rejects `membership@` generic inboxes.
- Decodes `mailto:` values before email validation.
- Rejects malformed local parts containing `%`.
