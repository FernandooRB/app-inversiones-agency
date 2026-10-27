-- Durable order claims must exist before any Paper POST. All observations are insert-only.
begin;
create table if not exists public.alpaca_paper_order_events (
    event_seq bigint generated always as identity primary key,
    owner text not null check (owner ~ '^[0-9a-f]{64}$'),
    account_id uuid not null,
    client_order_id text not null check (client_order_id ~ '^sig-paper-[0-9a-f]{32}$'),
    event_key text not null,
    kind text not null check (kind in ('intent','accepted','rejected','unknown','observed')),
    payload jsonb not null check (jsonb_typeof(payload)='object'
        and octet_length(payload::text)<=8192),
    recorded_at timestamptz not null default now(),
    unique(owner, account_id, event_key),
    foreign key(owner, account_id, client_order_id)
        references public.alpaca_paper_order_events(owner, account_id, event_key),
    check ((kind='intent' and event_key=client_order_id) or
        (kind<>'intent' and event_key ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))
);

create unique index if not exists alpaca_paper_intent_unique_idx
    on public.alpaca_paper_order_events(account_id,event_key) where kind='intent';
create index if not exists alpaca_paper_events_owner_account_seq_idx
    on public.alpaca_paper_order_events(owner,account_id,event_seq);
create index if not exists alpaca_paper_events_parent_idx
    on public.alpaca_paper_order_events(owner,account_id,client_order_id);

alter table public.alpaca_paper_order_events enable row level security;
revoke all on table public.alpaca_paper_order_events from public, anon, authenticated, service_role;
grant select, insert on table public.alpaca_paper_order_events to service_role;
revoke all on sequence public.alpaca_paper_order_events_event_seq_seq
    from public, anon, authenticated, service_role;
grant usage, select on sequence public.alpaca_paper_order_events_event_seq_seq to service_role;
create policy "No direct client access to paper orders"
    on public.alpaca_paper_order_events for all to anon, authenticated
    using(false) with check(false);
commit;
