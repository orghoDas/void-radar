-- Phase 3: the hybrid layer.
--
-- Two things the earlier phases could not answer:
--   1. What does the model cost per qualified company?
--   2. Is model-derived data accurate enough to trust?
--
-- llm_usage records every model call so spend is attributable to a company and
-- a purpose. company_enrichment stores validated model output separately from
-- deterministic facts, with its extraction method and confidence, so it can be
-- audited or disabled without disturbing the rest of the system.

create table if not exists llm_usage (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id) on delete set null,
    purpose text not null,
    model text not null,
    prompt_tokens integer not null default 0,
    completion_tokens integer not null default 0,
    total_tokens integer not null default 0,
    cost_usd numeric(12, 6) not null default 0,
    succeeded boolean not null default true,
    error text,
    created_at timestamptz not null default now()
);

create index if not exists idx_llm_usage_company_id on llm_usage(company_id);
create index if not exists idx_llm_usage_purpose on llm_usage(purpose);
create index if not exists idx_llm_usage_created_at on llm_usage(created_at);

create table if not exists company_enrichment (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    positioning text,
    business_model text,
    customer_type text,
    technology_mentions jsonb not null default '[]'::jsonb,
    contact_routes jsonb not null default '[]'::jsonb,
    decision_makers jsonb not null default '[]'::jsonb,
    service_fit_evidence text,
    extraction_method text not null,
    model text,
    confidence numeric(5, 4) not null default 0,
    validation_notes jsonb not null default '[]'::jsonb,
    source_urls jsonb not null default '[]'::jsonb,
    reviewed_at timestamptz,
    review_verdict text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (company_id, extraction_method)
);

create index if not exists idx_company_enrichment_company_id
    on company_enrichment(company_id);

-- Records that a human has checked, so extraction accuracy can be measured
-- rather than assumed.
create index if not exists idx_company_enrichment_reviewed
    on company_enrichment(reviewed_at) where reviewed_at is not null;
