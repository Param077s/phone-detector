-- ============================================================================
--  Vigil Exams — migration v3 (run AFTER schema_v2.sql)
--
--  Fixes "infinite recursion detected in policy for relation exams": the v2
--  exams_read_joined policy read participants, whose policy reads exams. We
--  break the loop by checking participation via a SECURITY DEFINER function
--  (runs without RLS), so the two tables no longer reference each other's RLS.
-- ============================================================================

create or replace function public.is_in_exam(p_exam uuid)
returns boolean
language sql security definer stable set search_path = public as $$
  select exists (
    select 1 from public.participants
     where exam_id = p_exam and user_id = auth.uid()
  );
$$;
grant execute on function public.is_in_exam(uuid) to anon, authenticated;

drop policy if exists exams_read_joined on public.exams;
create policy exams_read_joined on public.exams
  for select using (public.is_in_exam(id));
