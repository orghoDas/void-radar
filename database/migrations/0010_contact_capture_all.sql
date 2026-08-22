-- Phase D: keep every contact and every web presence.
--
-- Plan v3 inverts the earlier policy. Previously only decision-makers were kept
-- and only verified addresses were exported. The deliverable is now a datasheet
-- handed to someone else, so nothing is discarded - everything is captured and
-- labelled, and the recipient decides what to use.
--
-- Suppression still applies. We do not send, but they will, and unlabelled bad
-- addresses damage their sending domain.

create table if not exists company_contacts_all (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    email text,
    full_name text,
    role text,
    phone text,
    -- person: a named individual. role_inbox: careers@, info@. generic: no local
    -- part signal. Kept rather than filtered so the recipient can choose.
    contact_kind text not null default 'unknown',
    on_company_domain boolean not null default false,
    deliverability text,
    source_type text not null,
    source_url text,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    raw_evidence jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (company_id, email),
    check (contact_kind in ('person', 'role_inbox', 'generic', 'unknown')),
    check (email is not null or phone is not null or full_name is not null)
);

create index if not exists idx_contacts_all_company on company_contacts_all(company_id);
create index if not exists idx_contacts_all_kind on company_contacts_all(contact_kind);
create index if not exists idx_contacts_all_email on company_contacts_all(lower(email))
    where email is not null;

-- A company's pages, queryable rather than buried in a payload.
create table if not exists company_web_presence (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references companies(id) on delete cascade,
    url text not null,
    -- website, careers, ats_board, blog, docs, linkedin, x, other
    presence_kind text not null default 'other',
    title text,
    discovered_from text,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    unique (company_id, url)
);

create index if not exists idx_web_presence_company on company_web_presence(company_id);
create index if not exists idx_web_presence_kind on company_web_presence(presence_kind);
