-- ============================================================================
--  Vigil Exams — migration v13 (run AFTER v12, in the Supabase SQL editor)
--
--  An exam now remembers WHERE it was, so it reads the same hour to everyone.
--
--  A timestamptz is an instant. The hour it displays as is a choice, and until
--  now the browser was making that choice from wherever the person reading
--  happened to be sitting. So:
--
--    • a teacher marking from another timezone saw every flag shifted by hours,
--      with nothing on the page saying so;
--    • the downloadable report — the thing that gets forwarded, filed and
--      attached to an escalation — showed a different set of times to the person
--      who ran the exam and the person who received it;
--    • two readers could disagree about when something happened while looking at
--      the same record, which is not a thing a record may do.
--
--  The teacher's own zone is stamped when they create the exam (an IANA name
--  like 'Asia/Kolkata'), and every surface formats in it. A short zone label is
--  shown only when the reader is somewhere else — saying "times in IST" to
--  someone already in IST would just be noise.
--
--  Safe to run anytime, safe to re-run. Existing exams get NULL and keep today's
--  behaviour exactly: no zone means format in the reader's own, which is what
--  every surface did before this.
-- ============================================================================

alter table public.exams
  add column if not exists timezone text;

-- An IANA zone name, or nothing. This is written by the browser at creation, so
-- the check is a sanity bound on shape, not a validation of the zone database —
-- an unknown-but-well-formed name simply falls back to the reader's zone in the
-- client, the same as NULL.
alter table public.exams drop constraint if exists exams_timezone_check;
alter table public.exams add constraint exams_timezone_check
  check (timezone is null or (length(timezone) between 3 and 64 and timezone ~ '^[A-Za-z][A-Za-z0-9+_/-]*$'));
