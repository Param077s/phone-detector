-- ============================================================================
--  Vigil Exams — migration v2 (run AFTER schema.sql, in the SQL editor)
--
--  Fixes exam-code enumeration: open exams are no longer globally readable, so
--  nobody can list other teachers' rooms or harvest join codes. A student
--  resolves a code through a SECURITY DEFINER function, and can read an exam
--  only once they've actually joined it.
-- ============================================================================

-- 1) stop open exams being world-readable
drop policy if exists exams_read_open on public.exams;

-- 2) a student may read an exam only if they've joined it (have a participant row)
drop policy if exists exams_read_joined on public.exams;
create policy exams_read_joined on public.exams
  for select using (exists (
    select 1 from public.participants p
     where p.exam_id = exams.id and p.user_id = auth.uid()));

-- 3) code -> exam lookup for joining, without exposing the table
create or replace function public.find_open_exam(p_code text)
returns table(id uuid, title text)
language sql security definer set search_path = public as $$
  select e.id, e.title from public.exams e
   where e.code = upper(p_code) and e.status = 'open'
   limit 1;
$$;
grant execute on function public.find_open_exam(text) to anon, authenticated;
