alter table source_records
    add column if not exists processing_status text not null default 'pending',
    add column if not exists processed_at timestamptz,
    add column if not exists processing_notes text;

create table if not exists identity_resolution_reviews (
    id uuid primary key default gen_random_uuid(),
    source_record_id uuid not null references source_records(id) on delete cascade,
    source text not null,
    reason text not null,
    normalized_name text,
    normalized_domain text,
    candidate_matches jsonb not null default '[]'::jsonb,
    confidence numeric(5, 4) not null default 0,
    status text not null default 'pending',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (source_record_id)
);

create index if not exists idx_source_records_processing_status
    on source_records(processing_status);

create index if not exists idx_identity_resolution_reviews_status
    on identity_resolution_reviews(status);

