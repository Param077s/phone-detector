-- ============================================================================
--  Vigil Exams — Supabase schema (run once in the SQL editor of a fresh project)
--
--  Model:
--    • Teachers  = normal Supabase Auth users (email/password or Google).
--    • Students  = Supabase ANONYMOUS auth users (signInAnonymously) — no signup,
--                  but each still gets a real auth.uid() so RLS can isolate them.
--    • exams          → one room, owned by a teacher, joined by a short code.
--    • participants   → one row per student who joined (presence + status).
--    • events         → flagged patterns (head_down, second_face, camera_off, …).
--
--  Multi-tenancy is enforced at the DATABASE via RLS: a teacher can only ever
--  read/write their OWN exams and their participants/events. A student can only
--  read the open exam they're joining and write their own participant + events.
-- ============================================================================

create extension if not exists "pgcrypto";

-- ---- tables ----------------------------------------------------------------
create table if not exists public.exams (
  id          uuid primary key default gen_random_uuid(),
  code        text unique not null,
  title       text not null default 'Exam',
  owner       uuid not null references auth.users (id) on delete cascade,
  status      text not null default 'open' check (status in ('open','closed')),
  created_at  timestamptz not null default now(),
  closed_at   timestamptz
);
create index if not exists exams_owner_idx on public.exams (owner);
create index if not exists exams_code_idx  on public.exams (code);

create table if not exists public.participants (
  id          uuid primary key default gen_random_uuid(),
  exam_id     uuid not null references public.exams (id) on delete cascade,
  user_id     uuid not null references auth.users (id) on delete cascade,  -- the anon student
  name        text not null,
  status      text not null default 'ok' check (status in ('ok','warn','alert','offline')),
  joined_at   timestamptz not null default now(),
  last_seen   timestamptz not null default now(),
  unique (exam_id, user_id)
);
create index if not exists participants_exam_idx on public.participants (exam_id);

create table if not exists public.events (
  id             uuid primary key default gen_random_uuid(),
  exam_id        uuid not null references public.exams (id) on delete cascade,
  participant_id uuid not null references public.participants (id) on delete cascade,
  kind           text not null,
  severity       text not null default 'info',
  at             timestamptz not null default now(),
  meta           jsonb
);
create index if not exists events_exam_idx on public.events (exam_id);

-- ---- row-level security ----------------------------------------------------
alter table public.exams        enable row level security;
alter table public.participants enable row level security;
alter table public.events       enable row level security;

-- exams: a teacher fully owns their rooms.
create policy exams_owner_all on public.exams
  for all using (owner = auth.uid()) with check (owner = auth.uid());
-- any signed-in user (incl. an anonymous student) may READ an OPEN exam to join it.
create policy exams_read_open on public.exams
  for select using (status = 'open');

-- participants: the student owns their own row; the exam's teacher can read them.
create policy participants_student_write on public.participants
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy participants_teacher_read on public.participants
  for select using (exists (
    select 1 from public.exams e where e.id = participants.exam_id and e.owner = auth.uid()));

-- events: the student writes their own; the exam's teacher reads them.
create policy events_student_write on public.events
  for insert with check (exists (
    select 1 from public.participants p
     where p.id = events.participant_id and p.user_id = auth.uid()));
create policy events_owner_read on public.events
  for select using (exists (
    select 1 from public.exams e where e.id = events.exam_id and e.owner = auth.uid()));
-- a student may read back their OWN events (their end-of-exam history).
create policy events_student_read on public.events
  for select using (exists (
    select 1 from public.participants p
     where p.id = events.participant_id and p.user_id = auth.uid()));

-- ---- realtime (teacher live room + lobby) ----------------------------------
alter publication supabase_realtime add table public.participants;
alter publication supabase_realtime add table public.events;

-- ---- helpers ---------------------------------------------------------------
-- server-side unique 6-char join code so two teachers never collide.
create or replace function public.new_exam_code() returns text
language plpgsql as $$
declare c text;
begin
  loop
    c := upper(substr(translate(encode(gen_random_bytes(6),'base64'),'+/=',''), 1, 6));
    exit when not exists (select 1 from public.exams where code = c);
  end loop;
  return c;
end $$;
