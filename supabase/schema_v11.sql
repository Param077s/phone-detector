-- ============================================================================
--  Vigil Exams — migration v11 (run AFTER v10, in the Supabase SQL editor)
--
--  SECURITY FIX — please run this before the next real exam.
--
--  The original policy was:
--
--      create policy participants_student_write on public.participants
--        for all using (user_id = auth.uid()) with check (user_id = auth.uid());
--
--  "for all" includes DELETE. And events.participant_id is declared
--  ON DELETE CASCADE. So a student could destroy every flag recorded against
--  them, permanently, with one line typed into their own browser console:
--
--      await sb.from("participants").delete().eq("user_id", MY_ID)
--
--  Their row vanished, every event of theirs cascaded away with it, and the
--  teacher's report showed them as though they had never joined the exam.
--  Cascades are not subject to RLS, so the "students can only INSERT events"
--  rule never came into it.
--
--  The same policy also let a student UPDATE any column of their row: name,
--  status, last_seen. Renaming themselves mid-exam, pinning status to 'ok', or
--  parking last_seen in the future to stay green after leaving.
--
--  This migration splits that one policy into the three things the app actually
--  does (insert on join, select your own row, update status/last_seen on the
--  heartbeat) and grants no DELETE to anyone but the exam's owner. Nothing in
--  the app has ever deleted a participant row, so nothing breaks.
--
--  Safe to run anytime, safe to re-run.
-- ============================================================================

-- 1) the over-broad policy goes
drop policy if exists participants_student_write on public.participants;

-- 2) a student may create their own row (this is how joining works)
drop policy if exists participants_student_insert on public.participants;
create policy participants_student_insert on public.participants
  for insert with check (user_id = auth.uid());

-- 3) …read their own row back
drop policy if exists participants_student_select on public.participants;
create policy participants_student_select on public.participants
  for select using (user_id = auth.uid());

-- 4) …and update it. WHICH columns is enforced by the trigger below, because a
--    policy can't see the old and the new row at the same time.
drop policy if exists participants_student_update on public.participants;
create policy participants_student_update on public.participants
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());

-- 5) the exam's owner may delete rows from their own exam. NOBODY else can —
--    in particular the student whose row it is cannot, which is the whole point.
drop policy if exists participants_owner_delete on public.participants;
create policy participants_owner_delete on public.participants
  for delete using (exists (
    select 1 from public.exams e where e.id = participants.exam_id and e.owner = auth.uid()));

-- 6) pin everything a student must not be able to change. This silently restores
--    the old values rather than raising, so a tampered write simply has no
--    effect instead of surfacing an error the student can learn from.
create or replace function public.participants_lock_identity()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  -- the exam's owner is unrestricted
  if exists (select 1 from public.exams e where e.id = old.exam_id and e.owner = auth.uid()) then
    return new;
  end if;
  new.id        := old.id;
  new.exam_id   := old.exam_id;
  new.user_id   := old.user_id;
  new.name      := old.name;
  new.joined_at := old.joined_at;
  -- a heartbeat is "I am here NOW". Parking it in the future kept a student
  -- showing as online long after they had gone.
  if new.last_seen > now() + interval '1 minute' then
    new.last_seen := now();
  end if;
  return new;
end $$;

drop trigger if exists participants_lock_identity_trg on public.participants;
create trigger participants_lock_identity_trg
  before update on public.participants
  for each row execute function public.participants_lock_identity();

-- 7) an event write only checked that the participant belonged to you — not that
--    the exam_id on the row was the exam that participant is actually in. Tie the
--    two together so a student can't write rows into an exam they aren't sitting.
drop policy if exists events_student_write on public.events;
create policy events_student_write on public.events
  for insert with check (exists (
    select 1 from public.participants p
     where p.id = events.participant_id
       and p.user_id = auth.uid()
       and p.exam_id = events.exam_id));
