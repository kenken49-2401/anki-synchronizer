-- Run once in the SQL editor of a FREE Supabase project.
-- No public/anonymous client can read these tables or invoke these functions.
create table if not exists public.anki_state (
  id integer primary key check (id = 1),
  revision bigint not null default 0,
  payload text,
  previous_payload text,
  lease uuid,
  lease_until timestamptz,
  rate_window timestamptz not null default now(),
  rate_count integer not null default 0
);
insert into public.anki_state(id) values (1) on conflict do nothing;
alter table public.anki_state enable row level security;
revoke all on public.anki_state from public, anon, authenticated;
grant select, insert, update, delete on public.anki_state to service_role;

create table if not exists public.anki_oauth (
  collection text not null,
  key text not null,
  payload text not null check (octet_length(payload) <= 524288),
  created_at timestamptz,
  expires_at timestamptz,
  primary key (collection, key)
);
alter table public.anki_oauth enable row level security;
revoke all on public.anki_oauth from public, anon, authenticated;
grant select, insert, update, delete on public.anki_oauth to service_role;

create or replace function public.anki_acquire(p_lease uuid)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare s public.anki_state%rowtype;
begin
  select * into s from public.anki_state where id = 1 for update;
  if s.lease_until > clock_timestamp() then
    raise exception 'busy';
  end if;
  if s.rate_window < clock_timestamp() - interval '1 minute' then
    s.rate_window := clock_timestamp(); s.rate_count := 0;
  end if;
  if s.rate_count >= 30 then raise exception 'rate limit'; end if;
  update public.anki_state set lease = p_lease,
    lease_until = clock_timestamp() + interval '120 seconds',
    rate_window = s.rate_window, rate_count = s.rate_count + 1 where id = 1;
  return jsonb_build_object('revision', s.revision, 'payload', s.payload);
end $$;

create or replace function public.anki_commit(p_lease uuid, p_revision bigint, p_payload text)
returns bigint language plpgsql security invoker set search_path = '' as $$
declare r bigint;
begin
  if octet_length(p_payload) > 30000000 then raise exception 'snapshot too large'; end if;
  update public.anki_state set previous_payload = payload, payload = p_payload,
    revision = revision + 1, lease = null, lease_until = null
    where id = 1 and lease = p_lease and revision = p_revision
      and lease_until > clock_timestamp() returning revision into r;
  if r is null then raise exception 'stale lease'; end if;
  return r;
end $$;

create or replace function public.anki_release(p_lease uuid)
returns void language sql security invoker set search_path = '' as $$
  update public.anki_state set lease = null, lease_until = null
    where id = 1 and lease = p_lease;
$$;

-- Serialize OAuth writes; remove expired rows and cap registrations to protect free storage.
create or replace function public.anki_oauth_put(
  p_collection text, p_key text, p_payload text,
  p_created_at timestamptz, p_expires_at timestamptz)
returns void language plpgsql security invoker set search_path = '' as $$
begin
  perform pg_catalog.pg_advisory_xact_lock(7192401);
  delete from public.anki_oauth where expires_at < clock_timestamp();
  if not exists (select 1 from public.anki_oauth where collection=p_collection and key=p_key)
     and (select count(*) from public.anki_oauth) >= 2000 then
    raise exception 'oauth storage limit';
  end if;
  insert into public.anki_oauth(collection,key,payload,created_at,expires_at)
    values(p_collection,p_key,p_payload,p_created_at,p_expires_at)
    on conflict(collection,key) do update set payload=excluded.payload,
      created_at=excluded.created_at, expires_at=excluded.expires_at;
end $$;

revoke all on function public.anki_acquire(uuid) from public, anon, authenticated;
revoke all on function public.anki_commit(uuid,bigint,text) from public, anon, authenticated;
revoke all on function public.anki_release(uuid) from public, anon, authenticated;
revoke all on function public.anki_oauth_put(text,text,text,timestamptz,timestamptz) from public, anon, authenticated;
grant execute on function public.anki_acquire(uuid) to service_role;
grant execute on function public.anki_commit(uuid,bigint,text) to service_role;
grant execute on function public.anki_release(uuid) to service_role;
grant execute on function public.anki_oauth_put(text,text,text,timestamptz,timestamptz) to service_role;
