create table if not exists founder_profiles (
    id uuid primary key default gen_random_uuid(),
    founder_id uuid not null references founders(id) on delete cascade,
    company_id uuid references companies(id) on delete cascade,
    source text not null,
    source_url text,
    profile_url text,
    linkedin_url text,
    x_url text,
    email text,
    bio text,
    confidence numeric(5, 4) not null default 0.95,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_founder_profiles_founder_id
    on founder_profiles(founder_id);

create index if not exists idx_founder_profiles_company_id
    on founder_profiles(company_id);

create index if not exists idx_founder_profiles_linkedin_url
    on founder_profiles(linkedin_url);

