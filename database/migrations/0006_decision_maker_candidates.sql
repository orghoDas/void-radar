create table if not exists decision_maker_candidates (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    full_name text,
    role text not null,
    role_category text not null,
    email text,
    linkedin_url text,
    x_url text,
    profile_url text,
    source_type text not null,
    source_url text not null,
    confidence numeric(5, 4) not null default 0.5,
    raw_evidence jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (
        role_category in (
            'founder',
            'executive',
            'business',
            'growth',
            'partnerships',
            'product',
            'marketing',
            'sales',
            'operations',
            'technical',
            'other'
        )
    ),
    check (
        source_type in (
            'company_website',
            'founder_personal_website',
            'public_profile',
            'trusted_source_payload',
            'verified_provider',
            'manual_review'
        )
    )
);

create index if not exists idx_decision_maker_candidates_company_id
    on decision_maker_candidates(company_id);

create index if not exists idx_decision_maker_candidates_role_category
    on decision_maker_candidates(role_category);

create index if not exists idx_decision_maker_candidates_email
    on decision_maker_candidates(lower(email))
    where email is not null;

create unique index if not exists idx_decision_maker_candidates_unique_source
    on decision_maker_candidates(
        company_id,
        coalesce(lower(full_name), ''),
        lower(role),
        role_category,
        coalesce(lower(email), ''),
        source_url
    );
