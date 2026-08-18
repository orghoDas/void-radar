create table if not exists source_identities (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    source_id uuid not null references sources(id) on delete cascade,
    external_id text not null,
    source_url text,
    confidence numeric(5, 4) not null default 1,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    unique (source_id, external_id)
);

create index if not exists idx_source_identities_company_id
    on source_identities(company_id);

create unique index if not exists idx_founders_full_name_location
    on founders(full_name, coalesce(location, ''));

