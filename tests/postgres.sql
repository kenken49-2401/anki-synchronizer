\set ON_ERROR_STOP on
begin;
do $$ begin
  if has_table_privilege('anon', 'public.anki_state', 'SELECT') then raise exception 'anonymous state access'; end if;
  if has_table_privilege('authenticated', 'public.anki_oauth', 'SELECT') then raise exception 'authenticated token access'; end if;
  if has_function_privilege('anon', 'public.anki_acquire(uuid)', 'EXECUTE') then raise exception 'anonymous RPC'; end if;
end $$;
set role service_role;
do $$ declare s jsonb; r bigint; begin
  s := public.anki_acquire('11111111-1111-4111-8111-111111111111');
  if s->>'revision' <> '0' then raise exception 'wrong initial revision'; end if;
  begin
    perform public.anki_acquire('22222222-2222-4222-8222-222222222222');
    raise exception 'second writer acquired active lease';
  exception when raise_exception then
    if sqlerrm <> 'busy' then raise; end if;
  end;
  r := public.anki_commit('11111111-1111-4111-8111-111111111111', 0, 'encrypted-test-one');
  if r <> 1 then raise exception 'revision not advanced'; end if;
  perform public.anki_acquire('22222222-2222-4222-8222-222222222222');
  begin
    perform public.anki_commit('11111111-1111-4111-8111-111111111111', 0, 'stale-overwrite');
    raise exception 'stale writer overwrote state';
  exception when raise_exception then
    if sqlerrm <> 'stale lease' then raise; end if;
  end;
  update public.anki_state set lease_until=clock_timestamp()-interval '1 second' where id=1;
  begin
    perform public.anki_commit('22222222-2222-4222-8222-222222222222', 1, 'expired-overwrite');
    raise exception 'expired writer overwrote state';
  exception when raise_exception then
    if sqlerrm <> 'stale lease' then raise; end if;
  end;
  perform public.anki_acquire('33333333-3333-4333-8333-333333333333');
  perform public.anki_release('22222222-2222-4222-8222-222222222222');
  if (select lease from public.anki_state where id=1) <> '33333333-3333-4333-8333-333333333333'::uuid then
    raise exception 'old owner released new owner lease';
  end if;
  perform public.anki_commit('33333333-3333-4333-8333-333333333333', 1, 'encrypted-test-two');
  if (select previous_payload from public.anki_state where id=1) <> 'encrypted-test-one' then
    raise exception 'previous snapshot missing';
  end if;
  update public.anki_state set rate_count=30,rate_window=clock_timestamp() where id=1;
  begin
    perform public.anki_acquire('44444444-4444-4444-8444-444444444444');
    raise exception 'rate cap bypassed';
  exception when raise_exception then
    if sqlerrm <> 'rate limit' then raise; end if;
  end;
  perform public.anki_oauth_put('tokens', 'expired', 'encrypted', now()-interval '2 days', now()-interval '1 day');
  perform public.anki_oauth_put('tokens', 'active', 'encrypted-active', now(), now()+interval '1 hour');
  if exists(select 1 from public.anki_oauth where key='expired') then raise exception 'expired token retained'; end if;
end $$;
rollback;
select 'SQL security, lease fencing, previous snapshot and rate limit checks passed' as result;
