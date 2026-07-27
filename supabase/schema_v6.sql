-- ============================================================================
--  Vigil Exams — migration v6 (run AFTER v5, in the Supabase SQL editor)
--
--  Flag review: the exam owner can mark each flagged moment Confirmed or
--  Dismissed. Dismissed flags drop out of the student's risk score, so the
--  report becomes a triaged, defensible record instead of raw machine output.
--
--  Safe to run anytime — the app tolerates the column/policy being absent
--  (the Confirm/Dismiss buttons simply don't appear until this is applied).
-- ============================================================================

-- 1) the review verdict on each event (null = not yet reviewed)
alter table public.events
  add column if not exists review text check (review in ('confirmed','dismissed'));

-- 2) let the exam's owner UPDATE that verdict (students still can't touch events)
drop policy if exists events_owner_update on public.events;
create policy events_owner_update on public.events
  for update using (exists (
    select 1 from public.exams e where e.id = events.exam_id and e.owner = auth.uid()))
  with check (exists (
    select 1 from public.exams e where e.id = events.exam_id and e.owner = auth.uid()));
