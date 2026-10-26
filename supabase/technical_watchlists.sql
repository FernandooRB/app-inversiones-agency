-- Run once in the SQL Editor of the Supabase project used by Seguimiento.
-- The Streamlit server checks OIDC access and sends only hashed issuer/subject IDs.
create table if not exists public.technical_watchlists (
    owner text primary key check (owner ~ '^[0-9a-f]{64}$'),
    symbols jsonb not null check (
        case when jsonb_typeof(symbols) = 'array'
            then jsonb_array_length(symbols) <= 25
            else false
        end
    ),
    updated_at timestamptz not null default now()
);

alter table public.technical_watchlists enable row level security;
revoke all on table public.technical_watchlists from anon, authenticated;
grant select, insert, update on table public.technical_watchlists to service_role;
create policy "No direct client access to technical watchlists"
    on public.technical_watchlists
    for all to anon, authenticated
    using (false) with check (false);
