-- ============================================================================
--  Vigil Exams — migration v8 (run AFTER v7, in the Supabase SQL editor)
--
--  Realtime exam state: closing / reopening an exam (and any future exam
--  setting) streams instantly to every open teacher surface — the live room
--  flips to its "who was in" view and the report drops its Live pill the
--  moment the button is pressed, no reload.
--
--  (Students can't receive the close over realtime — RLS only lets them read
--  OPEN exams — so the student room also polls every few seconds as before.)
--
--  Safe to run anytime, safe to re-run.
-- ============================================================================

do $$ begin
  alter publication supabase_realtime add table public.exams;
exception when duplicate_object then null; end $$;
