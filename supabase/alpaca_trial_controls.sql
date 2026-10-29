-- Trial controls are private server data. Neither function executes broker orders.
begin;
create table public.alpaca_trial_events (
    event_seq bigint generated always as identity primary key,
    owner text not null check (owner ~ '^[0-9a-f]{64}$'),
    account_id uuid not null,
    event_key text not null check (event_key ~ '^[a-z_]+:[0-9a-f]{32,64}$'),
    kind text not null check (kind in ('settings','plan','fill','fills_sync','alert','ack','observation')),
    payload jsonb not null check (jsonb_typeof(payload)='object' and octet_length(payload::text)<=8192),
    recorded_at timestamptz not null default now(),
    unique(owner,account_id,event_key),
    check (split_part(event_key,':',1)=kind)
);
create index alpaca_trial_owner_account_seq_idx
    on public.alpaca_trial_events(owner,account_id,event_seq);
alter table public.alpaca_trial_events enable row level security;
revoke all on public.alpaca_trial_events from public,anon,authenticated,service_role;
grant select,insert on public.alpaca_trial_events to service_role;
revoke all on sequence public.alpaca_trial_events_event_seq_seq from public,anon,authenticated,service_role;
grant usage,select on sequence public.alpaca_trial_events_event_seq_seq to service_role;
create policy "No direct access to trial controls" on public.alpaca_trial_events
    for all to anon,authenticated using(false) with check(false);

create function public.append_alpaca_trial_event(
    p_owner text,p_account uuid,p_key text,p_kind text,p_payload jsonb)
returns setof public.alpaca_trial_events
language plpgsql security invoker set search_path=public,pg_temp as $$
declare saved public.alpaca_trial_events%rowtype;
begin
    perform pg_advisory_xact_lock(hashtextextended(p_owner||p_account::text,0));
    select * into saved from public.alpaca_trial_events
        where owner=p_owner and account_id=p_account and event_key=p_key;
    if found then
        if saved.kind<>p_kind or (saved.payload<>p_payload and p_kind not in ('alert','observation','ack')) then
            raise exception 'TRIAL_EVENT_CONFLICT';
        end if;
        return next saved; return;
    end if;
    if (select count(*) from public.alpaca_trial_events where owner=p_owner and account_id=p_account)>=10000 then
        raise exception 'TRIAL_EVENT_LIMIT';
    end if;
    insert into public.alpaca_trial_events(owner,account_id,event_key,kind,payload)
        values(p_owner,p_account,p_key,p_kind,p_payload) returning * into saved;
    return next saved;
end; $$;
revoke all on function public.append_alpaca_trial_event(text,uuid,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.append_alpaca_trial_event(text,uuid,text,text,jsonb) to service_role;

create function public.claim_alpaca_trial_order(
    p_owner text,p_account uuid,p_client text,p_payload jsonb)
returns setof public.alpaca_paper_order_events
language plpgsql security invoker set search_path=public,pg_temp as $$
declare ctx jsonb:=p_payload->'trial_context'; cfg public.alpaca_trial_events%rowtype;
    plan public.alpaca_trial_events%rowtype; item record; prior jsonb; state jsonb;
    extra_cost numeric:=0; extra_risk numeric:=0; extra_symbol numeric:=0;
    cutoff timestamptz; saved public.alpaca_paper_order_events%rowtype;
begin
    perform pg_advisory_xact_lock(hashtextextended(p_owner||p_account::text,0));
    if exists(select 1 from public.alpaca_paper_order_events
              where owner=p_owner and account_id=p_account and event_key=p_client) then
        raise exception using errcode='23505', message='ORDER_ALREADY_RECORDED';
    end if;
    select * into cfg from public.alpaca_trial_events where owner=p_owner and account_id=p_account
        and kind='settings' order by event_seq desc limit 1;
    select * into plan from public.alpaca_trial_events where owner=p_owner and account_id=p_account
        and kind='plan' and payload->>'symbol'=p_payload->>'symbol' order by event_seq desc limit 1;
    if ctx is null or cfg.event_key is null or plan.event_key is null
        or cfg.event_key is distinct from ctx->>'settings_key'
        or plan.event_key is distinct from ctx->>'plan_key'
        or cfg.payload is distinct from ctx->'settings' or plan.payload is distinct from ctx->'plan' then
        raise exception 'TRIAL_CONTROL_CHANGED';
    end if;
    cutoff:=(ctx->>'read_started_at')::timestamptz;
    if cutoff>now()+interval '1 minute' or cutoff<now()-interval '5 minutes' then
        raise exception 'TRIAL_CHECK_EXPIRED';
    end if;
    for item in select a.payload as intent,r.kind as receipt_kind,r.payload as receipt,r.recorded_at
        from public.alpaca_paper_order_events a left join lateral (
            select kind,payload,recorded_at from public.alpaca_paper_order_events r
            where r.owner=p_owner and r.account_id=p_account and r.client_order_id=a.client_order_id
                and r.kind in ('accepted','observed','rejected') order by event_seq desc limit 1
        ) r on true where a.owner=p_owner and a.account_id=p_account and a.kind='intent'
    loop
        state:=item.receipt;
        if item.receipt_kind='rejected' or coalesce(ctx->'seen_order_ids' ? (state->>'id'),false)
            or (state->>'status' in ('filled','canceled','expired','rejected','replaced')
                and item.recorded_at<=cutoff) then continue; end if;
        prior:=item.intent->'trial_context';
        if prior is null then raise exception 'TRIAL_UNRECONCILED'; end if;
        extra_cost:=extra_cost+(prior->>'order_cost')::numeric;
        extra_risk:=extra_risk+(prior->>'order_loss')::numeric;
        if item.intent->>'symbol'=p_payload->>'symbol' then
            extra_symbol:=extra_symbol+(prior->>'order_cost')::numeric;
        end if;
    end loop;
    if (ctx->>'base_cost')::numeric+extra_cost+(ctx->>'order_cost')::numeric>(cfg.payload->>'capital')::numeric
        or (ctx->>'symbol_cost')::numeric+extra_symbol+(ctx->>'order_cost')::numeric
            >(cfg.payload->>'max_position')::numeric
        or (ctx->>'base_risk')::numeric+extra_risk+(ctx->>'order_loss')::numeric
            >(cfg.payload->>'max_loss')::numeric
        or (ctx->>'order_loss')::numeric>(cfg.payload->>'max_order_loss')::numeric then
        raise exception 'TRIAL_BUDGET_EXCEEDED';
    end if;
    insert into public.alpaca_paper_order_events(owner,account_id,client_order_id,event_key,kind,payload)
        values(p_owner,p_account,p_client,p_client,'intent',p_payload) returning * into saved;
    return next saved;
end; $$;
revoke all on function public.claim_alpaca_trial_order(text,uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.claim_alpaca_trial_order(text,uuid,text,jsonb) to service_role;
commit;
