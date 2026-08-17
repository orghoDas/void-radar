create extension if not exists pgcrypto;

create table if not exists companies (
    id uuid primary key default gen_random_uuid(),
    canonical_name text not null,
    canonical_domain text,
    description text,
    industry text,
    country text,
    city text,
    company_stage text,
    employee_estimate integer,
    status text not null default 'candidate',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (canonical_domain)
);

create table if not exists founders (
    id uuid primary key default gen_random_uuid(),
    full_name text not null,
    location text,
    bio text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists sources (
    id uuid primary key default gen_random_uuid(),
    source_key text not null unique,
    name text not null,
    source_type text not null,
    base_url text,
    terms_url text,
    enabled boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists company_founders (
    company_id uuid not null references companies(id) on delete cascade,
    founder_id uuid not null references founders(id) on delete cascade,
    role text,
    source_id uuid references sources(id) on delete set null,
    confidence numeric(5, 4) not null default 0,
    created_at timestamptz not null default now(),
    primary key (company_id, founder_id)
);

create table if not exists company_aliases (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    alias text not null,
    alias_type text not null default 'name',
    source text,
    confidence numeric(5, 4) not null default 0,
    created_at timestamptz not null default now(),
    unique (company_id, alias, alias_type)
);

create table if not exists source_records (
    id uuid primary key default gen_random_uuid(),
    source_id uuid not null references sources(id) on delete restrict,
    source_record_id text,
    company_id uuid references companies(id) on delete set null,
    raw_payload jsonb not null,
    source_url text,
    collected_at timestamptz not null default now(),
    content_hash text,
    created_at timestamptz not null default now(),
    unique (source_id, source_record_id)
);

create table if not exists research_runs (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    run_type text not null,
    status text not null default 'queued',
    started_at timestamptz,
    completed_at timestamptz,
    actor_run_id text,
    error_message text,
    model_version text,
    created_at timestamptz not null default now()
);

create table if not exists observations (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    research_run_id uuid references research_runs(id) on delete set null,
    evidence_kind text not null,
    field_name text not null,
    value jsonb not null,
    source text,
    source_url text,
    collected_at timestamptz not null default now(),
    confidence numeric(5, 4) not null default 0,
    created_at timestamptz not null default now(),
    check (evidence_kind in ('FACT', 'OBSERVATION', 'INFERENCE', 'RECOMMENDATION'))
);

create table if not exists signals (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id) on delete cascade,
    founder_id uuid references founders(id) on delete set null,
    signal_type text not null,
    description text not null,
    source text,
    source_url text,
    detected_at timestamptz not null default now(),
    confidence numeric(5, 4) not null default 0,
    raw_evidence jsonb,
    created_at timestamptz not null default now()
);

create table if not exists opportunities (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    service_type text not null,
    description text not null,
    reasoning jsonb not null default '[]'::jsonb,
    supporting_evidence jsonb not null default '[]'::jsonb,
    confidence numeric(5, 4) not null default 0,
    status text not null default 'new',
    model_version text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists scores (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    company_fit integer not null,
    opportunity_strength integer not null,
    timing integer not null,
    technical_capacity_gap integer not null,
    commercial_potential integer not null,
    source_confidence integer not null,
    overall_score integer not null,
    positive_reasons jsonb not null default '[]'::jsonb,
    penalties jsonb not null default '[]'::jsonb,
    calculated_at timestamptz not null default now(),
    model_version text not null,
    check (company_fit between 0 and 100),
    check (opportunity_strength between 0 and 100),
    check (timing between 0 and 100),
    check (technical_capacity_gap between 0 and 100),
    check (commercial_potential between 0 and 100),
    check (source_confidence between 0 and 100),
    check (overall_score between 0 and 100)
);

create table if not exists contacts (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    founder_id uuid references founders(id) on delete set null,
    full_name text,
    role text,
    email text,
    contact_source text,
    verification_status text not null default 'unverified',
    confidence numeric(5, 4) not null default 0,
    last_checked_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists outreach (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    contact_id uuid references contacts(id) on delete set null,
    status text not null default 'not_started',
    thesis text,
    owner text,
    last_activity_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists feedback (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    score_id uuid references scores(id) on delete set null,
    reviewer text,
    prospect_quality text,
    opportunity_quality text,
    company_info_quality text,
    notes text,
    outcome text,
    created_at timestamptz not null default now()
);

create index if not exists idx_companies_domain on companies(canonical_domain);
create index if not exists idx_companies_region on companies(country, city);
create index if not exists idx_source_records_company_id on source_records(company_id);
create index if not exists idx_research_runs_company_id on research_runs(company_id);
create index if not exists idx_observations_company_id on observations(company_id);
create index if not exists idx_signals_company_id on signals(company_id);
create index if not exists idx_opportunities_company_id on opportunities(company_id);
create index if not exists idx_scores_company_id_calculated_at
    on scores(company_id, calculated_at desc);
