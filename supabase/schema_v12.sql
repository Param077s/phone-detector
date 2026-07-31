-- ============================================================================
--  Vigil Exams — migration v12 (run AFTER v11, in the Supabase SQL editor)
--
--  An exam finally has a START and an END.
--
--  Until now there was no such thing. `created_at` was when the teacher made the
--  room — often twenty minutes early, while students trickled in and calibrated —
--  and `closed_at` was whenever somebody remembered to press Close. The report
--  called that span "the exam", which meant:
--
--    • settling-in fidgeting counted against students exactly like exam-time
--      behaviour, because nothing distinguished them;
--    • an exam nobody closed stayed open forever, monitoring people who had left;
--    • two exams were never comparable, because neither span meant the same thing.
--
--  starts_at is stamped when the teacher presses Start. ends_at is starts_at plus
--  the duration, so the exam ends on its own whether or not anyone is watching.
--
--  Safe to run anytime, safe to re-run. Existing exams get NULLs and keep their
--  old behaviour exactly — every surface falls back to created_at/closed_at when
--  starts_at is absent, so nothing that already happened is reinterpreted.
-- ============================================================================

alter table public.exams
  add column if not exists starts_at    timestamptz,
  add column if not exists ends_at      timestamptz,
  add column if not exists duration_min integer;

-- a sane bound: 5 minutes to 8 hours, and only when a duration is set at all
alter table public.exams drop constraint if exists exams_duration_check;
alter table public.exams add constraint exams_duration_check
  check (duration_min is null or (duration_min >= 5 and duration_min <= 480));

-- the live room reads "has it started / how long left" constantly
create index if not exists exams_ends_idx on public.exams (ends_at);
