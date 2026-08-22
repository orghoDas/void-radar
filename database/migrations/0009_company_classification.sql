-- Phase C: LLM technical/non-technical classification.
--
-- Keyword matching cannot read a multilingual company set. "Université
-- Paris-Est Créteil", "Vrije Universiteit Brussel" and "Huddinge kommun" are a
-- university, a university and a municipality, and no English keyword list
-- catches them without becoming an endless per-language patch.
--
-- Stored separately from deterministic facts so a model verdict can be audited,
-- compared, or disabled without disturbing the rest of the pipeline.

create table if not exists company_classification (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    company_type text not null,
    builds_software text not null,
    sector text,
    engineering_signals jsonb not null default '[]'::jsonb,
    buyer_signals jsonb not null default '[]'::jsonb,
    confidence numeric(5, 4) not null default 0,
    model text,
    validation_notes jsonb not null default '[]'::jsonb,
    source_urls jsonb not null default '[]'::jsonb,
    classified_at timestamptz not null default now(),
    reviewed_at timestamptz,
    review_verdict text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (company_id),
    check (company_type in (
        'software_vendor', 'agency', 'non_technical_buyer', 'unclear'
    )),
    check (builds_software in ('true', 'false', 'unknown'))
);

create index if not exists idx_company_classification_type
    on company_classification(company_type);
create index if not exists idx_company_classification_company_id
    on company_classification(company_id);
