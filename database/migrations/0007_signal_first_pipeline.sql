alter table sources
    add column if not exists tier text,
    add column if not exists cadence text,
    add column if not exists last_run_at timestamptz,
    add column if not exists politeness jsonb not null default '{}'::jsonb;

alter table contacts
    add column if not exists verified_at timestamptz;

alter table scores
    add column if not exists fit_score integer,
    add column if not exists intent_score integer,
    add column if not exists total_score integer,
    add column if not exists score_version text,
    add column if not exists scoring_inputs jsonb not null default '{}'::jsonb;

create table if not exists raw_pages (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id) on delete cascade,
    source_id uuid references sources(id) on delete set null,
    url text not null,
    final_url text,
    body text not null,
    content_type text,
    status_code integer,
    content_hash text,
    fetched_at timestamptz not null default now(),
    created_at timestamptz not null default now()
);

create table if not exists ats_boards (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    domain text not null,
    ats_provider text not null,
    board_key text not null,
    board_token text,
    board_url text,
    careers_url text,
    evidence_url text,
    confidence numeric(5, 4) not null default 0,
    raw_evidence jsonb not null default '{}'::jsonb,
    status text not null default 'detected',
    first_detected_at timestamptz not null default now(),
    last_detected_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (company_id, ats_provider, board_key),
    check (
        ats_provider in (
            'greenhouse',
            'lever',
            'ashby',
            'workable',
            'generic'
        )
    ),
    check (status in ('detected', 'inactive'))
);

create table if not exists job_postings (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    ats_board_id uuid references ats_boards(id) on delete set null,
    ats_provider text not null,
    external_job_id text not null,
    title text not null,
    department text,
    location text,
    remote_policy text,
    employment_type text,
    posted_at timestamptz,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    url text not null,
    description_text text,
    stack_terms jsonb not null default '[]'::jsonb,
    seniority text,
    is_active boolean not null default true,
    raw_payload jsonb not null default '{}'::jsonb,
    missing_since_at timestamptz,
    missing_observation_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (company_id, ats_provider, external_job_id),
    check (
        ats_provider in (
            'greenhouse',
            'lever',
            'ashby',
            'workable',
            'generic'
        )
    )
);

alter table job_postings
    add column if not exists missing_since_at timestamptz,
    add column if not exists missing_observation_count integer not null default 0;

create table if not exists suppression (
    id uuid primary key default gen_random_uuid(),
    email text,
    domain text,
    reason text not null,
    source text,
    added_at timestamptz not null default now(),
    check (email is not null or domain is not null)
);

create table if not exists outcomes (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id) on delete cascade,
    contact_id uuid references contacts(id) on delete set null,
    email text,
    event text not null,
    source text,
    signal_id uuid references signals(id) on delete set null,
    metadata jsonb not null default '{}'::jsonb,
    occurred_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    check (
        event in (
            'sent',
            'opened',
            'clicked',
            'replied',
            'positive_reply',
            'negative_reply',
            'meeting_booked',
            'bounced',
            'complained',
            'unsubscribed'
        )
    )
);

create table if not exists parser_versions (
    id uuid primary key default gen_random_uuid(),
    source_id uuid references sources(id) on delete cascade,
    source_key text not null,
    schema_version text not null,
    selectors jsonb not null default '{}'::jsonb,
    generated_at timestamptz not null default now(),
    validated_at timestamptz,
    success_rate numeric(5, 4),
    sample_size integer not null default 0,
    status text not null default 'candidate',
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (source_key, schema_version, generated_at),
    check (status in ('candidate', 'active', 'failed', 'retired'))
);

create index if not exists idx_raw_pages_company_id
    on raw_pages(company_id);

create index if not exists idx_raw_pages_content_hash
    on raw_pages(content_hash);

create index if not exists idx_ats_boards_company_id
    on ats_boards(company_id);

create index if not exists idx_ats_boards_provider
    on ats_boards(ats_provider);

create index if not exists idx_job_postings_company_id
    on job_postings(company_id);

create index if not exists idx_job_postings_active
    on job_postings(is_active);

create index if not exists idx_job_postings_posted_at
    on job_postings(posted_at);

create index if not exists idx_suppression_email
    on suppression(lower(email))
    where email is not null;

create index if not exists idx_suppression_domain
    on suppression(lower(domain))
    where domain is not null;

create index if not exists idx_outcomes_company_id
    on outcomes(company_id);

create index if not exists idx_outcomes_contact_id
    on outcomes(contact_id);

create index if not exists idx_outcomes_event
    on outcomes(event);

create index if not exists idx_parser_versions_source_key
    on parser_versions(source_key);
