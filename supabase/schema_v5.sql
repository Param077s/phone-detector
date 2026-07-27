-- ============================================================================
--  Vigil Exams — migration v5 (run AFTER v4, in the Supabase SQL editor)
--
--  Per-exam integrity control: a teacher can require students to SIGN IN
--  (no anonymous "guest" joins) when creating a real exam. Casual quizzes can
--  still allow guests. The join flow reads this through find_open_exam().
--
--  Safe to run anytime — the app already tolerates the column being absent
--  (it just treats every exam as guest-allowed until this migration is applied).
-- ============================================================================

-- 1) the flag (default false = guests allowed, matches today's behaviour)
alter table public.exams
  add column if not exists require_signin boolean not null default false;

-- 2) surface it to the join screen. find_open_exam is SECURITY DEFINER so the
--    student can read just these fields for the code they typed, nothing else.
--    (return type changes, so drop + recreate rather than CREATE OR REPLACE)
drop function if exists public.find_open_exam(text);
create function public.find_open_exam(p_code text)
returns table(id uuid, title text, require_signin boolean)
language sql security definer set search_path = public as $$
  select e.id, e.title, e.require_signin
    from public.exams e
   where e.code = upper(p_code) and e.status = 'open'
   limit 1;
$$;
grant execute on function public.find_open_exam(text) to anon, authenticated;
