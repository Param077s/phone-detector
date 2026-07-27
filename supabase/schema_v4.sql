-- ============================================================================
--  Vigil Exams — migration v4 (optional hardening; run AFTER v3)
--
--  Only REAL (non-anonymous) teacher accounts may create exams. Students use
--  anonymous auth, so this blocks a student session from creating exam rooms.
--  Splits the old "for all" owner policy into granular ones so INSERT can carry
--  the extra check without affecting select/update/delete.
-- ============================================================================

drop policy if exists exams_owner_all on public.exams;

create policy exams_owner_select on public.exams
  for select using (owner = auth.uid());

create policy exams_owner_update on public.exams
  for update using (owner = auth.uid()) with check (owner = auth.uid());

create policy exams_owner_delete on public.exams
  for delete using (owner = auth.uid());

-- INSERT: must be yourself AND not an anonymous session
create policy exams_teacher_insert on public.exams
  for insert with check (
    owner = auth.uid()
    and coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false) = false
  );
