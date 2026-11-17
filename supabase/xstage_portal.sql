-- X-Stage Apps Portal tables. All public tables use the xstage_ prefix.
-- Execute ONLY in the selected project for X-Stage; do not overwrite other apps.
-- An authenticated account can review and see its own history; anonymous can only read reviews.
-- Admin access must be granted by a database operator (insert into xstage_admins).
create table if not exists public.xstage_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null default 'สมาชิก X-Stage' check (char_length(display_name) between 1 and 80),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.xstage_admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  granted_at timestamptz not null default now()
);
create table if not exists public.xstage_download_events (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  app_id text not null check (app_id ~ '^[a-z0-9-]{1,64}$'),
  event_type text not null check (event_type in ('download_clicked','installation_confirmed')),
  app_version text check (char_length(app_version)<=64),
  client_platform text not null check (client_platform in ('web','android-portal')),
  created_at timestamptz not null default now()
);
create index if not exists xstage_events_user_recent_idx
  on public.xstage_download_events (user_id,created_at desc);
create table if not exists public.xstage_reviews (
  user_id uuid not null references auth.users(id) on delete cascade,
  app_id text not null check (app_id ~ '^[a-z0-9-]{1,64}$'),
  rating smallint not null check (rating between 1 and 5),
  comment text not null default '' check (char_length(comment)<=1000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id,app_id)
);
create index if not exists xstage_reviews_app_recent_idx
  on public.xstage_reviews (app_id,updated_at desc);
-- Prevent clients overwriting timestamps. Trigger names are xstage_-prefixed too.
create or replace function public.xstage_reviews_set_updated()
returns trigger language plpgsql set search_path = '' as $$
begin
  new.created_at=old.created_at;
  new.updated_at=now();
  return new;
end;$$;
drop trigger if exists xstage_reviews_updated on public.xstage_reviews;
create trigger xstage_reviews_updated before update on public.xstage_reviews
  for each row execute function public.xstage_reviews_set_updated();
alter table public.xstage_profiles enable row level security;
alter table public.xstage_admins enable row level security;
alter table public.xstage_download_events enable row level security;
alter table public.xstage_reviews enable row level security;
-- RLS: no public access to personal histories, no user-created admins.
drop policy if exists xstage_profiles_self_select on public.xstage_profiles;
create policy xstage_profiles_self_select on public.xstage_profiles for select to authenticated
  using ((select auth.uid())=user_id);
drop policy if exists xstage_profiles_self_insert on public.xstage_profiles;
create policy xstage_profiles_self_insert on public.xstage_profiles for insert to authenticated
  with check ((select auth.uid())=user_id);
drop policy if exists xstage_profiles_self_update on public.xstage_profiles;
create policy xstage_profiles_self_update on public.xstage_profiles for update to authenticated
  using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
drop policy if exists xstage_admins_self_read on public.xstage_admins;
create policy xstage_admins_self_read on public.xstage_admins for select to authenticated
  using ((select auth.uid())=user_id);
drop policy if exists xstage_events_self_or_admin_read on public.xstage_download_events;
create policy xstage_events_self_or_admin_read on public.xstage_download_events for select to authenticated
  using ((select auth.uid())=user_id or exists(select 1 from public.xstage_admins a where a.user_id=(select auth.uid())));
drop policy if exists xstage_events_self_insert on public.xstage_download_events;
create policy xstage_events_self_insert on public.xstage_download_events for insert to authenticated
  with check ((select auth.uid())=user_id);
drop policy if exists xstage_events_self_delete on public.xstage_download_events;
create policy xstage_events_self_delete on public.xstage_download_events for delete to authenticated
  using ((select auth.uid())=user_id);
drop policy if exists xstage_reviews_public_read on public.xstage_reviews;
create policy xstage_reviews_public_read on public.xstage_reviews for select to anon,authenticated
  using (true);
drop policy if exists xstage_reviews_self_insert on public.xstage_reviews;
create policy xstage_reviews_self_insert on public.xstage_reviews for insert to authenticated
  with check ((select auth.uid())=user_id);
drop policy if exists xstage_reviews_self_update on public.xstage_reviews;
create policy xstage_reviews_self_update on public.xstage_reviews for update to authenticated
  using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
drop policy if exists xstage_reviews_self_or_admin_delete on public.xstage_reviews;
create policy xstage_reviews_self_or_admin_delete on public.xstage_reviews for delete to authenticated
  using ((select auth.uid())=user_id or exists(select 1 from public.xstage_admins a where a.user_id=(select auth.uid())));
-- RLS alone does not grant Data API access.
revoke all on public.xstage_profiles,public.xstage_admins,
  public.xstage_download_events,public.xstage_reviews from anon,authenticated;
grant select on public.xstage_reviews to anon;
grant select,insert,update,delete on public.xstage_reviews to authenticated;
grant select on public.xstage_admins to authenticated;
grant select,insert,update on public.xstage_profiles to authenticated;
grant select,insert,delete on public.xstage_download_events to authenticated;
grant usage,select on sequence public.xstage_download_events_id_seq to authenticated;
-- An RLS-invoker view gives exact totals and averages even with >100 reviews.
create or replace view public.xstage_review_stats with (security_invoker = true) as
select app_id, count(*)::bigint as review_count, avg(rating)::numeric(4,2) as avg_rating
from public.xstage_reviews group by app_id;
grant select on public.xstage_review_stats to anon,authenticated;
-- Provision admin after Google sign-in, from SQL editor (not in a public script):
-- insert into public.xstage_admins(user_id)
-- select id from auth.users where email='<administrator email>'
-- on conflict do nothing;
