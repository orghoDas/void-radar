# Outreach Validation Playbook

Phase 0 is the manual proof that Void Radar is finding a market worth building
for. Run it in parallel with Phase 1 engineering.

## Goal

Create a first send-ready batch:

```text
100 verified contacts
with a concrete reason-to-write
sent or ready to send within 10 working days
```

## First Wedge

Start narrow:

```text
B2B SaaS, logistics, operations, marketplace, or internal-systems-heavy
companies with technical/product/engineering roles open for 60 to 90+ days.
```

Avoid:

- Agencies and consultancies.
- Companies with huge obvious in-house engineering teams.
- Companies with no public website.
- Rows where the trigger is only a vague guess.
- Any contact that is unverified or suppressed.

## Manual Spreadsheet Columns

Use this template:

```text
campaigns/phase-0/manual-prospects-template.csv
```

Validate it before sending:

```bash
python3 scripts/validate_phase0_campaign.py campaigns/phase-0/manual-prospects-template.csv
```

Use these columns:

```text
company
domain
segment
country
trigger_type
trigger_summary
trigger_url
role_title
role_age_days
target_person
target_role
email
email_source
email_verification
message_angle
status
outcome
notes
```

Required before a row can be exported:

```text
domain
trigger_summary
trigger_url
target_person or target_role
email
email_source
email_verification
message_angle
```

## Manual Discovery Workflow

1. Pick 30 to 50 companies from one narrow segment.
2. Open each company's careers page.
3. Look for engineering, product, data, automation, platform, backend, frontend,
   DevOps, or internal systems roles.
4. Record the job URL and role title.
5. Estimate role age from posted date, first-seen date, or job-board metadata.
6. Keep only rows where the reason-to-write is specific.
7. Find the likely decision-maker through permitted manual/provider sources.
8. Verify the email with a dedicated verification provider.
9. Remove suppressed domains or emails.
10. Send in small batches and record outcomes.

## Reason-To-Write Examples

Good:

```text
Your backend engineer role has been open for 104 days, and the job description
mentions payments and partner integrations. We help product teams unblock this
kind of delivery without waiting for a full-time hire.
```

Good:

```text
You are hiring for product operations and automation roles at the same time.
That usually means internal workflows are stretching. Void builds internal
systems and workflow automation for teams at that stage.
```

Weak:

```text
We saw your company and think you might need software development.
```

## Outcome Tracking

Use this template:

```text
campaigns/phase-0/outcomes-template.csv
```

Record every event:

```text
sent
opened
replied
positive_reply
negative_reply
meeting_booked
bounced
complained
unsubscribed
```

The first learning is not whether the scraper works. It is which segment,
trigger, and message angle creates replies.
