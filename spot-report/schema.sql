-- Spot India: report store.
-- Run this once in your Supabase project: SQL Editor -> New query -> paste -> Run.

create table if not exists public.spot_reports (
  id               bigint generated always as identity primary key,
  tracking_id      text not null unique,
  created_at       timestamptz not null default now(),

  -- classification
  category_id      text not null,
  category_name    text not null,
  severity         text not null check (severity in ('critical','high','medium','low')),
  confidence       double precision,

  -- routing
  authority_id     text not null,
  authority_name   text not null,
  authority_email  text,

  -- where
  lat              double precision,
  lng              double precision,
  accuracy_m       double precision,
  address          text,
  address_short    text,
  city             text,
  locality         text,

  -- what the reporter added
  note             text,
  answer           text,
  reporter         text,

  -- the exact message that was sent, kept verbatim for audit
  subject          text,
  body             text,
  photo_url        text,

  -- lifecycle
  status           text not null default 'submitted'
                   check (status in ('submitted','acknowledged','in_progress','resolved','rejected')),
  resolved_at      timestamptz,
  delivery         jsonb not null default '{}'::jsonb
);

create index if not exists spot_reports_created_idx  on public.spot_reports (created_at desc);
create index if not exists spot_reports_category_idx on public.spot_reports (category_id);
create index if not exists spot_reports_status_idx   on public.spot_reports (status);
create index if not exists spot_reports_geo_idx      on public.spot_reports (lat, lng);

-- Status history, so a reporter can see a timeline rather than one flag.
create table if not exists public.spot_report_events (
  id          bigint generated always as identity primary key,
  tracking_id text not null references public.spot_reports (tracking_id) on delete cascade,
  at          timestamptz not null default now(),
  status      text not null,
  note        text
);
create index if not exists spot_report_events_tid_idx on public.spot_report_events (tracking_id, at desc);

-- Record the opening event automatically.
create or replace function public.spot_log_submit() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.spot_report_events (tracking_id, status, note)
  values (new.tracking_id, new.status, 'Report submitted and routed to ' || new.authority_name);
  return new;
end $$;

drop trigger if exists spot_reports_log_submit on public.spot_reports;
create trigger spot_reports_log_submit
  after insert on public.spot_reports
  for each row execute function public.spot_log_submit();

-- Row Level Security -------------------------------------------------------
-- The app talks to PostgREST with the publishable (anon) key, so the policies
-- below are what make that safe: anyone may file a report and look one up,
-- nobody may edit or delete through the API.
alter table public.spot_reports       enable row level security;
alter table public.spot_report_events enable row level security;

drop policy if exists spot_reports_insert on public.spot_reports;
create policy spot_reports_insert on public.spot_reports
  for insert to anon, authenticated with check (true);

drop policy if exists spot_reports_select on public.spot_reports;
create policy spot_reports_select on public.spot_reports
  for select to anon, authenticated using (true);

drop policy if exists spot_events_select on public.spot_report_events;
create policy spot_events_select on public.spot_report_events
  for select to anon, authenticated using (true);

-- NOTE: select is open so the public accountability feed works. If you later
-- want reports private, drop spot_reports_select and read the feed with the
-- service key from the server only.

-- Photo bucket (public read) ----------------------------------------------
insert into storage.buckets (id, name, public)
values ('report-photos', 'report-photos', true)
on conflict (id) do nothing;

drop policy if exists spot_photos_insert on storage.objects;
create policy spot_photos_insert on storage.objects
  for insert to anon, authenticated
  with check (bucket_id = 'report-photos');

drop policy if exists spot_photos_select on storage.objects;
create policy spot_photos_select on storage.objects
  for select to anon, authenticated
  using (bucket_id = 'report-photos');
