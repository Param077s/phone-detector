-- ============================================================================
--  Vigil Exams — migration v7 (run AFTER v6, in the Supabase SQL editor)
--
--  Invigilator notes: the teacher can jot timestamped observations during a
--  live exam ("10:41 — phone buzz, back left"). They appear in the live feed
--  and are woven into the report beside the AI flags, so the report becomes
--  the COMPLETE record of the room — human plus machine.
--
--  Safe to run anytime — the app tolerates this table being absent (the note
--  box and the report section simply don't appear until it exists).
-- ============================================================================

create table if not exists public.exam_notes (
  id       uuid primary key default gen_random_uuid(),
  exam_id  uuid not null references public.exams (id) on delete cascade,
  owner    uuid not null references auth.users (id) on delete cascade default auth.uid(),
  at       timestamptz not null default now(),
  text     text not null check (char_length(text) between 1 and 500)
);
create index if not exists exam_notes_exam_idx on public.exam_notes (exam_id);

alter table public.exam_notes enable row level security;

-- only the exam's OWNER can write or read its notes (students never see them)
drop policy if exists notes_exam_owner_all on public.exam_notes;
create policy notes_exam_owner_all on public.exam_notes
  for all using (exists (
    select 1 from public.exams e where e.id = exam_notes.exam_id and e.owner = auth.uid()))
  with check (exists (
    select 1 from public.exams e where e.id = exam_notes.exam_id and e.owner = auth.uid()));

-- live report updates while the exam is open
alter publication supabase_realtime add table public.exam_notes;
