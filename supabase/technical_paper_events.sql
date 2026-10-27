-- Apply once to the existing Seguimiento project before deploying the paper journal.
-- The Streamlit server verifies Google OIDC and sends only a SHA-256 issuer/subject owner.
-- Events are insert-only: historical observations and assumed quotes cannot be edited.
create table if not exists public.technical_paper_events (
    owner text not null check (owner ~ '^[0-9a-f]{64}$'),
    event_key text not null check (length(event_key) between 1 and 160),
    signal_key text not null check (length(signal_key) between 1 and 150),
    kind text not null check (kind in ('signal', 'entry', 'exit')),
    ticker text not null check (ticker ~ '^[A-Z0-9.^=-]{1,20}$'),
    signal_date date not null,
    payload jsonb not null check (jsonb_typeof(payload) = 'object'
        and octet_length(payload::text) <= 8192),
    recorded_at timestamptz not null default now(),
    primary key (owner, event_key),
    check (event_key = case kind
        when 'signal' then signal_key
        when 'entry' then signal_key || ':entry'
        when 'exit' then signal_key || ':exit'
    end)
);

create index if not exists technical_paper_events_owner_time_idx
    on public.technical_paper_events (owner, recorded_at, event_key);

alter table public.technical_paper_events enable row level security;
revoke all on table public.technical_paper_events from public, anon, authenticated, service_role;
grant select, insert on table public.technical_paper_events to service_role;
create policy "No direct client access to paper events"
    on public.technical_paper_events
    for all to anon, authenticated
    using (false) with check (false);
