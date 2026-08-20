# Phase 0 Message Template

Use this only after the row passes `scripts/validate_phase0_campaign.py`.

## Subject Options

```text
Quick thought on {{role_title}}
```

```text
Noticed {{company}} is hiring for {{role_title}}
```

## Email

```text
Hi {{target_person}},

I noticed {{company}} has had {{role_title}} open for about {{role_age_days}}
days, and the role mentions {{specific_stack_or_workflow_detail}}.

That usually points to approved work waiting on capacity. Void helps teams
unblock product and engineering delivery without waiting for the perfect
full-time hire, especially around backend systems, integrations, internal tools,
and automation.

Would it be useful if I sent over 2-3 ways we could help reduce the load around
{{specific_project_area}}?

Best,
{{sender_name}}
```

## Rules

- Lead with the observed trigger, not Void's capability list.
- Keep the first email under 120 words.
- Do not mention scraping, automation, or the pipeline.
- Do not send if the trigger URL is missing.
- Do not send if the email is unverified.
- Do not send from Void's primary domain during testing.
