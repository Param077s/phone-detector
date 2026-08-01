-- ============================================================================
--  Vigil Exams — migration v14 (run AFTER v13, in the Supabase SQL editor)
--
--  The two people in an exam can both write in the record now.
--
--  Until this, only one of them could. A student could read every flag against
--  them and had no way to say the phone was a calculator, or that the invigilator
--  had been talking to them — the record was complete, visible to them, and shut.
--  And "To discuss" was a verdict whose whole meaning is "I need to talk to this
--  person first", with nowhere to write down what the conversation concluded: the
--  teacher's only moves were to leave it on 'discuss' forever, or flip it to
--  upheld/set aside, recording the decision and losing the reason.
--
--  One table answers both. A note hangs off (participant, kind) — the same unit a
--  student-level finding is built from — so it lands beside the thing it is about.
--
--  ONE note per finding per author, enforced by a unique index. This is deliberate
--  and it is the whole safety of the feature: a student states their case once and
--  may edit it, and a teacher records one outcome. It is a record, not a thread,
--  and it cannot become an argument.
--
--  Safe to run anytime, safe to re-run. Nothing reads these until they exist; the
--  pages hide both affordances when the table is absent, so the app works exactly
--  as it does today until this is applied.
-- ============================================================================

create table if not exists public.finding_notes (
  id             uuid primary key default gen_random_uuid(),
  exam_id        uuid not null references public.exams (id) on delete cascade,
  participant_id uuid not null references public.participants (id) on delete cascade,
  kind           text not null,                              -- which finding: 'phone', 'look_away', …
  author         text not null check (author in ('student','teacher')),
  body           text not null check (length(btrim(body)) between 1 and 400),
  at             timestamptz not null default now()
);

-- one statement, one outcome. Not a conversation.
create unique index if not exists finding_notes_one_per_author
  on public.finding_notes (participant_id, kind, author);
create index if not exists finding_notes_exam_idx on public.finding_notes (exam_id);

alter table public.finding_notes enable row level security;

-- ---- the student -----------------------------------------------------------
-- They may write ONE statement about a finding of their own, and edit it. `author`
-- is pinned to 'student' in both directions, so they cannot file a note as the
-- teacher, and the participant must be theirs AND in the exam the row claims —
-- the same pairing v11 had to add to events, for the same reason.
drop policy if exists finding_notes_student_insert on public.finding_notes;
create policy finding_notes_student_insert on public.finding_notes
  for insert with check (
    author = 'student'
    and exists (select 1 from public.participants p
                 where p.id = finding_notes.participant_id
                   and p.user_id = auth.uid()
                   and p.exam_id = finding_notes.exam_id));

drop policy if exists finding_notes_student_update on public.finding_notes;
create policy finding_notes_student_update on public.finding_notes
  for update using (
    author = 'student'
    and exists (select 1 from public.participants p
                 where p.id = finding_notes.participant_id and p.user_id = auth.uid()))
  with check (
    author = 'student'
    and exists (select 1 from public.participants p
                 where p.id = finding_notes.participant_id and p.user_id = auth.uid()));

-- They read their OWN words back, and only those. A teacher's outcome may name a
-- next step, another student, or a conclusion not yet delivered, so it is not
-- published to them here. v10's addressed exam_notes remain the deliberate channel
-- for anything a teacher means the student to read.
drop policy if exists finding_notes_student_select on public.finding_notes;
create policy finding_notes_student_select on public.finding_notes
  for select using (
    author = 'student'
    and exists (select 1 from public.participants p
                 where p.id = finding_notes.participant_id and p.user_id = auth.uid()));

-- They may also withdraw it. v11 stops a student destroying EVIDENCE about them;
-- this is the opposite thing — their own voluntary words — and someone who thinks
-- better of what they wrote must be able to take it back rather than be held to a
-- first draft. They still cannot touch a flag, an event, or the teacher's outcome.
drop policy if exists finding_notes_student_delete on public.finding_notes;
create policy finding_notes_student_delete on public.finding_notes
  for delete using (
    author = 'student'
    and exists (select 1 from public.participants p
                 where p.id = finding_notes.participant_id and p.user_id = auth.uid()));

-- ---- the exam's owner ------------------------------------------------------
drop policy if exists finding_notes_owner_select on public.finding_notes;
create policy finding_notes_owner_select on public.finding_notes
  for select using (exists (
    select 1 from public.exams e where e.id = finding_notes.exam_id and e.owner = auth.uid()));

-- The owner writes outcomes, and only as themselves: `author = 'teacher'` is
-- checked so a teacher cannot author words in a student's name.
drop policy if exists finding_notes_owner_insert on public.finding_notes;
create policy finding_notes_owner_insert on public.finding_notes
  for insert with check (
    author = 'teacher'
    and exists (select 1 from public.exams e
                 where e.id = finding_notes.exam_id and e.owner = auth.uid()));

drop policy if exists finding_notes_owner_update on public.finding_notes;
create policy finding_notes_owner_update on public.finding_notes
  for update using (
    author = 'teacher'
    and exists (select 1 from public.exams e where e.id = finding_notes.exam_id and e.owner = auth.uid()))
  with check (
    author = 'teacher'
    and exists (select 1 from public.exams e where e.id = finding_notes.exam_id and e.owner = auth.uid()));

drop policy if exists finding_notes_owner_delete on public.finding_notes;
create policy finding_notes_owner_delete on public.finding_notes
  for delete using (exists (
    select 1 from public.exams e where e.id = finding_notes.exam_id and e.owner = auth.uid()));

-- ---- when it was said ------------------------------------------------------
-- `at` is what lets an outcome say "spoken to at 14:20" and a statement carry its
-- own date into a filed document, so it is stamped by the database rather than
-- accepted from a browser. Backdating your own statement is otherwise one line in
-- a console.
create or replace function public.finding_notes_stamp()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  new.at := now();
  if tg_op = 'UPDATE' then
    new.id := old.id; new.exam_id := old.exam_id;
    new.participant_id := old.participant_id; new.kind := old.kind; new.author := old.author;
  end if;
  return new;
end $$;

drop trigger if exists finding_notes_stamp_trg on public.finding_notes;
create trigger finding_notes_stamp_trg
  before insert or update on public.finding_notes
  for each row execute function public.finding_notes_stamp();

-- ---- live -------------------------------------------------------------------
-- A statement written during an exam should reach the teacher's open room the way
-- a flag does, without a reload.
do $$ begin
  alter publication supabase_realtime add table public.finding_notes;
exception when duplicate_object then null; end $$;
