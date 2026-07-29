-- ============================================================================
--  Vigil Exams — migration v10 (run AFTER v9, in the Supabase SQL editor)
--
--  A note can now be ADDRESSED to one student, and that student sees it on their
--  own screen while the exam is running. This is what makes an invigilator's
--  "do not look here and there" actually reach the person it is about, instead
--  of sitting in a report they read afterwards.
--
--  Notes stay private by default. A note with participant_id NULL is a note
--  about the room, and only the exam's owner can ever read it. A note with a
--  participant_id is readable by that ONE student and nobody else — not the
--  rest of the class, not other exams.
--
--  Safe to run anytime, safe to re-run. Existing notes get participant_id NULL,
--  so nothing that was private becomes visible.
-- ============================================================================

-- 1) who the note is for (null = the room, teacher's eyes only)
alter table public.exam_notes
  add column if not exists participant_id uuid
  references public.participants (id) on delete cascade;

create index if not exists exam_notes_participant_idx
  on public.exam_notes (participant_id);

-- 2) the owner keeps full control of every note in their exam
drop policy if exists notes_exam_owner_all on public.exam_notes;
create policy notes_exam_owner_all on public.exam_notes
  for all using (exists (
    select 1 from public.exams e where e.id = exam_notes.exam_id and e.owner = auth.uid()))
  with check (exists (
    select 1 from public.exams e where e.id = exam_notes.exam_id and e.owner = auth.uid()));

-- 3) …and a student may READ only the notes addressed to them. Read only:
--    students can never write, edit or delete an invigilator's note.
drop policy if exists notes_addressed_student_select on public.exam_notes;
create policy notes_addressed_student_select on public.exam_notes
  for select using (
    exam_notes.participant_id is not null
    and exists (
      select 1 from public.participants p
      where p.id = exam_notes.participant_id and p.user_id = auth.uid()));
