alter table contacts
    add column if not exists source_url text;

alter table contacts
    add column if not exists source_type text;

alter table contacts
    add column if not exists provider_name text;

alter table contacts
    add column if not exists evidence jsonb not null default '{}'::jsonb;

create table if not exists contact_enrichment_evidence (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    founder_id uuid references founders(id) on delete set null,
    contact_id uuid references contacts(id) on delete set null,
    full_name text,
    role text,
    email text not null,
    source_type text not null,
    source_url text not null,
    provider_name text,
    verification_status text not null default 'unverified',
    confidence numeric(5, 4) not null default 0,
    raw_evidence jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    check (
        source_type in (
            'company_website',
            'founder_personal_website',
            'public_profile',
            'trusted_source_payload',
            'verified_provider',
            'manual_review'
        )
    ),
    check (
        verification_status in (
            'unverified',
            'public_source',
            'provider_verified',
            'manual_verified'
        )
    )
);

create index if not exists idx_contacts_company_email
    on contacts(company_id, lower(email))
    where email is not null;

create index if not exists idx_contact_enrichment_evidence_company_id
    on contact_enrichment_evidence(company_id);

create index if not exists idx_contact_enrichment_evidence_founder_id
    on contact_enrichment_evidence(founder_id);

create index if not exists idx_contact_enrichment_evidence_email
    on contact_enrichment_evidence(lower(email));

create unique index if not exists idx_contact_enrichment_evidence_unique_source
    on contact_enrichment_evidence(
        company_id,
        coalesce(founder_id, '00000000-0000-0000-0000-000000000000'::uuid),
        lower(email),
        source_type,
        source_url
    );
